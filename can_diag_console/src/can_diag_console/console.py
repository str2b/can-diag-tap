from __future__ import annotations

import argparse
import threading

from .commands import CommandProcessor
from .extensions import load_command_plugins
from .session import DiagnosticSession


class DiagnosticConsole:
    def __init__(self, args: argparse.Namespace) -> None:
        self._session = DiagnosticSession(args=args, emit=self._print)
        self._running = False
        self._stdout_lock = threading.Lock()
        self._commands = CommandProcessor(
            session=self._session,
            emit=self._print,
            stop_console=self._stop,
        )

        plugin_specs = list(getattr(args, "command_plugin", []) or [])
        if plugin_specs:
            load_command_plugins(plugin_specs, self._commands)

    def _stop(self) -> None:
        self._running = False

    def _print(self, line: str) -> None:
        with self._stdout_lock:
            print(line, flush=True)

    def run(self) -> int:
        self._running = True
        args = self._session.args

        self._print("CAN Diagnostic Console ready. Enter :help for available commands")
        line = (
            f"adapter={args.adapter} interface={args.interface} "
            f"channel={args.channel} bitrate={args.bitrate} "
            f"proto={args.protocol} can_tx=0x{args.tx_id:X} can_rx=0x{args.rx_id:X} "
            f"isotp={args.isotp_addressing}"
        )
        if args.isotp_addressing == "extended":
            line += f" ext_src=0x{args.source_addr:X} ext_tgt=0x{args.target_addr:X}"
        self._print(line)

        if self._session.defs_file:
            status = "enabled" if self._session.defs_available else "unavailable"
            self._print(f"defs={self._session.defs_file} ({status})")

        self._session.start()

        try:
            while self._running:
                line = input("> ")
                if not line.strip():
                    continue
                if line.startswith(":"):
                    try:
                        self._commands.execute(line)
                    except Exception as exc:  # pylint: disable=broad-except
                        self._print(f"Error: {exc}")
                    continue

                self._print("Input must be a command (start with ':'). Use :help")
        except KeyboardInterrupt:
            self._print("Interrupted.")
        finally:
            self._stop()
            self._session.stop()

        return 0

    def run_commands(self, commands: list[str]) -> int:
        """Execute a list of commands non-interactively and exit."""
        self._session.start()
        exit_code = 0
        try:
            for cmd in commands:
                cmd = cmd.strip()
                if not cmd:
                    continue
                if cmd.startswith(":"):
                    try:
                        self._commands.execute(cmd)
                    except Exception as exc:  # pylint: disable=broad-except
                        self._print(f"Error: {exc}")
                        exit_code = 1
                else:
                    self._print("Error: non-command input is not allowed. Use :help")
                    exit_code = 1
        except KeyboardInterrupt:
            self._print("Interrupted.")
            exit_code = 1
        finally:
            self._session.stop()
        return exit_code
