"""API: Portfolio Reviewer, Crypto Monitor, Forecast Journal (book numbers, every route)."""

import base64

import pytest
from fastapi.testclient import TestClient

from plugai_trade.api import app
from plugai_trade.api.routes import portfolio as routes

c = TestClient(app)
P = "/api/portfolio"


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@pytest.fixture(autouse=True)
def fresh():
    routes._reset()
    yield
    routes._reset()


def tile(tiles, label):
    return next(t for t in tiles if t["label"] == label)


# ------------------------------------------------------------------ holdings / import
def test_holdings_sample_import_and_match():
    h = c.get(f"{P}/holdings?market=IN").json()
    assert h["count"] == 8 and h["unmatched"] == 1 and h["total_text"] == "₹18,45,200"
    csv = "name,units,price,value,asset_class,account\nMystery fund,10,10,100,Equity,Demat\n"
    r = c.post(f"{P}/import", json={"market": "IN", "filename": "h.csv", "content_b64": b64(csv)}).json()
    assert r["imported"] == 1 and r["label"] == "Imported: h.csv" and r["unmatched"] == 1
    r = c.post(f"{P}/match", json={"market": "IN", "index": 0, "fund_id": "A"}).json()
    assert r["rows"][0]["matched_to"] == "A · Large-cap" and r["unmatched"] == 0
    assert c.post(f"{P}/match", json={"market": "IN", "index": 9, "fund_id": "A"}).status_code == 400
    r = c.post(f"{P}/sample", json={"market": "IN"}).json()
    assert r["count"] == 8


def test_import_errors_are_plain_english():
    bad = c.post(f"{P}/import", json={"market": "IN", "filename": "x.csv", "content_b64": b64("foo,bar\n1,2\n")})
    assert bad.status_code == 400 and "name/symbol column" in bad.json()["detail"]
    pdf = c.post(f"{P}/import", json={"market": "IN", "filename": "cas.pdf", "content_b64": b64("not a pdf")})
    assert pdf.status_code == 400


def test_import_cas_pdf_with_password(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(72, 72)
    w.encrypt("ABCDE1234F")
    f = tmp_path / "cas.pdf"
    with open(f, "wb") as fh:
        w.write(fh)
    data = base64.b64encode(f.read_bytes()).decode()
    wrong = c.post(f"{P}/import", json={"market": "IN", "filename": "cas.pdf", "content_b64": data, "password": "x"})
    assert wrong.status_code == 400 and "password" in wrong.json()["detail"].lower()
    empty = c.post(f"{P}/import", json={"market": "IN", "filename": "cas.pdf", "content_b64": data,
                                         "password": "ABCDE1234F"})
    assert empty.status_code == 400 and "No holdings found" in empty.json()["detail"]


# ------------------------------------------------------------------ overlap / costs / concentration
def test_overlap_book_matrix_and_fund_file():
    o = c.get(f"{P}/overlap?market=IN").json()
    cell = {(x["row"], x["col"]): x["overlap"] for x in o["cells"]}
    assert cell[("A", "E")] == 57 and cell[("A", "B")] == 40
    assert tile(o["tiles"], "Highest overlap")["value"] == "57%"
    assert o["csv"].startswith("Fund,")
    csv = "company,weight,sector\nSyn Co 001,50,IT\nOther,50,Energy\n"
    r = c.post(f"{P}/fund-file", json={"market": "IN", "name": "My fund", "content_b64": b64(csv)}).json()
    assert r["companies"] == 2 and any(f["name"] == "My fund" for f in r["funds"])
    bad = c.post(f"{P}/fund-file", json={"market": "IN", "name": "X", "content_b64": b64("a,b\n1,2\n")})
    assert bad.status_code == 400


def test_costs_book_numbers():
    r = c.post(f"{P}/costs", json={"market": "IN", "equity_only": True}).json()
    assert tile(r["tiles"], "Annual difference")["value"] == "₹10,680"
    assert tile(r["tiles"], "Weighted TER now")["value"] == "1.53%"
    assert tile(r["tiles"], "Weighted TER in direct plans")["value"] == "0.64%"
    full = c.post(f"{P}/costs", json={"market": "US"}).json()
    assert full["fee_gap"]["cheaper"] > full["fee_gap"]["dearer"]


def test_concentration_look_through():
    r = c.get(f"{P}/concentration?market=IN").json()
    assert tile(r["tiles"], "Largest single company")["value"] == "8.7%"
    assert tile(r["tiles"], "Top 10 companies")["value"] == "36.3%"
    assert len(r["top"]) == 10 and r["sectors"]


# ------------------------------------------------------------------ allocation
def test_allocation_target_band_and_lots():
    r = c.post(f"{P}/allocation", json={"market": "IN", "monthly": 20000}).json()
    assert r["target"] == {"Equity": 60.0, "Debt": 30.0, "Gold": 10.0} and len(r["checklist"]) == 6
    eq = next(x for x in r["rows"] if x["Sleeve"] == "Equity")
    assert eq["Status"] == "OUTSIDE BAND" and eq["Months of new money"] is not None
    bad = c.post(f"{P}/allocation/target", json={"market": "IN", "target": {"Equity": 50, "Debt": 30, "Gold": 10},
                                                 "band": 5}).json()
    assert bad["warning"].startswith("Target adds up to 90.0%")
    ok = c.post(f"{P}/allocation/target", json={"market": "IN", "target": {"Equity": 70, "Debt": 20, "Gold": 10},
                                                "band": 5}).json()
    assert ok["warning"] is None
    lots = c.post(f"{P}/sale-lots", json={"lots": [{"bought": "2024-04-01", "units": 100, "cost": 50}],
                                          "units": 50, "price": 60}).json()
    assert lots[0]["Gain"] == 500.0 and "Draft for your CA" in lots[0]["Note"]


# ------------------------------------------------------------------ ETF / income / SIP
def test_etf_cost_of_gap_book_number():
    r = c.post(f"{P}/etf", json={"market": "IN"}).json()
    assert r["gap"]["gap_text"] == "₹40,747" and r["premium"]["flagged"]
    assert [t["label"] for t in r["funds"][0]["tiles"]] == ["Expense", "Tracking difference",
                                                           "Tracking error", "Trading cost"]
    add = c.post(f"{P}/etf/add", json={"market": "IN", "name": "MYETF"}).json()
    assert "stand-in" in add["added"]
    assert c.post(f"{P}/etf/save", json={"market": "IN"}).json()["id"] > 0
    assert c.post(f"{P}/etf/add", json={"market": "IN", "name": " "}).status_code == 400


def test_income_tax_profiles():
    r = c.post(f"{P}/income", json={"market": "IN", "slab_pct": 30, "cess_pct": 4}).json()
    assert any(x["flag"] for x in r["rows"]) and len(r["trap"]) == 37
    assert tile(r["tiles"], "After-tax income")["value"] == "₹11,834"
    us = c.post(f"{P}/income", json={"market": "US", "holding_period": True, "niit": True}).json()
    assert "Treated as" in us["rows"][0] and "NIIT" in us["profile"]
    assert c.post(f"{P}/income", json={"market": "US", "qualified_rate": 0.33}).status_code == 400


def test_sip_book_numbers_and_save():
    r = c.post(f"{P}/sip", json={"market": "IN", "monthly": 10000, "years": 20,
                                 "returns_pct": [6, 8, 10, 12]}).json()
    lakh = [round(v / 1e5, 1) for v in r["values"].values()]
    assert lakh == [45.6, 57.3, 72.4, 92.0]
    assert len(r["series"][0]["values"]) == 240 and r["invested"][-1] == 2_400_000
    g = c.post(f"{P}/sip", json={"market": "IN", "goal": 5_000_000, "inflation_pct": 6,
                                 "step_up_pct": 10, "pause_from": 13, "pause_months": 6}).json()
    assert "Monthly needed for goal" in g["table"][0] and "Value in today's money" in g["table"][0]
    assert c.post(f"{P}/sip/save", json={"market": "IN", "start": "2026-10-01"}).json()["id"] > 0
    assert c.post(f"{P}/sip", json={"returns_pct": [99]}).status_code == 400


# ------------------------------------------------------------------ thesis
def test_thesis_tracker_flow():
    t = c.get(f"{P}/theses").json()
    first = t["theses"][0]
    assert first["tripped"] == 1 and first["check"][3]["review"]
    new = c.post(f"{P}/theses", json={"holding": "Gold ETF", "why": "Hedge",
                                      "conditions": [{"metric": "tracking_error", "op": "<", "threshold": 1}]}).json()
    tid = new["id"]
    r = c.post(f"{P}/theses/{tid}/figure", json={"quarter": "2026-Q3", "metric": "tracking_error",
                                                 "value": 2, "source": "p. 1"}).json()
    assert r["tripped"] == 1
    assert c.post(f"{P}/theses/{tid}/figure", json={"quarter": "q", "metric": "nope", "value": 1}).status_code == 400
    assert c.post(f"{P}/theses/{tid}/note", json={"text": "Hold; look again next quarter"}).json()["id"] > 0
    assert c.post(f"{P}/theses", json={"holding": "X", "why": "", "conditions": []}).status_code == 400


def test_explain_is_local_and_cites():
    r = c.post(f"{P}/explain", json={"facts": ["Top 10 companies: 36.3%"]}).json()
    assert r["sources"] == ["Top 10 companies: 36.3%"] and r["where"] in ("Local", "Fallback")


# ------------------------------------------------------------------ crypto
def test_crypto_watch_positions_funding_alerts():
    w = c.get(f"{P}/crypto/watch?market=IN").json()
    assert {r["Symbol"] for r in w["rows"]} == {"BTC", "ETH"} and w["rows"][0]["Basis"] is not None
    f = c.post(f"{P}/crypto/funding", json={"market": "IN"}).json()
    assert f["print_no"] == 40
    assert tile(f["tiles"], "Funding/8h")["value"] == "0.0656%"
    assert tile(f["tiles"], "Annualised")["value"] == "≈ 71.8%"
    assert tile(f["tiles"], "To liquidation")["value"] == "−9.5%"
    liq = {r["Leverage"]: r["Fall to liquidation %"] for r in f["liquidation"]}
    assert liq["10×"] == 9.5 and liq["2×"] == 49.5
    f4 = c.post(f"{P}/crypto/funding", json={"market": "IN", "times_per_day": 6, "print_no": 1}).json()
    assert f4["print_no"] == 1 and f4["times_per_day"] == 6
    w2 = c.post(f"{P}/crypto/positions", json={"market": "US", "symbol": "ETH", "notional": 5000,
                                                "leverage": 5, "entry": 3000, "venue": "kraken"}).json()
    assert len(w2["positions"]) == 2
    assert c.post(f"{P}/crypto/positions", json={"market": "US", "venue": "moon"}).status_code == 400
    sent = c.post(f"{P}/crypto/send-alerts", json={"market": "IN", "level_pct": 0.03}).json()
    assert sent["count"] == 4
    part = c.post(f"{P}/crypto/send-alerts", json={"market": "IN", "kinds": ["Funding"]}).json()
    assert part["count"] == 1
    al = c.get(f"{P}/crypto/alerts").json()
    assert len(al["rows"]) == 5 and all(r["status"] == "proposed" for r in al["rows"])
    assert c.post(f"{P}/crypto/fiu-notes", json={"text": "CoinDCX listed, checked today"}).json()[0]["text"]
    assert c.get(f"{P}/crypto/fiu-notes").json()


def test_vda_ledger_import_and_reconcile():
    r = c.post(f"{P}/crypto/ledger", json={"cess_pct": 4}).json()
    assert tile(r["tiles"], "Taxable VDA income")["value"] == "₹62,000"
    assert tile(r["tiles"], "Losses (recorded, not set off)")["value"] == "−₹20,000"
    rec = c.post(f"{P}/crypto/ledger/reconcile", json={}).json()
    assert rec["self_check"] and rec["mismatches"] == 0
    stmt = b64("date,TDS\n2026-05-01,2000\n2026-06-01,500\n")
    rec2 = c.post(f"{P}/crypto/ledger/reconcile", json={"statement_b64": stmt}).json()
    assert rec2["mismatches"] >= 2
    csv = "trade,asset,bought,sold,tds\n1,BTC,100,150,1.5\n"
    assert c.post(f"{P}/crypto/ledger/import", json={"content_b64": b64(csv)}).json()["imported"] == 1
    assert c.post(f"{P}/crypto/ledger/import", json={"content_b64": b64("x,y\n1,2\n")}).status_code == 400


# ------------------------------------------------------------------ forecasts
def test_forecast_journal_us_flow_and_in_disabled():
    s = c.get(f"{P}/forecasts?market=US").json()
    assert s["sample"]["n"] == 160 and round(s["sample"]["brier"], 3) == 0.215 and s["sample"]["ready"]
    assert c.post(f"{P}/forecasts/break-even", json={"price_cents": 62, "fee_cents": 1}).json()["break_even"] == 0.63
    rules = c.post(f"{P}/forecasts/rules", json={
        "rules": "Resolves YES if CPI exceeds 3% according to BLS. Published 8:30 AM ET. If delayed, resolves NO."
    }).json()
    assert rules["Source"] and rules["Time"] and rules["Edge cases"]
    assert c.post(f"{P}/forecasts/rules-ai", json={"rules": "x"}).json()["text"]
    fid = c.post(f"{P}/forecasts", json={"market": "US", "question": "CPI above 3%?", "prob_pct": 70,
                                         "reason": "sticky services"}).json()["id"]
    assert c.post(f"{P}/forecasts/{fid}/price", json={"market": "US", "price_cents": 62, "fee_cents": 1}).json()["id"] == fid
    r = c.post(f"{P}/forecasts/{fid}/resolve", json={"market": "US", "outcome": 1}).json()
    assert r["score"]["n"] == 1 and abs(r["score"]["brier"] - 0.09) < 1e-9
    blocked = c.post(f"{P}/forecasts", json={"market": "IN", "question": "q", "prob_pct": 50})
    assert blocked.status_code == 400 and "Disabled for IN" in blocked.json()["detail"]
    assert c.get(f"{P}/forecasts?market=IN").json()["disabled"]
