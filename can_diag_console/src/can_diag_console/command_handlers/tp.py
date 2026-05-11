from __future__ import annotations

from ..hex_utils import parse_hex_bytes
from .base import CommandContext, CommandSpec


def _handle_tp(ctx: CommandContext, args: str) -> bool:
    payload_text = args.strip()
    if not payload_text:
        ctx.emit("Usage: :tp <hex bytes>")
        return True

    payload = parse_hex_bytes(payload_text)
    ctx.session.send(payload)
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="tp",
        handler=_handle_tp,
        summary=":tp <hex-bytes>                          send raw transport payload bytes",
    )
