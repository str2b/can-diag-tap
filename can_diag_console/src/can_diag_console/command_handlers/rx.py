from __future__ import annotations

from .base import CommandContext, CommandSpec


def _handle_rx(ctx: CommandContext, args: str) -> bool:
    if not args:
        ctx.emit("Usage: :rx <id>")
        return True
    val = int(args, 0)
    ctx.session.set_rx_id(val)
    ctx.emit(f"RX id set to 0x{val:X}")
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="rx",
        handler=_handle_rx,
        summary=":rx <id>                                 set ECU-to-tester CAN ID (hex)",
    )
