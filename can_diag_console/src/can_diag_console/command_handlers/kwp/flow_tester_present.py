from __future__ import annotations

from ...hex_utils import fmt_hex, parse_hex_bytes
from ..base import CommandContext, CommandSpec


_SECTIONS = [
    (
        ":kwp-tp subcommands:",
        [
            "  on [<interval_s>] [<hex-bytes>]   start tester-present  (default: 2.0 s, payload '3E 00')",
            "  off                               stop tester-present",
            "  status                            show current tester-present state",
            "  toggle                            toggle tester-present on/off",
        ],
    )
]


def _emit_status(ctx: CommandContext) -> None:
    status = ctx.session.tester_present_status()
    state = "on" if status["enabled"] else "off"
    ctx.emit(f"kwp-tp {state} interval={status['interval']:.2f}s payload={fmt_hex(status['payload'])}")


def _handle_kwp_tester_present(ctx: CommandContext, args: str) -> bool:
    rest = args.strip()
    if not rest:
        _emit_status(ctx)
        return True

    tokens = rest.split()
    mode = tokens[0].lower()

    if mode in {"off", "stop", "disable"}:
        ctx.session.stop_tester_present()
        ctx.emit("kwp-tp disabled")
        return True

    if mode in {"status", "show"}:
        _emit_status(ctx)
        return True

    if mode == "toggle":
        status = ctx.session.tester_present_status()
        if status["enabled"]:
            ctx.session.stop_tester_present()
            ctx.emit("kwp-tp disabled")
        else:
            ctx.session.start_tester_present()
            ctx.emit("kwp-tp enabled interval=2.00s payload=3E 00")
        return True

    if mode not in {"on", "start", "enable"}:
        ctx.emit("Usage: :kwp-tp <on|off|status|toggle> [interval_s] [hex bytes]")
        return True

    interval = 2.0
    payload = bytes([0x3E, 0x00])

    if len(tokens) >= 2:
        try:
            interval = float(tokens[1])
            payload_tokens = tokens[2:]
        except ValueError:
            payload_tokens = tokens[1:]
    else:
        payload_tokens = []

    if payload_tokens:
        payload = parse_hex_bytes(" ".join(payload_tokens))

    ctx.session.start_tester_present(interval=interval, payload=payload)
    ctx.emit(f"kwp-tp enabled interval={interval:.2f}s payload={fmt_hex(payload)}")
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="kwp-tp",
        handler=_handle_kwp_tester_present,
        summary=":kwp-tp <subcommand> [...]               manage tester-present keepalive",
        help_sections=_SECTIONS,
    )
