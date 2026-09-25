import os, tempfile, pytest

@pytest.fixture(autouse=True)
def lab_home(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGAI_TRADE_HOME", str(tmp_path / "lab"))
    import plugai_trade.store as s
    s._default = None
    yield tmp_path / "lab"
