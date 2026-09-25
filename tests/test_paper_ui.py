"""The in-lab walkthroughs of Chapters 12, 13, 21 and 34, clicked through with AppTest."""

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import ai, config, paper, plans


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ai.Explanation(text="", where="Fallback"))
    monkeypatch.setattr(ai, "ollama_ok", lambda *a, **k: False)


def app(module, market="IN"):
    config.set_value("market", market)
    at = AppTest.from_string(f"from plugai_trade.app.pages import {module} as m\nm.render()\n",
                             default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def labels(at):
    return {b.label for b in at.button}


def test_position_sizer_ch12_nifty():
    at = app("position_sizer")
    assert {"Explain", "Use in plan", "Simulate streaks"} <= labels(at)
    at.text_input(key="sz_sym_IN").set_value("NIFTY FUT").run()
    at.number_input(key="fx_entry").set_value(24850.0).run()
    at.number_input(key="fx_stop").set_value(24700.0).run()
    m = {x.label: x.value for x in at.tabs[0].metric}   # the Fixed risk % tab
    assert m["Risk budget"] == "₹15,000" and m["Risk / lot"] == "₹10,950.00"
    assert m["Raw size"] == "1.37 lots" and m["Size ↓"] == "1 lot" and m["Actual risk"] == "0.73%"
    assert m["Notional"] == "1.08×"
    button(at, "Simulate streaks").click().run()
    assert not at.exception


def test_paper_desk_replay_place_kill_switch():
    at = app("paper_desk")
    assert {"Replay", "Place paper order", "Kill switch", "Cost preview",
            "Compare with backtest"} <= labels(at)
    assert any(m.label == "Breakeven (pts)" for m in at.metric)
    button(at, "Replay").click().run()
    button(at, "Next 1 bar").click().run()
    button(at, "Place paper order").click().run()
    assert any("WORKING" in s.value for s in at.success)
    button(at, "Next 1 bar").click().run()
    assert any("Close at next bar" == b.label for b in at.button)
    button(at, "Cost preview").click().run()
    button(at, "Kill switch").click().run()
    assert any("Kill switch" in w.value for w in at.warning)
    button(at, "Place paper order").click().run()
    assert any("BLOCKED" in e.value for e in at.error)
    button(at, "Compare with backtest").click().run()
    button(at, "Run shadow backtest").click().run()
    assert not at.exception


def test_paper_desk_pending_accept_reject():
    a = paper.draft_pending({"symbol": "SPY", "market": "US", "qty": 10}, source="MCP paper_order")
    paper.draft_pending({"symbol": "QQQ", "market": "US", "qty": 5}, source="Alert #2")
    at = app("paper_desk", "US")
    accepts = [b for b in at.button if b.label == "Accept"]
    assert len(accepts) == 2
    next(b for b in at.button if b.key == f"pd_acc_{a}").click().run()
    assert not at.exception
    button(at, "Reject").click().run()
    assert not paper.pending()


def test_trade_plan_walkthrough():
    at = app("trade_plan")
    button(at, "New plan").click().run()
    assert {"Critique", "Save to journal", "Send to Paper Desk", "Size it"} <= labels(at)
    button(at, "Critique").click().run()
    assert any("Yes/no" in i.value for i in at.info)
    button(at, "Show sources").click().run()
    button(at, "Save to journal").click().run()
    assert any("timestamped" in s.value for s in at.success)
    button(at, "Size it").click().run()
    assert not at.exception


def test_weekend_swing_template_has_owner_chips():
    at = app("trade_plan")
    at.selectbox(key="tp_template").set_value("Weekend swing plan").run()
    button(at, "New plan").click().run()
    md = " ".join(m.value for m in at.markdown)
    assert "YOU" in md and "CODE" in md and "CALENDAR" in md


def test_rule_card_tabs_and_buttons():
    at = app("rule_card")
    assert [t.label for t in at.tabs] == ["Written rules", "Checklist", "Go / no-go", "Monthly audit"]
    assert {"New version", "Sync limits", "Run check", "Save pilot plan", "Start audit"} <= labels(at)
    button(at, "Sync limits").click().run()
    assert config.get("paper.daily_loss_limit_by_market")["IN"] == 30_000
    button(at, "New version").click().run()
    button(at, "Run check").click().run()
    assert any("NOT YET" in w.value for w in at.warning)
    button(at, "Start audit").click().run()
    assert not at.exception


def test_alerts_walkthrough():
    p = plans.new_plan("Seven-field plan", "IN", "NIFTY FUT", name="Plan A")
    p.entry, p.stop, p.qty = 24850, 24700, 65
    plans.save(p)
    at = app("alerts")
    button(at, "New alert").click().run()
    button(at, "Propose alerts").click().run()
    assert any(c.label == "Attach paper order" for c in at.checkbox)
    button(at, "Accept").click().run()
    assert any("active" in s.value for s in at.success)
    button(at, "Send test").click().run()
    assert any("SIMULATED" in i.value for i in at.info)
