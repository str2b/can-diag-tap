from can_diag_console.hex_utils import parse_hex_bytes


def test_parse_hex_bytes_space_separated() -> None:
    assert parse_hex_bytes("10 81") == bytes([0x10, 0x81])


def test_parse_hex_bytes_compact() -> None:
    assert parse_hex_bytes("1081") == bytes([0x10, 0x81])
