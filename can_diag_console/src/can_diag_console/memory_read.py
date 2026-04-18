from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class MemoryChunk:
    address: int
    data: bytes

    @property
    def end(self) -> int:
        return self.address + len(self.data)


@dataclass
class MemoryReadResult:
    chunks: list[MemoryChunk] = field(default_factory=list)
    blocked_addresses: list[int] = field(default_factory=list)

    @property
    def bytes_read(self) -> int:
        return sum(len(c.data) for c in self.chunks)


@dataclass
class MemoryReadOptions:
    chunk_size: int = 0xFE
    memory_type: int = 0x00
    timeout: float = 1.0


class KwpMemoryReader:
    """Chunked ReadMemoryByAddress with protected-byte recovery.

    If a block read fails with a negative response, this reader recursively
    splits the block (binary-search style) until readable chunks and blocked
    single addresses are identified.
    """

    def __init__(
        self,
        request_fn: Callable[[bytes, float, Callable[[bytes], bool] | None], bytes | None],
        emit: Callable[[str], None],
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> None:
        self._request = request_fn
        self._emit = emit
        self._progress_cb = progress_cb

    def read_range(self, start: int, end: int, options: MemoryReadOptions) -> MemoryReadResult:
        if end <= start:
            raise ValueError("end must be greater than start")
        if not (0 < options.chunk_size <= 0xFF):
            raise ValueError("chunk_size must be in range 1..0xFF")
        if not (0 <= options.memory_type <= 0xFF):
            raise ValueError("memory_type must be in range 0..0xFF")

        out = MemoryReadResult()
        cursor = start
        total = end - start
        resolved = 0

        while cursor < end:
            size = min(options.chunk_size, end - cursor)
            chunks, blocked = self._read_segment(cursor, size, options)
            out.chunks.extend(chunks)
            out.blocked_addresses.extend(blocked)
            cursor += size
            resolved += size
            if self._progress_cb is not None:
                self._progress_cb(resolved, total)

        out.chunks = self._merge_adjacent_chunks(out.chunks)
        out.blocked_addresses = sorted(set(out.blocked_addresses))
        return out

    def _read_segment(
        self,
        address: int,
        size: int,
        options: MemoryReadOptions,
    ) -> tuple[list[MemoryChunk], list[int]]:
        end = address + size
        cursor = address
        out_chunks: list[MemoryChunk] = []
        blocked: list[int] = []

        while cursor < end:
            remaining = end - cursor
            ok, data, nrc = self._read_block(cursor, remaining, options)
            if ok and len(data) == remaining:
                out_chunks.append(MemoryChunk(cursor, data))
                break

            # Try to keep a maximal readable prefix using binary search on length.
            prefix_len = self._find_max_readable_prefix(cursor, remaining, options)
            if prefix_len > 0:
                ok_p, data_p, _ = self._read_block(cursor, prefix_len, options)
                if ok_p and len(data_p) == prefix_len:
                    out_chunks.append(MemoryChunk(cursor, data_p))
                    cursor += prefix_len
                    continue

            # First byte at cursor is unreadable. Jump ahead exponentially to find
            # the next readable point, then binary-search boundary.
            next_readable = self._find_next_readable(cursor + 1, end, options)
            if next_readable is None:
                blocked.extend(range(cursor, end))
                self._emit(
                    f"[memread] blocked range 0x{cursor:08X}-0x{end - 1:08X} "
                    f"({end - cursor} bytes, NRC=0x{nrc:02X})"
                )
                break

            blocked.extend(range(cursor, next_readable))
            self._emit(
                f"[memread] blocked range 0x{cursor:08X}-0x{next_readable - 1:08X} "
                f"({next_readable - cursor} bytes, NRC=0x{nrc:02X})"
            )
            cursor = next_readable

        return out_chunks, blocked

    def _find_max_readable_prefix(
        self,
        address: int,
        max_len: int,
        options: MemoryReadOptions,
    ) -> int:
        """Return the largest readable prefix length in [1, max_len], or 0."""
        lo = 0
        hi = max_len

        while lo < hi:
            mid = (lo + hi + 1) // 2
            ok, data, _ = self._read_block(address, mid, options)
            if ok and len(data) == mid:
                lo = mid
            else:
                hi = mid - 1

        return lo

    def _find_next_readable(
        self,
        start: int,
        end: int,
        options: MemoryReadOptions,
    ) -> int | None:
        """Find next readable address in [start, end) using exponential jumps.

        Returns None if no readable address exists in the range.
        """
        if start >= end:
            return None

        if self._is_readable_address(start, options):
            return start

        first_bad = start
        step = 1
        probe = start + step

        while probe < end and not self._is_readable_address(probe, options):
            first_bad = probe
            step <<= 1
            probe = start + step

        if probe >= end:
            if not self._is_readable_address(end - 1, options):
                return None
            probe = end - 1

        # Binary-search first readable address between (first_bad, probe].
        lo = first_bad + 1
        hi = probe
        while lo < hi:
            mid = (lo + hi) // 2
            if self._is_readable_address(mid, options):
                hi = mid
            else:
                lo = mid + 1
        return lo

    def _is_readable_address(self, address: int, options: MemoryReadOptions) -> bool:
        ok, data, _ = self._read_block(address, 1, options)
        return ok and len(data) == 1

    def _read_block(
        self,
        address: int,
        size: int,
        options: MemoryReadOptions,
    ) -> tuple[bool, bytes, int]:
        req = self._build_read_memory_by_address(address, size, options.memory_type)

        resp = self._request(req, options.timeout, self._response_matcher)
        if resp is None:
            return False, b"", 0x78  # response pending / timeout surrogate

        if len(resp) >= 1 and resp[0] == 0x63:
            return True, bytes(resp[1:]), 0x00

        if len(resp) >= 3 and resp[0] == 0x7F and resp[1] == 0x23:
            return False, b"", int(resp[2])

        return False, b"", 0x10  # general reject / unexpected

    @staticmethod
    def _build_read_memory_by_address(address: int, size: int, memory_type: int) -> bytes:
        if not (0 <= address <= 0xFFFFFFFF):
            raise ValueError("address must fit in 4 bytes")
        if not (0 < size <= 0xFF):
            raise ValueError("size must fit in 1 byte and be > 0")
        if not (0 <= memory_type <= 0xFF):
            raise ValueError("memory_type must be one byte")

        return bytes([0x23]) + address.to_bytes(4, "big") + bytes([memory_type, size])

    @staticmethod
    def _response_matcher(payload: bytes) -> bool:
        if not payload:
            return False
        if payload[0] == 0x63:
            return True
        return len(payload) >= 3 and payload[0] == 0x7F and payload[1] == 0x23

    @staticmethod
    def _merge_adjacent_chunks(chunks: list[MemoryChunk]) -> list[MemoryChunk]:
        if not chunks:
            return []

        chunks_sorted = sorted(chunks, key=lambda c: c.address)
        merged: list[MemoryChunk] = [MemoryChunk(chunks_sorted[0].address, bytes(chunks_sorted[0].data))]

        for chunk in chunks_sorted[1:]:
            last = merged[-1]
            if last.end == chunk.address:
                merged[-1] = MemoryChunk(last.address, last.data + chunk.data)
            else:
                merged.append(MemoryChunk(chunk.address, bytes(chunk.data)))

        return merged


def export_srec(chunks: list[MemoryChunk], output_path: str | Path) -> Path:
    try:
        from hexrec.formats.srec import Memory, SrecFile  # type: ignore[import-untyped]
    except Exception as exc:
        raise RuntimeError("hexrec is required for SREC export") from exc

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    mem = Memory()
    for chunk in chunks:
        if chunk.data:
            mem.write(chunk.address, bytes(chunk.data))

    SrecFile.from_memory(mem).save(str(path))
    return path
