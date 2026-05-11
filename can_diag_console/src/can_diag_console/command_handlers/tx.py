from __future__ import annotations

from .base import CommandContext, CommandSpec


def _handle_tx(ctx: CommandContext, args: str) -> bool:
    if not args:
        ctx.emit("Usage: :tx <id>")
        return True
    val = int(args, 0)
    ctx.session.set_tx_id(val)
    ctx.emit(f"TX id set to 0x{val:X}")
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="tx",
        handler=_handle_tx,
        summary=":tx <id>                                 set tester-to-ECU CAN ID (hex)",
    )
