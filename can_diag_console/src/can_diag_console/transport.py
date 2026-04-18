from __future__ import annotations

import queue
import threading
import time
from abc import ABC, abstractmethod

import can
import isotp


class DiagTransport(ABC):
    @abstractmethod
    def send(self, payload: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv(self, timeout: float = 0.1) -> bytes | None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class IsotpDiagTransport(DiagTransport):
    """ISO-TP transport used by UDS and KWP2000 over CAN."""

    def __init__(
        self,
        bus: can.BusABC,
        tx_id: int,
        rx_id: int,
        isotp_addressing: str = "normal",
        source_address: int | None = None,
        target_address: int | None = None,
    ) -> None:
        self._rx_queue: queue.Queue[bytes] = queue.Queue()
        self._stop = threading.Event()

        if isotp_addressing == "extended":
            if source_address is None or target_address is None:
                raise ValueError("Extended ISO-TP addressing requires source_address and target_address.")
            address = isotp.Address(
                isotp.AddressingMode.Extended_11bits,
                txid=tx_id,
                rxid=rx_id,
                source_address=source_address,
                target_address=target_address,
            )
        else:
            address = isotp.Address(
                isotp.AddressingMode.Normal_11bits,
                txid=tx_id,
                rxid=rx_id,
            )
        self._stack = isotp.CanStack(
            bus=bus,
            address=address,
            params={
                "stmin": 0,
                "blocksize": 8,
                "wftmax": 0,
                "tx_padding": 0x00,
                "rx_flowcontrol_timeout": 1000,
                "rx_consecutive_frame_timeout": 1000,
            },
        )
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while not self._stop.is_set():
            self._stack.process()
            if self._stack.available():
                data = self._stack.recv()
                if data is not None:
                    self._rx_queue.put(bytes(data))
            time.sleep(0.001)

    def send(self, payload: bytes) -> None:
        self._stack.send(payload)

    def recv(self, timeout: float = 0.1) -> bytes | None:
        try:
            return self._rx_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)


def build_transport_with_options(
    protocol: str,
    bus: can.BusABC,
    tx_id: int,
    rx_id: int,
    *,
    isotp_addressing: str = "normal",
    source_address: int | None = None,
    target_address: int | None = None,
) -> DiagTransport:
    if protocol in {"kwp2000", "uds"}:
        return IsotpDiagTransport(
            bus=bus,
            tx_id=tx_id,
            rx_id=rx_id,
            isotp_addressing=isotp_addressing,
            source_address=source_address,
            target_address=target_address,
        )
    raise ValueError(f"Unsupported protocol: {protocol}")
