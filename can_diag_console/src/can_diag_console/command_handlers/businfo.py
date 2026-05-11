from __future__ import annotations

from .base import CommandContext, CommandSpec


_KEYS = (
    "adapter",
    "interface",
    "channel",
    "bitrate",
    "bus_open",
    "adapter_options",
    "gs_usb_selected",
)


def _handle_businfo(ctx: CommandContext, _args: str) -> bool:
    ctx.emit("Bus info:")
    info = ctx.session.bus_info()
    for key in _KEYS:
        if key in info:
            ctx.emit(f"  {key}: {info[key]}")
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="businfo",
        handler=_handle_businfo,
        summary=":businfo                                 show adapter / bus information",
    )
