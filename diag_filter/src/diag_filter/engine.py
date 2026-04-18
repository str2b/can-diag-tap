from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class Filterable(Protocol):
    @property
    def layer(self) -> str:
        ...

    def filter_attrs(self) -> dict[str, Any]:
        ...


@dataclass
class GenericMessage:
    layer_name: str
    attrs: dict[str, Any]

    @property
    def layer(self) -> str:
        return self.layer_name

    def filter_attrs(self) -> dict[str, Any]:
        return self.attrs


class FilterEngine:
    """Loads a JSON filter definition and evaluates messages against its rules."""

    def __init__(
        self,
        filter_file: str | None = None,
        *,
        logger_name: str = "diag.filter",
        exit_on_error: bool = True,
    ):
        self.mode: str = "whitelist"
        self.rules: list[dict[str, Any]] = []
        self._log = logging.getLogger(logger_name)

        if not filter_file:
            return

        try:
            with Path(filter_file).open("r", encoding="utf-8") as f:
                filter_def: dict[str, Any] = json.load(f)
            self.mode = str(filter_def.get("mode", "whitelist")).lower()
            self.rules = list(filter_def.get("rules", []))
            self._log.info("Loaded %d filter rules in %s mode.", len(self.rules), self.mode)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._log.error("Failed to load filter file %s: %s", filter_file, exc)
            if exit_on_error:
                raise SystemExit(1) from exc
            raise

    def should_drop(self, message: Filterable) -> bool:
        """Return True when message should be dropped according to rules/mode."""
        if not self.rules:
            return False

        layer = message.layer
        layer_rules = [r for r in self.rules if str(r.get("layer", "")).lower() == layer]
        if not layer_rules:
            return False

        attrs = message.filter_attrs()
        rule_matched = False
        for rule in layer_rules:
            if self._rule_matches(rule, attrs):
                rule_matched = True
                break

        return not rule_matched if self.mode == "whitelist" else rule_matched

    @staticmethod
    def _rule_matches(rule: dict[str, Any], attrs: dict[str, Any]) -> bool:
        for key, expected_val in rule.items():
            if key == "layer":
                continue

            val = attrs.get(key)
            if val is None:
                return False

            if key == "payload":
                if not isinstance(val, (bytes, bytearray)):
                    return False
                if not re.search(str(expected_val), val.hex().upper(), re.IGNORECASE):
                    return False
                continue

            str_val = f"0X{val:0X}" if isinstance(val, int) else str(val).upper()
            exp_val_str = str(expected_val).upper()
            if str_val != exp_val_str and exp_val_str != str(val):
                return False

        return True
