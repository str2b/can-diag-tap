from argparse import Namespace

from can_diag_console.commands import CommandProcessor


class _FakeSession:
    def __init__(self) -> None:
        self.defs_available = True
        self.sent = []
        self.tp = {"enabled": False, "interval": 2.0, "payload": bytes([0x3E, 0x00])}
        self.args = Namespace()
        self.requests = []
        self.scripted_responses = []

    def bus_info(self):
        return {"adapter": "python-can"}

    def set_tx_id(self, _):
        return

    def set_rx_id(self, _):
        return

    def set_protocol(self, _):
        return

    def set_defs(self, _):
        return

    def disable_defs(self):
        return

    def send(self, payload: bytes, *, tag: str = "TX"):
        self.sent.append((tag, payload))

    def request(self, payload: bytes, *, timeout: float = 1.0, matcher=None):
        self.requests.append((payload, timeout))
        if self.scripted_responses:
            resp = self.scripted_responses.pop(0)
            if matcher is None or matcher(resp):
                return resp
            return None
        resp = bytes([0x63]) + bytes([0x00] * payload[-1])
        if matcher is None or matcher(resp):
            return resp
        return None

    def tester_present_status(self):
        return self.tp

    def start_tester_present(self, interval: float = 2.0, payload: bytes | None = None):
        self.tp = {
            "enabled": True,
            "interval": interval,
            "payload": payload or bytes([0x3E, 0x00]),
        }

    def stop_tester_present(self):
        self.tp["enabled"] = False

    def suppress_trace_output(self, _enabled: bool):
        return


def test_tp_command_sends_payload() -> None:
    out = []
    stopped = {"v": False}
    sess = _FakeSession()

    proc = CommandProcessor(
        session=sess,
        emit=out.append,
        stop_console=lambda: stopped.__setitem__("v", True),
    )

    assert proc.execute(":tp 3e 01") is True
    assert sess.sent == [("TX", bytes([0x3E, 0x01]))]


def test_kwp_tp_enable_and_disable() -> None:
    out = []
    sess = _FakeSession()

    proc = CommandProcessor(
        session=sess,
        emit=out.append,
        stop_console=lambda: None,
    )

    assert proc.execute(":kwp-tp on 1.5 3e 00") is True
    assert sess.tp["enabled"] is True
    assert abs(sess.tp["interval"] - 1.5) < 1e-6
    assert sess.tp["payload"] == bytes([0x3E, 0x00])

    assert proc.execute(":kwp-tp off") is True
    assert sess.tp["enabled"] is False


def test_kwp_rmem_command_requests_blocks() -> None:
    out = []
    sess = _FakeSession()

    proc = CommandProcessor(
        session=sess,
        emit=out.append,
        stop_console=lambda: None,
    )

    assert proc.execute(":kwp-rmem 0x1000 0x1008 chunk=0x04 type=0x00 timeout=0.1") is True
    # Two requests of size 4: [0x1000..0x1004), [0x1004..0x1008)
    assert len(sess.requests) == 2
    assert sess.requests[0][0][:1] == bytes([0x23])


def test_kwp_auth_sk_command_prompts_for_key(monkeypatch) -> None:
    out = []
    sess = _FakeSession()
    sess.scripted_responses = [
        bytes([0x5A, 0x89, 0x33, 0x32, 0x31]),
        bytes([0x71, 0x07, 0x66, 0xD0, 0xFE, 0xF9, 0x91, 0xCB, 0x65, 0xC7]),
        bytes([0x71, 0x08, 0x01]),
    ]

    proc = CommandProcessor(
        session=sess,
        emit=out.append,
        stop_console=lambda: None,
    )

    monkeypatch.setattr("builtins.input", lambda _prompt: "00112233445566778899AABBCCDDEEFF")

    assert (
        proc.execute(":kwp-auth-sk retries=1 delay=0 timeout=0.1")
        is True
    )

    assert sess.requests[0][0] == bytes([0x1A, 0x89])
    assert sess.requests[1][0] == bytes([0x31, 0x07, 0x03, 0x43, 0x44, 0x43, 0x31])
    assert sess.requests[2][0][:6] == bytes([0x31, 0x08, 0x00, 0x00, 0x00, 0x10])
    assert len(sess.requests) == 3
    assert not any(req[0] == bytes([0x10, 0x85]) for req in sess.requests)
    assert any(
        "seeds seed1=43444331 seed2=89333231 seed3=66D0FEF991CB65C7" in line
        for line in out
    )
    assert any("[kwp-auth-sk] completed" in line for line in out)


def test_kwp_auth_sk_command_accepts_custom_seed1(monkeypatch) -> None:
    out = []
    sess = _FakeSession()
    sess.scripted_responses = [
        bytes([0x5A, 0x89, 0xDE, 0xAD, 0xBE, 0xEF]),
        bytes([0x71, 0x07, 0x01, 0x02, 0x03, 0x04]),
        bytes([0x71, 0x08, 0x01]),
    ]

    proc = CommandProcessor(
        session=sess,
        emit=out.append,
        stop_console=lambda: None,
    )

    monkeypatch.setattr("builtins.input", lambda _prompt: "00112233445566778899AABBCCDDEEFF")

    assert proc.execute(":kwp-auth-sk seed1=A1B2C3D4 retries=1 delay=0 timeout=0.1") is True
    assert sess.requests[1][0] == bytes([0x31, 0x07, 0x03, 0xA1, 0xB2, 0xC3, 0xD4])
    assert any("seeds seed1=A1B2C3D4" in line for line in out)


def test_kwp_auth_sk_command_can_abort_at_key_prompt(monkeypatch) -> None:
    out = []
    sess = _FakeSession()
    sess.scripted_responses = [
        bytes([0x5A, 0x89, 0xAA, 0xBB, 0xCC, 0xDD]),
        bytes([0x71, 0x07, 0x11, 0x22, 0x33, 0x44]),
    ]

    proc = CommandProcessor(
        session=sess,
        emit=out.append,
        stop_console=lambda: None,
    )

    monkeypatch.setattr("builtins.input", lambda _prompt: "abort")

    assert proc.execute(":kwp-auth-sk retries=1 delay=0 timeout=0.1") is True
    assert len(sess.requests) == 2
    assert not any(req[0][:2] == bytes([0x31, 0x08]) for req in sess.requests)
    assert any("[kwp-auth-sk] aborted" in line for line in out)
    assert not any("[kwp-auth-sk] failed" in line for line in out)
