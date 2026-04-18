from pathlib import Path

from can_diag_console.memory_read import KwpMemoryReader, MemoryReadOptions, export_srec


def _make_request_fn(memory: bytes, base_addr: int, protected: set[int]):
    def _request(payload: bytes, _timeout: float, matcher):
        assert payload[0] == 0x23
        addr = int.from_bytes(payload[1:5], "big")
        size = payload[6]

        if any(a in protected for a in range(addr, addr + size)):
            resp = bytes([0x7F, 0x23, 0x33])
            return resp if matcher is None or matcher(resp) else None

        start = addr - base_addr
        data = memory[start : start + size]
        resp = bytes([0x63]) + data
        return resp if matcher is None or matcher(resp) else None

    return _request


def test_memory_read_binary_split_with_protected_addresses(tmp_path: Path) -> None:
    base = 0x1000
    data = bytes(range(0, 0x40))
    protected = set(range(0x1010, 0x1020))

    reader = KwpMemoryReader(
        request_fn=_make_request_fn(data, base, protected),
        emit=lambda _msg: None,
    )

    result = reader.read_range(
        0x1008,
        0x1028,
        MemoryReadOptions(chunk_size=0x20, memory_type=0x00, timeout=0.1),
    )

    assert len(result.chunks) == 2
    assert result.chunks[0].address == 0x1008
    assert result.chunks[0].data == data[0x08:0x10]
    assert result.chunks[1].address == 0x1020
    assert result.chunks[1].data == data[0x20:0x28]

    assert result.blocked_addresses == sorted(protected)


def test_export_srec_creates_file(tmp_path: Path) -> None:
    from can_diag_console.memory_read import MemoryChunk

    out = tmp_path / "dump.srec"
    export_srec(
        [
            MemoryChunk(0x1000, bytes([1, 2, 3])),
            MemoryChunk(0x2000, bytes([0xAA, 0xBB])),
        ],
        out,
    )
    assert out.exists()
    assert out.stat().st_size > 0
