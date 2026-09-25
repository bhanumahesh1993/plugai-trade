"""Journal and Tax API routes, driven like the book's walkthroughs (offline, no model)."""

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plugai_trade import ai, journal
from plugai_trade.api import app
from plugai_trade.api.routes import journal as jr
from plugai_trade.journal import review

c = TestClient(app)
JFIX = Path(__file__).parent / "fixtures" / "journal"
TFIX = Path(__file__).parent / "fixtures" / "tax"


def b64(p: Path | bytes) -> str:
    return base64.b64encode(p if isinstance(p, bytes) else p.read_bytes()).decode()


@pytest.fixture(autouse=True)
def fresh(monkeypatch, lab_home):
    def offline(*a, **k):
        raise ConnectionError("offline test")
    monkeypatch.setattr(ai, "_ollama_chat", offline)
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)
    seen = {}
    real = ai.complete

    def spy(prompt, section="Research", *a, sensitive=False, **k):
        seen.setdefault("sensitive", []).append(sensitive)
        return real(prompt, section, *a, sensitive=sensitive, **k)
    monkeypatch.setattr(ai, "complete", spy)
    jr.reset_state()
    yield seen
    jr.reset_state()


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ Trades
def test_meta_template_and_columns():
    m = ok(c.get("/api/journal/meta?market=IN"))
    assert m["brokers"] == ["Zerodha", "Upstox", "Groww", "Dhan", "Angel One", "Generic CSV"]
    assert set(m["tags"]) == {"REAL", "PAPER", "REPLAY", "PILOT", "BLOCKED"} and m["kind"] == "empty"
    assert ok(c.get("/api/journal/meta?market=US"))["brokers"][:4] == ["IBKR", "Schwab",
                                                                     "Robinhood", "Webull"]
    assert ok(c.get("/api/journal/template"))["csv"].startswith("time,symbol,side")
    cols = ok(c.post("/api/journal/columns", json={"file_b64": b64(JFIX / "generic_custom.csv")}))
    assert cols["columns"] and set(cols["guess"]) >= {"time", "symbol", "side", "qty", "price"}
    assert c.get("/api/journal/meta?market=XX").status_code == 400


def test_import_match_accept_tags_and_replay():
    p = ok(c.post("/api/journal/import", json={"market": "IN", "broker": "Zerodha",
                                               "file_b64": b64(JFIX / "zerodha_tradebook.csv"),
                                               "paper": True}))["pending"]
    assert p["round_trips"] == 3 and p["broker"] == "Zerodha"
    assert all("PAPER" in r["tags"] for r in p["rows"])
    assert ok(c.get("/api/journal/pending?market=IN"))["pending"]["fills"] == p["fills"]
    p = ok(c.post("/api/journal/pending/match?market=IN"))["pending"]
    tid = p["rows"][0]["trade_id"]
    edits = [{"trade_id": tid, "stop_distance": 20, "setup": "Pullback", "tags": ["PAPER", "late"]}]
    p = ok(c.post("/api/journal/pending/preview", json={"market": "IN", "edits": edits}))["pending"]
    assert p["rows"][0]["stop_distance"] == 20 and p["rows"][0]["r_multiple"] is not None
    assert ok(c.post("/api/journal/pending/accept", json={"market": "IN", "edits": edits}))["saved"] == 3
    assert ok(c.get("/api/journal/pending?market=IN"))["pending"] is None

    t = ok(c.get("/api/journal/trades?market=IN"))
    assert t["kind"] == "journal" and t["round_trips"] == 3 and t["histogram"]
    assert ok(c.get("/api/journal/trades?market=IN&show_simulated=false"))["round_trips"] == 0
    assert ok(c.get("/api/journal/trades?market=IN&tag=PAPER"))["round_trips"] == 3
    row = t["rows"][0]
    ok(c.post("/api/journal/tags", json={"market": "IN", "edits": [
        {"trade_id": row["trade_id"], "tags": ["PAPER", "FOMO"], "setup": "Breakout"}]}))
    assert "FOMO" in journal.trades().filter(journal.trades()["trade_id"] == row["trade_id"])["tags"][0]
    assert ok(c.post("/api/journal/tags/add", json={"market": "IN", "rows": [row["trade_id"]],
                                                    "tag": "moved stop"}))["tagged"] == 1

    rep = ok(c.post("/api/journal/replay", json={"market": "IN", "day": t["sessions"][0]}))["replay"]
    assert rep["handoff"]["tag"] == "REPLAY" and rep["handoff"]["speed"] == 5
    assert ok(c.get("/api/journal/replay/handoff?market=IN"))["handoff"]["day"] == rep["day"]
    assert ok(c.get("/api/journal/replay?market=IN"))["replay"]["day"] == rep["day"]
    assert ok(c.post("/api/journal/replay/note", json={"market": "IN", "day": rep["day"],
                                                       "note": "Wait 30 min after a loss."}))["id"]
    assert c.post("/api/journal/replay", json={"market": "IN", "day": "1999-01-01"}).status_code == 400


def test_generic_mapper_discard_and_errors():
    cols = ok(c.post("/api/journal/columns", json={"file_b64": b64(JFIX / "generic_custom.csv")}))
    assert cols["columns"] == ["when", "ticker", "direction", "units", "fill", "commission", "mkt"]
    mapping = {"time": "When", "symbol": "Ticker", "side": "Direction", "qty": "Units",
               "price": "Fill", "fees": "Commission", "market": "Mkt"}
    p = ok(c.post("/api/journal/import", json={"market": "US", "broker": "Generic CSV",
                                               "file_b64": b64(JFIX / "generic_custom.csv"),
                                               "mapping": mapping}))["pending"]
    assert [r["qty"] for r in p["rows"]] == [4.0, 6.0] and p["unpaired"] == 1
    r = c.post("/api/journal/import", json={"market": "US", "broker": "Generic CSV",
                                           "file_b64": b64(JFIX / "generic_custom.csv"),
                                           "mapping": {}})
    assert r.status_code == 400 and "Map these columns" in r.json()["detail"]
    assert ok(c.post("/api/journal/pending/discard?market=US"))["pending"] is None
    assert c.post("/api/journal/pending/match?market=US").status_code == 400
    assert c.post("/api/journal/pending/accept", json={"market": "US"}).status_code == 400
    assert c.post("/api/journal/import", json={"market": "IN", "broker": "Zerodha",
                                               "file_b64": ""}).status_code == 400


def test_sample_is_read_only_and_explain_is_local(fresh):
    assert ok(c.post("/api/journal/sample?market=IN"))["kind"] == "sample"
    t = ok(c.get("/api/journal/trades?market=IN"))
    assert t["kind"] == "sample" and not t["saved"] and t["round_trips"] == 54
    assert c.post("/api/journal/tags", json={"market": "IN", "edits": []}).status_code == 400
    e = ok(c.post("/api/journal/explain", json={"facts": t["facts"][:3], "section": "Journal"}))
    e2 = ok(c.post("/api/journal/explain", json={"facts": t["facts"][:3], "second_of": e["text"]}))
    assert e["where"] in ("Local", "Fallback") and e2["text"]
    assert fresh["sensitive"] and all(fresh["sensitive"])


# ------------------------------------------------------------------ Weekly Review
def test_weekly_review_flow():
    assert ok(c.get("/api/journal/weekly?market=IN"))["kind"] == "empty"
    ok(c.post("/api/journal/sample?market=IN"))
    w = ok(c.get("/api/journal/weekly?market=IN"))
    assert [t["label"] for t in w["tiles"]] == ["TRADES", "RESULT", "CHARGES", "NET",
                                                "ADHERENCE", "BREAKS COST"]
    assert w["start"] == "2026-09-07" and w["tiles"][0]["value"] == "14"
    assert any(b["n"] for b in w["rule_breaks"]) and w["bars"]
    assert "SELECT" in w["queries"]["q1"]
    assert any("too few to conclude" in p["n_label"] for p in w["patterns"] if p["n"])
    assert ok(c.get("/api/journal/weekly?market=IN&account=Real"))["tiles"][0]["value"] == "14"
    assert ok(c.get("/api/journal/weekly?market=IN&account=Paper"))["tiles"][0]["value"] == "0"
    assert c.get("/api/journal/weekly?market=IN&week_of=nope").status_code == 400
    g = ok(c.post("/api/journal/weekly/generate", json={"market": "IN"}))
    assert g["text"] and g["sources"]
    a = ok(c.post("/api/journal/weekly/accept", json={"market": "IN", "change": "No trade after two losses"}))
    assert a["change"] == "No trade after two losses"
    assert c.post("/api/journal/weekly/accept", json={"market": "IN", "change": " "}).status_code == 400
    s = ok(c.post("/api/journal/weekly/save", json={"market": "IN", "narration": g["text"],
                                                    "decision": a["change"]}))
    assert s["id"]
    assert review.last_decision() == "No trade after two losses"
    assert ok(c.get("/api/journal/weekly?market=IN"))["last_decision"] == a["change"]


# ------------------------------------------------------------------ Ask My Journal
def test_ask_follow_up_show_query_pin_and_clear():
    assert c.post("/api/journal/ask", json={"market": "IN", "question": "x"}).status_code == 400
    ok(c.post("/api/journal/sample?market=IN"))
    h = ok(c.post("/api/journal/ask", json={"market": "IN", "question":
                                            "How did I do on trades I opened soon after a loss?"}))
    a = h["history"][0]
    assert a["via"] != "none" and "gap_minutes <= 30" in a["sql"] and a["rows"] and a["facts"]
    h = ok(c.post("/api/journal/ask", json={"market": "IN",
                                            "question": "Which of those broke a Rule Card line?"}))
    assert len(h["history"]) == 2 and h["history"][1]["via"] in ("follow-up", "pattern")
    assert ok(c.post("/api/journal/ask/pin", json={"market": "IN", "index": 0}))["id"]
    assert len(review.pinned_specs()) == 1
    assert ok(c.get("/api/journal/weekly?market=IN"))["pinned"]
    assert c.post("/api/journal/ask/pin", json={"market": "IN", "index": 9}).status_code == 400
    assert len(ok(c.get("/api/journal/ask?market=IN"))["history"]) == 2
    assert ok(c.post("/api/journal/ask/clear?market=IN"))["history"] == []


# ------------------------------------------------------------------ Tax Export: India
def test_tax_india_book_numbers():
    s = ok(c.get("/api/tax/state?market=IN"))
    assert s["draft"] == "Draft for your CA / CPA" and s["samples"] == ["Meera", "Farhan"]
    assert c.get("/api/tax/in/turnover?market=IN").status_code == 400      # Classify first
    s = ok(c.post("/api/tax/sample", json={"market": "IN", "name": "Meera"}))
    assert s["rows"] == 10
    cl = ok(c.post("/api/tax/in/classify?market=IN"))
    counts = {x["bucket"]: x["n"] for x in cl["counts"]}
    assert counts["NON_SPECULATIVE"] == 10 and len(cl["section_map"]) == 12
    assert ok(c.get("/api/tax/in/classify?market=IN"))["classified"]["fys"] == ["2025-26"]
    t = ok(c.get("/api/tax/in/turnover?market=IN&months=12"))
    assert t["fo"]["turnover"] == 39585.0 and t["fo"]["net"] == -1105.0
    assert t["per_contract_fo"] == 39585.0 and t["old_method_fo"] == 51675.0
    assert t["deemed_profit"] == 2375.1 and t["audit"]["status"] == "Below limit"
    assert t["suggested_losses"] == [{"fy": "2025-26", "bucket": "NON_SPECULATIVE", "amount": 1105.0}]
    lock = ok(c.get("/api/tax/in/turnover?market=IN&opted=2025-26"))
    assert "ASK CA" in lock["audit"]["lock_in"]
    assert c.get("/api/tax/in/turnover?market=IN&months=13").status_code == 400
    led = ok(c.post("/api/tax/in/ledger/add", json={"fy": "2025-26", "bucket": "SPECULATIVE",
                                                    "amount": 5000}))
    assert led["rows"][0]["expires_after_fy"] == "2029-30"
    assert c.post("/api/tax/in/ledger/add", json={"fy": "2025-26", "bucket": "X",
                                                  "amount": 1}).status_code == 400
    assert ok(c.post("/api/tax/in/ledger/from-classified?market=IN"))["added"] == 1
    adv = ok(c.get("/api/tax/in/advance?estimated=60000&fy=2026-27&paid=0"))
    assert [r["cumulative"] for r in adv["rows"]] == [9000, 27000, 45000, 60000] and adv["due"]
    ex = ok(c.post("/api/tax/in/export", json={"market": "IN", "fy": "all"}))
    assert ex["csv"].startswith("# DRAFT FOR YOUR CA / CPA")
    assert ok(c.post("/api/tax/in/export", json={"market": "IN", "fy": "2025-26"}))["csv"]


def test_tax_india_vda_ais_and_sources():
    ok(c.post("/api/tax/sample", json={"market": "IN", "name": "farhan"}))
    cl = ok(c.post("/api/tax/in/classify?market=IN"))
    assert (cl["vda"]["gains"], cl["vda"]["losses"], cl["vda"]["tds"]) == (62000, 20000, 3720)
    tds = ok(c.post("/api/tax/in/reconcile-tds", json={"file_b64": b64(TFIX / "form26as_vda.csv")}))
    assert tds["matched"] == 2 and len(tds["mismatches"]) == 1
    ais = ok(c.post("/api/tax/in/reconcile-ais", json={"ais_b64": b64(TFIX / "ais.csv")}))
    assert ais["matched"] == 1 and len(ais["mismatches"]) == 4
    both = ok(c.post("/api/tax/in/reconcile-ais", json={"ais_b64": b64(TFIX / "ais.csv"),
                                                        "broker_b64": b64(TFIX / "ais.csv")}))
    assert not both["mismatches"]
    assert c.post("/api/tax/sample", json={"market": "IN", "name": "dan"}).status_code == 400
    ok(c.post("/api/tax/import", json={"market": "IN", "broker": "Zerodha",
                                       "file_b64": b64(JFIX / "zerodha_tradebook.csv")}))
    assert ok(c.get("/api/tax/state?market=IN"))["rows"] == 6
    assert ok(c.post("/api/tax/use-journal?market=IN"))["rows"] == 0
    assert ok(c.post("/api/tax/clear?market=IN"))["rows"] == 0


# ------------------------------------------------------------------ Tax Export: US
def test_tax_us_wash_1256_1099b_and_export():
    assert c.post("/api/tax/us/wash", json={"market": "US"}).status_code == 400
    assert ok(c.get("/api/tax/us/8949?market=US"))["form"] is None
    ok(c.post("/api/tax/sample", json={"market": "US", "name": "dan"}))
    assert ok(c.post("/api/tax/us/account", json={"name": "Taxable", "kind": "Taxable"}))["accounts"]
    assert c.post("/api/tax/us/account", json={"name": "x", "kind": "Roth"}).status_code == 400
    tags = {r["instrument"]: r for r in ok(c.get("/api/tax/us/1256?market=US"))["rows"]}
    assert tags["SPX"]["sec_1256"] is True and tags["SPY"]["sec_1256"] is False
    w = ok(c.post("/api/tax/us/wash", json={"market": "US", "crypto": False, "pairs": "SPY/VOO"}))
    assert len(w["hits"]) == 1 and w["hits"][0]["disallowed"] == 800 and not w["crypto_checked"]
    assert w["form"]["rows"] and w["form"]["form_6781"]
    assert ok(c.get("/api/tax/us/8949?market=US"))["form"]["rows"]
    rec = ok(c.post("/api/tax/us/compare-1099b", json={"market": "US",
                                                       "file_b64": b64(TFIX / "form_1099b.csv")}))
    assert "matched" in rec
    ex = ok(c.post("/api/tax/us/export?market=US"))
    assert ",W,800.00," in ex["csv"] and ex["csv"].startswith("# DRAFT FOR YOUR CA / CPA")
