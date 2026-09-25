"""API: Research A — Daily Briefing, Document Desk, Screener, Score-Tester (offline)."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from plugai_trade.api import app
    from plugai_trade.api.routes import research_a
    research_a._docs.clear()
    return TestClient(app)


# ---------------------------------------------------------------- Daily Briefing
def test_briefing_setup_generate_schedule_runs(client):
    s = client.get("/api/research/briefing/setup?market=IN").json()
    assert s["defaults"]["cutoff"] == "08:45" and s["tz"] == "IST"
    assert "NIFTY" in s["sample"] and s["channels"][0] == "Dashboard"

    b = client.post("/api/research/briefing/generate",
                    json={"symbols": ["nifty", "BANKNIFTY"], "market": "IN", "cutoff": "08:45"}).json()
    assert b["edition"] == 1 and set(b["panels"]) == {"Watchlist", "Overnight news", "Events today"}
    assert b["panels"]["Watchlist"][0]["text"].startswith("NIFTY")
    assert b["sourced"] >= 2 and b["unsourced"] >= 1          # the GIFT Nifty line has no time
    assert any(not ln["sourced"] and ln["reason"] for ln in b["panels"]["Overnight news"])
    assert b["dropped"] and b["questions"] and b["yesterday"]
    assert b["facts"][0].startswith("Daily Briefing")

    r = client.post("/api/research/briefing/schedule",
                    json={"market": "IN", "run_time": "07:30", "cutoff": "08:45",
                          "delivery": ["Dashboard", "Email"], "refresh_time": None})
    assert r.status_code == 200
    runs = client.get("/api/research/briefing/runs?market=IN").json()
    assert len(runs["editions"]) == 1 and runs["jobs"][0]["delivery"] == ["Dashboard", "Email"]


def test_briefing_errors(client):
    assert client.post("/api/research/briefing/generate", json={"symbols": [" "]}).status_code == 400
    assert client.post("/api/research/briefing/generate",
                       json={"symbols": ["SPY"], "market": "XX"}).status_code == 400
    assert client.post("/api/research/briefing/generate",
                       json={"symbols": ["SPY"], "market": "US", "cutoff": "late"}).status_code == 400
    assert client.post("/api/research/briefing/schedule",
                       json={"market": "US", "delivery": ["Pager"]}).status_code == 400


def test_briefing_saved_watchlist_appears(client):
    client.post("/api/research/screener/watchlist",
                json={"name": "Week list", "market": "US", "symbols": ["SPY"],
                      "reasons": {"SPY": "index"}, "review_by": "2030-01-01"})
    s = client.get("/api/research/briefing/setup?market=US").json()
    assert s["saved"][0]["name"] == "Week list" and s["saved"][0]["symbols"] == ["SPY"]


# ---------------------------------------------------------------- Document Desk
Q = "What did management say about receivables and credit terms?"


def test_documents_load_ask_extract_compare_accept(client):
    d = client.get("/api/research/documents").json()
    assert "Kaveri_Q1-FY27_concall" in d["samples"] and "Red-flag checklist" in d["templates"]
    client.post("/api/research/documents/sample", json={"name": "Kaveri_Q4-FY26_concall"})
    d = client.post("/api/research/documents/sample", json={"name": "Kaveri_Q1-FY27_concall"}).json()
    assert d["added"] == "Kaveri_Q1-FY27_concall" and len(d["documents"]) == 2
    assert "text OK" in d["documents"][1]["check"]

    a = client.post("/api/research/documents/ask",
                    json={"question": Q, "document": "Kaveri_Q1-FY27_concall"}).json()
    assert a["found"] and a["quotes"][0]["cite"] == "[p. 6]" and a["hits"]
    assert a["facts"][0] == f"Question: {Q}"

    f = client.get("/api/research/documents/fields?template=Red-flag checklist").json()
    assert ":" in f["fields"]
    e = client.post("/api/research/documents/extract",
                    json={"document": "Kaveri_Q1-FY27_concall", "template": "Red-flag checklist"}).json()
    assert len(e["rows"]) == 6 and e["found"] >= 1 and e["csv"].startswith("field,quote")
    e2 = client.post("/api/research/documents/extract",
                     json={"document": "Kaveri_Q1-FY27_concall", "template": "Red-flag checklist",
                           "fields": "Pledge: pledged"}).json()
    assert [r["field"] for r in e2["rows"]] == ["Pledge"]

    c = client.post("/api/research/documents/compare",
                    json={"a": "Kaveri_Q4-FY26_concall", "b": "Kaveri_Q1-FY27_concall"}).json()
    assert c["rows"] and c["tone_a"]["words"] > 0 and c["facts"][-1].startswith("Tone B")

    for body in ({"kind": "extraction", "extract": {"document": "Kaveri_Q1-FY27_concall",
                                                    "template": "Red-flag checklist"}},
                 {"kind": "comparison", "compare": {"a": "Kaveri_Q4-FY26_concall",
                                                    "b": "Kaveri_Q1-FY27_concall"}}):
        assert client.post("/api/research/documents/accept", json=body).status_code == 200
    from plugai_trade.store import default as store
    kinds = {r["kind"] for r in store().all("theses", tag="document_desk")}
    assert kinds == {"extraction", "comparison"}

    d = client.post("/api/research/documents/remove", json={"name": "Kaveri_Q4-FY26_concall"}).json()
    assert [x["name"] for x in d["documents"]] == ["Kaveri_Q1-FY27_concall"]


def test_documents_text_upload_link(client):
    t = client.post("/api/research/documents/text",
                    json={"text": "Receivable days rose to 78.\fPledge is nil.", "name": "Notes"}).json()
    assert t["documents"][0]["untrusted"] and t["documents"][0]["pages"] == 2
    assert client.post("/api/research/documents/text", json={"text": "  "}).status_code == 400

    from plugai_trade import docdesk
    pdf = docdesk.make_pdf(["Receivable days went up to 78 from 71 in the quarter."])
    u = client.post("/api/research/documents/upload",
                    json={"name": "q1.pdf", "data_b64": base64.b64encode(pdf).decode(),
                          "market": "IN"}).json()
    assert u["added"] == "q1" and u["documents"][-1]["kind"] == "pdf"
    md = client.post("/api/research/documents/upload",
                     json={"name": "n.md", "data_b64": base64.b64encode(b"# hello there").decode()})
    assert md.status_code == 200
    bad = client.post("/api/research/documents/upload",
                      json={"name": "x.docx", "data_b64": base64.b64encode(b"zz").decode()})
    assert bad.status_code == 400
    broken = client.post("/api/research/documents/upload",
                         json={"name": "x.pdf", "data_b64": base64.b64encode(b"not a pdf").decode()})
    assert broken.status_code == 400 and "PDF" in broken.json()["detail"]
    # offline: the link fails with a plain-English reason, not a crash
    link = client.post("/api/research/documents/link", json={"url": "ftp://nope"})
    assert link.status_code == 400 and "http" in link.json()["detail"]


def test_documents_upload_file_multipart(client):
    pytest.importorskip("python_multipart")
    r = client.post("/api/research/documents/upload-file",
                    files={"file": ("notes.txt", b"Capex of 60 crore planned.", "text/plain")},
                    data={"market": "US"})
    assert r.status_code == 200 and r.json()["documents"][0]["market"] == "US"


def test_documents_errors(client):
    assert client.post("/api/research/documents/ask", json={"question": "x"}).status_code == 400
    assert client.post("/api/research/documents/ask",
                       json={"question": "x", "document": "missing"}).status_code == 400
    assert client.post("/api/research/documents/ask", json={"question": " "}).status_code == 400
    assert client.post("/api/research/documents/sample", json={"name": "nope"}).status_code == 400
    assert client.get("/api/research/documents/fields?template=nope").status_code == 400
    assert client.post("/api/research/documents/accept", json={"kind": "extraction"}).status_code == 400


def test_library_samples_folder_and_ask(client, tmp_path):
    lib = client.get("/api/research/documents/library").json()
    assert lib["counts"]["chunks"] == 0
    s = client.post("/api/research/documents/library/samples").json()
    assert s["counts"]["documents"] >= 6 and "chunks indexed" in s["line"]
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("Promoter shares encumbered: 4.1% of holding.")
    f = client.post("/api/research/documents/library/folder",
                    json={"folder": str(tmp_path / "notes"), "market": "IN"}).json()
    assert "chunks" in f["line"] and any(d["name"] == "a" for d in f["docs"])
    assert client.post("/api/research/documents/library/folder",
                       json={"folder": str(tmp_path / "missing")}).status_code == 400
    assert client.post("/api/research/documents/library/folder", json={"folder": ""}).status_code == 400
    a = client.post("/api/research/documents/ask",
                    json={"question": "Has the promoter pledged shares?", "scope": "Ask my documents"}).json()
    assert a["hits"] and all("·" in h["cite"] or "p." in h["cite"] for h in a["hits"])


# ---------------------------------------------------------------- Screener
def test_screener_setup_preset_parse_edit(client):
    s = client.get("/api/research/screener/setup?market=IN").json()
    assert s["universe"] == "NIFTY 500" and "Gap scan" in s["presets"] and s["asof"]
    text = client.get("/api/research/screener/preset?name=Swing · Breakout&market=IN").json()["text"]
    p = client.post("/api/research/screener/parse", json={"text": text, "market": "IN"}).json()
    assert len(p["rules"]) == 5 and p["exclude_events"] == 10
    assert any(r["interpreted"] for r in p["rules"])
    e = client.post("/api/research/screener/parse",
                    json={"text": text, "market": "IN", "edits": {"2": 2.0}}).json()
    assert e["rules"][2]["value"] == 2.0 and "(edited to 2)" in e["rules"][2]["text"]
    assert any("edited to 2" in f for f in e["facts"])
    u = client.post("/api/research/screener/parse",
                    json={"text": "near the high; purple unicorns", "market": "IN"}).json()
    assert u["unparsed"]
    assert client.get("/api/research/screener/preset?name=Nope").status_code == 400


def test_screener_run_save_schedule(client):
    text = "close within 10% of the 52-week high; median traded value at least ₹1 cr"
    r = client.post("/api/research/screener/run",
                    json={"text": text, "market": "IN", "universe": "NIFTY 50",
                          "exclude_events": 0}).json()
    assert r["tested"] > 0 and r["columns"][0] == "Symbol" and "Next event" in r["columns"]
    assert r["facts"][0].startswith("Universe: NIFTY 50")
    syms = [row["Symbol"] for row in r["rows"]][:2] or ["SYN-IN-001"]
    bad = client.post("/api/research/screener/watchlist",
                      json={"name": "Screen", "market": "IN", "symbols": syms,
                            "reasons": {syms[0]: "near high"}, "review_by": "2030-01-01"})
    assert (bad.status_code == 400) == (len(syms) > 1)
    ok = client.post("/api/research/screener/watchlist",
                     json={"name": "Screen", "market": "IN", "symbols": syms,
                           "reasons": {s: "near high" for s in syms}, "review_by": "2030-01-01",
                           "rules_text": text, "triage": {s: "Watch closely" for s in syms}}).json()
    assert ok["saved"] == len(syms)
    assert client.get("/api/research/screener/setup?market=IN").json()["watchlists"][0]["name"] == "Screen"
    j = client.post("/api/research/screener/schedule",
                    json={"name": "Gap scan", "market": "IN", "run_time": "09:08", "text": text,
                          "universe": "NIFTY 50"})
    assert j.status_code == 200
    from plugai_trade.store import default as store
    assert store().all("jobs", tag="screener")[0]["run_time"] == "09:08"


def test_screener_errors(client):
    assert client.post("/api/research/screener/run",
                       json={"text": "", "market": "IN", "universe": "NIFTY 50"}).status_code == 400
    assert client.post("/api/research/screener/run",
                       json={"text": "RSI(14) below 30", "market": "IN",
                             "universe": "S&P 500"}).status_code == 400
    assert client.post("/api/research/screener/schedule",
                       json={"name": " ", "run_time": "09:08", "text": "x",
                             "universe": "NIFTY 50"}).status_code == 400
    assert client.post("/api/research/screener/watchlist",
                       json={"name": "x", "symbols": [], "reasons": {},
                             "review_by": "2030-01-01"}).status_code == 400


# ---------------------------------------------------------------- Score-Tester
def test_scoretest_flow(client):
    s = client.get("/api/research/score-tester/setup?market=US").json()
    assert s["preset"] == "US-equity" and s["horizons"]["3 months"] == 91
    csv = client.get("/api/research/score-tester/sample?market=IN").json()["csv"]
    cols = client.post("/api/research/score-tester/columns", json={"csv": csv}).json()
    assert cols["guess"] == {"Date": "date", "Symbol": "symbol", "Score": "score",
                             "Published at": "published_at"}
    assert cols["rows"] > 100 and len(cols["preview"]) == 5
    rep = client.post("/api/research/score-tester/run",
                      json={"csv": csv, "mapping": cols["guess"], "market": "IN"}).json()
    assert len(rep["buckets"]) == 5 and rep["buckets"][0]["label"] == "1–2"
    assert rep["n_dates"] > 0 and any("unmatched" in w for w in rep["warnings"])
    assert any(f.startswith("Top-minus-bottom spread") for f in rep["facts"])
    no_pub = {**cols["guess"], "Published at": None}
    rep2 = client.post("/api/research/score-tester/run",
                       json={"csv": csv, "mapping": no_pub, "market": "IN", "horizon": "1 month",
                             "include_delisted": False, "cost_preset": "IN-equity-intraday"}).json()
    assert rep2["assumed_next_day"] and any("next-day" in w for w in rep2["warnings"])
    assert rep2["cost_preset"] == "IN-equity-intraday" and not rep2["include_delisted"]


def test_scoretest_errors(client):
    assert client.post("/api/research/score-tester/columns", json={"csv": ""}).status_code == 400
    csv = "date,symbol,score\n2024-01-31,SYN-IN-001,5\n"
    m = {"Date": "date", "Symbol": "symbol", "Score": None}
    r = client.post("/api/research/score-tester/run", json={"csv": csv, "mapping": m})
    assert r.status_code == 400 and "Score" in r.json()["detail"]
    r = client.post("/api/research/score-tester/run",
                    json={"csv": csv, "mapping": {**m, "Score": "nope"}})
    assert r.status_code == 400
    r = client.post("/api/research/score-tester/run",
                    json={"csv": csv, "mapping": {**m, "Score": "score"}, "horizon": "2 weeks"})
    assert r.status_code == 400
