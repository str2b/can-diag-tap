"""CAN Diagnostic Trace. A modular streaming pipeline for CAN/ISOTP diagnostic analysis."""

from __future__ import annotations

import abc
import argparse
import importlib.util
import logging
import os
import struct
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import NamedTuple, Any, TypeAlias, TypedDict

import can
from scapy.all import Raw
from scapy.contrib.automotive.kwp import KWP

from diag_defs import DefsEngine
from diag_filter import FilterEngine


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AddressingMode(Enum):
    """ISOTP addressing modes."""
    STANDARD = "standard"
    EXTENDED = "extended"


def _enable_pyusb_libusb_backend() -> None:
    """Ensure PyUSB can locate a libusb DLL on Windows for gs_usb access."""
    try:
        import libusb_package  # type: ignore
    except Exception:
        return

    try:
        dll_path = Path(libusb_package.get_library_path())
    except Exception:
        return

    if not dll_path.exists():
        return

    dll_dir = str(dll_path.parent)
    path = os.environ.get("PATH", "")
    parts = path.split(";") if path else []
    if dll_dir not in parts:
        os.environ["PATH"] = f"{dll_dir};{path}" if path else dll_dir


def _resolve_live_channel(interface: str, channel: str | None) -> str | int:
    """Resolve the python-can channel, with gs_usb auto-discovery support."""
    if interface != "gs_usb":
        if channel is None:
            raise ValueError("--channel is required when using --interface.")
        return channel

    _enable_pyusb_libusb_backend()

    if channel is not None:
        try:
            return int(channel)
        except (TypeError, ValueError):
            return channel

    try:
        from gs_usb.gs_usb import GsUsb  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "gs_usb requires gs-usb/pyusb/libusb-package packages in the active environment."
        ) from exc

    devices = list(GsUsb.scan())
    if not devices:
        raise RuntimeError(
            "No gs_usb devices detected. Check USB connection and WinUSB driver."
        )
    return 0


# ---------------------------------------------------------------------------
# Type aliases and structured dicts
# ---------------------------------------------------------------------------

CanFrameEntry: TypeAlias = tuple[float, str, int, bytes]  # (timestamp, direction, arb_id, payload)
SessionKey: TypeAlias = int | tuple[int, int]  # standard (int) or extended (arb_id, target_addr)


class ServiceInfo(TypedDict, total=False):
    """Service definition lookup result."""
    service_id: int
    service_name: str
    src: int
    tgt: int
    params: dict[str, Any]


class ISOTPSession(TypedDict):
    """Active ISOTP reassembly session."""
    dl: int
    data: bytearray
    sn: int
    started: float
    can_frames: list[CanFrameEntry]


# ---------------------------------------------------------------------------
# Data classes - one per protocol layer
# ---------------------------------------------------------------------------

class Message(abc.ABC):
    """Base class for protocol messages flowing through the pipeline.

    Provides layer identification and filter attributes for rule evaluation.
    """

    @property
    @abc.abstractmethod
    def layer(self) -> str:
        """The protocol layer name (e.g. 'can', 'isotp', 'kwp')."""
        return ""

    @abc.abstractmethod
    def filter_attrs(self) -> dict:
        """Attributes exposed to FilterEngine for rule evaluation."""
        return {}


class CANFrame(Message):
    """Wraps a raw can.Message with a resolved direction field."""

    def __init__(self, arb_id: int, data: bytes, timestamp: float, direction: str):
        self.arb_id: int = arb_id
        self.data: bytes = data
        self.timestamp: float = timestamp
        self.direction: str = direction

    @property
    def layer(self) -> str:
        return "can"

    def filter_attrs(self) -> dict[str, Any]:
        return {"id": self.arb_id, "payload": self.data}


class ISOTPMessage(Message):
    """Carries a fully reassembled ISOTP data payload and its metadata."""

    def __init__(self, rx_id: int, tgt_addr: int, time: float, direction: str,
                 data: bytes, can_frames: list[CanFrameEntry] | None = None):
        self.rx_id: int = rx_id
        self.tgt_addr: int = tgt_addr
        self.time: float = time
        self.direction: str = direction
        self.data: bytes = data
        self.can_frames: list[CanFrameEntry] = can_frames or []

    @property
    def layer(self) -> str:
        return "isotp"

    def filter_attrs(self) -> dict[str, Any]:
        return {"payload": self.data}


class KWPMessage(Message):
    """Carries a decoded KWP service message and its metadata."""

    def __init__(self, isotp_msg: ISOTPMessage, service_id: int, service_name: str,
                 params: dict[str, Any], scapy_pkt: Any = None):
        self.isotp_msg: ISOTPMessage = isotp_msg
        self.src: int = isotp_msg.rx_id & 0xFF
        self.tgt: int = isotp_msg.tgt_addr
        self.time: float = isotp_msg.time
        self.direction: str = isotp_msg.direction
        self.service_id: int = service_id
        self.service_name: str = service_name
        self.params: dict[str, Any] = params
        self.data: bytes = isotp_msg.data
        self._scapy_pkt: Any = scapy_pkt

    @property
    def layer(self) -> str:
        return "kwp"

    @property
    def packet(self) -> Any:
        """Uniform access to the Scapy KWP object (lazy-loaded if decoded via Defs)."""
        if self._scapy_pkt is None:
            self._scapy_pkt = KWP(self.data)
        return self._scapy_pkt

    def filter_attrs(self) -> dict[str, Any]:
        """Attributes exposed to FilterEngine for rule evaluation."""
        return {
            "src": self.src,
            "tgt": self.tgt,
            "service": f"0x{self.service_id:0X}",
            "payload": self.data,
        }


# ---------------------------------------------------------------------------
# DefsEngine
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ISOTPReassembler
# ---------------------------------------------------------------------------

class _ISOTPFrame(NamedTuple):
    """Addressing-resolved view of a CAN frame, ready for ISOTP processing."""
    rx_id: int
    target_addr: int
    isotp_payload: bytes
    session_key: SessionKey
    timestamp: float
    direction: str
    frame_entry: CanFrameEntry


class ISOTPReassembler:
    """Stateful ISOTP session reassembler. Consumes CANFrames, yields ISOTPMessage on completion."""

    @dataclass
    class Config:
        addressing: AddressingMode = AddressingMode.STANDARD
        physical_ids: list[str] | None = None
        functional_ids: list[str] | None = None
        session_timeout: float = 2.0

    def __init__(self, config: ISOTPReassembler.Config | None = None):
        if config is None:
            config = self.Config()

        self.addressing: AddressingMode = config.addressing
        self.session_timeout: float = config.session_timeout
        self._sessions: dict[SessionKey, ISOTPSession] = {}
        self._id_to_target: dict[int, int] = {}
        self._use_custom_ids = config.physical_ids is not None or config.functional_ids is not None
        self._diagnostic_ids = set()
        for ids_list in (config.physical_ids, config.functional_ids):
            if not ids_list:
                continue
            for rxid in ids_list:
                try:
                    parsed = int(rxid, 16) if rxid.lower().startswith("0x") else int(rxid)
                    self._diagnostic_ids.add(parsed)
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

    def is_isotp_id(self, arb_id: int) -> bool:
        """Returns True if this arb_id should be treated as an ISOTP frame."""
        if self._use_custom_ids:
            return arb_id in self._diagnostic_ids
        if 0x600 <= arb_id <= 0x6FF:
            return True
        if 0x7DF <= arb_id <= 0x7EF:
            return True
        if arb_id & 0x00FFFF00 in (0x00DA0000, 0x00DB0000):
            return True
        return False

    def process(self, can_frame: CANFrame) -> ISOTPMessage | None:
        """Process a CANFrame. Returns an ISOTPMessage on reassembly completion, or None."""
        frame = self._extract_addressing(can_frame)
        if frame is None:
            return None

        self._evict_stale(frame.timestamp)

        pci = frame.isotp_payload[0] >> 4
        if pci == 0:
            return self._handle_sf(frame)
        if pci == 1:
            self._handle_ff(frame)
        if pci == 2:
            return self._handle_cf(frame)
        if pci == 3:
            self._handle_fc(frame)
        return None

    def _extract_addressing(self, can_frame: CANFrame) -> _ISOTPFrame | None:
        """Resolve addressing fields from a CANFrame based on the configured mode.

        Returns an _ISOTPFrame or None if the frame is invalid.
        """
        payload = can_frame.data
        arb_id = can_frame.arb_id
        timestamp = can_frame.timestamp
        direction = can_frame.direction

        if not payload:
            return None

        if self.addressing == AddressingMode.EXTENDED:
            if len(payload) < 2:
                return None
            target_addr = payload[0]
            self._id_to_target[arb_id] = target_addr
            isotp_payload = payload[1:]
            session_key = (arb_id, target_addr)
        else:
            target_addr = self._id_to_target.get(arb_id, 0xFF)
            isotp_payload = payload
            session_key = arb_id

        if not isotp_payload:
            return None

        return _ISOTPFrame(
            rx_id=arb_id,
            target_addr=target_addr,
            isotp_payload=isotp_payload,
            session_key=session_key,
            timestamp=timestamp,
            direction=direction,
            frame_entry=(timestamp, direction, arb_id, payload),
        )

    @staticmethod
    def _fmt_key(key: SessionKey) -> str:
        if isinstance(key, tuple):
            return f"(0x{key[0]:X}, 0x{key[1]:X})"
        return f"0x{key:X}"

    @staticmethod
    def _fmt_partial_payload(data: bytearray, max_len: int = 16) -> str:
        if not data:
            return "<empty>"
        clipped = bytes(data[:max_len])
        hex_part = " ".join(f"{b:02X}" for b in clipped)
        if len(data) > max_len:
            return f"{hex_part} ..."
        return hex_part

    def _evict_stale(self, timestamp: float):
        """Remove sessions that have exceeded the inactivity timeout."""
        if self.session_timeout <= 0:
            return
        stale = [k for k, v in self._sessions.items()
                 if timestamp - v["started"] > self.session_timeout]
        for k in stale:
            sess = self._sessions[k]
            partial = self._fmt_partial_payload(sess["data"])
            got = len(sess["data"])
            direction = sess["can_frames"][0][1] if sess["can_frames"] else "?"
            logging.getLogger("cdt.isotp").warning(
                "Dropped ISOTP session on %s dir=%s: timeout exceeded (expected %d bytes, got %d, partial=%s)",
                self._fmt_key(k), direction, sess["dl"], got, partial
            )
            del self._sessions[k]

    def _handle_sf(self, frame: _ISOTPFrame) -> ISOTPMessage | None:
        """Handle a Single Frame (PCI=0). Returns ISOTPMessage or None."""
        max_sf_dl = 7 if self.addressing == AddressingMode.STANDARD else 6
        dl = frame.isotp_payload[0] & 0x0F
        if not (0 < dl <= len(frame.isotp_payload) - 1) or dl > max_sf_dl:
            return None
        extracted = frame.isotp_payload[1: 1 + dl]
        padding = frame.isotp_payload[1 + dl:]
        if padding and (len(set(padding)) > 1 or padding[0] not in (0x00, 0x55, 0xAA, 0xCC, 0xFF)):
            return None
        return ISOTPMessage(frame.rx_id, frame.target_addr, frame.timestamp,
                            frame.direction, bytes(extracted), [frame.frame_entry])

    def _handle_ff(self, frame: _ISOTPFrame):
        """Handle a First Frame (PCI=1). Opens a new reassembly session."""
        max_sf_dl = 7 if self.addressing == AddressingMode.STANDARD else 6
        if len(frame.isotp_payload) < 2:
            return
        if frame.session_key in self._sessions:
            logging.getLogger("cdt.isotp").warning(
                "Dropped ISOTP session on %s: overwritten by new First Frame", self._fmt_key(frame.session_key)
            )
        dl = ((frame.isotp_payload[0] & 0x0F) << 8) | frame.isotp_payload[1]
        if dl > max_sf_dl:
            self._sessions[frame.session_key] = {
                "dl": dl,
                "data": bytearray(frame.isotp_payload[2:]),
                "sn": 1,
                "started": frame.timestamp,
                "can_frames": [frame.frame_entry],
            }

    def _handle_cf(self, frame: _ISOTPFrame) -> ISOTPMessage | None:
        """Handle a Consecutive Frame (PCI=2). Returns ISOTPMessage on completion or None."""
        if frame.session_key not in self._sessions:
            logging.getLogger("cdt.isotp").warning(
                "Dropped ISOTP CF on %s: no active session (orphan CF)", self._fmt_key(frame.session_key)
            )
            return None
        sess = self._sessions[frame.session_key]
        sn = frame.isotp_payload[0] & 0x0F
        if sn != sess["sn"]:
            logging.getLogger("cdt.isotp").warning(
                "Dropped ISOTP session on %s: sequence mismatch (expected %X, got %X)",
                self._fmt_key(frame.session_key), sess["sn"], sn
            )
            del self._sessions[frame.session_key]
            return None
        sess["data"].extend(frame.isotp_payload[1:])
        sess["sn"] = (sn + 1) & 0x0F
        sess["can_frames"].append(frame.frame_entry)
        if len(sess["data"]) >= sess["dl"]:
            full_data = bytes(sess["data"][: sess["dl"]])
            frames = sess["can_frames"]
            del self._sessions[frame.session_key]
            return ISOTPMessage(frame.rx_id, frame.target_addr, frame.timestamp,
                                frame.direction, full_data, frames)
        return None

    @staticmethod
    def _handle_fc(_frame: _ISOTPFrame):
        """Handle a Flow Control frame (PCI=3). Transport handshake, no application data."""

    def reset(self):
        """Clears all active reassembly sessions (call before each analyze pass)."""
        self._sessions.clear()
        self._id_to_target.clear()


# ---------------------------------------------------------------------------
# Protocol Layer - registry pattern, multiple decoders active simultaneously
#
#   ProtocolDecoder (ABC)
#    KWPDecoder   (KWP2000 / ISO 14230)
#
#   ProtocolRegistry   tries each decoder in order, dispatches first match
# ---------------------------------------------------------------------------

class ProtocolDecoder(abc.ABC):
    """Decodes ISOTPMessages into typed application-layer protocol messages."""

    @abc.abstractmethod
    def process(self, isotp_msg: ISOTPMessage) -> "Message | None":
        """Return a decoded protocol message, or None if not applicable."""


class ProtocolRegistry:
    """Tries each ProtocolDecoder in order; dispatches the first successful result."""

    def __init__(self):
        self._decoders: list[ProtocolDecoder] = []

    def register(self, decoder: ProtocolDecoder) -> "ProtocolRegistry":
        """Add a decoder and return self for fluent chaining."""
        self._decoders.append(decoder)
        return self

    def process(self, isotp_msg: ISOTPMessage) -> "Message | None":
        for decoder in self._decoders:
            result = decoder.process(isotp_msg)
            if result is not None:
                return result
        return None


class KWPDecoder(ProtocolDecoder):
    """Decodes KWP messages from ISOTPMessage payloads.

    Tries DefsEngine first for fast custom-JSON decoding; falls back to Scapy
    transparently. Always returns a KWPMessage - the caller never sees raw dicts
    or Scapy internals.
    """

    def __init__(self, defs_engine: DefsEngine) -> None:
        self.defs: DefsEngine = defs_engine

    def process(self, isotp_msg: ISOTPMessage) -> KWPMessage | None:
        """Decode an ISOTPMessage as KWP. Returns KWPMessage or None if not decodable."""
        data = isotp_msg.data
        if len(data) < 1 or data[0] not in range(0x10, 0xFF):
            return None

        try:
            message_context = {
                "src": isotp_msg.rx_id & 0xFF,
                "tgt": isotp_msg.tgt_addr,
                "service_id": data[0],
                "service_name": "",
                "params": {},
            }

            decoded_info = self.defs.parse_payload(data, message_context)
            if decoded_info:
                return KWPMessage(
                    isotp_msg=isotp_msg,
                    service_id=decoded_info["service_id"],
                    service_name=decoded_info["service_name"],
                    params=decoded_info["params"],
                    scapy_pkt=None,
                )

            # Scapy fallback
            scapy_pkt = KWP(data)
            service_id, service_name, params = self._decode_via_scapy(scapy_pkt, message_context)
            return KWPMessage(
                isotp_msg=isotp_msg,
                service_id=service_id,
                service_name=service_name,
                params=params,
                scapy_pkt=scapy_pkt,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.getLogger("cdt.kwp").debug(
                "Error decoding KWP 0x%02X on 0x%X: %s", data[0], isotp_msg.rx_id, e,
            )
            return None

    def _decode_via_scapy(self, kwp_pkt: Any, message_context: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
        """Extract service id, name, and params dict from a Scapy KWP packet."""
        service_id = kwp_pkt.fields.get("service", 0)
        service_name = kwp_pkt.sprintf("%KWP.service%")

        if service_name.startswith("0x") or service_name.isdigit():
            request_service_name = None
            if isinstance(service_id, int) and service_id > 0x40:
                request_service_id = service_id - 0x40
                _, request_service_name = self.defs.lookup(request_service_id, message_context)
                if not request_service_name:
                    try:
                        candidate = KWP(bytes([request_service_id])).sprintf("%KWP.service%")
                        if not (candidate.startswith("0x") or candidate.isdigit()):
                            request_service_name = candidate
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass
            service_name = (
                f"{request_service_name}PositiveResponse"
                if request_service_name
                else f"UnknownService_{service_id:02X}"
            )

        decoded_params = {}
        if kwp_pkt.payload:
            for k, v in kwp_pkt.payload.fields.items():
                if isinstance(v, int):
                    field_obj = kwp_pkt.payload.get_field(k)
                    if field_obj:
                        repr_val = str(field_obj.i2repr(kwp_pkt.payload, v))
                        if repr_val.startswith("'") and repr_val.endswith("'"):
                            repr_val = repr_val[1:-1]
                        if repr_val and not repr_val.isdigit() and not repr_val.lower().startswith("0x"):
                            decoded_params[k] = {"value": v, "name": repr_val}
                        else:
                            decoded_params[k] = v
                    else:
                        decoded_params[k] = v
                else:
                    decoded_params[k] = v
            if kwp_pkt.haslayer(Raw):
                raw_bytes = getattr(kwp_pkt.getlayer(Raw), "load", b"")
                if raw_bytes:
                    decoded_params["raw_payload"] = raw_bytes

        return service_id, service_name, decoded_params


# ---------------------------------------------------------------------------
# Plugin Registry - fan-out pattern, all plugins receive every event
#
#   PluginRegistry
#    load(path)            dynamically imports a plugin module
#    add_arguments(parser) lets plugins register their own CLI args
#    init(args)            initializes all plugins after arg parsing
#    dispatch(msg)         calls on_{layer}_message(msg) on each plugin
#    teardown()            graceful shutdown for all plugins
# ---------------------------------------------------------------------------

class PluginRegistry:
    """Loads plugin modules and fans out protocol events to all of them."""

    def __init__(self) -> None:
        self._plugins: list[Any] = []

    def load(self, path: str) -> "PluginRegistry":
        """Dynamically load a plugin from a file path. Returns self for chaining."""
        abs_path = os.path.abspath(path)
        name = f"cdt_plugin_{len(self._plugins)}"
        spec = importlib.util.spec_from_file_location(name, abs_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create module spec for plugin: {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        self._plugins.append(mod)
        logging.getLogger("cdt.plugins").info("Loaded plugin: %s", path)
        return self

    def add_arguments(self, parser: argparse.ArgumentParser):
        """Let each plugin register its own CLI arguments."""
        for plugin in self._plugins:
            if hasattr(plugin, "add_arguments"):
                plugin.add_arguments(parser)

    def init(self, args: argparse.Namespace):
        """Initialize all plugins after CLI argument parsing."""
        for plugin in self._plugins:
            if hasattr(plugin, "init"):
                plugin.init(args)

    def teardown(self):
        """Tear down all plugins in load order."""
        for plugin in self._plugins:
            if hasattr(plugin, "teardown"):
                plugin.teardown()

    def dispatch(self, msg: Message):
        """Call on_{layer}_message(msg) on every plugin that implements it."""
        handler = f"on_{msg.layer}_message"
        for plugin in self._plugins:
            fn = getattr(plugin, handler, None)
            if fn:
                fn(msg)


# ---------------------------------------------------------------------------
# TraceAnalyzer - pure pipeline orchestrator
# ---------------------------------------------------------------------------

class TraceAnalyzer:
    """Orchestrates the CAN -> ISOTP -> Protocol pipeline over a file or live bus."""

    @dataclass
    class Config:
        trace_file: str | None = None
        interface: str | None = None
        channel: str | None = None
        bitrate: int | None = None
        addressing: AddressingMode = AddressingMode.STANDARD
        filter_file: str | None = None
        physical_ids: list[str] | None = None
        functional_ids: list[str] | None = None
        protocols: ProtocolRegistry | None = None
        plugins: PluginRegistry | None = None

    def __init__(self, config: TraceAnalyzer.Config):
        self.config: TraceAnalyzer.Config = config
        self.filter: FilterEngine = FilterEngine(config.filter_file, logger_name="cdt.filter")
        self.reassembler: ISOTPReassembler = ISOTPReassembler(
            ISOTPReassembler.Config(
                addressing=config.addressing,
                physical_ids=config.physical_ids,
                functional_ids=config.functional_ids,
            )
        )
        self.protocols: ProtocolRegistry = config.protocols or ProtocolRegistry()
        self.plugins: PluginRegistry = config.plugins or PluginRegistry()

        self.can_count: int = 0
        self.isotp_count: int = 0
        self.protocol_count: int = 0

    def analyze(self):
        """Open the data source and run the full protocol pipeline until exhausted."""
        source_reader = self._open_source()
        self.reassembler.reset()
        self.can_count = self.isotp_count = self.protocol_count = 0

        try:
            for can_message in source_reader:
                if can_message.is_error_frame or can_message.is_remote_frame:
                    continue

                #  CAN layer
                direction = "Rx" if can_message.is_rx else "Tx"
                can_frame = CANFrame(
                    can_message.arbitration_id, can_message.data, can_message.timestamp, direction
                )

                if self.filter.should_drop(can_frame):
                    continue

                self.can_count += 1
                self.plugins.dispatch(can_frame)

                #  ISOTP layer
                if not self.reassembler.is_isotp_id(can_frame.arb_id):
                    continue

                isotp_msg = self.reassembler.process(can_frame)
                if not isotp_msg:
                    continue

                if self.filter.should_drop(isotp_msg):
                    continue

                self.isotp_count += 1
                self.plugins.dispatch(isotp_msg)

                #  Protocol layer
                protocol_msg = self.protocols.process(isotp_msg)
                if not protocol_msg:
                    continue

                if self.filter.should_drop(protocol_msg):
                    continue

                self.protocol_count += 1
                self.plugins.dispatch(protocol_msg)

        except KeyboardInterrupt:
            logging.getLogger("cdt.analyzer").info("Capture interrupted by user.")
        except struct.error as exc:
            if self.config.interface == "gs_usb" and "buffer of 24 bytes" in str(exc):
                raise RuntimeError(
                    "gs_usb frame unpack failed (short USB frame). "
                    "This is commonly caused by hardware timestamps in some gs_usb/python-can combinations. "
                    "The tool now disables gs_usb hardware timestamps by default; "
                    "if this persists, reconnect adapter and ensure WinUSB/libusb are configured."
                ) from exc
            raise
        finally:
            self._close_source(source_reader)

        logging.getLogger("cdt.analyzer").info(
            "Processed %d CAN frames, yielding %d ISOTPs and %d protocol messages (after filtering).",
            self.can_count, self.isotp_count, self.protocol_count,
        )

    @staticmethod
    def _close_source(source_reader: can.Bus | can.ASCReader | can.BLFReader) -> None:
        """Close/shutdown source reader if supported to avoid destructor-time errors."""
        shutdown_fn = getattr(source_reader, "shutdown", None)
        if callable(shutdown_fn):
            try:
                shutdown_fn()
            except Exception:
                pass

        close_fn = getattr(source_reader, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass

    def _open_source(self) -> can.Bus | can.ASCReader | can.BLFReader:
        """Open and return a CAN message iterator (live bus or trace file reader)."""
        if self.config.interface:
            channel = _resolve_live_channel(self.config.interface, self.config.channel)
            if (
                self.config.interface == "gs_usb"
                and self.config.bitrate is not None
                and self.config.bitrate > 1_000_000
            ):
                raise ValueError(
                    "Unsupported gs_usb bitrate. gs_usb in this tool uses nominal CAN bitrate "
                    "(typically up to 1000000)."
                )
            logging.getLogger("cdt.analyzer").info(
                "Opening LIVE interface '%s' on channel '%s'...",
                self.config.interface, channel,
            )
            kwargs = {"interface": self.config.interface, "channel": channel}
            if self.config.bitrate:
                kwargs["bitrate"] = self.config.bitrate
            if self.config.interface == "gs_usb":
                # Avoid known short-frame unpack failures on some gs_usb setups.
                kwargs.setdefault("disable_hw_timestamps", True)
            try:
                return can.Bus(**kwargs)
            except ValueError as exc:
                # python-can/gs_usb raises this when bitrate cannot be represented by device timing.
                if (
                    self.config.interface == "gs_usb"
                    and "No suitable bit timings found" in str(exc)
                ):
                    raise ValueError(
                        "Unsupported gs_usb bitrate. Use a nominal CAN bitrate supported by your adapter/bus "
                        "(commonly 125000, 250000, 500000, or 1000000)."
                    ) from exc
                raise

        if not self.config.trace_file:
            raise ValueError("Specify a trace_file or a live --interface (with --channel).")

        # Auto-detect trace format by extension
        ext = Path(self.config.trace_file).suffix.lower()
        reader_map = {
            ".asc": can.ASCReader,
            ".blf": can.BLFReader,
        }

        if ext not in reader_map:
            raise ValueError(
                f"Unsupported trace format: {ext}. Supported: {', '.join(reader_map.keys())}"
            )

        logging.getLogger("cdt.analyzer").info(
            "Reading %s (format: %s) in real-time streaming mode...",
            self.config.trace_file, ext[1:].upper(),
        )
        return reader_map[ext](self.config.trace_file)


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def setup_parser() -> argparse.ArgumentParser:
    """Build and return the core argument parser."""
    parser = argparse.ArgumentParser(
        description="Python-based CAN Trace Analyzer using Scapy"
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "-t", "--trace",
        dest="trace_file",
        help="Path to the .asc or .blf trace file to analyze.",
    )
    source_group.add_argument(
        "-i", "--interface",
        help="Live python-can interface (e.g., 'pcan', 'socketcan', 'vector').",
    )

    live_group = parser.add_argument_group(
        "live options", "Arguments only applicable when using --interface."
    )
    live_group.add_argument(
        "-c", "--channel",
        help="python-can channel (e.g., 'vcan0', 'PCAN_USBBUS1').",
    )
    live_group.add_argument(
        "-b", "--bitrate", type=int,
        help="Bitrate for the live interface (e.g., 500000).",
    )

    parser.add_argument(
        "-a", "--addressing",
        type=AddressingMode,
        choices=list(AddressingMode),
        default=AddressingMode.EXTENDED,
        help="Type of ISOTP addressing layer (default: extended).",
    )
    parser.add_argument(
        "-d", "--defs",
        help="Optional JSON file defining custom service layouts to override Scapy.",
    )
    parser.add_argument(
        "-f", "--filter",
        help="Optional JSON filter engine configuration to dynamically route and drop payloads.",
    )
    parser.add_argument(
        "-p", "--protocols", nargs="+", default=["kwp"],
        choices=["kwp", "uds"],
        help="Protocols to decode (default: kwp). UDS is not yet implemented.",
    )
    parser.add_argument(
        "-pids", "--physical-ids", nargs="+",
        help="Optional list of physical CAN Arbitration IDs (hex or decimal).",
    )
    parser.add_argument(
        "-fids", "--functional-ids", nargs="+",
        help="Optional list of functional CAN Arbitration IDs (hex or decimal)."
             "to natively parse as ISO-TP.",
    )
    _add_plugin_argument(parser)
    return parser


def _add_plugin_argument(parser: argparse.ArgumentParser):
    """Add the plugin argument to a parser."""
    parser.add_argument(
        "-P", "--plugin", nargs="+", default=[],
        metavar="FILE",
        help="One or more Python plugin files (e.g. plugins/trace_printer.py).",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Build the plugin registry, parse arguments, assemble the pipeline, and run."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(message)s",
        stream=sys.stderr,
    )

    # Pre-parse to discover plugins before the main parser enforces required args.
    # Plugins may call add_arguments() to register their own flags.
    pre_parser = argparse.ArgumentParser(add_help=False)
    _add_plugin_argument(pre_parser)
    pre_args, _ = pre_parser.parse_known_args()

    plugins = PluginRegistry()
    for path in pre_args.plugin:
        try:
            plugins.load(path)
        except Exception as e: 
            logging.getLogger("cdt.plugins").error("Failed to load plugin %s: %s", path, e)

    arg_parser = setup_parser()
    plugins.add_arguments(arg_parser)
    args = arg_parser.parse_args()

    if args.interface:
        if not args.channel and args.interface != "gs_usb":
            arg_parser.error("--channel is required when using --interface.")
    else:
        if args.channel:
            arg_parser.error("--channel can only be used with --interface.")
        if args.bitrate:
            arg_parser.error("--bitrate can only be used with --interface.")

    protocols = ProtocolRegistry()
    if "kwp" in args.protocols:
        protocols.register(KWPDecoder(DefsEngine(args.defs)))
    if "uds" in args.protocols:
        logging.getLogger("cdt").warning("UDS decoder not yet implemented.")

    plugins.init(args)

    try:
        config = TraceAnalyzer.Config(
            trace_file=args.trace_file,
            interface=args.interface,
            channel=args.channel,
            bitrate=args.bitrate,
            addressing=args.addressing,
            filter_file=args.filter,
            physical_ids=args.physical_ids,
            functional_ids=args.functional_ids,
            protocols=protocols,
            plugins=plugins,
        )
        TraceAnalyzer(config).analyze()
    finally:
        plugins.teardown()


if __name__ == "__main__":
    main()
