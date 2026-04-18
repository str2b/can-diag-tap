from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


class ExtensionLoadError(RuntimeError):
    """Raised when an extension module cannot be loaded or is invalid."""


def load_extension_module(spec: str) -> ModuleType:
    """Load an extension module from dotted name or file path."""
    path = Path(spec)
    if path.exists():
        module_name = f"can_diag_console_ext_{abs(hash(str(path.resolve())))}"
        mod_spec = importlib.util.spec_from_file_location(module_name, str(path))
        if mod_spec is None or mod_spec.loader is None:
            raise ExtensionLoadError(f"Failed to create import spec for extension: {spec}")
        module = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(module)
        return module

    try:
        return importlib.import_module(spec)
    except Exception as exc:  # pylint: disable=broad-except
        raise ExtensionLoadError(f"Failed to import extension module '{spec}': {exc}") from exc


def load_adapter_plugins(
    specs: list[str],
    register_adapter: Callable[[str, Callable[[Any], Any]], None],
) -> None:
    """Load adapter plugins and register custom adapter factories."""
    for spec in specs:
        module = load_extension_module(spec)
        registrar = getattr(module, "register_adapters", None)
        if not callable(registrar):
            raise ExtensionLoadError(
                f"Adapter plugin '{spec}' must export register_adapters(register_adapter)."
            )
        registrar(register_adapter)


def load_command_plugins(specs: list[str], processor: Any) -> None:
    """Load command plugins and let them register handlers on the processor."""
    for spec in specs:
        module = load_extension_module(spec)
        registrar = getattr(module, "register_commands", None)
        if not callable(registrar):
            raise ExtensionLoadError(
                f"Command plugin '{spec}' must export register_commands(processor)."
            )
        registrar(processor)
