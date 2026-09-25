import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "mocknet: test mocks HTTP itself; do not force offline mode")


@pytest.fixture(autouse=True)
def lab_home(monkeypatch, tmp_path, request):
    monkeypatch.setenv("PLUGAI_TRADE_HOME", str(tmp_path / "lab"))
    if request.node.get_closest_marker("mocknet") is None:
        monkeypatch.setenv("PLUGAI_TRADE_OFFLINE", "1")
    else:
        monkeypatch.delenv("PLUGAI_TRADE_OFFLINE", raising=False)
    import plugai_trade.store as s
    s._default = None
    yield tmp_path / "lab"
