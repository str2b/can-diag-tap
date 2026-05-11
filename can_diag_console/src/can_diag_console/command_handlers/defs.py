from __future__ import annotations

from .base import CommandContext, CommandSpec


def _handle_defs(ctx: CommandContext, args: str) -> bool:
    defs_path = args.strip()
    if not defs_path:
        ctx.emit("Usage: :defs <path>")
        return True
    ctx.session.set_defs(defs_path)
    if ctx.session.defs_available:
        ctx.emit(f"Defs loaded from {defs_path}")
    else:
        ctx.emit("Defs parser unavailable. Ensure the definitions file is valid.")
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="defs",
        handler=_handle_defs,
        summary=":defs <path>                             load service definitions JSON",
    )
