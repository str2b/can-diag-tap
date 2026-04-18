from __future__ import annotations

import argparse
import queue
import threading
import time
from typing import Callable, Any

from diag_filter import FilterEngine, GenericMessage

from .adapters import BusAdapter, build_adapter, settings_from_args
from .defs_adapter import DefsParser, build_defs_parser
from .protocols import fmt_hex
from .transport import DiagTransport, build_transport_with_options


class DiagnosticSession:
    """Core runtime session holding adapter, transport, decoder, and workers."""

    def __init__(self, args: argparse.Namespace, emit: Callable[[str], None]) -> None:
        self._args = args
        self._emit = emit

        self._adapter: BusAdapter = build_adapter(settings_from_args(args))
        self._transport: DiagTransport | None = None
        self._defs: DefsParser = build_defs_parser(
            defs_file=args.defs,
            cdt_file=args.cdt_file,
            provider=getattr(args, "defs_provider", "auto"),
        )
        self._filter = FilterEngine(getattr(args, "filter", None), logger_name="cdc.filter")

        self._send_lock = threading.Lock()
        self._trace_lock = threading.Lock()
        self._trace_suppressed = False
        self._running = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._inbound_queue: queue.Queue[bytes] = queue.Queue()

        self._tp_running = threading.Event()
        self._tp_thread: threading.Thread | None = None
        self._tp_interval = 2.0
        self._tp_payload = bytes([0x3E, 0x00])

        self.rebuild_transport()

    @property
    def args(self) -> argparse.Namespace:
        return self._args

    @property
    def defs_file(self) -> str | None:
        return self._args.defs

    @property
    def defs_available(self) -> bool:
        return self._defs.available

    def start(self) -> None:
        self._running.set()
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()

    def stop(self) -> None:
        self.stop_tester_present()
        self._running.clear()
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=1.0)
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._adapter.close()

    def bus_info(self) -> dict[str, Any]:
        return self._adapter.runtime_info()

    def send(self, payload: bytes, *, tag: str = "TX") -> None:
        if self._transport is None:
            raise RuntimeError("Transport is not initialized.")

        with self._send_lock:
            self._transport.send(payload)

        decoded = self._parse_defs_for_tx(payload)
        if not self.trace_output_suppressed():
            self._emit(
                self._format_diag_line(
                    direction=tag,
                    payload=payload,
                    src=(self._args.tx_id & 0xFF),
                    tgt=(self._args.rx_id & 0xFF),
                    decoded=decoded,
                )
            )

    def suppress_trace_output(self, enabled: bool) -> None:
        with self._trace_lock:
            self._trace_suppressed = enabled

    def trace_output_suppressed(self) -> bool:
        with self._trace_lock:
            return self._trace_suppressed

    def request(
        self,
        payload: bytes,
        *,
        timeout: float = 1.0,
        matcher: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        """Send payload and wait for an inbound frame matching matcher.

        RX frames are consumed by the background RX worker and mirrored into
        an internal queue used for request/response operations.
        """
        self._drain_inbound_queue()
        self.send(payload)

        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.01, deadline - time.time())
            try:
                resp = self._inbound_queue.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue

            if matcher is None or matcher(resp):
                return resp

        return None

    def rebuild_transport(self) -> None:
        if self._transport is not None:
            self._transport.close()

        bus = self._adapter.open_bus()
        self._transport = build_transport_with_options(
            protocol=self._args.protocol,
            bus=bus,
            tx_id=self._args.tx_id,
            rx_id=self._args.rx_id,
            isotp_addressing=self._args.isotp_addressing,
            source_address=self._args.source_addr,
            target_address=self._args.target_addr,
        )

    def set_tx_id(self, tx_id: int) -> None:
        self._args.tx_id = tx_id
        self.rebuild_transport()

    def set_rx_id(self, rx_id: int) -> None:
        self._args.rx_id = rx_id
        self.rebuild_transport()

    def set_protocol(self, protocol: str) -> None:
        self._args.protocol = protocol
        self.rebuild_transport()

    def set_defs(self, defs_file: str) -> None:
        self._args.defs = defs_file
        self._defs = build_defs_parser(
            defs_file=defs_file,
            cdt_file=self._args.cdt_file,
            provider=getattr(self._args, "defs_provider", "auto"),
        )

    def disable_defs(self) -> None:
        self._args.defs = None
        self._defs = build_defs_parser(
            defs_file=None,
            cdt_file=self._args.cdt_file,
            provider=getattr(self._args, "defs_provider", "auto"),
        )

    def tester_present_status(self) -> dict[str, Any]:
        return {
            "enabled": self._tp_running.is_set(),
            "interval": self._tp_interval,
            "payload": self._tp_payload,
        }

    def start_tester_present(self, interval: float = 2.0, payload: bytes | None = None) -> None:
        if payload is None:
            payload = bytes([0x3E, 0x00])

        self.stop_tester_present()

        self._tp_interval = max(0.1, float(interval))
        self._tp_payload = payload
        self._tp_running.set()
        self._tp_thread = threading.Thread(target=self._tp_loop, daemon=True)
        self._tp_thread.start()

    def stop_tester_present(self) -> None:
        self._tp_running.clear()
        if self._tp_thread is not None:
            self._tp_thread.join(timeout=1.0)
            self._tp_thread = None

    def _tp_loop(self) -> None:
        while self._tp_running.is_set():
            try:
                self.send(self._tp_payload)
            except Exception as exc:  # pylint: disable=broad-except
                self._emit(f"Error: tester present send failed: {exc}")

            deadline = time.time() + self._tp_interval
            while self._tp_running.is_set() and time.time() < deadline:
                time.sleep(0.05)

    def _rx_loop(self) -> None:
        while self._running.is_set():
            if self._transport is None:
                continue

            try:
                payload = self._transport.recv(timeout=0.2)
            except Exception as exc:  # pylint: disable=broad-except
                self._emit(f"Error: transport receive failed: {exc}")
                continue

            if payload is None:
                continue

            if self._should_drop_inbound(payload):
                continue

            self._inbound_queue.put(payload)
            if not self.trace_output_suppressed():
                self._emit(self._format_rx(payload))

    def _should_drop_inbound(self, payload: bytes) -> bool:
        if not self._filter.rules:
            return False

        src = self._args.rx_id & 0xFF
        tgt = self._args.tx_id & 0xFF

        isotp_msg = GenericMessage(
            "isotp",
            {
                "payload": payload,
            },
        )
        if self._filter.should_drop(isotp_msg):
            return True

        kwp_attrs: dict[str, Any] = {
            "src": src,
            "tgt": tgt,
            "payload": payload,
        }
        if payload:
            kwp_attrs["service"] = f"0x{payload[0]:0X}"

        kwp_msg = GenericMessage("kwp", kwp_attrs)
        return self._filter.should_drop(kwp_msg)

    def _drain_inbound_queue(self) -> None:
        while True:
            try:
                self._inbound_queue.get_nowait()
            except queue.Empty:
                return

    def _format_rx(self, payload: bytes) -> str:
        parsed = self._defs.parse(
            payload,
            src=(self._args.rx_id & 0xFF),
            tgt=(self._args.tx_id & 0xFF),
        ) if self._defs.available else None

        return self._format_diag_line(
            direction="RX",
            payload=payload,
            src=(self._args.rx_id & 0xFF),
            tgt=(self._args.tx_id & 0xFF),
            decoded=parsed,
        )

    def _parse_defs_for_tx(self, payload: bytes) -> dict[str, Any] | None:
        if not self._defs.available:
            return None
        return self._defs.parse(
            payload,
            src=(self._args.tx_id & 0xFF),
            tgt=(self._args.rx_id & 0xFF),
        )

    @staticmethod
    def _format_params(params: dict[str, Any]) -> str:
        chunks: list[str] = []
        for key, value in params.items():
            if isinstance(value, dict) and "name" in value and "value" in value:
                raw_val = value.get("value")
                if isinstance(raw_val, int):
                    chunks.append(f"{key}=0x{raw_val:X} ({value['name']})")
                else:
                    chunks.append(f"{key}={raw_val} ({value['name']})")
                continue

            if isinstance(value, (bytes, bytearray)):
                chunks.append(f"{key}={fmt_hex(bytes(value))}")
                continue

            if isinstance(value, int):
                chunks.append(f"{key}=0x{value:X}")
                continue

            chunks.append(f"{key}={value}")

        return ", ".join(chunks)

    def _format_diag_line(
        self,
        *,
        direction: str,
        payload: bytes,
        src: int,
        tgt: int,
        decoded: dict[str, Any] | None,
    ) -> str:
        ts = time.time()
        payload_hex = fmt_hex(payload)
        base = (
            f"[{ts:15.6f}] {direction:3} "
            f"[0x{src:02X}->0x{tgt:02X} | L:0x{len(payload):03X}]"
        )

        if not decoded:
            return f"{base} [{payload_hex}]"

        service_id = decoded.get("service_id")
        service_name = decoded.get("service_name", "")
        params = decoded.get("params", {})

        if isinstance(service_id, int):
            service_label = f"0x{service_id:02X} ({service_name})"
        else:
            service_label = service_name if service_name else payload_hex

        params_label = self._format_params(params) if isinstance(params, dict) else ""
        trailer = f" | {params_label}" if params_label else ""
        return f"{base} [{service_label}{trailer}]"
