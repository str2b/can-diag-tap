from __future__ import annotations

from ..base import CommandContext


def parse_int_token(token: str) -> int:
    return int(token, 0)


def parse_keyvals(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    positional: list[str] = []
    options: dict[str, str] = {}
    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            options[key.strip().lower()] = value.strip()
        else:
            positional.append(token)
    return positional, options


def request_with_standard_match(
    ctx: CommandContext,
    request_payload: bytes,
    *,
    positive_sid: int,
    timeout: float = 1.0,
) -> bytes | None:
    service_id = request_payload[0] if request_payload else 0x00

    def _matcher(resp: bytes) -> bool:
        if not resp:
            return False
        if resp[0] == positive_sid:
            return True
        return len(resp) >= 2 and resp[0] == 0x7F and resp[1] == service_id

    return ctx.session.request(request_payload, timeout=timeout, matcher=_matcher)


def emit_response(ctx: CommandContext, label: str, response: bytes | None) -> None:
    if response is None:
        ctx.emit(f"{label}: no response")
        return
    resp_hex = " ".join(f"{b:02X}" for b in response)
    ctx.emit(f"{label}: {resp_hex}")
