from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from ..session import DiagnosticSession


@dataclass
class CommandContext:
    session: DiagnosticSession
    emit: Callable[[str], None]
    stop_console: Callable[[], None]


CommandHandler = Callable[[CommandContext, str], bool]


@dataclass
class CommandSpec:
    name: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    summary: str | None = None
    help_sections: list[tuple[str, list[str]]] = field(default_factory=list)


class CommandRegistry:
    def __init__(self) -> None:
        self._specs: list[CommandSpec] = []
        self._by_name: dict[str, CommandSpec] = {}

    def add(self, spec: CommandSpec) -> None:
        names = (spec.name, *spec.aliases)
        for name in names:
            normalized = name.strip().lower()
            if not normalized:
                raise ValueError("Command name must not be empty.")
            self._by_name[normalized] = spec
        self._specs.append(spec)

    def get(self, name: str) -> CommandSpec | None:
        return self._by_name.get(name.strip().lower())

    def specs(self) -> Iterable[CommandSpec]:
        return tuple(self._specs)
