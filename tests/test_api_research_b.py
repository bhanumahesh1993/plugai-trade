"""API: Research (b) — Chart Helper, Earnings Desk, IPO Dashboard (offline)."""

import base64

import pytest
from fastapi.testclient import TestClient

from plugai_trade.api import app

c = TestClient(app)
P = "/api/research-b"
pytestmark = pytest.mark.filterwarnings("ignore:.*live sources unavailable.*")


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ Chart Helper
def test_chart_options_and_bars():
    o = ok(c.get(f"{P}/chart/options"))
    assert o["timeframes"] == ["Daily", "Weekly", "15-min", "5-min"]
    assert "Screenshot" not in o["sources"] and "Synthetic" in o["sources"]
    b = ok(c.post(f"{P}/chart/bars", json={"symbol": "nifty", "market": "IN"}))
    assert b["symbol"] == "NIFTY" and len(b["bars"]) == 60
    assert b["provenance"]["source"] == "synthetic"
    i = ok(c.post(f"{P}/chart/bars", json={"symbol": "SPY", "market": "US", "timeframe": "5-min"}))
    assert "time" in i["bars"][0]


def test_chart_describe_numbers_and_screenshot():
    d = ok(c.post(f"{P}/chart/describe", json={"symbol": "NIFTY", "market": "IN"}))
    assert d["claims"] is None and d["lines"][0].startswith("Close ")
    assert d["facts"][0].startswith("NIFTY · Daily")
    s = ok(c.post(f"{P}/chart/describe",
                  json={"symbol": "SPY", "market": "US", "screenshot": True}))
    assert s["claims"] and {x["Check"] for x in s["claims"]} <= {"✓", "✗"}
    assert s["crosses"] >= 1  # the pattern claim is always unverifiable


def test_chart_levels_zones_intraday_save_send():
    z = ok(c.post(f"{P}/chart/levels", json={"symbol": "NIFTY", "market": "IN"}))
    assert {"Level", "Zone", "Touches", "Distance", "±1 ATR", "From"} <= set(z["table"][0])
    assert z["atr"] > 0 and z["lines"]
    body = {"symbol": "NIFTY FUT", "market": "IN", "timeframe": "5-min", "set": "Intraday",
            "or_minutes": 15}
    i = ok(c.post(f"{P}/chart/levels", json=body))
    assert [r["Level"] for r in i["table"]] == ["PDH", "PDL", "OR high", "OR low", "VWAP"]
    assert i["facts"][0].startswith("PDH: ")
    assert ok(c.post(f"{P}/chart/levels/save", json=body))["id"]
    assert ok(c.post(f"{P}/chart/levels/send", json=body))["id"]
    bad = c.post(f"{P}/chart/levels", json={**body, "or_minutes": 7})
    assert bad.status_code == 400


def test_chart_timeframes_and_errors():
    t = ok(c.post(f"{P}/chart/timeframes",
                  json={"symbol": "SPY", "market": "US", "frames": ["Daily", "Weekly", "15-min"]}))
    assert [r["Timeframe"] for r in t["rows"]] == ["Daily", "Weekly", "15-min"]
    assert c.post(f"{P}/chart/timeframes", json={"frames": ["Hourly"]}).status_code == 400
    assert c.post(f"{P}/chart/bars", json={"timeframe": "Monthly"}).status_code == 400
    assert c.post(f"{P}/chart/bars", json={"market": "UK"}).status_code == 400


# ------------------------------------------------------------------ Earnings Desk
def test_earnings_setup_import_calendar_alerts():
    s = ok(c.get(f"{P}/earnings/setup?market=IN"))
    assert s["sample"] == ["SYN-IN-004", "SYN-IN-010", "SYN-IN-027"]
    assert ok(c.post(f"{P}/earnings/import", json={"market": "US"}))["symbols"] == [
        "SYN-US-006", "SYN-US-012"]
    body = {"market": "IN", "symbols": ["SYN-IN-004"], "days": 60, "macro": True}
    cal = ok(c.post(f"{P}/earnings/calendar", json=body))
    assert cal["rows"] and {"Date", "Time", "Event", "Status", "Source", "Overlap"} <= set(
        cal["rows"][0])
    assert cal["facts"][0].startswith("rows: ")
    assert any(r["Kind"] == "macro" for r in cal["rows"])
    assert ok(c.post(f"{P}/earnings/alerts", json=body))["ids"]
    assert c.post(f"{P}/earnings/calendar", json={**body, "days": 90}).status_code == 400


def test_earnings_digest_consensus_accept_history():
    d = ok(c.post(f"{P}/earnings/digest", json={"market": "IN"}))
    assert [r["Item"] for r in d["digest"]["rows"]][0] == "Revenue"
    assert d["digest"]["chip"] in ("unchanged", "wording softer", "wording firmer")
    assert d["facts"][0].startswith("Revenue: ")
    cons = ok(c.post(f"{P}/earnings/consensus",
                     json={"digest": d["digest"], "item": "Revenue", "value": 450,
                           "source": "Broker note", "as_of": "2026-09-01"}))
    assert cons["digest"]["consensus"][0]["Difference"] == "+4.0%"
    assert c.post(f"{P}/earnings/consensus", json={"digest": d["digest"], "item": "Revenue",
                                                   "value": 1, "source": " "}).status_code == 400
    assert ok(c.post(f"{P}/earnings/digest/accept",
                     json={"digest": cons["digest"], "market": "IN"}))["id"]
    h = ok(c.get(f"{P}/earnings/history?company=Kaveri Pumps (fictional)"))
    assert h["rows"] and h["rows"][0]["chip"]
    bad = c.post(f"{P}/earnings/digest", json={"pdf_base64": base64.b64encode(b"nope").decode()})
    assert bad.status_code == 400


def test_earnings_implied_move_split_and_actions():
    ev = ok(c.get(f"{P}/earnings/move/events?symbol=NIFTY&market=IN"))
    rbi = next(e for e in ev["events"] if e.startswith("RBI"))
    m = ok(c.post(f"{P}/earnings/move",
                  json={"symbol": "NIFTY", "market": "IN", "event": rbi, "quiet_pct": 0.8}))
    assert m["available"] and m["tiles"]["Implied move"].startswith("±")
    assert m["split"]["normal-day move %"] == 0.8
    assert [r["Move"] for r in m["scenarios"]] == ["-10%", "-5%", "+0%", "+5%", "+10%"]
    us = ok(c.post(f"{P}/earnings/move", json={"symbol": "SYN-US-006", "market": "US"}))
    assert "Average move (last 8)" in us["tiles"] and us["moves"]
    body = {"symbol": "SYN-US-006", "market": "US"}
    assert ok(c.post(f"{P}/earnings/move/options-builder", json=body))["strike"]
    assert ok(c.post(f"{P}/earnings/move/journal", json=body))["id"]
    na = ok(c.post(f"{P}/earnings/move", json={"symbol": "SYN-IN-004", "market": "IN"}))
    assert na["available"] is False and na["moves"]
    assert c.post(f"{P}/earnings/move", json={**body, "event": "nope"}).status_code == 400


# ------------------------------------------------------------------ IPO Dashboard
def test_ipo_issues_add_rhp():
    i = ok(c.get(f"{P}/ipo/issues"))
    assert [x["name"] for x in i["issues"]][:2] == ["Example Ltd", "Example SME Ltd"]
    assert i["gmp_banner"] == "UNOFFICIAL · UNREGULATED · NOT A FORECAST"
    assert ok(c.post(f"{P}/ipo/add", json={"name": "Test Co", "board": "SME"}))["id"]
    assert "Test Co" in [x["name"] for x in ok(c.get(f"{P}/ipo/issues"))["issues"]]
    assert c.post(f"{P}/ipo/add", json={"name": " "}).status_code == 400
    r = ok(c.post(f"{P}/ipo/rhp", json={"name": "Example Ltd"}))
    assert r["tiles"]["Issue size (upper)"] == "₹994.0 cr"
    assert r["quotes"]["Fresh / OFS"].startswith("“") and len(r["rows"]) == 8
    assert ok(c.post(f"{P}/ipo/rhp/accept", json={"name": "Example Ltd"}))["id"]
    assert c.post(f"{P}/ipo/rhp", json={"name": "Nope"}).status_code == 400


def test_ipo_subscription_odds_gmp():
    s = ok(c.post(f"{P}/ipo/subscription", json={"name": "Example Ltd", "day": 3}))
    overall = next(r for r in s["rows"] if r["Category"].startswith("Overall"))
    assert overall["Times"] == 59.14 and set(s["by_day"]) == {"1", "2", "3"}
    o = ok(c.post(f"{P}/ipo/odds", json={"name": "Example Ltd", "applicants": 2}))
    assert o["is_estimate"] and round(o["at_least_one"], 4) == 0.19
    assert o["money_blocked"] == 28400
    o2 = ok(c.post(f"{P}/ipo/odds", json={"name": "Example Ltd", "applications": 2_460_000}))
    assert not o2["is_estimate"]
    assert c.post(f"{P}/ipo/odds", json={"name": "Example Ltd", "applicants": 0}).status_code == 400
    g = ok(c.post(f"{P}/ipo/gmp", json={"figures": {"Site A": 22, "Site B": 35, "Msg": 48}}))
    assert g["spread"] == 26 and "Not used" in g["note"]


def test_ipo_sme_and_plan():
    assert ok(c.post(f"{P}/ipo/sme", json={"name": "Example Ltd"}))["sme"] is False
    info = ok(c.post(f"{P}/ipo/sme", json={"name": "Example SME Ltd"}))
    assert info["liquidity"]["Minimum application"].startswith("₹216,000")
    run = ok(c.post(f"{P}/ipo/sme/run", json={"name": "Example SME Ltd"}))
    assert {x["Status"] for x in run["checks"]} <= {"meets", "does not meet", "not found"}
    assert ok(c.post(f"{P}/ipo/sme/accept", json={"name": "Example SME Ltd"}))["id"]
    assert c.post(f"{P}/ipo/sme/run", json={"name": "Example Ltd"}).status_code == 400
    p = ok(c.post(f"{P}/ipo/plan", json={"name": "Example Ltd", "shares": 50}))
    assert [r["Change"] for r in p["plan"]] == [3550.0, 1420.0, 0.0, -1420.0]
    acts = ["Sell all", "Sell half", "Hold; review at day 30", "Exit below; no averaging down"]
    crit = ok(c.post(f"{P}/ipo/plan/critique",
                     json={"name": "Example Ltd", "shares": 50, "actions": acts}))
    assert "all rows have actions" in crit["text"]
    lk = ok(c.post(f"{P}/ipo/plan/lockin", json={"name": "Example Ltd"}))
    assert lk["rows"][0]["Day"] == 30 and lk["alerts"] == len(lk["rows"])
    assert ok(c.post(f"{P}/ipo/plan/save", json={"name": "Example Ltd", "shares": 50,
                                                "actions": acts}))["id"]
