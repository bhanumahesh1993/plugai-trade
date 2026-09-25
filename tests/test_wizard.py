"""First-run wizard and Home dashboard, offline: every self-test line passes except the model."""

import keyring
import pytest
from keyring.backend import KeyringBackend
from streamlit.testing.v1 import AppTest

from plugai_trade import ai, config, wizard
from plugai_trade.app import nav
from plugai_trade.app.pages import home


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.d = {}

    def get_password(self, service, name):
        return self.d.get((service, name))

    def set_password(self, service, name, value):
        self.d[(service, name)] = value

    def delete_password(self, service, name):
        self.d.pop((service, name), None)


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    old = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)
    yield
    keyring.set_keyring(old)


@pytest.mark.parametrize("ram,size", [(8, "small"), (12, "small"), (16, "mid"), (24, "mid"),
                                      (32, "large"), (64, "large"), (None, "mid")])
def test_ram_suggestion(ram, size):
    assert wizard.suggest(ram).size == size


def test_self_test_offline_passes_except_model():
    wizard.load_sample_data("IN")
    res = wizard.self_test("IN")
    names = [c.name for c in res.checks]
    assert names == list(wizard.SelfTest.NAMES)
    assert [c.name for c in res.failed()] == ["Model quoted it"]
    assert "Ollama not found" in res.checks[2].detail
    assert config.get("wizard.self_test")["failed"] == ["Model quoted it"]
    diag = wizard.diagnostic(res)
    assert "Self-test" in diag and "✗ Model quoted it" in diag
    assert wizard.PROBE_KEY not in (config.get("keys_index") or [])


def test_self_test_model_check_when_model_quotes(monkeypatch):
    monkeypatch.setattr(wizard, "ollama_reachable", lambda timeout=1.5: True)

    def fake_complete(prompt, **kw):
        value = prompt.split("20-day average close: ")[1].split("\n")[0]
        return ai.Explanation(text=f"The 20-day average close is {value}.", model="m")
    monkeypatch.setattr(ai, "complete", fake_complete)
    assert wizard.self_test("US").passed


def test_sample_data_both_markets():
    for m in ("IN", "US"):
        out = wizard.load_sample_data(m)
        assert set(out.rows) == set(config.DEFAULTS["watchlists"][m])
        assert all(n > 200 for n in out.rows.values())
    assert config.get("wizard.sample_loaded") == ["IN", "US"]


def test_pull_model_offline_refuses():
    with pytest.raises(ConnectionError):
        next(wizard.pull_model("qwen3.5:4b"))


@pytest.mark.mocknet
def test_pull_model_streams_progress(monkeypatch):
    import httpx
    lines = b'{"status":"pulling manifest"}\n{"status":"downloading","completed":50,"total":100}\n' \
            b'{"status":"success"}\n'
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=lines))
    monkeypatch.setattr(httpx, "stream", httpx.Client(transport=transport).stream)
    got = list(wizard.pull_model("qwen3.5:4b"))
    assert [p.status for p in got] == ["pulling manifest", "downloading", "success"]
    assert got[1].fraction == 0.5


def test_fit_check_colours():
    mid = wizard.MODELS[1]
    assert wizard.fit_check(mid, 8192, ram=16, used=4).colour == "green"
    assert wizard.fit_check(wizard.MODELS[2], 32768, ram=16, used=4).colour == "red"


def test_start_redirect_targets(monkeypatch):
    monkeypatch.delenv("PLUGAI_TRADE_LESSON", raising=False)
    monkeypatch.setenv("PLUGAI_TRADE_START_PAGE", "lessons")
    assert nav.start_target() == "lessons"
    monkeypatch.setenv("PLUGAI_TRADE_START_PAGE", "no-such-page")
    assert nav.start_target() is None
    monkeypatch.setenv("PLUGAI_TRADE_LESSON", "22")
    assert nav.start_target() == "lessons"


def _home() -> AppTest:
    return AppTest.from_string("from plugai_trade.app.pages import home as m\nm.render()\n",
                               default_timeout=60).run()


def _click(at, label):
    next(b for b in at.button if b.label == label).click()
    return at.run()


def test_wizard_walkthrough_then_dashboard():
    at = _home()
    assert any("screen 1 of 5" in m.value for m in at.markdown)
    assert any("Ollama not found" in w.value for w in at.warning)
    at = _click(at, "Check again")
    at = _click(at, "Next")
    at = _click(at, "Next")                   # model screen → cloud key
    at = _click(at, "Skip for now")
    at = _click(at, "Load sample data")
    assert any("Synthetic sample loaded" in s.value for s in at.success)
    at = _click(at, "Next")
    at = _click(at, "Run self-test")
    assert len(at.success) == 5 and len(at.error) == 1
    at = _click(at, "Copy diagnostic")
    assert any("PlugAI-Trade" in c.value for c in at.code)
    at = _click(at, "Open dashboard")
    assert not at.exception
    assert wizard.is_done()
    assert any("Sample watchlist" in m.value for m in at.markdown)


def test_dashboard_watchlists_and_clock():
    wizard.mark_done()
    at = _home()
    assert not at.exception
    t = home.watchlist_table("IN")
    assert t["Symbol"].to_list() == ["NIFTY", "BANKNIFTY", "SENSEX"]
    assert home.watchlist_table("US")["Symbol"].to_list() == ["SPY", "QQQ", "DIA"]
    clock = home.session_clock()
    assert clock[0]["Session"] == "09:15–15:30 IST" and clock[1]["Session"] == "09:30–16:00 ET"
