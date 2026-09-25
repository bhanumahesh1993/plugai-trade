"""Kill switch, daily loss limit and the intraday guardrails (Chapters 13 and 21)."""

import pytest

from plugai_trade import config, paper, rulecard
from plugai_trade.store import default as store


def bar(t, o, h, lo, c, day="2026-05-26"):
    return {"date": day, "time": f"{day}T{t}", "open": o, "high": h, "low": lo, "close": c,
            "volume": 1e6}


def open_long(d, t="09:35"):
    d.on_bar("NIFTY FUT", bar(t, 24800, 24840, 24790, 24830))
    d.place_paper_order("NIFTY FUT", "buy", 65, stop=24500, plan_id=1)


def test_kill_switch_semantics():
    d = paper.PaperDesk("IN", 1_500_000)
    open_long(d)
    d.on_bar("NIFTY FUT", bar("09:40", 24830, 24850, 24820, 24840))
    working = d.place_paper_order("NIFTY FUT", "buy", 65, kind="limit", price=24000, plan_id=1)
    pend = paper.draft_pending({"symbol": "NIFTY FUT", "market": "IN", "side": "buy", "qty": 65},
                               source="MCP paper_order")
    res = d.kill_switch()
    assert working.status == "CANCELLED" and res["cancelled"] == 2
    assert store().get("paper_orders", pend)["tag"] == "cancelled"
    assert d.positions and d.positions[0].closing           # closes at the NEXT bar, not now
    blocked = d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1)
    assert blocked.status == "BLOCKED" and "kill switch" in blocked.reason
    d.on_bar("NIFTY FUT", bar("09:45", 24700, 24720, 24680, 24690))
    assert not d.positions and d.trades[-1]["exit"] == 24698   # next open − 2
    assert d.trades[-1]["exit_reason"] == "kill switch"
    assert store().count("audit_log", tag="kill_switch") == 1
    assert d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1).status == "BLOCKED"
    d.on_bar("NIFTY FUT", bar("09:35", 24700, 24720, 24680, 24690, day="2026-05-27"))
    assert d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1).status == "WORKING"  # new session


def test_kill_switch_with_nothing_open_still_blocks():
    d = paper.PaperDesk("US", 40_000)
    res = d.kill_switch()
    assert res == {"cancelled": 0, "closing": 0}
    assert d.place_paper_order("SPY", "buy", 1).status == "BLOCKED"


def test_daily_loss_limit_blocks_without_override():
    config.set_value("paper.daily_loss_limit_by_market", {"IN": 30_000})
    d = paper.PaperDesk("IN", 1_500_000)
    open_long(d)
    d.on_bar("NIFTY FUT", bar("09:40", 24830, 24840, 24300, 24350))  # stop 24,500 hit
    assert d.trades and d.trades[-1]["net"] < -20_000
    open_long(d, "09:45")
    d.on_bar("NIFTY FUT", bar("09:50", 24830, 24840, 24400, 24450))
    assert d.limit_hit
    o = d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1)
    assert o.status == "BLOCKED" and o.reason == "daily limit hit"
    assert not hasattr(d, "override")
    rows = store().all("journal", tag="BLOCKED")
    assert rows and rows[0]["reason"] == "daily limit hit"


def test_guardrails_window_max_trades_cooldown_lockout():
    config.set_value("paper.trading_window", {"IN": "09:30-15:00"})
    config.set_value("paper.max_trades_per_day", 2)
    config.set_value("paper.cooldown_minutes", 30)
    config.set_value("paper.event_lockout_minutes", 15)
    config.set_value("paper.events", [{"when": "2026-05-26T12:00", "name": "RBI policy"}])
    d = paper.PaperDesk("IN", 1_500_000)
    d.on_bar("NIFTY FUT", bar("09:20", 24800, 24840, 24790, 24830))
    o = d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1)
    assert o.status == "BLOCKED" and o.reason.startswith("outside window")
    d.on_bar("NIFTY FUT", bar("09:35", 24800, 24840, 24790, 24830))
    first = d.place_paper_order("NIFTY FUT", "buy", 65, stop=24700, plan_id=1)
    assert first.status == "WORKING"
    d.on_bar("NIFTY FUT", bar("09:40", 24830, 24840, 24650, 24660))   # fill then stopped out
    assert d.trades[-1]["net"] < 0
    cool = d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1)
    assert cool.status == "BLOCKED" and cool.reason.startswith("cooldown")
    assert d.guardrail_strip()["cooldown_min"] == 30
    d.on_bar("NIFTY FUT", bar("11:50", 24700, 24710, 24690, 24700))
    lock = d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1)
    assert lock.status == "BLOCKED" and "RBI policy" in lock.reason
    d.on_bar("NIFTY FUT", bar("13:00", 24700, 24710, 24690, 24700))
    assert d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1).status == "WORKING"
    maxed = d.place_paper_order("NIFTY FUT", "buy", 65, plan_id=1)
    assert maxed.status == "BLOCKED" and maxed.reason.startswith("max reached")
    assert d.guardrail_strip()["trades_left"] == 0
    assert store().count("journal", tag="BLOCKED") == 4


def test_strict_mode_raises():
    d = paper.PaperDesk("US", 40_000)
    d.kill_switch()
    with pytest.raises(paper.PaperOrderBlocked):
        d.place_paper_order("SPY", "buy", 1, strict=True)


def test_rule_card_sync_limits_reach_desk():
    card = rulecard.template_card()
    card.max_trades_day = 1
    rulecard.sync_limits(card)
    assert config.get("paper.daily_loss_limit_by_market") == {"IN": 30_000, "US": 800}
    d = paper.PaperDesk("US", 40_000)
    lim = d.limits()
    assert lim["daily_loss_limit"] == 800 and lim["one_r"] == 400 and lim["max_trades_per_day"] == 1
    assert config.get("sizing.cap_pct") == 0.25
