from __future__ import annotations

from ...hex_utils import parse_hex_bytes
from ..base import CommandContext, CommandSpec
from .common import emit_response, parse_keyvals, request_with_standard_match


_SECTIONS = [
    (
        ":kwp-writemem (aliases: :writemem) arguments:",
        [
            "  <address> <hex bytes...>   write bytes at 4-byte address (big-endian)",
            "  [type=<byte>]              memoryTypeIdentifier            (default: 0x00)",
            "  [timeout=<seconds>]        per-request timeout             (default: 1.0)",
            "  note                       memory size field is auto-set from payload length (0x01..0xFA)",
        ],
    )
]


def _handle_kwp_write_memory(ctx: CommandContext, args: str) -> bool:
    tokens = args.split()
    positional, options = parse_keyvals(tokens)
    if len(positional) < 2:
        ctx.emit("Usage: :kwp-writemem <address> <hex bytes...> [type=0x00] [timeout=1.0]")
        return True

    try:
        address = int(positional[0], 0)
    except ValueError:
        ctx.emit("Invalid address. Use decimal or 0x-prefixed hex.")
        return True

    if not (0 <= address <= 0xFFFFFFFF):
        ctx.emit("address must fit in 4 bytes (0x00000000..0xFFFFFFFF)")
        return True

    try:
        data = parse_hex_bytes(" ".join(positional[1:]))
    except Exception as exc:  # pylint: disable=broad-except
        ctx.emit(f"Invalid data bytes: {exc}")
        return True

    if not (1 <= len(data) <= 0xFA):
        ctx.emit("recordData length must be in range 0x01..0xFA")
        return True

    try:
        memory_type = int(options.get("type", "0x00"), 0)
    except ValueError:
        ctx.emit("type must be a byte value (0x00..0xFF)")
        return True

    if not (0 <= memory_type <= 0xFF):
        ctx.emit("type must be a byte value (0x00..0xFF)")
        return True

    try:
        timeout = max(0.1, float(options.get("timeout", "1.0")))
    except ValueError:
        ctx.emit("timeout must be numeric")
        return True

    payload = (
        bytes([0x3D])
        + address.to_bytes(4, "big")
        + bytes([memory_type, len(data)])
        + data
    )
    response = request_with_standard_match(ctx, payload, positive_sid=0x7D, timeout=timeout)
    emit_response(ctx, "writemem", response)
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="kwp-writemem",
        aliases=("writemem",),
        handler=_handle_kwp_write_memory,
        summary=":kwp-writemem <address> <hex bytes...>  KWP WriteMemoryByAddress (0x3D, 4-byte addr)",
        help_sections=_SECTIONS,
    )
