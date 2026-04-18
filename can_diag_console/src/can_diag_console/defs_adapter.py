from __future__ import annotations

from typing import Any

from diag_defs import DefsEngine


class DefsParser:
    """Protocol-like base for optional defs parsing support."""

    @property
    def available(self) -> bool:
        return False

    def parse(self, payload: bytes, src: int, tgt: int) -> dict[str, Any] | None:
        return None


class NullDefsParser(DefsParser):
    """No-op defs parser used when defs convenience is disabled/unavailable."""


class JsonDefsParser(DefsParser):
    """Adapter for loading and using the shared diag_defs.DefsEngine."""

    def __init__(self, defs_file: str | None, cdt_file: str | None = None) -> None:
        del cdt_file
        self._engine: Any = None

        if not defs_file:
            return

        self._engine = DefsEngine(defs_file)
        if not self._engine.defs:
            self._engine = None

    @property
    def available(self) -> bool:
        return self._engine is not None

    def parse(self, payload: bytes, src: int, tgt: int) -> dict[str, Any] | None:
        if self._engine is None or not payload:
            return None

        context = {
            "src": src,
            "tgt": tgt,
            "service_id": payload[0],
            "service_name": "",
            "params": {},
        }
        return self._engine.parse_payload(payload, context)


def build_defs_parser(
    defs_file: str | None,
    *,
    cdt_file: str | None = None,
    provider: str = "auto",
) -> DefsParser:
    provider_name = (provider or "auto").strip().lower()
    if not defs_file:
        return NullDefsParser()

    if provider_name == "none":
        return NullDefsParser()

    if provider_name not in {"auto", "cdt", "none"}:
        raise ValueError("Unsupported defs provider. Use auto, cdt, or none.")

    parser = JsonDefsParser(defs_file=defs_file, cdt_file=cdt_file)
    if parser.available:
        return parser

    if provider_name == "cdt":
        raise RuntimeError("Defs provider 'cdt' is deprecated and maps to the shared diag_defs parser.")

    return NullDefsParser()
