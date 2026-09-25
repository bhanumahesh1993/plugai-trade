"""API: Home wizard, Lessons, Prompt Library and the Settings screens (offline, memory keychain)."""

import json

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend

from plugai_trade import ai, config, wizard
from plugai_trade.api import app
from plugai_trade.api.routes import settings as routes

c = TestClient(app)


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.d = {}

    def get_password(self, service, name):
        return self.d.get((service, name))

    def set_password(self, service, name, value):
        self.d[(service, name)] = value

    def delete_password(self, service, name):
        self.d.pop((service, name), None)


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    old = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)
    routes._last_cmp.clear()
    routes._preview.clear()
    routes._last_test.clear()
    yield
    keyring.set_keyring(old)


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ wizard
def test_wizard_state_and_steps():
    s = ok(c.get("/api/wizard/state"))
    assert s["done"] is False and s["step"] == 0 and len(s["steps"]) == 5
    assert s["machine"]["ollama"] is False and "Ollama not found" in s["machine"]["lines"]
    assert [m["tag"] for m in s["models"]] == [m.tag for m in wizard.MODELS]
    assert set(s["fits"]) == {m.tag for m in wizard.MODELS}
    assert s["fits"]["qwen3.5:9b"]["line"].startswith("Total")
    assert ok(c.get("/api/wizard/machine"))["ollama"] is False
    assert ok(c.post("/api/wizard/step", json={"step": 3}))["step"] == 3
    assert ok(c.post("/api/wizard/step", json={"step": 99}))["step"] == 4


def test_wizard_pull_streams_a_plain_failure_offline():
    r = c.get("/api/wizard/pull?tag=qwen3.5:4b")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert "event: fail" in r.text and "Pull model did not finish" in r.text
    assert c.get("/api/wizard/pull?tag=bad tag;rm").status_code == 400


def test_wizard_pull_streams_progress(monkeypatch):
    prog = [wizard.PullProgress("pulling", 50, 100), wizard.PullProgress("success", 100, 100)]
    monkeypatch.setattr(wizard, "pull_model", lambda tag: iter(prog))
    r = c.get("/api/wizard/pull?tag=qwen3.5:4b")
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert events[0]["fraction"] == 0.5 and "event: done" in r.text
    assert config.get("ai.local_model") == "qwen3.5:4b"


def test_wizard_cloud_key_sample_selftest_diagnostic_done():
    k = ok(c.post("/api/wizard/cloud-key", json={"provider": "Gemini", "key": "abcd1234WXYZ"}))
    assert k["masked"] == "••••WXYZ" and "WXYZ" in k["message"]
    assert c.post("/api/wizard/cloud-key", json={"provider": "Nope", "key": "x"}).status_code == 400
    assert c.post("/api/wizard/cloud-key", json={"provider": "Groq", "key": " "}).status_code == 400

    smp = ok(c.post("/api/wizard/sample", json={"market": "US"}))
    assert smp["market"] == "US" and [r["symbol"] for r in smp["rows"]] == ["SPY", "QQQ", "DIA"]
    assert config.get("market") == "US"
    assert c.post("/api/wizard/sample", json={"market": "XX"}).status_code == 400

    t = ok(c.post("/api/wizard/self-test", json={"market": "US"}))
    assert len(t["checks"]) == 6 and t["passed"] is False
    failed = [x["name"] for x in t["checks"] if not x["passed"]]
    assert failed == ["Model quoted it"] and t["score"] == "5 of 6"
    d = ok(c.post("/api/wizard/diagnostic"))["text"]
    assert "Self-test:" in d and "WXYZ" not in d

    h = ok(c.get("/api/wizard/home"))
    assert h["self_test"]["failed"] == ["Model quoted it"]
    assert [q["slug"] for q in h["quick"]][:2] == ["briefing", "lessons"] and h["pinned"] == []

    assert ok(c.post("/api/wizard/done", json={"done": True}))["done"] is True
    again = ok(c.post("/api/wizard/done", json={"done": False}))
    assert again == {"done": False, "step": 0}


def test_wizard_start_redirect(monkeypatch):
    assert ok(c.get("/api/wizard/start")) == {"target": None, "lesson": None}
    monkeypatch.setenv("PLUGAI_TRADE_START_PAGE", "/paper-desk")
    assert ok(c.get("/api/wizard/start"))["target"] == "paper-desk"
    monkeypatch.setenv("PLUGAI_TRADE_START_PAGE", "nope")
    assert ok(c.get("/api/wizard/start"))["target"] is None
    monkeypatch.setenv("PLUGAI_TRADE_LESSON", "22")
    assert ok(c.get("/api/wizard/start")) == {"target": "lessons", "lesson": 22}


# ------------------------------------------------------------------ lessons
def test_lessons_list_detail_check_reset():
    ls = ok(c.get("/api/lessons"))
    assert len(ls["lessons"]) == 34 and ls["lessons"][0]["badge"] == "Not started"
    d = ok(c.get("/api/lessons/1?market=IN"))
    assert d["exercise"]["table"]["rows"] and d["checks"][0]["kind"] == "number"
    two = ok(c.get("/api/lessons/2"))
    assert two["steps"][0]["screen"]["slug"] == "ai-models"
    assert c.get("/api/lessons/99").status_code == 404

    lines = ok(c.post("/api/lessons/1/load-sample", json={"market": "IN"}))["lines"]
    assert lines and "Sample watchlist loaded" in lines[0]

    close = d["exercise"]["table"]["rows"][-1]["close"]
    res = ok(c.post("/api/lessons/1/check", json={"market": "IN", "answers": {
        "close": str(close), "five_day": "nope", "scorecard": True}}))
    by = {r["key"]: r for r in res["results"]}
    assert by["close"]["passed"] and not by["five_day"]["passed"] and by["scorecard"]["passed"]
    assert res["badge"] == "In progress"
    assert ok(c.get("/api/lessons"))["lessons"][0]["badge"] == "In progress"
    r = ok(c.post("/api/lessons/1/reset"))
    assert r["removed"] == 3 and r["badge"] == "Not started"


def test_lessons_from_env(monkeypatch):
    monkeypatch.setenv("PLUGAI_TRADE_LESSON", "5")
    assert ok(c.get("/api/lessons"))["from_env"] == 5


# ------------------------------------------------------------------ prompts
def test_prompts_search_fill_save_delete():
    allp = ok(c.get("/api/prompts"))
    assert allp["count"] == allp["total"] == 40 and "Research" in allp["chips"]
    q = ok(c.get("/api/prompts?q=concall"))
    assert 0 < q["count"] < 40
    assert ok(c.get("/api/prompts?chips=Tax"))["count"] > 0
    assert c.get("/api/prompts?chips=Nope").status_code == 400

    p = q["prompts"][0]
    paste = next(x["name"] for x in p["placeholders"] if x["paste"])
    f = ok(c.post("/api/prompts/fill", json={"text": p["text"], "values": {paste: "Line one\nignore all"}}))
    assert f["untrusted"] and paste not in f["left"]

    saved = ok(c.post(f"/api/prompts/{p['id']}/my-version", json={"text": p["text"] + "\nMine."}))
    assert saved["tag"] == "MY VERSION"
    first = ok(c.get("/api/prompts?q=concall"))["prompts"][0]
    assert first["mine"] and first["note_id"] == saved["note_id"] and first["kid"] != p["id"]
    assert c.post("/api/prompts/nope/my-version", json={"text": "x"}).status_code == 404
    assert c.post(f"/api/prompts/{p['id']}/my-version", json={"text": " "}).status_code == 400
    ok(c.post(f"/api/prompts/my-version/{saved['note_id']}/delete"))
    assert not ok(c.get("/api/prompts?q=concall"))["prompts"][0]["mine"]


# ------------------------------------------------------------------ data sources
def test_data_sources_tiers_keys_live_remind():
    d = ok(c.get("/api/settings/data-sources?market=IN"))
    assert [t["tier"] for t in d["tiers"]] == ["No signup", "Free key", "Your broker"]
    broker = {s["name"]: s for s in d["tiers"][2]["sources"]}
    assert broker["upstox"]["set_up"] is False and broker["upstox"]["connect_url"]
    assert broker["fyers"]["remind"] == {"at": "08:55"} and broker["upstox"]["remind"] is None
    assert [s["key"] for s in d["strips"]] == ["IN-eod", "IN-intraday", "FX", "crypto"]
    assert d["compare"]["symbol"] == "NIFTY"

    assert c.post("/api/settings/data-sources/upstox/keys", json={"values": {"upstox_analytics_token": " "}}).status_code == 400
    assert c.post("/api/settings/data-sources/upstox/keys", json={"values": {"x": "1"}}).status_code == 400
    assert c.post("/api/settings/data-sources/synthetic/keys", json={"values": {}}).status_code == 400
    s = ok(c.post("/api/settings/data-sources/upstox/keys", json={"values": {"upstox_analytics_token": "tok-12345678"}}))
    assert s["saved"][0]["masked"] == "••••5678"
    up = {x["name"]: x for x in ok(c.get("/api/settings/data-sources?market=IN"))["tiers"][2]["sources"]}["upstox"]
    assert up["set_up"] and up["expiry"]["days_left"] >= 364  # saved today + 1 year
    strip = ok(c.get("/api/settings/data-sources?market=IN"))["strips"][0]
    assert "Upstox" in strip["text"]

    live = ok(c.post("/api/settings/data-sources/upstox/live", json={"on": True}))
    assert live["live_stream"] and live["live"]["symbols"]
    live = ok(c.post("/api/settings/data-sources/upstox/live", json={"on": True, "symbols": ["nifty", "NIFTY", " "]}))
    assert live["live"]["symbols"] == ["NIFTY"]
    assert ok(c.post("/api/settings/data-sources/upstox/live", json={"on": False}))["live_stream"] is False
    assert c.post("/api/settings/data-sources/nse_bhavcopy/live", json={"on": True}).status_code == 400

    assert ok(c.post("/api/settings/data-sources/fyers/remind", json={"at": "08:50"}))["at"] == "08:50"
    assert c.post("/api/settings/data-sources/fyers/remind", json={"at": "8"}).status_code == 400
    assert c.post("/api/settings/data-sources/upstox/remind", json={"at": "08:50"}).status_code == 400

    a = ok(c.post("/api/settings/data-sources/add-key", json={"name": "finnhub_api_key", "value": "fh-0000abcd"}))
    assert a["masked"] == "••••abcd" and config.get("data.saved_on.finnhub_api_key")
    assert c.post("/api/settings/data-sources/add-key", json={"name": "nope", "value": "x"}).status_code == 400
    assert c.post("/api/settings/data-sources/add-key", json={"name": "fred_api_key", "value": ""}).status_code == 400

    e = ok(c.post("/api/settings/data-sources/edgar-contact", json={"contact": " Ann ann@example.com "}))
    assert e["contact"] == "Ann ann@example.com"


def test_data_sources_test_connection_offline():
    r = ok(c.post("/api/settings/data-sources/nse_bhavcopy/test", json={"market": "IN"}))
    assert r["ok"] is False and r["message"].startswith("NSE bhavcopy:") and r["last_test"]["ok"] is False
    assert c.post("/api/settings/data-sources/synthetic/test", json={"market": "IN"}).status_code == 400
    assert c.post("/api/settings/data-sources/nope/test", json={"market": "IN"}).status_code == 404


def test_fallback_strip_reorder_and_reset():
    cur = config.get("data.fallback.IN-eod")
    new = [cur[1], cur[0], *cur[2:]]
    s = ok(c.post("/api/settings/data-sources/fallback", json={"key": "IN-eod", "chain": new}))
    assert [x["name"] for x in s["chain"]] == new and s["is_default"] is False
    assert c.post("/api/settings/data-sources/fallback", json={"key": "IN-eod", "chain": ["synthetic"]}).status_code == 400
    assert c.post("/api/settings/data-sources/fallback", json={"key": "XX", "chain": []}).status_code == 400
    r = ok(c.post("/api/settings/data-sources/fallback", json={"key": "IN-eod", "reset": True}))
    assert r["is_default"] is True


def test_compare_sources_and_save():
    assert c.post("/api/settings/data-sources/compare/save").status_code == 400
    body = {"symbol": "nifty", "market": "IN", "start": "2026-05-01", "end": "2026-05-29",
            "source_a": "synthetic", "source_b": "synthetic"}
    r = ok(c.post("/api/settings/data-sources/compare", json=body))
    assert r["symbol"] == "NIFTY" and r["rows_compared"] > 15 and r["missing"] == 0
    assert r["facts"][2].startswith("Rows compared:")
    day = r["table"][0]["date"]
    assert r["provenance"][day]["A"]["close"] == r["table"][0]["close_a"]
    assert ok(c.post("/api/settings/data-sources/compare/save"))["id"] > 0
    bad = c.post("/api/settings/data-sources/compare", json={**body, "source_a": "nse_bhavcopy"})
    assert bad.status_code == 400 and "Could not load both sources" in bad.json()["detail"]
    assert c.post("/api/settings/data-sources/compare", json={**body, "start": "2026-06-01"}).status_code == 400


# ------------------------------------------------------------------ AI models
def test_ai_models_all_sections():
    m = ok(c.get("/api/settings/ai-models"))
    assert m["default"] == "qwen3.5:9b" and m["ollama"] is False
    assert len(m["models"]) == 3 and m["models"][0]["fit"]["colour"] in ("green", "amber", "red")
    sec = {u["section"]: u for u in m["use_for"]}
    assert sec["Journal"]["forced"] and sec["Journal"]["policy"] == "Local only"
    assert "Documents" in sec and "Settings" not in sec

    assert ok(c.post("/api/settings/ai-models/context", json={"tokens": 16384}))["context_length"] == 16384
    assert c.post("/api/settings/ai-models/context", json={"tokens": 1000}).status_code == 400
    f = ok(c.get("/api/settings/ai-models/fit?tag=qwen3.5:9b&context=8192"))
    assert f["facts"][-1] == f["line"]
    assert c.get("/api/settings/ai-models/fit?tag=nope").status_code == 400

    t = ok(c.post("/api/settings/ai-models/test", json={}))
    assert t["ok"] is False and "Ollama not found" in t["detail"]
    assert ok(c.post("/api/settings/ai-models/default", json={"tag": "qwen3.5:4b"}))["default"] == "qwen3.5:4b"
    assert c.post("/api/settings/ai-models/default", json={"tag": " "}).status_code == 400

    s = ok(c.post("/api/settings/ai-models/local-server", json={"url": "http://localhost:1234/v1"}))
    assert s["local_servers"] == ["http://localhost:1234/v1"]
    assert c.post("/api/settings/ai-models/local-server", json={"url": "localhost"}).status_code == 400
    assert ok(c.post("/api/settings/ai-models/local-server/remove", json={"url": "http://localhost:1234/v1"}))["local_servers"] == []

    no_key = c.post("/api/settings/ai-models/cloud", json={"provider": "Gemini", "name": "gemini-flash"})
    assert no_key.status_code == 400 and "Settings › Keys" in no_key.json()["detail"]
    ok(c.post("/api/settings/keys", json={"name": "gemini_api_key", "value": "g-123456789"}))
    added = ok(c.post("/api/settings/ai-models/cloud", json={"provider": "Gemini", "name": "gemini-flash"}))
    assert added["added"] == "gemini/gemini-flash"
    assert c.post("/api/settings/ai-models/cloud", json={"provider": "X", "name": "y"}).status_code == 400

    r = ok(c.post("/api/settings/ai-models/roles", json={"drafting": "gemini/gemini-flash", "journal": "qwen3.5:4b"}))
    assert r["drafting"] == "gemini/gemini-flash" and config.get("ai.drafting_model") == "gemini/gemini-flash"
    assert c.post("/api/settings/ai-models/roles", json={"drafting": "x", "journal": "gemini/gemini-flash"}).status_code == 400
    assert ok(c.post("/api/settings/ai-models/cloud/remove", json={"name": "gemini/gemini-flash"}))["cloud_models"] == []

    assert ok(c.post("/api/settings/ai-models/use-for", json={"section": "Research", "policy": "Local only"}))["use_for"]["Research"] == "Local only"
    assert c.post("/api/settings/ai-models/use-for", json={"section": "Journal", "policy": "Cloud allowed"}).status_code == 400
    assert c.post("/api/settings/ai-models/use-for", json={"section": "Nope", "policy": "Local only"}).status_code == 400

    assert ok(c.post("/api/settings/ai-models/budget", json={"usd": 4}))["budget"] == 4
    assert c.post("/api/settings/ai-models/budget", json={"usd": -1}).status_code == 400
    assert ok(c.post("/api/settings/ai-models/embedding", json={"model": "nomic-embed-text"}))["embedding"] == "nomic-embed-text"
    assert c.post("/api/settings/ai-models/embedding", json={"model": "bad name"}).status_code == 400


# ------------------------------------------------------------------ keys
def test_keys_masked_and_refused():
    assert ok(c.get("/api/settings/keys"))["keys"] == []
    s = ok(c.post("/api/settings/keys", json={"name": "Groq API key", "value": "gsk_abcdef9876"}))
    assert s == {"name": "groq_api_key", "masked": "••••9876"}
    assert ok(c.get("/api/settings/keys"))["keys"] == [{"name": "groq_api_key", "masked": "••••9876"}]
    bad = c.post("/api/settings/keys", json={"name": "exchange_key", "value": "x1234", "permissions": ["read", "trade"]})
    assert bad.status_code == 400 and "Refused" in bad.json()["detail"] and "read-only" in bad.json()["detail"]
    assert c.post("/api/settings/keys", json={"name": "", "value": "x"}).status_code == 400
    ok(c.post("/api/settings/keys/groq_api_key/remove"))
    assert ok(c.get("/api/settings/keys"))["keys"] == []


# ------------------------------------------------------------------ MCP
def test_mcp_tools_toggle_log():
    m = ok(c.get("/api/settings/mcp"))
    assert {t["tag"] for t in m["tools"]} == {"READ", "PAPER"} and m["offered"] == 6
    assert json.loads(m["config"])["mcpServers"]["plugai-trade"]["args"] == ["mcp"]
    off = ok(c.post("/api/settings/mcp/paper-order", json={"on": False}))
    assert off["paper_order"] is False and off["offered"] == 5
    from plugai_trade import mcp_server
    mcp_server.get_watchlist("IN")
    log = ok(c.get("/api/settings/mcp"))["log"]
    assert log and log[0]["tool"] == "get_watchlist"


# ------------------------------------------------------------------ privacy
def test_privacy_toggles_preview_lag():
    p = ok(c.get("/api/settings/privacy"))
    assert p["defaults_on"] and p["lag"] == 90 and p["min_lag"] == 30
    t = ok(c.post("/api/settings/privacy/toggle", json={"name": "crash_reports", "on": True}))
    assert t["defaults_on"] is False
    assert c.post("/api/settings/privacy/toggle", json={"name": "nope", "on": True}).status_code == 400
    pv = ok(c.post("/api/settings/privacy/preview", json={"text": "PAN ABCPK1234F client"}))
    assert "PAN" in pv["found"] and "ABCPK1234F" not in pv["payload"]
    lag = ok(c.post("/api/settings/privacy/lag", json={"days": 10}))
    assert lag["lag"] == 30 and lag["raised"]
    assert ok(c.post("/api/settings/privacy/lag", json={"days": 120}))["lag"] == 120
    assert c.post("/api/settings/privacy/lag", json={"days": 5000}).status_code == 400


# ------------------------------------------------------------------ security
def test_security_checklist_registers_pitch_audit_export():
    s = ok(c.get("/api/settings/security"))
    assert s["total"] == 9 and s["score"].endswith("of 9") and "Cloud" in s["filters"]
    t = ok(c.post("/api/settings/security/tick", json={"key": "2fa", "on": True}))
    assert t["passed"] == s["passed"] + 1
    assert c.post("/api/settings/security/tick", json={"key": "nope", "on": True}).status_code == 400
    regs = ok(c.get("/api/settings/security/registers?market=US&kind=Futures / forex"))["registers"]
    assert regs[0]["url"].startswith("https://www.nfa")
    assert c.get("/api/settings/security/registers?market=IN&kind=Nope").status_code == 400

    pc = ok(c.post("/api/settings/security/pitch", json={"text": "Earn 3% a day, guaranteed. Only 5 seats left!"}))
    assert pc["flags"] and pc["compound"][0]["pct"] == 3 and round(pc["compound"][0]["multiple"]) > 1600
    assert c.post("/api/settings/security/pitch", json={"text": " "}).status_code == 400

    rows = ok(c.get("/api/settings/security/audit?filter=All"))["rows"]
    assert any(r["kind"] == "pitch_check" for r in rows)
    assert c.get("/api/settings/security/audit?filter=Nope").status_code == 400
    ex = c.get("/api/settings/security/export?filter=All")
    assert ex.status_code == 200 and ex.text.startswith("time,kind,category,detail")
    assert "attachment" in ex.headers["content-disposition"]


# ------------------------------------------------------------------ workspace
def test_workspace_preview_accept_export():
    w = ok(c.get("/api/settings/workspace"))
    assert w["preview"] is None and "Swing" in w["styles"] and w["briefing_at"]["IN"] == "08:40"
    assert c.post("/api/settings/workspace/accept", json={"group": "Pinned screens"}).status_code == 400
    pv = ok(c.post("/api/settings/workspace/preview", json={"style": "Swing", "market": "Both", "times": {"IN": "08:45"}}))
    assert pv["markets"] == ["IN", "US"] and pv["groups"][0]["name"] == "Pinned screens"
    assert any("08:45" in line for line in pv["groups"][1]["lines"])
    assert c.post("/api/settings/workspace/preview", json={"style": "Nope"}).status_code == 400
    assert c.post("/api/settings/workspace/preview", json={"style": "Swing", "times": {"IN": "9"}}).status_code == 400

    a = ok(c.post("/api/settings/workspace/accept", json={"group": "Pinned screens"}))
    assert a["accepted"] == ["Pinned screens"] and "Pinned" in a["message"] and a["pinned"]
    assert c.post("/api/settings/workspace/accept", json={"group": "Pinned screens"}).status_code == 400
    assert ok(c.get("/api/wizard/home"))["pinned"][0]["slug"] == "screener"
    ok(c.post("/api/settings/workspace/accept", json={"group": "Rhythm reminders"}))
    ex = c.get("/api/settings/workspace/export")
    body = json.loads(ex.text)
    assert body["pinned"] and "Keys and the journal are never included." == body["note"]
