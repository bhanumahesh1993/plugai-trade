"""Tax Export driven like a reader: IN tabs and US checks, offline, always a draft."""

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import ai


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def offline(*a, **k):
        raise ConnectionError("offline test")
    monkeypatch.setattr(ai, "_ollama_chat", offline)
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)


def app(market: str) -> AppTest:
    at = AppTest.from_string("from plugai_trade.app.pages import tax_export as m\nm.render()\n",
                             default_timeout=60)
    at.session_state["market"] = market
    return at.run()


def click(at: AppTest, label: str, key: str | None = None) -> AppTest:
    next(b for b in at.button if b.label == label and (key is None or b.key == key)).click()
    return at.run()


def test_india_classify_turnover_export(lab_home):
    at = app("IN")
    assert any("DRAFT FOR YOUR CA / CPA" in w.value for w in at.warning)
    assert [t.label for t in at.tabs][:4] == ["Classify", "Turnover", "AIS check", "Export"]
    click(at, "Load lesson sample (Meera, synthetic)")
    click(at, "Classify")
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["F&O TURNOVER (ICAI)"] == "₹39,585"
    assert metrics["F&O NET RESULT"] == "−₹1,105"
    assert metrics["AUDIT CHECK"] == "Below limit"
    click(at, "Export")
    assert at.session_state["tx_itr"].startswith("# DRAFT FOR YOUR CA / CPA")
    click(at, "Add this year's losses from the classified rows")
    assert not at.exception


def test_us_wash_sale_1256_and_export(lab_home):
    at = app("US")
    click(at, "Load lesson sample (Dan, synthetic)")
    assert not at.toggle[0].value                          # Crypto wash-sale check: off
    click(at, "Wash-sale check")
    assert at.session_state["tx_wash"].hits.height == 1
    click(at, "1256 tagging")
    click(at, "Export", key="tx_exp_us")
    assert not at.exception
    assert ",W,800.00," in at.session_state["tx_8949"]
