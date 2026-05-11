from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable
import subprocess
import sys
from ..hex_utils import fmt_hex, parse_hex_bytes
from .base import CommandContext, CommandSpec


class AuthState(str, Enum):
    READ_SERIAL = "read-serial"
    REQUEST_CHALLENGE = "request-challenge"
    WAIT_USER_KEY = "wait-user-key"
    SUBMIT_KEY = "submit-key"
    DONE = "done"


class AuthRunResult(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class KwpAuthOem1Config:
    user_magic: bytes = b"CDC1"
    security_level: int = 0x03
    auth_key_length: int = 0x10
    request_timeout: float = 2.0
    release_retries: int = 3
    release_retry_delay: float = 2.0


class KwpAuthOem1Runner:
    """Runs the KWP seed-key auth sequence with user-provided key material."""

    def __init__(
        self,
        request_fn: Callable[[bytes, float, Callable[[bytes], bool] | None], bytes | None],
        emit: Callable[[str], None],
        prompt_input: Callable[[str], str],
        sleep_fn: Callable[[float], None],
        config: KwpAuthOem1Config | None = None,
        key_calc_fn: Callable[[bytes, bytes, bytes], bytes] | None = None,
    ) -> None:
        self._request = request_fn
        self._emit = emit
        self._prompt_input = prompt_input
        self._sleep = sleep_fn
        self._cfg = config or KwpAuthOem1Config()
        self._key_calc_fn = key_calc_fn

    def run(self) -> AuthRunResult:
        state = AuthState.READ_SERIAL
        serial: bytes | None = None
        seed2: bytes | None = None
        challenge: bytes | None = None

        while state != AuthState.DONE:
            if state == AuthState.READ_SERIAL:
                self._emit("[kwp-auth-sk] state=read-serial")
                serial_resp = self._request_with_match(
                    payload=bytes([0x1A, 0x89]),
                    expected_positive=lambda resp: len(resp) >= 2 and resp[0] == 0x5A and resp[1] == 0x89,
                    timeout=self._cfg.request_timeout,
                )
                if serial_resp is None:
                    self._emit("[kwp-auth-sk] failed: no response to 1A 89")
                    return AuthRunResult.FAILED
                if self._is_negative(serial_resp, 0x1A):
                    self._emit(f"[kwp-auth-sk] failed: negative on 1A 89 -> {fmt_hex(serial_resp)}")
                    return AuthRunResult.FAILED

                if len(serial_resp) < 4:
                    self._emit("[kwp-auth-sk] failed: short response to 1A 89 (need >= 4 bytes for seed2)")
                    return AuthRunResult.FAILED

                serial = serial_resp[2:]
                seed2 = serial_resp[-4:]
                self._emit(f"[kwp-auth-sk] serial={fmt_hex(serial)}")
                state = AuthState.REQUEST_CHALLENGE
                continue

            if state == AuthState.REQUEST_CHALLENGE:
                self._emit("[kwp-auth-sk] state=request-challenge")
                payload = bytes([0x31, 0x07, self._cfg.security_level]) + self._cfg.user_magic
                challenge_resp = self._request_with_match(
                    payload=payload,
                    expected_positive=lambda resp: len(resp) >= 3 and resp[0] == 0x71 and resp[1] == 0x07,
                    timeout=self._cfg.request_timeout,
                )
                if challenge_resp is None:
                    self._emit("[kwp-auth-sk] failed: no response to challenge request")
                    return AuthRunResult.FAILED
                if self._is_negative(challenge_resp, 0x31):
                    self._emit(
                        f"[kwp-auth-sk] failed: negative on challenge request -> {fmt_hex(challenge_resp)}"
                    )
                    return AuthRunResult.FAILED

                challenge = challenge_resp[2:]
                self._emit(
                    "[kwp-auth-sk] seeds "
                    f"seed1={self._compact_hex(self._cfg.user_magic)} "
                    f"seed2={self._compact_hex(seed2 or b'')} "
                    f"seed3={self._compact_hex(challenge)}"
                )
                state = AuthState.WAIT_USER_KEY
                continue

            if state == AuthState.WAIT_USER_KEY:
                self._emit("[kwp-auth-sk] state=wait-user-key")
                if self._key_calc_fn is not None:
                    try:
                        key_payload = self._key_calc_fn(
                            self._cfg.user_magic, seed2 or b"", challenge or b""
                        )
                    except Exception as exc:  # pylint: disable=broad-except
                        self._emit(f"[kwp-auth-sk] key-script error: {exc}")
                        return AuthRunResult.FAILED
                    if not key_payload:
                        self._emit("[kwp-auth-sk] key-script returned empty payload")
                        return AuthRunResult.FAILED
                    self._emit(f"[kwp-auth-sk] key-script result: {fmt_hex(key_payload)}")
                else:
                    prompt = "Enter auth key payload as hex bytes: "
                    try:
                        key_hex = self._prompt_input(prompt).strip()
                    except KeyboardInterrupt:
                        self._emit("[kwp-auth-sk] aborted by user")
                        return AuthRunResult.ABORTED

                    if key_hex.lower() in {"abort", "cancel", ":q", ":quit", ":exit"}:
                        self._emit("[kwp-auth-sk] aborted by user")
                        return AuthRunResult.ABORTED

                    try:
                        key_payload = parse_hex_bytes(key_hex)
                    except Exception as exc:  # pylint: disable=broad-except
                        self._emit(f"[kwp-auth-sk] invalid key input: {exc}")
                        return AuthRunResult.FAILED

                    if not key_payload:
                        self._emit("[kwp-auth-sk] invalid key input: empty payload")
                        return AuthRunResult.FAILED

                state = AuthState.SUBMIT_KEY
                release_payload = bytes([0x31, 0x08]) + self._cfg.auth_key_length.to_bytes(4, "big") + key_payload
                self._emit(f"[kwp-auth-sk] key-bytes={len(key_payload)}")

                accepted = False
                for attempt in range(1, self._cfg.release_retries + 1):
                    self._emit(f"[kwp-auth-sk] submit-key attempt {attempt}/{self._cfg.release_retries}")
                    release_resp = self._request_with_match(
                        payload=release_payload,
                        expected_positive=lambda resp: len(resp) >= 2 and resp[0] == 0x71 and resp[1] == 0x08,
                        timeout=self._cfg.request_timeout,
                    )
                    if release_resp is None:
                        self._emit("[kwp-auth-sk] no response on submit-key")
                    elif self._is_negative(release_resp, 0x31):
                        self._emit(f"[kwp-auth-sk] submit-key negative -> {fmt_hex(release_resp)}")
                    else:
                        self._emit("[kwp-auth-sk] auth accepted")
                        accepted = True
                        break

                    if attempt < self._cfg.release_retries:
                        self._sleep(self._cfg.release_retry_delay)

                if not accepted:
                    return AuthRunResult.FAILED

                state = AuthState.DONE
                continue

            self._emit(f"[kwp-auth-sk] internal error: unknown state {state}")
            return AuthRunResult.FAILED

        return AuthRunResult.SUCCESS

    def _request_with_match(
        self,
        *,
        payload: bytes,
        expected_positive: Callable[[bytes], bool],
        timeout: float,
    ) -> bytes | None:
        service_id = payload[0] if payload else 0x00

        def _matcher(resp: bytes) -> bool:
            return expected_positive(resp) or self._is_negative(resp, service_id)

        return self._request(payload, timeout, _matcher)

    @staticmethod
    def _is_negative(payload: bytes, service_id: int) -> bool:
        return len(payload) >= 2 and payload[0] == 0x7F and payload[1] == service_id

    @staticmethod
    def _compact_hex(payload: bytes) -> str:
        return payload.hex().upper()


_SECTIONS = [
    (
        ":kwp-auth-sk options:",
        [
            f"  seed1=<hex>               challenge request seed1        (default: {KwpAuthOem1Config().user_magic.hex().upper()})",
            "  retries=<n>               release-auth retry count      (default: 3)",
            "  delay=<seconds>           delay between retries         (default: 2.0)",
            "  timeout=<seconds>         timeout per request           (default: 2.0)",
            "  keyscript=<path>          path to key-calc script       (called with --s1/--s2/--s3 hex args, prints key hex)",
            "  prompt cancel             type abort/cancel/:q (or Ctrl+C) at key prompt",
        ],
    )
]


def _handle_kwp_auth_sk(ctx: CommandContext, args: str) -> bool:
    retries = 3
    delay = 2.0
    timeout = 2.0
    seed1: bytes | None = None
    keyscript: str | None = None

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
            elif token.startswith("keyscript="):
                keyscript = token.split("=", 1)[1]
            else:
                ctx.emit("Usage: :kwp-auth-sk [seed1=<hex>] [retries=<n>] [delay=<seconds>] [timeout=<seconds>]")
                ctx.emit("Key payload is entered interactively after ECU challenge is read.")
                return True
        except Exception as exc:  # pylint: disable=broad-except
            ctx.emit(f"Invalid option value: {exc}")
            return True

    if seed1 is not None and len(seed1) != 4:
        ctx.emit("Usage error: seed1 must be exactly 4 bytes")
        return True

    cfg = KwpAuthOem1Config(
        **(dict(user_magic=seed1) if seed1 is not None else {}),
        request_timeout=max(0.1, timeout),
        release_retries=max(1, retries),
        release_retry_delay=max(0.0, delay),
    )

    def _run_keyscript(s1: bytes, s2: bytes, s3: bytes) -> bytes:
        cmd = [
            sys.executable,
            keyscript,
            "--s1",
            s1.hex(),
            "--s2",
            s2.hex(),
            "--s3",
            s3.hex(),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "").strip()
            if details:
                raise RuntimeError(f"external script failed ({exc.returncode}): {details}") from exc
            raise RuntimeError(f"external script failed ({exc.returncode})") from exc

        return parse_hex_bytes(result.stdout.strip())

    runner = KwpAuthOem1Runner(
        request_fn=lambda payload, req_timeout, matcher: ctx.session.request(
            payload,
            timeout=req_timeout,
            matcher=matcher,
        ),
        emit=ctx.emit,
        prompt_input=input,
        sleep_fn=time.sleep,
        config=cfg,
        key_calc_fn=_run_keyscript if keyscript is not None else None,
    )

    result = runner.run()
    if result == AuthRunResult.SUCCESS:
        ctx.emit("[kwp-auth-sk] completed")
    elif result == AuthRunResult.ABORTED:
        ctx.emit("[kwp-auth-sk] aborted")
    else:
        ctx.emit("[kwp-auth-sk] failed")
    return True


def command_spec() -> CommandSpec:
    return CommandSpec(
        name="kwp-auth-sk",
        handler=_handle_kwp_auth_sk,
        summary=":kwp-auth-sk [seed1=<hex>] [...]         run KWP seed-key auth flow",
        help_sections=_SECTIONS,
    )
