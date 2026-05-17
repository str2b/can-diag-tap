from __future__ import annotations

from . import diag_session, flow_auth_sk, flow_memory_read, memory_write, flow_tester_present
from ..base import CommandSpec


def command_specs() -> list[CommandSpec]:
    return [
        flow_tester_present.command_spec(),
        diag_session.command_spec(),
        flow_memory_read.command_spec(),
        memory_write.command_spec(),
        flow_auth_sk.command_spec(),
    ]
