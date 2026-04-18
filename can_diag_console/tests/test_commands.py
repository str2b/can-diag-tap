from argparse import Namespace

from can_diag_console.commands import CommandProcessor


class _FakeSession:
    def __init__(self) -> None:
        self.defs_available = True
        self.sent = []
        self.tp = {"enabled": False, "interval": 2.0, "payload": bytes([0x3E, 0x00])}
        self.args = Namespace()
        self.requests = []

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


def test_kwp_command_sends_payload() -> None:
    out = []
    stopped = {"v": False}
    sess = _FakeSession()

    proc = CommandProcessor(
        session=sess,
        emit=out.append,
        stop_console=lambda: stopped.__setitem__("v", True),
    )

    assert proc.execute(":kwp 3e 01") is True
    assert sess.sent == [("KWP", bytes([0x3E, 0x01]))]


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
