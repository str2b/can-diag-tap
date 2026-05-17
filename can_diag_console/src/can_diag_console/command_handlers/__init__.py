from __future__ import annotations

from typing import Callable

from . import businfo, defs, nodefs, quit, raw, rx, tx
from . import kwp
from .base import CommandRegistry, CommandSpec
from .help import make_help_command


def build_builtin_registry(help_lines_provider: Callable[[], list[str]]) -> CommandRegistry:
    registry = CommandRegistry()
    specs: list[CommandSpec] = [
        make_help_command(help_lines_provider),
        quit.command_spec(),
        businfo.command_spec(),
        tx.command_spec(),
        rx.command_spec(),
        defs.command_spec(),
        nodefs.command_spec(),
        raw.command_spec(),
        *kwp.command_specs(),
    ]
    for spec in specs:
        registry.add(spec)
    return registry
