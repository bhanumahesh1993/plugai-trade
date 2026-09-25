"""API: Automate › Scheduler, News Pipeline, ML Lab, Agents, Plugins (offline)."""

import time

import pytest
from fastapi.testclient import TestClient

from plugai_trade.api import app
from plugai_trade.api.routes import automate as A
from plugai_trade.store import default as store

c = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_state():
    for d in (A._news, A._ml, A._runs, A._installs, A._reports):
        d.clear()
    yield
    for d in (A._news, A._ml, A._runs, A._installs, A._reports):
        d.clear()


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def bad(r, text=""):
    assert r.status_code == 400, r.text
    assert text.lower() in r.json()["detail"].lower()
    return r.json()["detail"]


# ------------------------------------------------------------------ Scheduler
def test_scheduler_flow():
    s = ok(c.get("/api/automate/scheduler"))
    assert s["jobs"] == [] and "News Pipeline: fetch" in s["job_types"] and s["cost"] == "₹0 / $0"
    assert s["presets"]["Weekly Review"]["day"] == "Sat"
    p = ok(c.post("/api/automate/scheduler/preview", json={
        "job": "News Pipeline: fetch", "market": "IN", "kind": "every N minutes", "at": "08:00",
        "until": "23:00", "minutes": 15}))
    assert p["when"].startswith("Every 15 min 08:00–23:00") and p["model"] == "none"
    bad(c.post("/api/automate/scheduler/preview", json={"job": "Backup", "at": "7pm"}), "07:30")
    bad(c.post("/api/automate/scheduler/jobs", json={"job": "Nope"}), "Job must be")
    bad(c.post("/api/automate/scheduler/jobs", json={"job": "Backup", "kind": "monthly", "day": "31"}),
        "Day of month")
    s = ok(c.post("/api/automate/scheduler/jobs", json={
        "job": "Weekly Review", "market": "US", "kind": "weekly", "at": "09:00", "day": "Sat"}))
    jid = s["added"]
    job = s["jobs"][0]
    assert job["when"].startswith("Sat 09:00") and job["model"] == "local" and job["next_run"]
    run = ok(c.post(f"/api/automate/scheduler/jobs/{jid}/run"))
    assert run["entry"]["trigger"] == "run now" and run["jobs"][0]["last_run"]
    log = ok(c.get(f"/api/automate/scheduler/log?job_id={jid}"))
    assert log and log[0]["job"] == "Weekly Review"
    assert ok(c.get("/api/automate/scheduler/log"))
    s = ok(c.post(f"/api/automate/scheduler/jobs/{jid}/enabled", json={"on": False}))
    assert s["jobs"][0]["enabled"] is False and s["jobs"][0]["next_run"] is None
    assert ok(c.post("/api/automate/scheduler/pause", json={"on": True}))["paused"] is True
    assert ok(c.post("/api/automate/scheduler/pause", json={"on": False}))["paused"] is False
    s = ok(c.post("/api/automate/scheduler/settings", json={"catch_up": False, "health_alert": True}))
    assert s["catch_up"] is False and s["health_alert"] is True
    s = ok(c.post(f"/api/automate/scheduler/jobs/{jid}/delete"))
    assert s["jobs"] == []
    bad(c.post(f"/api/automate/scheduler/jobs/{jid}/run"), "no job")


# ------------------------------------------------------------------ News Pipeline
def test_news_pipeline_flow():
    s = ok(c.get("/api/automate/news/state?market=IN"))
    assert {x["key"] for x in s["sources"]} == {"nse-rss", "bse-rss", "gdelt"}
    assert s["fetched"] is False and s["indexes"][0] == "NIFTY"
    bad(c.post("/api/automate/news/score", json={"market": "IN"}), "Fetch headlines")
    bad(c.post("/api/automate/news/fetch", json={"market": "IN", "sources": []}), "Tick at least one")
    bad(c.post("/api/automate/news/fetch", json={"market": "IN", "sources": ["sec-8k"]}), "Unknown source")
    s = ok(c.post("/api/automate/news/fetch", json={
        "market": "IN", "sources": ["nse-rss", "bse-rss", "gdelt"], "start": "2025-01-01",
        "end": "2025-06-30"}))
    assert s["fetched"] and len(s["heads"]) > 20
    h = s["heads"][0]
    assert h["published"] and h["seen"] and h["tradable_from"]
    assert any("synthetic" in v for v in s["status"].values())
    bad(c.post("/api/automate/news/compare", json={"market": "IN"}), "Score with both")
    s = ok(c.post("/api/automate/news/score", json={"market": "IN", "finbert": True, "llm": True}))
    assert len(s["scored"]["scorers"]) == 2 and len(s["scored"]["scorers"][0]["labels"]) == len(s["heads"])
    bad(c.post("/api/automate/news/event-study", json={"market": "IN"}), "Compare scorers")
    s = ok(c.post("/api/automate/news/compare", json={"market": "IN"}))
    cmp = s["compare"]
    assert 0 <= cmp["agreement"] <= 1 and cmp["facts"][0].startswith("Headlines compared")
    assert sum(r["total"] for r in cmp["table"]) == cmp["n"]
    bad(c.post("/api/automate/news/rule", json={"market": "IN", "rule": "whatever"}), "Rule must")
    s = ok(c.post("/api/automate/news/rule", json={"market": "IN", "rule": A.RULES[0], "note": "n"}))
    assert s["rule_saved"]["rule"] == A.RULES[0]
    assert store().all("notes", tag="news-rule")
    bad(c.post("/api/automate/news/event-study", json={"market": "IN", "benchmark": "SPY"}), "Index")
    s = ok(c.post("/api/automate/news/event-study", json={
        "market": "IN", "group": "Both agreed: positive", "window": [-5, 10], "benchmark": "NIFTY",
        "costs": "IN-equity-delivery", "entry": "tradable_from"}))
    es = s["study"]
    assert es["trials"] >= 1 and len(es["path"]) == 16 and len(es["cost_table"]) == 6
    assert es["facts"][0].startswith("HYPOTHETICAL")
    s2 = ok(c.post("/api/automate/news/event-study", json={
        "market": "IN", "group": "Both agreed: positive", "window": [-5, 10], "benchmark": "NIFTY",
        "costs": "IN-equity-delivery", "entry": "published_date"}))
    assert s2["study"]["trials"] == es["trials"] + 1
    # state survives a reload of the screen
    assert ok(c.get("/api/automate/news/state?market=IN"))["study"] is not None


def test_news_edgar_contact():
    s = ok(c.get("/api/automate/news/state?market=US"))
    assert any(x["key"] == "sec-8k" for x in s["sources"]) and s["edgar_contact_set"] is False
    bad(c.post("/api/automate/news/contact", json={"contact": "no email"}), "email")
    ok(c.post("/api/automate/news/contact", json={"contact": "Asha Rao asha@example.com"}))
    assert ok(c.get("/api/automate/news/state?market=US"))["edgar_contact_set"] is True


# ------------------------------------------------------------------ ML Lab
def test_ml_lab_flow():
    m = ok(c.get("/api/automate/ml/meta"))
    assert m["horizon"] == 10 and len(m["features"]) == 8 and m["noise"]["key"] == "noise (control)"
    assert ok(c.get("/api/automate/ml/state?market=IN"))["card"] is None
    bad(c.post("/api/automate/ml/shuffle", json={"market": "IN"}), "Train baseline")
    body = {"market": "IN", "symbol": "NIFTY", "features": [f["key"] for f in m["features"]],
            "noise": True, "label": "high_vol_next_10", "train_pct": 60, "valid_pct": 20,
            "purge": 10, "embargo": 0, "rule": "vol_20 > 1"}
    bad(c.post("/api/automate/ml/train", json={**body, "purge": 3}), "purge")
    bad(c.post("/api/automate/ml/train", json={**body, "features": []}), "feature")
    bad(c.post("/api/automate/ml/train", json={**body, "rule": "bogus"}), "one-line rule")
    s = ok(c.post("/api/automate/ml/train", json=body))
    card = s["card"]
    assert card["grade"] in ("Robust", "Fragile", "Likely overfit") and card["trials"] >= 1
    assert {"train", "valid", "test"} <= set(card["scores"]) and card["baselines"][0]["name"] == "majority"
    assert any(i["control"] for i in card["importance"]) and card["overfit"]
    assert "MODEL CARD" in card["text"]
    s2 = ok(c.post("/api/automate/ml/train", json=body))
    assert s2["card"]["trials"] == card["trials"] + 1
    s = ok(c.post("/api/automate/ml/shuffle", json={"market": "IN"}))
    assert s["card"]["shuffle"]["label"] == "for learning only"
    assert s["card"]["trials"] == s2["card"]["trials"]  # not counted as a trial
    s = ok(c.post("/api/automate/ml/accept", json={"market": "IN", "text": "narration"}))
    assert s["accepted"] and store().all("notes", tag="journal")[0]["kind"] == "model_card"
    bad(c.post("/api/automate/ml/send-to-sizer", json={"market": "IN"}), "Volatility scenarios")
    bad(c.post("/api/automate/ml/scenarios", json={"market": "IN", "horizon": 2}), "Horizon")
    s = ok(c.post("/api/automate/ml/scenarios", json={"market": "IN", "symbol": "NIFTY", "horizon": 10}))
    sc = s["scenarios"]
    assert sc["low_pct"] <= sc["middle_pct"] <= sc["high_pct"] and sc["horizon"] == 10
    assert s["history"]["rows"] and s["history"]["facts"][0].startswith("Month-ends scored")
    s = ok(c.post("/api/automate/ml/send-to-sizer", json={"market": "IN"}))
    assert s["sent"] and store().all("notes", tag="sizer")[0]["kind"] == "vol_scenarios"


# ------------------------------------------------------------------ Agents
def _wait(rid):
    deadline = time.monotonic() + 60  # Windows CI runners are slow to spawn the run thread
    while time.monotonic() < deadline:
        r = ok(c.get(f"/api/automate/agents/runs/{rid}"))
        if r["status"] != "running":
            return r
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_agents_flow():
    m = ok(c.get("/api/automate/agents/meta"))
    assert [t["key"] for t in m["teams"]] == ["builtin", "tradingagents", "ai-hedge-fund"]
    assert "run_backtest" in m["tools"]
    bad(c.post("/api/automate/agents/run", json={"team": "nope"}), "Team")
    bad(c.post("/api/automate/agents/run", json={"max_steps": 0}), "max steps")
    r = ok(c.post("/api/automate/agents/run", json={
        "market": "IN", "team": "tradingagents", "symbol": "NIFTY", "as_of": "2026-05-29",
        "mask": True, "max_steps": 40, "max_cost": 0.5}))
    assert "not installed" in r["warning"] and r["config_path"].endswith("tradingagents.toml")
    r = _wait(r["id"])
    assert r["status"] == "done", r
    kinds = {e["kind"] for e in r["events"]}
    assert {"tool", "turn"} <= kinds
    tool = next(e for e in r["events"] if e["kind"] == "tool")
    assert tool["tool"] == "get_bars" and "data" in tool
    p = r["proposal"]
    assert p["kind"] == "rule_proposal" and p["rules"]["text"] and p["facts"][0].startswith("Research proposal")
    assert ok(c.get("/api/automate/agents/meta"))["latest"] == r["id"]
    s = ok(c.post(f"/api/automate/agents/runs/{r['id']}/send"))
    assert s["sent"] and store().all("proposals", tag="PROPOSED")
    bad(c.post(f"/api/automate/agents/runs/{r['id']}/reject", json={"reason": " "}), "reason")
    s = ok(c.post(f"/api/automate/agents/runs/{r['id']}/reject", json={"reason": "Too few trades"}))
    assert s["rejected"]["reason"] == "Too few trades"
    bad(c.get("/api/automate/agents/runs/nope"), "not in this session")


def test_agents_budget_and_stop():
    r = ok(c.post("/api/automate/agents/run", json={"market": "US", "symbol": "SPY", "max_steps": 2}))
    r = _wait(r["id"])
    assert r["status"] == "stopped" and r["events"][-1]["kind"] == "stop"
    assert r["proposal"]["stopped"]
    bad(c.post(f"/api/automate/agents/runs/{r['id']}/send"), "no rule")
    # Stop on a finished run is harmless
    assert ok(c.post(f"/api/automate/agents/runs/{r['id']}/stop"))["status"] == "stopped"


# ------------------------------------------------------------------ Plugins
def test_plugins_flow(monkeypatch):
    s = ok(c.get("/api/automate/plugins"))
    assert s["plugins"] == [] and {a["key"] for a in s["adapters"]} == {"tradingagents", "ai-hedge-fund"}
    assert "no order or paper-order tool" in s["adapters"][0]["plan"]
    bad(c.post("/api/automate/plugins/new", json={"name": "Bad Name", "kind": "Report"}), "lower-case")
    s = ok(c.post("/api/automate/plugins/new", json={"name": "gap_report", "kind": "Report"}))
    assert s["plugins"][0]["name"] == "gap_report" and s["plugins"][0]["kind"] == "report"
    f = ok(c.get("/api/automate/plugins/gap_report/folder"))
    assert "plugin.toml" in f["files"] and "AGENTS.md" in f["files"]
    bad(c.get("/api/automate/plugins/etc/folder"), "no plugin")
    bad(c.post("/api/automate/plugins/gap_report/enable", json={"on": True}), "cannot be enabled")
    bad(c.post("/api/automate/plugins/gap_report/run", json={"market": "IN"}), "Plugin check")
    s = ok(c.post("/api/automate/plugins/gap_report/check"))
    rep = s["report"]
    assert rep["passed"] and rep["summary"].startswith("Plugin check passed")
    assert [i["name"] for i in rep["items"]][:2] == ["Manifest", "Tests (pytest)"]
    assert s["plugins"][0]["status"]["passed"] and "gap_report" in s["reports"]
    s = ok(c.post("/api/automate/plugins/gap_report/enable", json={"on": True}))
    assert s["plugins"][0]["status"]["enabled"]
    r = ok(c.post("/api/automate/plugins/gap_report/run", json={"market": "IN", "symbol": "NIFTY"}))
    assert r["height"] > 0 and "change_pct" in r["columns"] and r["backtest"] is None
    assert r["facts"][0].startswith("Plugin gap_report")
    s = ok(c.post("/api/automate/plugins/gap_report/enable", json={"on": False}))
    assert not s["plugins"][0]["status"]["enabled"]

    calls = []
    monkeypatch.setattr("plugai_trade.agents.install", lambda k: calls.append(k) or f"Installed {k}")
    bad(c.post("/api/automate/plugins/install/nope"), "Unknown")
    s = ok(c.post("/api/automate/plugins/install/tradingagents"))
    assert s["adapters"][0]["install"]["state"] in ("running", "done")
    for _ in range(100):
        st = ok(c.get("/api/automate/plugins"))["adapters"][0]["install"]
        if st["state"] != "running":
            break
        time.sleep(0.02)
    assert st["state"] == "done" and calls == ["tradingagents"]


def test_strategy_plugin_run_has_backtest():
    ok(c.post("/api/automate/plugins/new", json={"name": "ma_cross", "kind": "Strategy"}))
    rep = ok(c.post("/api/automate/plugins/ma_cross/check"))["report"]
    assert rep["passed"], rep["text"]
    r = ok(c.post("/api/automate/plugins/ma_cross/run", json={"market": "US", "symbol": "SPY"}))
    assert r["backtest"]["grade"] and len(r["backtest"]["dates"]) == len(r["backtest"]["equity"])


def test_bad_market():
    bad(c.get("/api/automate/news/state?market=XX"), "Market")
