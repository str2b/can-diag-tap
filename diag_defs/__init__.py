"""Repo-level shim for the shared diag_defs package implementation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_ENGINE_PATH = Path(__file__).resolve().parent.parent / "can_diag_console" / "src" / "diag_defs" / "engine.py"
_SPEC = importlib.util.spec_from_file_location("diag_defs._shared_engine", str(_ENGINE_PATH))
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Failed to load shared diag_defs engine from {_ENGINE_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

DefsEngine = _MODULE.DefsEngine

__all__ = ["DefsEngine"]