from __future__ import annotations

import json
import logging
from typing import Any


class DefsEngine:
    """Loads JSON service definitions and decodes diagnostic payloads."""

    def __init__(self, defs_file: str | None = None):
        self.defs: dict[str, Any] = {}
        if not defs_file:
            return
        try:
            with open(defs_file, "r", encoding="utf-8") as handle:
                self.defs = json.load(handle)
            logging.getLogger("diag_defs").info("Loaded definitions from %s", defs_file)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.getLogger("diag_defs").error("Failed to load defs file %s: %s", defs_file, exc)

    @staticmethod
    def _parse_int(value: str | int) -> int:
        if isinstance(value, str) and value.lower().startswith("0x"):
            return int(value, 16)
        return int(value)

    def lookup(
        self,
        service_id: int,
        message_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Return a service definition and name for a service id if present."""
        services_dict = self.defs.get("services", self.defs)
        hex_key = f"0x{service_id:02X}"
        service_entry = services_dict.get(hex_key) or services_dict.get(str(service_id))

        if not service_entry:
            return None, None

        candidates = service_entry if isinstance(service_entry, list) else [service_entry]
        best_match = None
        best_score = -1

        message_src = message_context.get("src") if message_context else None
        message_tgt = message_context.get("tgt") if message_context else None

        for service_candidate in candidates:
            score = 0
            candidate_src = service_candidate.get("src")
            candidate_tgt = service_candidate.get("tgt")

            if candidate_src is not None:
                candidate_src_val = self._parse_int(candidate_src)
                if message_src is not None and candidate_src_val == message_src:
                    score += 1
                else:
                    continue

            if candidate_tgt is not None:
                candidate_tgt_val = self._parse_int(candidate_tgt)
                if message_tgt is not None and candidate_tgt_val == message_tgt:
                    score += 1
                else:
                    continue

            if score > best_score:
                best_score = score
                best_match = service_candidate

        if best_match:
            return best_match, best_match.get("name", f"UnknownService_{hex_key}")

        return None, None

    def parse_payload(self, payload_bytes: bytes, message_context: dict[str, Any]) -> dict[str, Any] | None:
        """Map payload bytes to named parameters using the loaded definitions."""
        if not self.defs or len(payload_bytes) < 1:
            return None

        service_def, service_name = self.lookup(payload_bytes[0], message_context)
        if not service_def:
            return None

        message_context["service_name"] = service_name
        args_layout = service_def.get("args") or {}
        payload_layout = args_layout.get(str(len(payload_bytes)), args_layout.get("default", []))

        decoded_params = {}
        byte_offset = 1
        pending_layout_items = list(payload_layout)

        while pending_layout_items:
            param_spec = pending_layout_items.pop(0)

            if "mux" in param_spec:
                expanded_layout = self._resolve_mux(param_spec, decoded_params)
                if expanded_layout:
                    pending_layout_items = expanded_layout + pending_layout_items
                continue

            if byte_offset >= len(payload_bytes):
                break

            param_name, param_value, byte_offset = self._decode_param(param_spec, payload_bytes, byte_offset)
            decoded_params[param_name] = param_value

        if byte_offset < len(payload_bytes):
            decoded_params["raw_payload"] = payload_bytes[byte_offset:]

        message_context["params"] = decoded_params
        return message_context

    @staticmethod
    def _resolve_mux(param_spec: dict[str, Any], decoded_params: dict[str, Any]) -> list[dict[str, Any]] | None:
        switch_on = param_spec.get("switch_on")
        if not switch_on:
            return None
        selector_value = decoded_params.get(switch_on)
        if selector_value is None:
            return None
        if isinstance(selector_value, dict):
            selector_int = selector_value.get("value")
        elif isinstance(selector_value, int):
            selector_int = selector_value
        elif isinstance(selector_value, (bytes, bytearray)):
            selector_int = int.from_bytes(selector_value, byteorder="big")
        else:
            return None
        cases = param_spec["mux"]
        matched = (
            cases.get(f"0x{selector_int:02X}")
            or cases.get(str(selector_int))
            or cases.get("default")
        )
        return matched if isinstance(matched, list) else None

    @staticmethod
    def _decode_param(
        param_spec: dict[str, Any],
        payload_bytes: bytes,
        byte_offset: int,
    ) -> tuple[str, Any, int]:
        param_name = param_spec.get("name", "unknown")
        param_len = param_spec.get("length", 1)

        if param_len == -1:
            raw_val = payload_bytes[byte_offset:]
            byte_offset = len(payload_bytes)
        else:
            raw_val = payload_bytes[byte_offset: byte_offset + param_len]
            byte_offset += param_len

        if param_len <= 0 or param_len > 8:
            return param_name, raw_val, byte_offset

        decoded_int = int.from_bytes(raw_val, byteorder="big")
        named_val = DefsEngine._lookup_enum(param_spec.get("enum", {}), decoded_int)

        if named_val:
            return param_name, {"value": decoded_int, "name": named_val}, byte_offset
        if param_len == 1:
            return param_name, decoded_int, byte_offset
        return param_name, raw_val, byte_offset

    @staticmethod
    def _lookup_enum(enum_map: dict[str, Any], enum_value: int) -> str | None:
        named = enum_map.get(f"0x{enum_value:02X}") or enum_map.get(str(enum_value))
        if named:
            return named
        for key, value in enum_map.items():
            if isinstance(key, str) and "-" in key:
                try:
                    lo, hi = key.split("-", 1)
                    if int(lo.strip(), 0) <= enum_value <= int(hi.strip(), 0):
                        return value
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
        return None