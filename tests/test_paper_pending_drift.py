"""Pending paper orders (Accept / Reject), the drift report, and the paper-only guarantee."""

import re
import sys
from pathlib import Path

import pytest

from plugai_trade import paper, paper_guard
from plugai_trade.paper import drift
from plugai_trade.store import default as store

MINE = ["paper", "sizing.py", "alerts.py", "plans.py", "rulecard.py", "app/pages/paper_desk.py",
        "app/pages/position_sizer.py", "app/pages/trade_plan.py", "app/pages/rule_card.py",
        "app/pages/alerts.py"]


def test_pending_waits_for_accept_then_passes_guardrails():
    rid = paper.draft_pending({"symbol": "SPY", "market": "US", "side": "buy", "qty": 10},
                              source="MCP paper_order")
    assert [r["id"] for r in paper.pending("US")] == [rid]
    d = paper.PaperDesk("US", 40_000)
    assert not d.orders                                      # nothing happens by itself
    o = paper.accept(rid, d)
    assert o.status == "WORKING" and o.source == "MCP paper_order"
    assert store().get("paper_orders", rid)["tag"] == "accepted"
    with pytest.raises(KeyError):
        paper.accept(rid, d)                                  # not pending any more


def test_reject_and_blocked_accept():
    a = paper.draft_pending({"symbol": "SPY", "market": "US", "qty": 5}, source="Alert #1")
    paper.reject(a, "not in my plan")
    assert store().get("paper_orders", a)["tag"] == "rejected" and not paper.pending()
    b = paper.draft_pending({"symbol": "SPY", "market": "US", "qty": 5}, source="Alert #2")
    d = paper.PaperDesk("US", 40_000)
    d.killed = True
    assert paper.accept(b, d).status == "BLOCKED"
    assert store().get("paper_orders", b)["tag"] == "blocked"
    with pytest.raises(ValueError):
        paper.draft_pending({"symbol": "SPY"}, source="x")


def test_ticket_handoff():
    tid = paper.hand_ticket({"symbol": "NIFTY FUT", "market": "IN", "side": "buy", "qty": 65,
                             "kind": "stop", "price": 24850, "stop": 24700, "plan_id": 3},
                            source="Trade Plan #3")
    t = paper.load_ticket()
    assert t["id"] == tid and t["price"] == 24850
    paper.ticket_used(tid)
    assert paper.load_ticket() is None


def kavita():
    """Book ch13: gap 6.90R = costs 1.48R + rule breaks 5.42R (synthetic rows shaped to match)."""
    shadow = [{"signal": str(i), "r": 0.5, "cost_r": 0.02} for i in range(1, 31)]
    shadow[8]["r"], shadow[19]["r"] = 1.73, 1.73               # skipped signals: 3.46R together
    shadow[14]["r"] = -0.94                                    # stop moved: lost 1.70 instead
    paper_rows = []
    cost_each = 1.48 / 26                                     # 26 clean matched trades
    for s in shadow:
        i = int(s["signal"])
        if i in (9, 20):
            continue
        if i == 15:
            paper_rows.append({"signal": "15", "r": -1.70, "cost_r": 0.02, "stop_moved": True})
        elif i == 5:
            paper_rows.append({"signal": "5", "r": s["r"] - 0.35, "cost_r": 0.02, "late": True})
        else:
            paper_rows.append({"signal": s["signal"], "r": s["r"] - cost_each})
    paper_rows.append({"signal": None, "r": -0.85, "id": 99})  # off-plan trade
    return paper_rows, shadow


def test_drift_split_costs_vs_rule_breaks():
    p, s = kavita()
    rep = paper.drift_report(p, s)
    assert round(rep.gap_r, 2) == 6.90
    assert round(rep.cost_gap_r, 2) == 1.48 and round(rep.break_gap_r, 2) == 5.42
    assert round(rep.cost_gap_r + rep.break_gap_r, 6) == round(rep.gap_r, 6)
    assert (rep.count("skip"), rep.count("late entry"), rep.count("stop moved away"),
            rep.count("off-plan")) == (2, 1, 1, 1)
    assert rep.signals == 30 and rep.taken == 28
    assert round(rep.adherence, 3) == round(26 / 31, 3)      # 26 / 31 (83.9%) in the book
    assert any("Rule-break gap: 5.42R" in f for f in rep.facts())


def test_skip_that_dodged_a_loser_is_still_a_break():
    rep = paper.drift_report([], [{"signal": "a", "r": -0.9}])
    assert rep.count("skip") == 1 and rep.break_gap_r == pytest.approx(-0.9)


def test_paper_rows_match_by_date_and_flag_late():
    rows = [{"id": 1, "kind": "paper_trade", "entry_time": "2026-05-26T09:20", "r": 1.0},
            {"id": 2, "kind": "paper_trade", "entry_time": "2026-05-28T09:20", "r": -1.0},
            {"id": 3, "kind": "paper_trade", "entry_time": "2026-06-10T09:20", "r": -0.5,
             "rule_breaks": ["off-plan"]}]
    out = paper.paper_rows_for_drift(rows, {"2026-05-26", "2026-05-27"})
    assert out[0]["signal"] == "2026-05-26" and not out[0]["late"]
    assert out[1]["signal"] == "2026-05-27" and out[1]["late"]
    assert out[2]["signal"] is None


def test_shadow_backtest_unavailable_gives_notice(monkeypatch):
    monkeypatch.setitem(sys.modules, "plugai_trade.backtest", None)
    with pytest.raises(drift.ShadowUnavailable):
        paper.run_shadow("Buy when close > 20-day average", None)


def test_shadow_trades_adapter():
    class Res:
        trades = [{"entry_date": "2026-05-26", "pnl": 800.0, "costs": 40.0}]
    assert paper.shadow_trades(Res(), one_r=400) == [{"signal": "2026-05-26", "r": 2.0, "cost_r": 0.1}]


def test_no_real_order_code_in_my_modules():
    root = Path(paper_guard.__file__).parent
    hits = [h for h in paper_guard.scan_path(root) if any(m in h[0] for m in MINE)]
    assert hits == []
    for rel in MINE:
        p = root / rel
        files = p.rglob("*.py") if p.is_dir() else [p]
        for f in files:
            text = f.read_text()
            assert not re.search(r"https?://[^\"']*(kite|upstox|alpaca|dhan|fyers|angel)[^\"']*/order",
                                 text, re.IGNORECASE), f
    assert "httpx" not in "".join(f.read_text() for f in (root / "paper").rglob("*.py"))


def test_shadow_backtest_runs_when_backtest_module_present():
    pytest.importorskip("plugai_trade.backtest")
    from plugai_trade import data
    bars = data.get("NIFTY", "IN", "2025-01-01", "2025-12-31", source="synthetic")
    res = paper.run_shadow("Buy at the next open on the first close above the 20-day average; "
                           "sell at the next open when the close is below the 20-day average",
                           bars, costs="IN-futures")
    rows = paper.shadow_trades(res, one_r=15_000)
    assert rows and all(set(r) == {"signal", "r", "cost_r"} for r in rows)
    assert paper.drift_report([], rows).count("skip") == len(rows)


def test_multi_leg_pending_is_accepted_for_tracking_only():
    rid = store().add("paper_orders", {"source": "Options Strategy Builder", "kind": "options",
                                       "strategy": {"legs": 4}}, tag="pending")
    d = paper.PaperDesk("IN", 1_500_000)
    assert paper.accept(rid, d) is None and not d.orders
    assert store().get("paper_orders", rid)["tag"] == "accepted"
