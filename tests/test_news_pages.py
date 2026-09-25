"""Walk the Chapter 6 / 28 / 31 in-lab steps through the real pages (AppTest, offline)."""

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import ai, scheduler
from plugai_trade.store import default as store


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(ai, "ollama_ok", lambda *a, **k: False)


def _app(module: str) -> AppTest:
    at = AppTest.from_string(f"from plugai_trade.app.pages import {module} as m\nm.render()\n",
                             default_timeout=90)
    at.run()
    assert not at.exception
    return at


def _click(at: AppTest, label: str) -> None:
    next(b for b in at.button if b.label == label).click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_news_pipeline_walkthrough():
    at = _app("news_pipeline")
    at.date_input(key="np_from_IN").set_value("2026-01-01")
    at.date_input(key="np_to_IN").set_value("2026-05-29")
    _click(at, "Fetch now")
    assert any("stamped headlines" in m.value for m in at.markdown)
    assert any(e.label.startswith("Unstamped") for e in at.expander)
    _click(at, "Score")
    _click(at, "Compare scorers")
    assert any("Agreement" in m.value for m in at.markdown)
    _click(at, "Save rule")
    assert store().count("notes", tag="news-rule") == 1
    _click(at, "Run event study")
    assert any(m.label == "Trials" for m in at.metric)
    assert store().count("trials", tag="news-event-study") == 1


def test_scheduler_walkthrough():
    at = _app("scheduler")
    _click(at, "Add job")
    at.selectbox(key="sch_type").set_value("News Pipeline: fetch")
    at.run()
    _click(at, "Accept")
    assert scheduler.jobs()[0]["job"] == "News Pipeline: fetch"
    _click(at, "Run now")
    _click(at, "View log")
    assert len(scheduler.log()) == 1
    _click(at, "Pause all")
    assert scheduler.paused()
    at.toggle(key="sch_health").set_value(True)
    at.run()
    assert scheduler.health_alert_enabled()


def test_mcp_page_walkthrough():
    at = _app("mcp_server")
    _click(at, "Copy config for Claude Desktop")
    assert any('"plugai-trade"' in c.value and '"mcp"' in c.value for c in at.code)
    assert any("public HTTPS" in i.value for i in at.info)
    at.toggle(key="mcp_paper_toggle").set_value(False)
    at.run()
    from plugai_trade import mcp_server
    assert not mcp_server.paper_order_enabled()
    assert any(e.label == "Tool-call log" for e in at.expander)
