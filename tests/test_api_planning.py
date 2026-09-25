"""API: Plan & Risk (Trade Plan, Position Sizer, Rule Card), Alerts and the Paper Desk."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from plugai_trade.api import app
from plugai_trade.api.routes import paper as paper_routes

c = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_desks():
    paper_routes._desks.clear()
    yield
    paper_routes._desks.clear()


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ Trade Plan
def _new_plan(**kw):
    body = {"template": "Seven-field plan", "market": "IN", "symbol": "nifty fut", **kw}
    return ok(c.post("/api/planning/plans", json=body))


def test_trade_plan_flow():
    t = ok(c.get("/api/planning/templates"))["templates"]
    assert [f["field"] for f in t["Seven-field plan"]][:3] == ["Setup", "Entry", "Stop"]
    assert c.post("/api/planning/plans", json={"template": "Nope"}).status_code == 400

    p = _new_plan()
    assert p["symbol"] == "NIFTY FUT" and p["version"] == 1 and p["owners"]["Size"] == "CODE"
    assert "Setup" in p["check"]["missing"]
    assert [x["id"] for x in ok(c.get("/api/planning/plans?market=IN"))] == [p["id"]]
    assert ok(c.get("/api/planning/plans?market=US")) == []
    assert ok(c.get(f"/api/planning/plans/{p['id']}"))["id"] == p["id"]
    assert c.get("/api/planning/plans/999").status_code == 404

    draft = {"entry": 24850, "stop": 24900, "side": "long",
             "fields": {"Setup": "Pullback maybe around support", "Entry": "24850"}}
    chk = ok(c.post(f"/api/planning/plans/{p['id']}/check", json=draft))["check"]
    assert chk["contradictions"] and any("maybe" in v for v in chk["vague"])
    assert ok(c.get(f"/api/planning/plans/{p['id']}"))["version"] == 1   # check saves nothing

    draft["stop"] = 24700
    s = ok(c.post(f"/api/planning/plans/{p['id']}/save", json=draft))
    assert s["version"] == 2 and len(s["versions"]) == 1 and s["stop"] == 24700

    crit = ok(c.post(f"/api/planning/plans/{p['id']}/critique", json=draft))
    assert crit["where"] == "Fallback" and "Missing" in crit["text"]
    assert crit["sources"][0].startswith("Setup:")
    sec = ok(c.post(f"/api/planning/plans/{p['id']}/second-opinion", json={**draft, "text": crit["text"]}))
    assert sec["text"]

    j = ok(c.post(f"/api/planning/plans/{p['id']}/journal", json=draft))
    assert j["row"] > 0 and j["plan"]["version"] == 3

    # Send to Paper Desk needs a size first.
    r = c.post(f"/api/planning/plans/{p['id']}/paper", json=draft)
    assert r.status_code == 400 and "size" in r.json()["detail"].lower()


# ------------------------------------------------------------------ Position Sizer
def test_sizer_book_numbers_and_use_in_plan():
    ctx = ok(c.get("/api/planning/sizer/context?market=IN&symbol=NIFTY FUT"))
    assert ctx["lot"] == 65 and ctx["defaults"]["account"] == 1_500_000 and ctx["atr"] > 0

    body = {"method": "fixed", "market": "IN", "symbol": "NIFTY FUT", "account": 1_500_000,
            "risk_pct": 1, "cap_pct": 25, "entry": 24850, "stop": 24700}
    r = ok(c.post("/api/planning/sizer/size", json=body))
    assert r["size"] == 1 and r["cost_allowance"] == 1200
    tiles = {t["label"]: t["value"] for t in r["tiles"]}
    assert tiles["Risk budget"] == "₹15,000" and tiles["Risk per lot"] == "₹10,950.00"
    assert tiles["Raw size"] == "1.37 lots" and tiles["Actual risk"] == "0.73%"
    assert r["notional_warning"]                     # one NIFTY lot > the account
    labels = {f.split(":")[0] for f in r["facts"]}
    assert all(t["label"] in labels for t in r["tiles"])   # citations light the tiles

    assert c.post("/api/planning/sizer/size", json={**body, "stop": 24850}).status_code == 400

    atr = ok(c.post("/api/planning/sizer/size", json={
        "method": "atr", "market": "IN", "symbol": "XYZ", "account": 400_000, "risk_pct": 1,
        "cap_pct": 0, "entry": 616.5, "atr": 12.79, "multiple": 1.5, "stop_typed": 597.30,
        "cost_per_lot": 1.2}))
    assert atr["suggested_stop"] == 597.32 and atr["stop"] == 597.30

    vol = ok(c.post("/api/planning/sizer/size", json={
        "method": "vol", "market": "US", "symbol": "SPY", "account": 40_000, "entry": 560,
        "target_vol": 12, "daily_vol": 1}))
    assert vol["method"] == "Vol target" and vol["tiles"][0]["label"] == "Daily risk target (÷16)"

    p = _new_plan()
    assert c.post("/api/planning/sizer/use-in-plan", json=body).status_code == 400
    u = ok(c.post("/api/planning/sizer/use-in-plan", json={**body, "plan_id": p["id"]}))
    assert u["version"] == 2 and u["size_text"].startswith("1 lot")
    plan = ok(c.get(f"/api/planning/plans/{p['id']}"))
    assert plan["qty"] == 65 and plan["fields"]["Size"].startswith("1 lot")

    # Now the plan can go to the Paper Desk; the desk shows it as a filled-in ticket.
    ok(c.post(f"/api/planning/plans/{p['id']}/save", json={"entry": 24850, "stop": 24700}))
    ok(c.post(f"/api/planning/plans/{p['id']}/paper", json={}))     # left-out fields keep their values
    t = ok(c.get("/api/paper/state?market=IN"))["ticket"]
    assert t["symbol"] == "NIFTY FUT" and t["qty"] == 65 and t["kind"] == "stop"
    assert t["price"] == 24850 and t["stop"] == 24700 and t["plan_id"] == p["id"]


def test_sizer_hedge_and_streaks():
    h = ok(c.post("/api/planning/sizer/hedge", json={"exposure": 20000, "side": "receivable",
                                                      "futures_price": 88.4, "ratio": 1}))
    assert h["lots"] == 20 and h["futures_side"] == "sell" and len(h["scenarios"]) == 8
    us = ok(c.post("/api/planning/sizer/hedge-us", json={"risk": 400, "distance": 0.0055,
                                                          "contract_size": 12500}))
    assert us["contracts"] == 5
    table = ok(c.post("/api/planning/sizer/hedge-us", json={"risk": 400, "distance": 0.0055}))
    assert table["table_contract_size"] == 12500 and table["contracts"] == 5  # dated table fills the size
    assert c.post("/api/planning/sizer/hedge-us", json={"risk": 400, "distance": 0,
                                                        "contract_size": 1}).status_code == 400
    s = ok(c.post("/api/planning/sizer/streaks", json={}))
    assert round(s["rows"][0]["typical_fall"], 3) == 0.113 and round(s["rows"][0]["bad_luck_fall"], 3) == 0.218
    assert s["rows"][1]["risk_pct"] == 0.005 and len(s["fan"]["p50"]) == 21
    j = ok(c.post("/api/planning/sizer/streaks", json={"use_journal": True, "sequences": 100}))
    assert j["note"]


# ------------------------------------------------------------------ Rule Card
def test_rule_card_flow():
    out = ok(c.get("/api/planning/rulecard"))
    card = out["card"]
    assert out["limits"]["IN"]["daily"] == 30_000 and out["limits"]["US"]["weekly"] == 1_600
    card["daily_limit_r"] = 3
    assert ok(c.post("/api/planning/rulecard/preview", json={"card": card}))["limits"]["IN"]["daily"] == 45_000

    s = ok(c.post("/api/planning/rulecard/suggest", json={"card": card, "lines": ["No revenge trades", " "],
                                                          "group": "Behaviour"}))
    assert s["card"]["rules"][-1] == {"group": "Behaviour", "text": "No revenge trades", "status": "suggested"}

    v = ok(c.post("/api/planning/rulecard/new-version", json={"card": s["card"], "note": "3R daily"}))
    assert v["card"]["version"] == 1 and v["card"]["note"] == "3R daily"
    v2 = ok(c.post("/api/planning/rulecard/new-version", json={"card": v["card"], "note": "again"}))
    assert v2["card"]["version"] == 2
    assert [h["version"] for h in ok(c.get("/api/planning/rulecard/history"))] == [2, 1]
    assert ok(c.get("/api/planning/rulecard"))["card"]["daily_limit_r"] == 3

    sync = ok(c.post("/api/planning/rulecard/sync", json={"card": v2["card"]}))
    assert sync["values"]["paper.daily_loss_limit_by_market"]["IN"] == 45_000
    # The Paper Desk now shows the synced daily loss limit.
    assert ok(c.get("/api/paper/state?market=IN"))["guardrails"]["daily_loss_limit"] == 45_000

    assert ok(c.get("/api/planning/rulecard/adherence"))["score"] is None
    g = ok(c.post("/api/planning/rulecard/gonogo", json={"account": "Paper"}))
    assert g["verdict"] == "NOT YET" and g["measures"][0]["name"] == "Paper length"
    assert c.post("/api/planning/rulecard/gonogo", json={"account": "Live"}).status_code == 400

    pid = ok(c.post("/api/planning/rulecard/pilot", json={
        "market": "IN", "budget": 45000, "trades_per_day": 1, "review_date": "2026-11-06",
        "stop_conditions": ["Budget used up", ""], "size": "1 lot"}))["id"]
    assert pid > 0
    assert c.post("/api/planning/rulecard/pilot", json={
        "budget": 0, "trades_per_day": 1, "review_date": "x", "stop_conditions": []}).status_code == 400

    a = ok(c.post("/api/planning/rulecard/audit/start"))
    assert [i["item"] for i in a["items"]][:2] == ["Rules", "Costs"]
    a["items"][0]["done"] = True
    assert ok(c.post("/api/planning/rulecard/audit/save", json=a))["id"] > 0


# ------------------------------------------------------------------ Alerts
def test_alerts_flow():
    s = ok(c.get("/api/planning/alerts?market=IN"))
    assert s["alerts"] == [] and "Telegram" in s["options"]["channels"]
    assert c.post("/api/planning/alerts/propose", json={"source": "From plan"}).status_code == 400

    p = _new_plan()
    body = {"entry": 24850, "stop": 24700, "fields": {"Exit logic": "Close below the 20-day average"}}
    ok(c.post(f"/api/planning/plans/{p['id']}/save", json=body))
    props = ok(c.post("/api/planning/alerts/propose", json={"source": "From plan", "market": "IN",
                                                             "plan_ids": [p["id"]]}))
    names = [a["name"].split(" · ")[0] for a in props]
    assert names[:3] == ["Entry trigger", "Stop", "Exit condition"] and "Daily loss −1R" in names
    assert ok(c.get("/api/planning/alerts?market=IN"))["alerts"] == []   # nothing until Accept

    blank = ok(c.post("/api/planning/alerts/propose", json={"source": "Blank", "symbol": "spy",
                                                            "kind": "price", "level": 560}))
    assert blank[0]["symbol"] == "SPY" and blank[0]["level"] == 560
    assert c.post("/api/planning/alerts/propose", json={"source": "Blank", "symbol": ""}).status_code == 400
    assert c.post("/api/planning/alerts/propose", json={"source": "From Crypto Monitor"}).status_code == 400

    props[0]["bar_size"] = "1-min close"
    acc = ok(c.post("/api/planning/alerts/accept", json={"alerts": props}))
    assert acc["accepted"] == len(props)
    s = ok(c.get("/api/planning/alerts?market=IN"))
    assert all(a["status"] == "active" for a in s["alerts"]) and s["alerts"][-1]["bar_size"] == "1-min close"

    aid = s["alerts"][0]["id"]
    t = ok(c.post(f"/api/planning/alerts/{aid}/test"))
    assert t["message"].startswith("SIMULATED") and t["delivered"] == ["Desktop"]
    assert ok(c.post(f"/api/planning/alerts/{aid}/pause"))["status"] == "paused"
    assert ok(c.post(f"/api/planning/alerts/{aid}/resume"))["status"] == "active"
    assert ok(c.get("/api/planning/alerts"))["log"][0]["event"] == "test"
    assert c.post("/api/planning/alerts/9999/test").status_code == 404

    # A proposal written by another screen: Accept or Discard.
    from plugai_trade import alerts
    a = alerts.save(alerts.Alert("Roll", "NIFTY FUT", kind="date", when="2026-10-20"))
    b = alerts.save(alerts.Alert("Other", "NIFTY FUT"))
    assert {x["id"] for x in ok(c.get("/api/planning/alerts"))["proposed"]} == {a.id, b.id}
    assert ok(c.post(f"/api/planning/alerts/{a.id}/accept"))["status"] == "active"
    ok(c.post(f"/api/planning/alerts/{b.id}/discard"))
    assert ok(c.get("/api/planning/alerts"))["proposed"] == []

    ch = ok(c.post("/api/planning/alerts/channels", json={"quiet_hours": "23:00-06:00",
                                                          "email_to": "me@example.com"}))
    assert ch["saved"]
    assert ok(c.get("/api/planning/alerts"))["channels"]["quiet_hours"] == "23:00-06:00"
    assert c.post("/api/planning/alerts/channels", json={"quiet_hours": "late"}).status_code == 400


# ------------------------------------------------------------------ Paper Desk
def _feed_until(market, pred, limit=80):
    s = ok(c.get(f"/api/paper/state?market={market}"))
    for _ in range(limit):
        if pred(s):
            return s
        s = ok(c.post(f"/api/paper/step?market={market}"))
    return s


def test_paper_desk_session_replay_and_ticket():
    s = ok(c.get("/api/paper/state?market=IN"))
    assert s["session"] == "Replay" and s["replay"]["cursor"] == 6 and s["tape"]
    assert "NIFTY FUT" in s["symbols"] and s["instruments"]["NIFTY FUT"]["lot"] == 65
    assert c.get("/api/paper/state?market=XX").status_code == 400

    r = c.post("/api/paper/session", json={"market": "IN", "session": "LIVE"})
    assert r.status_code == 400 and "Replay" in r.json()["detail"]
    assert ok(c.post("/api/paper/session", json={"market": "IN", "session": "Replay"}))["mode"] == "REPLAY"

    s = ok(c.post("/api/paper/replay", json={"market": "IN", "symbol": "NIFTY FUT", "interval": "1m", "speed": 5}))
    assert s["replay"]["cursor"] == 0 and s["replay"]["interval"] == "1m" and s["tape"] == []
    assert c.post("/api/paper/replay", json={"market": "IN", "symbol": "NIFTY FUT", "interval": "2h"}).status_code == 400
    assert c.post("/api/paper/replay", json={"market": "IN", "symbol": "NIFTY FUT", "day": "soon"}).status_code == 400
    s = ok(c.post("/api/paper/step?market=IN"))
    assert s["replay"]["cursor"] == 5 and s["handoff"] is None
    fills = [{"time": "2026-09-24T09:40:00", "side": "long", "symbol": "NIFTY FUT", "price": 21100, "kind": "entry"}]
    h = ok(c.post("/api/paper/replay", json={"market": "IN", "symbol": "NIFTY FUT", "day": "2026-09-24",
                                             "speed": 5, "fills": fills, "source": "Journal › Trades"}))
    assert h["handoff"]["fills"] == fills and h["replay"]["speed"] == 5 and h["mode"] == "REPLAY"
    assert ok(c.post("/api/paper/speed?market=IN&speed=20"))["replay"]["speed"] == 20
    assert c.post("/api/paper/speed?market=IN&speed=3").status_code == 400

    pv = ok(c.post("/api/paper/preview", json={"market": "IN", "symbol": "NIFTY FUT", "qty": 65}))
    assert pv["ready"] and pv["breakeven_pts"] > 0 and pv["charges"] > 0
    last = pv["price"]
    amber = ok(c.post("/api/paper/preview", json={"market": "IN", "symbol": "NIFTY FUT", "qty": 65,
                                                  "price": last, "target": last + 5}))
    assert amber["amber"] and "not blocked" in amber["amber"]
    assert not ok(c.post("/api/paper/preview", json={"market": "IN", "symbol": "SYNTH-P", "qty": 1}))["ready"]

    s = ok(c.post("/api/paper/assumptions", json={"market": "IN", "symbol": "NIFTY FUT",
                                                  "half_spread": 2, "slippage": 1}))
    assert s["instruments"]["NIFTY FUT"]["half_spread"] == 2
    assert c.post("/api/paper/assumptions", json={"market": "IN", "symbol": "NIFTY FUT",
                                                  "half_spread": -1, "slippage": 0}).status_code == 400

    assert c.post("/api/paper/order", json={"market": "IN", "symbol": "NIFTY FUT", "side": "buy",
                                            "qty": 65, "kind": "limit"}).status_code == 400
    o = ok(c.post("/api/paper/order", json={"market": "IN", "symbol": "NIFTY FUT", "side": "buy",
                                            "qty": 65, "stop": round(last * 0.9, 2)}))
    assert o["placed"]["status"] == "WORKING" and o["placed"]["unplanned"]
    lim = ok(c.post("/api/paper/order", json={"market": "IN", "symbol": "NIFTY FUT", "side": "buy",
                                              "qty": 65, "kind": "limit", "price": round(last * 0.5, 2)}))
    wid = lim["placed"]["id"]
    assert ok(c.post(f"/api/paper/orders/{wid}/cancel?market=IN"))["working"][0]["id"] != wid

    s = _feed_until("IN", lambda s: s["positions"])
    pos = s["positions"][0]
    assert pos["side"] == "long" and pos["unplanned"]
    r = c.post(f"/api/paper/positions/{pos['id']}/move-stop", json={"market": "IN", "stop": pos["stop"] - 10})
    assert r.status_code == 400 and "reason" in r.json()["detail"]
    s = ok(c.post(f"/api/paper/positions/{pos['id']}/move-stop",
                  json={"market": "IN", "stop": pos["stop"] - 10, "reason": "wider"}))
    assert "stop moved away" in s["positions"][0]["rule_breaks"]
    assert c.post(f"/api/paper/positions/{pos['id']}/funding", json={"market": "IN", "rate_pct": 0.01}).status_code == 400
    s = ok(c.post(f"/api/paper/positions/{pos['id']}/close?market=IN"))
    assert s["positions"][0]["closing"]
    assert c.post("/api/paper/positions/999/close?market=IN").status_code == 400
    s = ok(c.post("/api/paper/step?market=IN&n=1"))
    t = s["trades"][-1]
    assert t["exit_reason"] == "Close at next bar" and t["mode"] == "REPLAY" and "slippage" in t

    s = ok(c.post("/api/paper/step?market=IN&to_end=true"))
    assert s["replay"]["done"]

    k = ok(c.post("/api/paper/kill?market=IN"))
    assert k["killed"] and "cancelled" in k["kill"] and k["blocked_now"].startswith("kill switch")
    b = ok(c.post("/api/paper/order", json={"market": "IN", "symbol": "NIFTY FUT", "side": "buy", "qty": 65}))
    assert b["placed"]["status"] == "BLOCKED" and b["blocked"]


def test_paper_pending_rows_and_perps():
    from plugai_trade.paper import draft_pending
    from plugai_trade.store import default as store
    single = draft_pending({"symbol": "SPY", "market": "US", "side": "buy", "qty": 10}, "Alert #1")
    store().add("paper_orders", {"source": "Options Strategy Builder", "kind": "options", "status": "pending",
                                 "strategy": {"name": "Bull put spread", "legs": [
                                     {"kind": "put", "strike": 540, "side": "sell", "qty": 1},
                                     {"kind": "put", "strike": 530, "side": "buy", "qty": 1}]}}, tag="pending")
    for sym in ("SPY", "QQQ"):
        rid = draft_pending({"symbol": sym, "market": "US", "side": "buy", "qty": 5, "note": "Pairs leg"}, "Pairs Lab")
        row = store().get("paper_orders", rid)
        store().update("paper_orders", rid, {**{k: v for k, v in row.items() if k not in ("id", "created", "tag")},
                                             "link_id": "pair:SPY/QQQ:1", "hedge_ratio": 0.9}, tag="pending")
    s = ok(c.get("/api/paper/state?market=US"))
    assert len(s["pending"]) == 4
    multi = next(p for p in s["pending"] if p["multi_leg"])
    assert multi["strategy_name"] == "Bull put spread" and len(multi["legs"]) == 2
    assert sum(1 for p in s["pending"] if p.get("link_id") == "pair:SPY/QQQ:1") == 2

    a = ok(c.post(f"/api/paper/pending/{multi['id']}/accept?market=US"))
    assert a["accepted"] is None                          # tracked, not filled by the bar model
    a = ok(c.post(f"/api/paper/pending/{single}/accept?market=US"))
    assert a["accepted"]["status"] == "WORKING" and a["accepted"]["source"] == "Alert #1"
    link = [p["id"] for p in a["pending"]]
    s = ok(c.post(f"/api/paper/pending/{link[0]}/reject?market=US"))
    assert len(s["pending"]) == 1
    assert c.post(f"/api/paper/pending/{link[0]}/accept?market=US").status_code == 400

    # Crypto perp: funding and Send to Crypto Monitor.
    s = ok(c.post("/api/paper/replay", json={"market": "US", "symbol": "BTC-PERP", "interval": "1d"}))
    ok(c.post("/api/paper/step?market=US&n=3"))
    ok(c.post("/api/paper/order", json={"market": "US", "symbol": "BTC-PERP", "side": "buy", "qty": 1}))
    s = _feed_until("US", lambda s: any(p["symbol"] == "BTC-PERP" for p in s["positions"]))
    perp = next(p for p in s["positions"] if p["symbol"] == "BTC-PERP")
    assert perp["funding_rate"] == 0.0001
    s = ok(c.post(f"/api/paper/positions/{perp['id']}/funding", json={"market": "US", "rate_pct": 0.05}))
    assert c.post(f"/api/paper/positions/{perp['id']}/funding", json={"market": "US", "rate_pct": 5}).status_code == 400
    s = ok(c.post("/api/paper/step?market=US&n=1"))
    assert s["funding_log"] and next(p for p in s["positions"] if p["symbol"] == "BTC-PERP")["funding"] != 0
    n = ok(c.post(f"/api/paper/positions/{perp['id']}/crypto-monitor?market=US"))
    assert n["note_id"] > 0
    cm = ok(c.get("/api/planning/alerts?market=US"))["crypto_positions"]
    assert any(p["symbol"] == "BTC-PERP" for p in cm)
    props = ok(c.post("/api/planning/alerts/propose", json={"source": "From Crypto Monitor", "market": "US",
                                                             "position_key": cm[0]["key"], "leverage": 5}))
    assert [a["kind"] for a in props] == ["funding", "liquidation", "price_band"]


def test_paper_compare_with_backtest_and_notes():
    end = date.today()
    body = {"market": "IN", "symbol": "NIFTY FUT", "start": str(end - timedelta(days=120)), "end": str(end)}
    r = ok(c.post("/api/paper/compare", json=body))
    assert r["bars"] > 50 and r["source"] == "REPLAY" and r["signals"] >= 1
    assert r["gap_r"] == pytest.approx(r["shadow_r"] - r["paper_r"], abs=1e-3)
    assert r["curve"][-1]["shadow"] == pytest.approx(r["shadow_r"], abs=1e-3)
    assert any(f.startswith("Shadow backtest:") for f in r["facts"])
    assert ok(c.get("/api/paper/state?market=IN"))["drift"]["signals"] == r["signals"]
    assert c.post("/api/paper/compare", json={**body, "start": "x"}).status_code == 400
    assert c.post("/api/paper/compare", json={**body, "start": body["end"], "end": body["start"]}).status_code == 400

    sig = r["breaks"][0]["signal"]
    assert ok(c.post("/api/paper/compare/note", json={"market": "IN", "signal": sig, "text": "Slept in"}))["id"]
    assert c.post("/api/paper/compare/note", json={"market": "IN", "signal": sig, "text": " "}).status_code == 400
    assert ok(c.get("/api/paper/state?market=IN"))["drift"]["breaks"][0]["saved_note"] == "Slept in"
