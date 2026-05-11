from __future__ import annotations

from typing import Callable

from . import businfo, defs, kwp_auth_sk, kwp_diag_session, kwp_read_memory, kwp_tester_present, nodefs, quit, rx, tp, tx
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
        tp.command_spec(),
        kwp_tester_present.command_spec(),
        kwp_diag_session.command_spec(),
        kwp_read_memory.command_spec(),
        kwp_auth_sk.command_spec(),
    ]
    for spec in specs:
        registry.add(spec)
    return registry
