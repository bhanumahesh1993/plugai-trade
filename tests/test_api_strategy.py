"""Strategy screens API: Strategy Builder, Backtest Report, Trend Lab, Pairs Lab (offline)."""

from fastapi.testclient import TestClient

from plugai_trade.api import app
from plugai_trade.store import default as store

c = TestClient(app)
IDEA = ("Buy when the price is above the 50-day average; get out when it falls below the "
        "20-day average")


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def _draft(market="IN"):
    return _ok(c.post("/api/strategy/draft", json={"idea": IDEA, "market": market}))


# ------------------------------------------------------------------ Strategy Builder
def test_options_and_draft_marks_assumed_fields():
    o = _ok(c.get("/api/strategy/options?market=US"))
    assert o["instruments"][0] == "SPY" and o["profiles"] == ["US-equity"]
    d = _draft()
    assert "fill" in d["spec"]["assumed"] and "cost.slippage" in d["spec"]["assumed"]
    assert [x["title"] for x in d["cards"]] == ["ENTRY", "EXIT", "FILL", "SIZE · COST"]
    assert c.post("/api/strategy/draft", json={"idea": "  "}).status_code == 400


def test_check_validates_and_counts_trials():
    spec = _draft()["spec"]
    ck = _ok(c.post("/api/strategy/check", json={"spec": spec, "market": "IN"}))
    assert ck["trials"] == 0 and "next session's open" in ck["read_back"]
    bad = {**spec, "exit": [], "time_stop": None}
    r = c.post("/api/strategy/check", json={"spec": bad, "market": "IN"})
    assert r.status_code == 400 and "EXIT is empty" in r.json()["detail"]


def test_chart_check_does_not_add_a_trial_and_backtest_does():
    spec = _draft()["spec"]
    body = {"spec": spec, "market": "IN", "symbol": "NIFTY", "years": 5}
    cc = _ok(c.post("/api/strategy/chart-check", json=body))
    assert cc["buys"] and "round trips in 10 sessions" in cc["chip"] and "50-day average" in cc["lines"]
    assert _ok(c.post("/api/strategy/check", json={"spec": spec, "market": "IN"}))["trials"] == 0
    bt = _ok(c.post("/api/strategy/backtest", json=body))
    assert bt["trials"] == 1 and bt["id"] and len(bt["frame"]["dates"]) == len(bt["frame"]["equity"])
    assert any(f.startswith("After costs:") for f in bt["facts"])


def test_agent_proposals_arrive_as_proposed_drafts():
    spec = _draft()["spec"]
    store().add("proposals", {"subject": "NIFTY", "spec": spec, "status": "PROPOSED"}, tag="PROPOSED")
    rows = _ok(c.get("/api/strategy/proposals"))
    assert rows[0]["spec"]["origin"] == "agent" and rows[0]["cards"]


# ------------------------------------------------------------------ Backtest Report
def test_backtest_report_costs_walk_forward_accept():
    assert c.get("/api/backtest/report").json().get("empty") is True
    assert _ok(c.get("/api/backtest/current"))["id"] is None
    sid = _ok(c.post("/api/backtest/sample", json={"market": "IN"}))["id"]
    rep = _ok(c.get("/api/backtest/report"))
    assert rep["id"] == sid and rep["kind"] == "rule"
    assert rep["card"]["grade"] in ("Robust", "Fragile", "Likely overfit")
    assert rep["walk_forward"]["windows"] and rep["trades"]
    assert any(w.startswith("Survivorship") for w in rep["card"]["warnings"])
    base = _ok(c.post("/api/backtest/costs", json={"id": sid}))
    intra = _ok(c.post("/api/backtest/costs", json={"id": sid, "profile": "IN-equity-intraday"}))
    assert intra["profile"] == "IN-equity-intraday" and intra["after"] != base["after"]
    assert "before_costs" in base["frame"] and base["items"]
    assert c.post("/api/backtest/costs", json={"id": sid, "profile": "US-equity"}).status_code == 400
    acc = _ok(c.post("/api/backtest/accept", json={"id": sid, "ai_note": "note"}))
    assert store().get("journal", acc["journal_id"])["kind"] == "backtest_report"
    saved = _ok(c.get("/api/backtest/saved"))
    assert {r["tag"] for r in saved} >= {"sample", "accepted"}


def test_saved_report_is_rebuilt_without_a_new_trial():
    from plugai_trade.api.routes import backtest as bt_routes
    sid = _ok(c.post("/api/backtest/sample", json={"market": "US"}))["id"]
    trials = _ok(c.get(f"/api/backtest/report?id={sid}"))["trials"]
    bt_routes._BY_ID.clear()
    again = _ok(c.get(f"/api/backtest/report?id={sid}"))
    assert again["trials"] == trials and again["meta"]["market"] == "US"
    us = _ok(c.post("/api/backtest/costs", json={"id": sid, "slippage_pct": 0.1}))
    assert us["slippage_pct"] == 0.1
    assert c.get("/api/backtest/report?id=9999").status_code == 400


def test_training_cutoff_warning_for_agent_rules():
    spec = {**_draft()["spec"], "origin": "agent"}
    bt = _ok(c.post("/api/strategy/backtest", json={"spec": spec, "market": "IN", "symbol": "NIFTY"}))
    rep = _ok(c.get(f"/api/backtest/report?id={bt['id']}"))
    assert rep["meta"]["origin"] == "agent"
    assert any("Training-cutoff" in w for w in rep["card"]["warnings"])


def test_legacy_idea_route_still_works():
    r = _ok(c.post("/api/backtest/run", json={"idea": IDEA}))
    assert r["id"] and r["card"]["grade"]


# ------------------------------------------------------------------ Trend Lab
def test_trend_lab_ma_crossover_run_tax_sweep_send():
    t = {"preset": "MA crossover", "market": "IN", "symbol": "NIFTY"}
    pv = _ok(c.post("/api/strategy/trend/preview", json=t))
    assert pv["sizing"]["units"] >= 0 and "Computed in code" in pv["sizing"]["formula"]
    run = _ok(c.post("/api/strategy/trend/run", json=t))
    assert run["trials"] == 1 and run["digest"] == pv["digest"]
    tax = _ok(c.post("/api/strategy/after-tax", json={"run_id": run["run_id"]}))
    assert len(tax["line"]) == len(run["frame"]["dates"]) and not tax["short_rate_assumed"]
    hm = _ok(c.post("/api/strategy/trend/heatmap", json={"settings": t}))
    assert hm["trials"] == 29 and hm["cells"] == 29 and hm["base"] == [50, 200]
    assert any(f.startswith("Trials:") for f in hm["facts"])
    sent = _ok(c.post("/api/strategy/send-backtest", json={"run_id": run["run_id"]}))
    assert _ok(c.get("/api/backtest/current"))["id"] == sent["id"]
    paper = _ok(c.post("/api/strategy/send-paper", json={"run_id": run["run_id"]}))
    for rid in paper["ids"]:
        assert store().get("paper_orders", rid)["status"] == "PENDING"
    assert c.post("/api/strategy/after-tax", json={"run_id": "nope"}).status_code == 400
    bad = _ok(c.get("/api/strategy/trend/heatmap-axes"))
    assert bad["Rotation"]["cols"]["label"] == "Top N"
    assert c.post("/api/strategy/trend/preview", json={**t, "fast": 200, "slow": 50}).status_code == 400


def test_trend_lab_momentum_and_rotation():
    ts = {"preset": "Time-series momentum", "market": "US", "symbol": "SPY", "check": "weekly"}
    run = _ok(c.post("/api/strategy/trend/run", json=ts))
    us_tax = _ok(c.post("/api/strategy/after-tax", json={"run_id": run["run_id"], "short_rate": 0.32}))
    assert us_tax["short_rate"] == 0.32
    rot = {"preset": "Rotation", "market": "US", "universe": ["XLK", "XLF", "XLV", "XLE"], "top_n": 2}
    pv = _ok(c.post("/api/strategy/trend/preview", json=rot))
    assert "sizing" not in pv and "ranks 4 instruments" in pv["read_back"]
    r = _ok(c.post("/api/strategy/trend/run", json=rot))
    assert r["meta"]["symbols"] == ["XLK", "XLF", "XLV", "XLE"]
    hm = _ok(c.post("/api/strategy/trend/heatmap", json={"settings": rot, "rows": "3, 6", "cols": "1, 2"}))
    assert hm["cells"] == 4
    assert c.post("/api/strategy/trend/preview", json={**rot, "top_n": 4}).status_code == 400


# ------------------------------------------------------------------ Pairs Lab
def test_pairs_lab_book_numbers_and_handoffs():
    unis = _ok(c.get("/api/strategy/pairs/universes"))
    assert unis[0]["symbols"] == ["SYN-A", "SYN-B", "SYN-C", "SYN-D"]
    cands = _ok(c.post("/api/strategy/pairs/find", json={"symbols": unis[0]["symbols"]}))
    top = cands[0]
    assert (top["a"], top["b"], top["passes"]) == ("SYN-A", "SYN-B", True)
    cd = next(x for x in cands if (x["a"], x["b"]) == ("SYN-C", "SYN-D"))
    assert cd["correlation"] > 0.8 and not cd["passes"]
    fit = _ok(c.post("/api/strategy/pairs/fit", json={"a": "SYN-A", "b": "SYN-B"}))
    assert round(fit["beta"], 3) == 1.168 and round(fit["half_life"], 1) == 6.1
    assert fit["default_time_stop"] == 18 and fit["suspended"] == 453
    assert "Hedge ratio: 1.168" in fit["facts"]
    us = _ok(c.post("/api/strategy/pairs/size", json={"market": "US", "beta": fit["beta"],
                                                      "price_a": 81.66, "price_b": 44.26}))
    assert us["shares_a"] == 122 and us["borrow_fee"] > 0
    ind = _ok(c.post("/api/strategy/pairs/size", json={"market": "IN", "beta": fit["beta"],
                                                       "price_a": 1630, "price_b": 885}))
    assert ind["lots_b"] == 1 and ind["near"]["lots_a"] == 8
    link = _ok(c.post("/api/strategy/pairs/check-link", json={"a": "SYN-A", "b": "SYN-B"}))
    assert link["rating"] is None
    assert c.post("/api/strategy/pairs/accept-link", json={"a": "SYN-A", "b": "SYN-B", "text": "x",
                                                          "rating": "Maybe"}).status_code == 400
    kept = _ok(c.post("/api/strategy/pairs/accept-link", json={"a": "SYN-A", "b": "SYN-B",
                                                              "text": "Rating: Strong", "rating": "Strong"}))
    assert store().get("notes", kept["id"])["rating"] == "Strong"
    sent = _ok(c.post("/api/strategy/pairs/send-backtest", json={"a": "SYN-A", "b": "SYN-B"}))
    rep = _ok(c.get(f"/api/backtest/report?id={sent['id']}"))
    assert rep["kind"] == "pairs" and rep["suspended_at"] == 453 and sent["trials"] == 1
    # The sample pair breaks at session 453, so paper is refused; a wide stop keeps it live.
    body = {"a": "SYN-A", "b": "SYN-B", "qty_a": 122, "qty_b": 225}
    assert c.post("/api/strategy/pairs/send-paper", json=body).status_code == 400
    live = _ok(c.post("/api/strategy/pairs/send-paper", json={**body, "stop": 10.0, "events": "results"}))
    legs = [store().get("paper_orders", i) for i in live["ids"]]
    assert len(legs) == 2 and legs[0]["link_id"] == legs[1]["link_id"] and legs[0]["status"] == "PENDING"
