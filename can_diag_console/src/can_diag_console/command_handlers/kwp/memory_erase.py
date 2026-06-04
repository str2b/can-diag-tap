from __future__ import annotations

from ..base import CommandContext, CommandSpec
from .common import emit_response, parse_keyvals, request_with_standard_match


_SECTIONS = [
    (
        ":kwp-erasemem (aliases: :erasemem) arguments:",
        [
            "  <address> <size>          erase memory at 4-byte address with 4-byte size (big-endian)",
            "  [type=<byte>]             memoryTypeIdentifier (not evaluated by command) (default: 0x00)",
            "  [timeout=<seconds>]       per-request timeout  (default: 1.0)",
        ],
    )
]


def _handle_kwp_erase_memory(ctx: CommandContext, args: str) -> bool:
    tokens = args.split()
    positional, options = parse_keyvals(tokens)
    if len(positional) != 2:
        ctx.emit("Usage: :kwp-erasemem <address> <size> [type=0x00] [timeout=1.0]")
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
        size = int(positional[1], 0)
    except ValueError:
        ctx.emit("Invalid size. Use decimal or 0x-prefixed hex.")
        return True

    if not (0 <= size <= 0xFFFFFFFF):
        ctx.emit("size must fit in 4 bytes (0x00000000..0xFFFFFFFF)")
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
        bytes([0x31, 0x02])
        + address.to_bytes(4, "big")
        + bytes([memory_type])
        + size.to_bytes(4, "big")
    )

    response = request_with_standard_match(ctx, payload, positive_sid=0x71, timeout=timeout)
    emit_response(ctx, "erasemem", response)
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="kwp-erasemem",
        aliases=("erasemem",),
        handler=_handle_kwp_erase_memory,
        summary=(
            ":kwp-erasemem <address> <size>  KWP RoutineControl erase memory "
            "(0x31 0x02, 4-byte addr/size)"
        ),
        help_sections=_SECTIONS,
    )
