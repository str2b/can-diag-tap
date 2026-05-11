from __future__ import annotations

from .base import CommandContext, CommandSpec

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
        ],
    )
]


def _handle_kwp_diag_session(ctx: CommandContext, args: str) -> bool:
    mode = args.strip().lower()
    if not mode:
        ctx.emit("Usage: :kwp-diag-session <default|programming|extended>")
        return True

    sub_func = _SESSION_MODES.get(mode)
    if sub_func is None:
        ctx.emit(f"Unknown session mode '{mode}'. Valid modes: {', '.join(_SESSION_MODES)}")
        return True

    payload = bytes([0x10, sub_func])
    response = ctx.session.request(payload)
    if response is None:
        ctx.emit(f"kwp-diag-session {mode}: no response")
    else:
        resp_hex = " ".join(f"{b:02X}" for b in response)
        ctx.emit(f"kwp-diag-session {mode}: {resp_hex}")
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="kwp-diag-session",
        handler=_handle_kwp_diag_session,
        summary=":kwp-diag-session <mode>                 start KWP diagnostic session (0x10)",
        help_sections=_SECTIONS,
    )
