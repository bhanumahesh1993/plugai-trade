"""Journal screens driven like a reader: the book's buttons, offline, no model."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import ai, journal

FIX = Path(__file__).parent / "fixtures" / "journal"


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def offline(*a, **k):
        raise ConnectionError("offline test")
    monkeypatch.setattr(ai, "_ollama_chat", offline)
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)


def app(module: str, market: str = "IN") -> AppTest:
    at = AppTest.from_string(f"from plugai_trade.app.pages import {module} as m\nm.render()\n",
                             default_timeout=60)
    at.session_state["market"] = market
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click()
    return at.run()


def labels(at: AppTest) -> set[str]:
    return {b.label for b in at.button}


def test_trades_import_accept_and_replay(lab_home):
    at = app("trades")
    at.session_state["trades_pending"] = journal.import_tradebook(FIX / "zerodha_tradebook.csv")
    at.run()
    assert {"Import tradebook", "Match plans", "Accept"} <= labels(at)
    click(at, "Match plans")
    click(at, "Accept")
    assert not at.exception
    assert journal.trades().height == 3
    assert {"Replay", "Save tags"} <= labels(at)
    click(at, "Replay")
    assert at.session_state["paper_replay_request"]["tag"] == "REPLAY"
    click(at, "Generate review")
    assert not at.exception and "Show sources" in labels(at)


def test_trades_lesson_sample_us():
    at = app("trades", "US").run()
    click(at, "Load lesson 14 sample (Marcus, synthetic)")
    assert not at.exception
    assert any(m.label == "Round trips" and m.value == "61" for m in at.metric)


def test_weekly_review_generate_show_query_save(lab_home):
    at = app("weekly_review").run()
    click(at, "Load lesson 14 sample (Kavita, synthetic)")
    assert [m.label for m in at.metric][:6] == ["TRADES", "RESULT", "CHARGES", "NET",
                                                "ADHERENCE", "BREAKS COST"]
    click(at, "Generate review")
    click(at, "Show query")
    assert any("SELECT" in c.value for c in at.code)
    click(at, "Save review")
    assert not at.exception
    from plugai_trade.store import default as store
    assert store().count("reviews", tag="weekly") == 1


def test_ask_my_journal_query_line_show_query_and_pin(lab_home):
    at = app("ask_journal").run()
    click(at, "Load lesson 14 sample (Kavita, synthetic)")
    at.chat_input[0].set_value("How did I do on trades I opened soon after a loss?").run()
    assert not at.exception
    assert any("The lab runs:" in c.value for c in at.caption)
    click(at, "Show query")
    assert any("gap_minutes <= 30" in c.value for c in at.code)
    click(at, "Accept")
    from plugai_trade.journal import review
    assert len(review.pinned_specs()) == 1
