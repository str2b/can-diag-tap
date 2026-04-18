from __future__ import annotations

import argparse
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import can


def _patch_gs_usb_read_compat() -> None:
    """Patch gs_usb read() to tolerate 20/24-byte frame variants.

    Some firmware/runtime combinations may return frame lengths that do not
    match the mode-selected unpack path exactly, causing struct errors.
    """
    try:
        import usb.core  # type: ignore
        import gs_usb.gs_usb as gs_usb_mod  # type: ignore
        from gs_usb.gs_usb_frame import GsUsbFrame  # type: ignore
    except Exception:
        return

    if getattr(gs_usb_mod.GsUsb.read, "_can_diag_console_patched", False):
        return

    def _compat_read(self, frame, timeout_ms):
        hw_timestamps = (
            (self.device_flags & gs_usb_mod.GS_CAN_MODE_HW_TIMESTAMP)
            == gs_usb_mod.GS_CAN_MODE_HW_TIMESTAMP
        )
        try:
            data = self.gs_usb.read(0x81, frame.__sizeof__(hw_timestamps), timeout_ms)
        except usb.core.USBError:
            return False

        if not data:
            return False

        data_len = len(data)
        if data_len == 24:
            GsUsbFrame.unpack_into(frame, data, True)
            return True
        if data_len == 20:
            GsUsbFrame.unpack_into(frame, data, False)
            return True

        # Unexpected frame size: report no frame instead of crashing worker threads.
        return False

    _compat_read._can_diag_console_patched = True  # type: ignore[attr-defined]
    gs_usb_mod.GsUsb.read = _compat_read


@dataclass
class AdapterSettings:
    adapter: str
    interface: str
    channel: str | int | None
    bitrate: int
    extra: dict[str, Any] = field(default_factory=dict)


AdapterFactory = Callable[[AdapterSettings], "BusAdapter"]
_ADAPTER_FACTORIES: dict[str, AdapterFactory] = {}


def _enable_pyusb_libusb_backend() -> None:
    """Ensure PyUSB can find a libusb DLL on Windows.

    gs_usb via python-can uses PyUSB. On Windows, WinUSB is the device driver,
    but PyUSB still requires libusb userspace DLL availability.
    """
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

    _patch_gs_usb_read_compat()


class BusAdapter(ABC):
    """Adapter boundary between the console and underlying hardware driver."""

    def __init__(self, settings: AdapterSettings) -> None:
        self._settings = settings
        self._bus: can.BusABC | None = None

    @property
    def settings(self) -> AdapterSettings:
        return self._settings

    @abstractmethod
    def open_bus(self) -> can.BusABC:
        raise NotImplementedError

    def close(self) -> None:
        if self._bus is None:
            return
        shutdown = getattr(self._bus, "shutdown", None)
        if callable(shutdown):
            shutdown()
        self._bus = None

    def runtime_info(self) -> dict[str, Any]:
        return {
            "adapter": self.settings.adapter,
            "interface": self.settings.interface,
            "channel": self.settings.channel,
            "bitrate": self.settings.bitrate,
            "adapter_options": self.settings.extra,
            "bus_open": self._bus is not None,
        }


class PythonCanAdapter(BusAdapter):
    """Default adapter using python-can for USB/CAN interfaces."""

    def __init__(self, settings: AdapterSettings) -> None:
        super().__init__(settings)
        self._selected_gs_usb: dict[str, Any] | None = None

    def _resolve_channel(self) -> str | int | None:
        if self.settings.interface != "gs_usb":
            return self.settings.channel

        # gs_usb depends on PyUSB/libusb userspace wiring and compatibility patching.
        _enable_pyusb_libusb_backend()

        if self.settings.channel is not None:
            try:
                return int(self.settings.channel)
            except (TypeError, ValueError):
                return self.settings.channel

        requested_serial = self.settings.extra.get("serial")
        configs = discover_gs_usb_configs()
        if not configs:
            raise RuntimeError(
                "No gs_usb devices detected. Check driver (WinUSB) and connection."
            )

        selected = select_gs_usb_config(configs, requested_serial=requested_serial)
        if selected is None:
            raise RuntimeError(
                f"No gs_usb device matched serial={requested_serial!r}."
            )

        self._selected_gs_usb = selected

        channel = selected.get("channel")
        if channel is None:
            raise RuntimeError(
                "Detected gs_usb config did not provide a channel. Set --channel explicitly."
            )

        self.settings.channel = int(channel)
        return channel

    def open_bus(self) -> can.BusABC:
        if self._bus is None:
            channel = self._resolve_channel()
            self._bus = can.Bus(
                interface=self.settings.interface,
                channel=channel,
                bitrate=self.settings.bitrate,
            )
            self._post_open_tuning()
        return self._bus

    def _post_open_tuning(self) -> None:
        """Apply backend-specific tuning after opening the bus.

        Some gs_usb firmware/driver combinations report HW timestamp support but
        return classic 20-byte frames, which crashes python-can unpacking when
        HW timestamp mode is enabled. Re-starting in normal mode avoids this.
        """
        if self._bus is None or self.settings.interface != "gs_usb":
            return

        disable_hw_ts = bool(self.settings.extra.get("disable_hw_timestamps", True))
        if not disable_hw_ts:
            return

        gs_dev = getattr(self._bus, "gs_usb", None)
        if gs_dev is None:
            return

        try:
            from gs_usb.constants import GS_CAN_MODE_NORMAL  # type: ignore

            gs_dev.stop()
            gs_dev.start(flags=GS_CAN_MODE_NORMAL)
        except Exception:
            # Keep default behavior if tuning fails; bus may still be usable.
            pass

    def runtime_info(self) -> dict[str, Any]:
        info = super().runtime_info()
        if self.settings.interface == "gs_usb":
            info["gs_usb_selected"] = self._selected_gs_usb
        return info


class KDcanAdapter(BusAdapter):
    """K/DCAN adapter placeholder.

    This keeps architecture-ready separation. A concrete implementation can
    later be dropped in here (or loaded as an external adapter) without
    touching console/transport code.
    """

    def open_bus(self) -> can.BusABC:
        raise NotImplementedError(
            "K/DCAN adapter hook is defined, but no concrete K/DCAN driver is wired yet. "
            "Use --adapter python-can for now and integrate your K/DCAN backend in this adapter."
        )


def register_adapter(name: str, factory: AdapterFactory) -> None:
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("Adapter name must not be empty.")
    _ADAPTER_FACTORIES[normalized] = factory


def available_adapters() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTER_FACTORIES.keys()))


def parse_adapter_options(raw_json: str | None) -> dict[str, Any]:
    if not raw_json:
        return {}
    parsed = json.loads(raw_json)
    if not isinstance(parsed, dict):
        raise ValueError("--adapter-options must be a JSON object.")
    return parsed


def settings_from_args(args: argparse.Namespace) -> AdapterSettings:
    return AdapterSettings(
        adapter=args.adapter,
        interface=args.interface,
        channel=args.channel,
        bitrate=args.bitrate,
        extra=parse_adapter_options(getattr(args, "adapter_options", None)),
    )


def build_adapter(settings: AdapterSettings) -> BusAdapter:
    adapter_name = settings.adapter.strip().lower()
    factory = _ADAPTER_FACTORIES.get(adapter_name)
    if factory is None:
        supported = ", ".join(available_adapters())
        raise ValueError(f"Unsupported adapter: {settings.adapter}. Supported adapters: {supported}")
    return factory(settings)


def _register_builtin_adapters() -> None:
    register_adapter("python-can", PythonCanAdapter)
    register_adapter("kdcan", KDcanAdapter)


_register_builtin_adapters()


def discover_gs_usb_configs() -> list[dict[str, Any]]:
    """Return gs_usb configs discovered via the gs_usb library scan API."""
    _enable_pyusb_libusb_backend()
    try:
        from gs_usb.gs_usb import GsUsb  # type: ignore
    except Exception:
        return []

    configs: list[dict[str, Any]] = []
    for index, dev in enumerate(GsUsb.scan()):
        configs.append(
            {
                "interface": "gs_usb",
                "channel": index,
                "serial": getattr(dev, "serial_number", None),
                "usb_bus": getattr(dev, "bus", None),
                "usb_address": getattr(dev, "address", None),
            }
        )
    return configs


def select_gs_usb_config(
    configs: list[dict[str, Any]], requested_serial: str | None = None
) -> dict[str, Any] | None:
    if not configs:
        return None
    if requested_serial is None:
        return configs[0]

    wanted = str(requested_serial).strip().lower()
    for cfg in configs:
        serial_candidates = [
            cfg.get("serial"),
            cfg.get("serial_number"),
            cfg.get("serialNumber"),
        ]
        for serial in serial_candidates:
            if serial is None:
                continue
            if str(serial).strip().lower() == wanted:
                return cfg
    return None
