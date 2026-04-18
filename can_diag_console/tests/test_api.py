from can_diag_console.api import DiagClient, DiagClientConfig


class _FakeTransport:
    def __init__(self) -> None:
        self.sent = []
        self.queue = []

    def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, timeout: float = 0.2):
        if self.queue:
            return self.queue.pop(0)
        return None

    def close(self) -> None:
        return


class _FakeAdapter:
    def __init__(self) -> None:
        self.opened = False

    def open_bus(self):
        self.opened = True
        return object()

    def close(self):
        self.opened = False

    def runtime_info(self):
        return {"adapter": "fake", "bus_open": self.opened}


def test_diag_client_request_and_recv(monkeypatch):
    fake_adapter = _FakeAdapter()
    fake_transport = _FakeTransport()
    fake_transport.queue.append(bytes([0x7E]))

    monkeypatch.setattr("can_diag_console.api.build_adapter", lambda _settings: fake_adapter)
    monkeypatch.setattr(
        "can_diag_console.api.build_transport_with_options",
        lambda **kwargs: fake_transport,
    )

    cfg = DiagClientConfig(tx_id=0x6F1, rx_id=0x612)
    with DiagClient(cfg) as client:
        response = client.request("3E 01", timeout=0.5)

    assert response == bytes([0x7E])
    assert fake_transport.sent == [bytes([0x3E, 0x01])]


def test_diag_client_tester_present(monkeypatch):
    fake_adapter = _FakeAdapter()
    fake_transport = _FakeTransport()

    monkeypatch.setattr("can_diag_console.api.build_adapter", lambda _settings: fake_adapter)
    monkeypatch.setattr(
        "can_diag_console.api.build_transport_with_options",
        lambda **kwargs: fake_transport,
    )

    cfg = DiagClientConfig(tx_id=0x6F1, rx_id=0x612)
    with DiagClient(cfg) as client:
        client.start_tester_present(interval=0.1, payload="3E 00")
        import time

        time.sleep(0.25)
        client.stop_tester_present()

    assert any(frame == bytes([0x3E, 0x00]) for frame in fake_transport.sent)
