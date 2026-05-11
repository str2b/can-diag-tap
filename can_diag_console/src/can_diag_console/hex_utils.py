from __future__ import annotations


def parse_hex_bytes(text: str) -> bytes:
    """Parse user-provided hex byte text into bytes.

    Accepted formats:
    - 10 81
    - 0x10 0x81
    - 1081
    - 10,81
    """
    cleaned = (
        text.replace(",", " ")
        .replace(";", " ")
        .replace("0x", "")
        .replace("0X", "")
        .strip()
    )
    if not cleaned:
        return b""

    if " " in cleaned:
        chunks = [c for c in cleaned.split() if c]
    else:
        if len(cleaned) % 2 != 0:
            raise ValueError("Hex string length must be even.")
        chunks = [cleaned[i : i + 2] for i in range(0, len(cleaned), 2)]

    out = bytearray()
    for chunk in chunks:
        if len(chunk) == 1:
            chunk = f"0{chunk}"
        if len(chunk) != 2:
            raise ValueError(f"Invalid hex byte token: {chunk}")
        out.append(int(chunk, 16))
    return bytes(out)


def fmt_hex(payload: bytes) -> str:
    return " ".join(f"{b:02X}" for b in payload)
