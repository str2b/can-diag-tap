from __future__ import annotations

import sys
import time

from ...memory_read import KwpMemoryReader, MemoryReadOptions, export_srec
from ..base import CommandContext, CommandSpec


class _ProgressBar:
    _BAR_WIDTH = 38

    def __init__(self, start: int, end: int) -> None:
        self._start = start
        self._drawn = False
        self._total = max(end - start, 1)

    def update(self, done: int, total: int) -> None:
        pct = 100.0 * done / total if total > 0 else 0.0
        filled = int(self._BAR_WIDTH * done / total) if total > 0 else 0
        bar = "=" * filled + "-" * (self._BAR_WIDTH - filled)
        addr = self._start + done
        sys.stdout.write(f"\r[{bar}] {pct:5.1f}%  @ 0x{addr:08X}")
        sys.stdout.flush()
        self._drawn = True

    def print_message(self, msg: str) -> None:
        if self._drawn:
            sys.stdout.write("\r" + " " * (self._BAR_WIDTH + 24) + "\r")
        print(msg, flush=True)
        self._drawn = False

    def finish(self) -> None:
        if self._drawn:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._drawn = False


_SECTIONS = [
    (
        ":kwp-memread (aliases: :memread, :rmem, :kwp-rmem) arguments:",
        [
            "  <start>                   start address, hex (e.g. 0x80000000)",
            "  <end>                     end address, hex, inclusive (e.g. 0x80000EFF)",
            "  [chunk=<size>]            bytes per read request       (default: 0xFE)",
            "  [type=<byte>]             memory type byte             (default: 0x00)",
            "  [timeout=<seconds>]       per-request timeout          (default: 1.0)",
            "  [srec=<path>]             save result as Motorola S-record file (enables quiet/progress mode)",
        ],
    )
]


def _handle_kwp_read_memory(ctx: CommandContext, args: str) -> bool:
    rest = args.strip()
    if not rest:
        ctx.emit("Usage: :kwp-memread <start> <end> [chunk=0xF0] [type=0x00] [timeout=1.0] [srec=<path>]")
        return True

    tokens = rest.split()
    if len(tokens) < 2:
        ctx.emit("Usage: :kwp-memread <start> <end> [chunk=0xF0] [type=0x00] [timeout=1.0] [srec=<path>]")
        return True

    start = int(tokens[0], 0)
    end = int(tokens[1], 0)

    chunk_size = 0xF0
    memory_type = 0x00
    timeout = 1.0
    srec_path: str | None = None

    for token in tokens[2:]:
        if token.startswith("chunk="):
            chunk_size = int(token.split("=", 1)[1], 0)
        elif token.startswith("type="):
            memory_type = int(token.split("=", 1)[1], 0)
        elif token.startswith("timeout="):
            timeout = float(token.split("=", 1)[1])
        elif token.startswith("srec="):
            srec_path = token.split("=", 1)[1]
        elif token.startswith("quiet"):
            ctx.emit("Option 'quiet' was removed. Quiet/progress mode is enabled automatically when srec=<path> is set.")
            return True

    quiet = srec_path is not None
    options = MemoryReadOptions(chunk_size=chunk_size, memory_type=memory_type, timeout=timeout)
    bar = _ProgressBar(start, end) if quiet else None

    reader = KwpMemoryReader(
        request_fn=lambda payload, req_timeout, matcher: ctx.session.request(
            payload,
            timeout=req_timeout,
            matcher=matcher,
        ),
        emit=bar.print_message if bar is not None else ctx.emit,
        progress_cb=bar.update if bar is not None else None,
    )

    ctx.emit(f"[memread] start=0x{start:08X} end=0x{end:08X} chunk=0x{chunk_size:02X} type=0x{memory_type:02X}")

    ctx.session.suppress_trace_output(quiet)
    t0 = time.monotonic()
    try:
        result = reader.read_range(start, end, options)
    finally:
        elapsed = time.monotonic() - t0
        ctx.session.suppress_trace_output(False)
        if bar is not None:
            bar.finish()

    ctx.emit(
        f"[memread] bytes_read=0x{result.bytes_read:X} chunks={len(result.chunks)}"
        f" blocked={len(result.blocked_addresses)} duration={elapsed:.1f}s"
    )

    if srec_path:
        out_path = export_srec(result.chunks, srec_path)
        ctx.emit(f"[memread] srec={out_path}")

    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="kwp-memread",
        aliases=("memread", "rmem", "kwp-rmem"),
        handler=_handle_kwp_read_memory,
        summary=":kwp-memread, :memread <start> <end> ... read ECU memory range in bulk",
        help_sections=_SECTIONS,
    )
