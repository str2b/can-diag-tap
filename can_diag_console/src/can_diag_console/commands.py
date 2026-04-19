from __future__ import annotations

import sys
import time
from typing import Callable

from .auth_oem1 import AuthRunResult, KwpAuthOem1Config, KwpAuthOem1Runner
from .memory_read import KwpMemoryReader, MemoryReadOptions, export_srec
from .protocols import DiagProtocol, parse_hex_bytes, fmt_hex
from .session import DiagnosticSession


class _ProgressBar:
    """In-place terminal progress bar for memory read operations."""

    _BAR_WIDTH = 38

    def __init__(self, start: int, end: int) -> None:
        self._start = start
        self._total = max(end - start, 1)
        self._drawn = False

    def update(self, done: int, total: int) -> None:
        pct = 100.0 * done / total if total > 0 else 0.0
        filled = int(self._BAR_WIDTH * done / total) if total > 0 else 0
        bar = "=" * filled + "-" * (self._BAR_WIDTH - filled)
        addr = self._start + done
        sys.stdout.write(f"\r[{bar}] {pct:5.1f}%  @ 0x{addr:08X}")
        sys.stdout.flush()
        self._drawn = True

    def print_message(self, msg: str) -> None:
        """Print a line above the bar (clears bar line first, then redraws after)."""
        if self._drawn:
            sys.stdout.write("\r" + " " * (self._BAR_WIDTH + 24) + "\r")
        print(msg, flush=True)
        self._drawn = False

    def finish(self) -> None:
        if self._drawn:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._drawn = False


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
        self._command_handlers: dict[str, Callable[[str], bool]] = {}
        self._custom_handlers: list[Callable[[str], bool]] = []
        self._register_builtin_commands()

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
        """Register a command handler under one or more command names."""
        command_names = (name, *aliases)
        for command_name in command_names:
            normalized = command_name.strip().lower()
            if not normalized:
                raise ValueError("Command name must not be empty.")
            self._command_handlers[normalized] = handler

    def register_custom_handler(self, handler: Callable[[str], bool]) -> None:
        """Backward-compatible fallback hook for plugin command handlers."""
        self._custom_handlers.append(handler)

    def _register_builtin_commands(self) -> None:
        self.register_command("quit", self._handle_quit, aliases=("q", "exit"))
        self.register_command("help", self._handle_help, aliases=("h",))
        self.register_command("businfo", self._handle_businfo)
        self.register_command("tx", self._handle_tx)
        self.register_command("rx", self._handle_rx)
        self.register_command("proto", self._handle_proto)
        self.register_command("defs", self._handle_defs)
        self.register_command("nodefs", self._handle_nodefs)
        self.register_command("tp", self._handle_tp)
        self.register_command("kwp-tp", self._handle_kwp_tester_present)
        self.register_command("kwp-rmem", self._handle_kwp_read_memory)
        self.register_command("kwp-auth-sk", self._handle_kwp_auth_sk)

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

        handler = self._command_handlers.get(command_name)
        if handler is not None:
            return handler(arguments)

        for handler in self._custom_handlers:
            if handler(cmd):
                return True

        self._emit("Unknown command. Use :help")
        return True

    def _handle_quit(self, _args: str) -> bool:
        self._stop_console()
        return True

    def _handle_help(self, _args: str) -> bool:
        lines = [
            "usage: :<command> [arguments]",
            "",
            "commands:",
            "  :help, :h                                show this help message",
            "  :quit, :q, :exit                         disconnect and exit",
            "  :businfo                                 show adapter / bus information",
            "  :proto <protocol>                        switch protocol  {kwp2000,uds}",
            "  :tx <id>                                 set tester-to-ECU CAN ID (hex)",
            "  :rx <id>                                 set ECU-to-tester CAN ID (hex)",
            "  :defs <path>                             load service definitions JSON",
            "  :nodefs                                  unload service definitions",
            "  :tp <hex-bytes>                          send raw transport payload bytes",
            "  :kwp-tp <subcommand> [...]               manage tester-present keepalive",
            "  :kwp-rmem <start> <end> [...]            read ECU memory range",
            "  :kwp-auth-sk [seed1=<hex>] [...]          run KWP seed-key auth flow",
            "",
            ":kwp-tp subcommands:",
            "  on [<interval_s>] [<hex-bytes>]   start tester-present  (default: 2.0 s, payload '3E 01')",
            "  off                               stop tester-present",
            "  status                            show current tester-present state",
            "  toggle                            toggle tester-present on/off",
            "",
            ":kwp-rmem arguments:",
            "  <start>                   start address, hex (e.g. 0x80000000)",
            "  <end>                     end address, hex, inclusive (e.g. 0x80000EFF)",
            "  [chunk=<size>]            bytes per read request       (default: 0xFE)",
            "  [type=<byte>]             memory type byte             (default: 0x00)",
            "  [timeout=<seconds>]       per-request timeout          (default: 1.0)",
            "  [srec=<path>]             save result as Motorola S-record file (enables quiet/progress mode)",
            "",
            ":kwp-auth-sk options:",
            f"  seed1=<hex>               challenge request seed1        (default: {KwpAuthOem1Config().user_magic.hex().upper()})",
            "  retries=<n>               release-auth retry count      (default: 3)",
            "  delay=<seconds>           delay between retries         (default: 2.0)",
            "  timeout=<seconds>         timeout per request           (default: 2.0)",
            "  prompt cancel             type abort/cancel/:q (or Ctrl+C) at key prompt",
        ]
        for line in lines:
            self._emit(line)
        return True

    def _handle_businfo(self, _args: str) -> bool:
        self._emit("Bus info:")
        info = self._session.bus_info()
        for key in (
            "adapter",
            "interface",
            "channel",
            "bitrate",
            "bus_open",
            "adapter_options",
            "gs_usb_selected",
        ):
            if key in info:
                self._emit(f"  {key}: {info[key]}")
        return True

    def _handle_tx(self, args: str) -> bool:
        if not args:
            self._emit("Usage: :tx <id>")
            return True
        val = int(args, 0)
        self._session.set_tx_id(val)
        self._emit(f"TX id set to 0x{val:X}")
        return True

    def _handle_rx(self, args: str) -> bool:
        if not args:
            self._emit("Usage: :rx <id>")
            return True
        val = int(args, 0)
        self._session.set_rx_id(val)
        self._emit(f"RX id set to 0x{val:X}")
        return True

    def _handle_proto(self, args: str) -> bool:
        val = args.strip().lower()
        if val not in {p.value for p in DiagProtocol}:
            self._emit("Unsupported protocol. Use kwp2000 or uds.")
            return True
        self._session.set_protocol(val)
        self._emit(f"Protocol switched to {val}")
        return True

    def _handle_defs(self, args: str) -> bool:
        defs_path = args.strip()
        if not defs_path:
            self._emit("Usage: :defs <path>")
            return True
        self._session.set_defs(defs_path)
        if self._session.defs_available:
            self._emit(f"Defs loaded from {defs_path}")
        else:
            self._emit("Defs parser unavailable. Ensure the definitions file is valid.")
        return True

    def _handle_nodefs(self, _args: str) -> bool:
        self._session.disable_defs()
        self._emit("Definitions parsing disabled.")
        return True

    def _handle_tp(self, args: str) -> bool:
        payload_text = args.strip()
        if not payload_text:
            self._emit("Usage: :tp <hex bytes>")
            return True

        payload = parse_hex_bytes(payload_text)
        self._session.send(payload, tag="TP")
        return True

    def _handle_kwp_tester_present(self, args: str) -> bool:
        rest = args.strip()
        if not rest:
            status = self._session.tester_present_status()
            state = "on" if status["enabled"] else "off"
            self._emit(
                f"kwp-tp {state} interval={status['interval']:.2f}s payload={fmt_hex(status['payload'])}"
            )
            return True

        tokens = rest.split()
        mode = tokens[0].lower()

        if mode in {"off", "stop", "disable"}:
            self._session.stop_tester_present()
            self._emit("kwp-tp disabled")
            return True

        if mode in {"status", "show"}:
            status = self._session.tester_present_status()
            state = "on" if status["enabled"] else "off"
            self._emit(
                f"kwp-tp {state} interval={status['interval']:.2f}s payload={fmt_hex(status['payload'])}"
            )
            return True

        if mode == "toggle":
            status = self._session.tester_present_status()
            if status["enabled"]:
                self._session.stop_tester_present()
                self._emit("kwp-tp disabled")
            else:
                self._session.start_tester_present()
                self._emit("kwp-tp enabled interval=2.00s payload=3E 00")
            return True

        if mode not in {"on", "start", "enable"}:
            self._emit("Usage: :kwp-tp <on|off|status|toggle> [interval_s] [hex bytes]")
            return True

        interval = 2.0
        payload = bytes([0x3E, 0x00])

        if len(tokens) >= 2:
            try:
                interval = float(tokens[1])
                payload_tokens = tokens[2:]
            except ValueError:
                payload_tokens = tokens[1:]
        else:
            payload_tokens = []

        if payload_tokens:
            payload = parse_hex_bytes(" ".join(payload_tokens))

        self._session.start_tester_present(interval=interval, payload=payload)
        self._emit(f"kwp-tp enabled interval={interval:.2f}s payload={fmt_hex(payload)}")
        return True

    def _handle_kwp_read_memory(self, args: str) -> bool:
        rest = args.strip()
        if not rest:
            self._emit(
                "Usage: :kwp-rmem <start> <end> [chunk=0xF0] [type=0x00] [timeout=1.0] [srec=<path>]"
            )
            return True

        tokens = rest.split()
        if len(tokens) < 2:
            self._emit(
                "Usage: :kwp-rmem <start> <end> [chunk=0xF0] [type=0x00] [timeout=1.0] [srec=<path>]"
            )
            return True

        start = int(tokens[0], 0)
        end = int(tokens[1], 0)

        chunk_size = 0xF0
        memory_type = 0x00
        timeout = 1.0
        srec_path: str | None = None

        for token in tokens[2:]:
            if token.startswith("chunk="):
                chunk_size = int(token.split("=", 1)[1], 0)
            elif token.startswith("type="):
                memory_type = int(token.split("=", 1)[1], 0)
            elif token.startswith("timeout="):
                timeout = float(token.split("=", 1)[1])
            elif token.startswith("srec="):
                srec_path = token.split("=", 1)[1]
            elif token.startswith("quiet"):
                self._emit("Option 'quiet' was removed. Quiet/progress mode is enabled automatically when srec=<path> is set.")
                return True

        quiet = srec_path is not None

        options = MemoryReadOptions(
            chunk_size=chunk_size,
            memory_type=memory_type,
            timeout=timeout,
        )

        bar = _ProgressBar(start, end) if quiet else None

        reader = KwpMemoryReader(
            request_fn=lambda payload, req_timeout, matcher: self._session.request(
                payload,
                timeout=req_timeout,
                matcher=matcher,
            ),
            emit=bar.print_message if bar is not None else self._emit,
            progress_cb=bar.update if bar is not None else None,
        )

        self._emit(
            f"[memread] start=0x{start:08X} end=0x{end:08X} chunk=0x{chunk_size:02X} type=0x{memory_type:02X}"
        )

        self._session.suppress_trace_output(quiet)
        t0 = time.monotonic()
        try:
            result = reader.read_range(start, end, options)
        finally:
            elapsed = time.monotonic() - t0
            self._session.suppress_trace_output(False)
            if bar is not None:
                bar.finish()

        self._emit(
            f"[memread] bytes_read=0x{result.bytes_read:X} chunks={len(result.chunks)}"
            f" blocked={len(result.blocked_addresses)} duration={elapsed:.1f}s"
        )

        if srec_path:
            out_path = export_srec(result.chunks, srec_path)
            self._emit(f"[memread] srec={out_path}")

        return True

    def _handle_kwp_auth_sk(self, args: str) -> bool:
        retries = 3
        delay = 2.0
        timeout = 2.0
        seed1: bytes | None = None

        for token in args.split():
            low = token.lower()
            try:
                if low.startswith("seed1="):
                    seed1 = parse_hex_bytes(token.split("=", 1)[1])
                elif low.startswith("retries="):
                    retries = int(token.split("=", 1)[1], 0)
                elif low.startswith("delay="):
                    delay = float(token.split("=", 1)[1])
                elif low.startswith("timeout="):
                    timeout = float(token.split("=", 1)[1])
                else:
                    self._emit(
                        "Usage: :kwp-auth-sk [seed1=<hex>] [retries=<n>] [delay=<seconds>] [timeout=<seconds>]"
                    )
                    self._emit("Key payload is entered interactively after ECU challenge is read.")
                    return True
            except Exception as exc:  # pylint: disable=broad-except
                self._emit(f"Invalid option value: {exc}")
                return True

        if seed1 is not None and len(seed1) != 4:
            self._emit("Usage error: seed1 must be exactly 4 bytes")
            return True

        cfg = KwpAuthOem1Config(
            **(dict(user_magic=seed1) if seed1 is not None else {}),
            # remaining fields always explicit
            request_timeout=max(0.1, timeout),
            release_retries=max(1, retries),
            release_retry_delay=max(0.0, delay),
        )

        runner = KwpAuthOem1Runner(
            request_fn=lambda payload, req_timeout, matcher: self._session.request(
                payload,
                timeout=req_timeout,
                matcher=matcher,
            ),
            emit=self._emit,
            prompt_input=input,
            sleep_fn=time.sleep,
            config=cfg,
        )

        result = runner.run()
        if result == AuthRunResult.SUCCESS:
            self._emit("[kwp-auth-sk] completed")
        elif result == AuthRunResult.ABORTED:
            self._emit("[kwp-auth-sk] aborted")
        else:
            self._emit("[kwp-auth-sk] failed")
        return True
