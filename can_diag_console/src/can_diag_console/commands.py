from __future__ import annotations

from typing import Callable

from .command_handlers import build_builtin_registry
from .command_handlers.base import CommandContext, CommandSpec
from .session import DiagnosticSession


class CommandProcessor:
    """Parses and executes console commands against a DiagnosticSession."""

    def __init__(
        self,
        session: DiagnosticSession,
        emit: Callable[[str], None],
        stop_console: Callable[[], None],
    ) -> None:
        self._session = session
        self._emit = emit
        self._stop_console = stop_console
        self._ctx = CommandContext(session=session, emit=emit, stop_console=stop_console)
        self._registry = build_builtin_registry(self._render_help_lines)
        self._custom_handlers: list[Callable[[str], bool]] = []

    @property
    def session(self) -> DiagnosticSession:
        return self._session

    @property
    def emit(self) -> Callable[[str], None]:
        return self._emit

    def register_command(
        self,
        name: str,
        handler: Callable[[str], bool],
        *,
        aliases: tuple[str, ...] = (),
    ) -> None:
        """Backward-compatible registration for plugin command handlers."""

        def _wrapped(ctx: CommandContext, args: str) -> bool:
            del ctx
            return handler(args)

        self.register_command_spec(
            CommandSpec(name=name, aliases=aliases, handler=_wrapped),
        )

    def register_command_spec(self, spec: CommandSpec) -> None:
        """Register a command using the new command contract/registry."""
        self._registry.add(spec)

    def register_custom_handler(self, handler: Callable[[str], bool]) -> None:
        """Backward-compatible fallback hook for plugin command handlers."""
        self._custom_handlers.append(handler)

    def execute(self, line: str) -> bool:
        cmd = line.strip()
        if not cmd.startswith(":"):
            return False

        raw = cmd[1:].strip()
        if not raw:
            self._emit("Unknown command. Use :help")
            return True

        parts = raw.split(maxsplit=1)
        command_name = parts[0].strip().lower()
        arguments = parts[1].strip() if len(parts) > 1 else ""

        spec = self._registry.get(command_name)
        if spec is not None:
            return spec.handler(self._ctx, arguments)

        for handler in self._custom_handlers:
            if handler(cmd):
                return True

        self._emit("Unknown command. Use :help")
        return True


    def _render_help_lines(self) -> list[str]:
        lines: list[str] = [
            "usage: :<command> [arguments]",
            "",
            "commands:",
        ]

        for spec in self._registry.specs():
            if spec.summary:
                lines.append(f"  {spec.summary}")

        emitted_headers: set[str] = set()
        for spec in self._registry.specs():
            for header, rows in spec.help_sections:
                if header in emitted_headers:
                    continue
                emitted_headers.add(header)
                lines.append("")
                lines.append(header)
                lines.extend(rows)

        return lines
