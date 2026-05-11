from __future__ import annotations

from .base import CommandContext, CommandSpec


def _handle_nodefs(ctx: CommandContext, _args: str) -> bool:
    ctx.session.disable_defs()
    ctx.emit("Definitions parsing disabled.")
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="nodefs",
        handler=_handle_nodefs,
        summary=":nodefs                                  unload service definitions",
    )
