from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .adapters import AdapterSettings, build_adapter
from .defs_adapter import DefsParser, build_defs_parser
from .memory_read import KwpMemoryReader, MemoryReadOptions, MemoryReadResult, export_srec
from .protocols import parse_hex_bytes
from .transport import build_transport_with_options, DiagTransport


@dataclass
class DiagClientConfig:
    adapter: str = "python-can"
    interface: str = "gs_usb"
    channel: str | int | None = None
    bitrate: int = 500000
    adapter_options: dict[str, Any] = field(default_factory=dict)

    protocol: str = "kwp2000"
    tx_id: int = 0x6F1
    rx_id: int = 0x612
    isotp_addressing: str = "extended"
    source_addr: int | None = None
    target_addr: int | None = None

    defs: str | None = None
    cdt_file: str | None = None
    defs_provider: str = "auto"


class DiagClient:
    """Programmatic API for diagnostics without the interactive console."""

    def __init__(self, config: DiagClientConfig) -> None:
        self._config = config

        if self._config.source_addr is None:
            self._config.source_addr = self._config.tx_id & 0xFF
        if self._config.target_addr is None:
            self._config.target_addr = self._config.rx_id & 0xFF

        self._adapter = build_adapter(
            AdapterSettings(
                adapter=config.adapter,
                interface=config.interface,
                channel=config.channel,
                bitrate=config.bitrate,
                extra=config.adapter_options,
            )
        )
        self._transport: DiagTransport | None = None
        self._defs: DefsParser = build_defs_parser(
            defs_file=config.defs,
            cdt_file=config.cdt_file,
            provider=config.defs_provider,
        )

        self._send_lock = threading.Lock()
        self._tp_running = threading.Event()
        self._tp_thread: threading.Thread | None = None
        self._tp_interval = 2.0
        self._tp_payload = bytes([0x3E, 0x00])

    def open(self) -> "DiagClient":
        if self._transport is None:
            bus = self._adapter.open_bus()
            self._transport = build_transport_with_options(
                protocol=self._config.protocol,
                bus=bus,
                tx_id=self._config.tx_id,
                rx_id=self._config.rx_id,
                isotp_addressing=self._config.isotp_addressing,
                source_address=self._config.source_addr,
                target_address=self._config.target_addr,
            )
        return self

    def close(self) -> None:
        self.stop_tester_present()
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._adapter.close()

    def __enter__(self) -> "DiagClient":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def bus_info(self) -> dict[str, Any]:
        return self._adapter.runtime_info()

    def send(self, payload: bytes | str) -> None:
        raw = parse_hex_bytes(payload) if isinstance(payload, str) else payload
        if self._transport is None:
            raise RuntimeError("DiagClient is not open.")
        with self._send_lock:
            self._transport.send(raw)

    def recv(self, timeout: float = 0.2) -> bytes | None:
        if self._transport is None:
            raise RuntimeError("DiagClient is not open.")
        return self._transport.recv(timeout=timeout)

    def request(
        self,
        payload: bytes | str,
        timeout: float = 1.0,
        matcher: callable | None = None,
    ) -> bytes | None:
        self.send(payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = self.recv(timeout=min(0.2, max(0.01, deadline - time.time())))
            if response is not None and (matcher is None or matcher(response)):
                return response
        return None

    def decode(self, payload: bytes) -> dict[str, Any] | None:
        if not self._defs.available:
            return None
        return self._defs.parse(
            payload,
            src=(self._config.rx_id & 0xFF),
            tgt=(self._config.tx_id & 0xFF),
        )

    def start_tester_present(self, interval: float = 2.0, payload: bytes | str = b"\x3E\x00") -> None:
        self.stop_tester_present()

        self._tp_interval = max(0.1, float(interval))
        self._tp_payload = parse_hex_bytes(payload) if isinstance(payload, str) else payload
        self._tp_running.set()
        self._tp_thread = threading.Thread(target=self._tp_loop, daemon=True)
        self._tp_thread.start()

    def stop_tester_present(self) -> None:
        self._tp_running.clear()
        if self._tp_thread is not None:
            self._tp_thread.join(timeout=1.0)
            self._tp_thread = None

    def read_memory(
        self,
        start: int,
        end: int,
        *,
        chunk_size: int = 0xF0,
        memory_type: int = 0x00,
        timeout: float = 1.0,
        srec_path: str | None = None,
    ) -> MemoryReadResult:
        if self._transport is None:
            raise RuntimeError("DiagClient is not open.")

        reader = KwpMemoryReader(
            request_fn=lambda payload, req_timeout, m: self.request(
                payload,
                timeout=req_timeout,
                matcher=m,
            ),
            emit=lambda _msg: None,
        )
        result = reader.read_range(
            start,
            end,
            MemoryReadOptions(
                chunk_size=chunk_size,
                memory_type=memory_type,
                timeout=timeout,
            ),
        )
        if srec_path:
            export_srec(result.chunks, srec_path)
        return result

    def _tp_loop(self) -> None:
        while self._tp_running.is_set():
            try:
                self.send(self._tp_payload)
            except Exception:
                pass

            deadline = time.time() + self._tp_interval
            while self._tp_running.is_set() and time.time() < deadline:
                time.sleep(0.05)
