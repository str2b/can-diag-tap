from __future__ import annotations

from .base import CommandContext, CommandSpec


def _handle_quit(ctx: CommandContext, _args: str) -> bool:
    ctx.stop_console()
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="quit",
        aliases=("q", "exit"),
        handler=_handle_quit,
        summary=":quit, :q, :exit                         disconnect and exit",
    )
