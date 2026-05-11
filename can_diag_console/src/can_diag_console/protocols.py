from __future__ import annotations

# Compatibility shim. Use can_diag_console.hex_utils for non-protocol helpers.
from .hex_utils import fmt_hex, parse_hex_bytes

__all__ = ["parse_hex_bytes", "fmt_hex"]
