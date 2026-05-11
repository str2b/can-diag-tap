from __future__ import annotations

from typing import Callable

from .base import CommandContext, CommandSpec


def make_help_command(help_lines_provider: Callable[[], list[str]]) -> CommandSpec:
    def _handle_help(ctx: CommandContext, _args: str) -> bool:
        for line in help_lines_provider():
            ctx.emit(line)
        return True

    return CommandSpec(
        name="help",
        aliases=("h",),
        handler=_handle_help,
        summary=":help, :h                                show this help message",
    )
