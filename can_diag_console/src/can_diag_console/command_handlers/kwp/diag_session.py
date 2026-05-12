from __future__ import annotations

from ..base import CommandContext, CommandSpec
from .common import emit_response, parse_keyvals, request_with_standard_match

# KWP2000 service 0x10 – StartDiagnosticSession
_SESSION_MODES: dict[str, int] = {
    "default":     0x01,
    "programming": 0x85,
    "extended":    0x86,
}

_SECTIONS = [
    (
        ":kwp-diag-session modes:",
        [
            "  default       start default diagnostic session      (0x10 0x01)",
            "  programming   start programming session             (0x10 0x85)",
            "  extended      start extended diagnostic session     (0x10 0x86)",
            "  [timeout=1.0] per-request timeout in seconds",
        ],
    )
]


def _handle_kwp_diag_session(ctx: CommandContext, args: str) -> bool:
    tokens = args.split()
    positional, options = parse_keyvals(tokens)
    if len(positional) != 1:
        ctx.emit("Usage: :kwp-diag-session <default|programming|extended> [timeout=1.0]")
        return True

    mode = positional[0].strip().lower()
    sub_func = _SESSION_MODES.get(mode)
    if sub_func is None:
        ctx.emit(f"Unknown session mode '{mode}'. Valid modes: {', '.join(_SESSION_MODES)}")
        return True

    timeout = float(options.get("timeout", "1.0"))
    payload = bytes([0x10, sub_func])
    response = request_with_standard_match(ctx, payload, positive_sid=0x50, timeout=max(0.1, timeout))
    emit_response(ctx, f"kwp-diag-session {mode}", response)
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="kwp-diag-session",
        handler=_handle_kwp_diag_session,
        summary=":kwp-diag-session <mode>                 start KWP diagnostic session (0x10)",
        help_sections=_SECTIONS,
    )
