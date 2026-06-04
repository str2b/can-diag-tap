from __future__ import annotations

from . import diag_session, flow_auth_sk, flow_memory_read, flow_tester_present, memory_erase, memory_write
from ..base import CommandSpec


def command_specs() -> list[CommandSpec]:
    return [
        flow_tester_present.command_spec(),
        diag_session.command_spec(),
        flow_memory_read.command_spec(),
        memory_write.command_spec(),
        memory_erase.command_spec(),
        flow_auth_sk.command_spec(),
    ]
