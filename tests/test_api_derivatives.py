"""API routes for Derivatives: Options Strategy Builder, Futures & Roll, Contract Table.

Asserts reproduce the book's printed numbers (Chapters 22, 23, 24).
"""

from fastapi.testclient import TestClient

from plugai_trade.api import app

c = TestClient(app)

CALL = {"symbol": "NIFTY", "market": "IN",
        "legs": [{"kind": "call", "strike": 25000, "side": "buy", "expiry": "weekly"}]}


# ------------------------------------------------------------------ options
def test_underlying_and_presets():
    u = c.get("/api/options/underlying?symbol=NIFTY&market=IN").json()
    assert u["spot"] == 24800 and u["strike"] == 25000 and u["step"] == 20 and u["lot"] == 65
    assert len(u["presets"]) == 5
    assert c.get("/api/options/underlying?symbol=SPY&market=US").json()["strike"] == 565
    assert c.get("/api/options/underlying?symbol=SPX&market=US").json()["strike"] == 5650
    ic = c.post("/api/options/preset", json={"name": "Iron condor", "symbol": "NIFTY",
                                             "market": "IN"}).json()
    assert [lg["strike"] for lg in ic["legs"]] == [24100, 24300, 25400, 25600]
    cc = c.post("/api/options/preset", json={"name": "Covered call", "symbol": "SPY",
                                             "market": "US"}).json()
    assert cc["legs"][0]["kind"] == "stock" and cc["legs"][1]["strike"] == 585
    assert c.post("/api/options/preset", json={"name": "Nope"}).status_code == 400


def test_quote_book_numbers_ch22():
    q = c.post("/api/options/quote", json=CALL).json()
    assert q["single"] and q["tiles"] == {"Breakeven": "25,089", "Max loss": "₹5,785",
                                          "Required move": "+289 pts", "Expected ±1σ": "±406 pts",
                                          "Theta/day": "−₹1,057", "Delta": "0.33"}
    assert q["days_slider_max"] == 5 and q["legs"][0]["premium"] == 89
    one = c.post("/api/options/quote", json={**CALL, "days_left": 1}).json()
    assert one["tiles"]["Theta/day"] != q["tiles"]["Theta/day"]
    spy = c.post("/api/options/quote", json={"symbol": "SPY", "market": "US", "legs": [
        {"kind": "call", "strike": 565}]}).json()
    assert spy["tiles"]["Breakeven"] == "567.27" and spy["tiles"]["Max loss"] == "$227"
    assert c.post("/api/options/quote", json={**CALL, "legs": []}).status_code == 400
    assert c.post("/api/options/quote", json={**CALL, "legs": [{"kind": "swap", "strike": 1}]}).status_code == 400


def test_quote_income_and_margin_ch23():
    legs = c.post("/api/options/preset", json={"name": "Iron condor", "symbol": "NIFTY"}).json()["legs"]
    body = {"symbol": "NIFTY", "market": "IN", "legs": legs, "name": "Iron condor"}
    q = c.post("/api/options/quote", json=body).json()
    assert q["name"] == "Iron condor" and "2nd Breakeven" in q["tiles"] and "Margin estimate" in q["tiles"]
    assert q["margin"]["expiry_day"] > q["margin"]["estimate"]
    exp = c.post("/api/options/quote", json={**body, "days_left": 0}).json()
    assert "Margin estimate (expiry day)" in exp["tiles"]
    cc = c.post("/api/options/preset", json={"name": "Covered call", "symbol": "SPY", "market": "US"}).json()
    q2 = c.post("/api/options/quote", json={"symbol": "SPY", "market": "US", "legs": cc["legs"]}).json()
    assert q2["name"] == "Covered call" and q2["margin"]["model"].startswith("Reg-T")


def test_iv_panel():
    iv = c.get("/api/options/iv?symbol=NIFTY").json()
    assert (round(iv["iv"], 1), round(iv["rank"]), round(iv["percentile"])) == (14.0, 29, 61)
    assert len(iv["series"]) == 252 and iv["events"]
    assert c.get("/api/options/iv?symbol=SPX").status_code == 200
    assert c.get("/api/options/iv?symbol=NIFTY&window=5").status_code == 400


def test_scenarios_book_numbers():
    gap = c.post("/api/options/scenario", json={**CALL, "gap": -300, "days_left": 5}).json()
    assert gap["tiles"] == {"Value per unit": "₹15.5", "P&L per lot": "−₹4,778"}
    crush = c.post("/api/options/scenario", json={**CALL, "iv_change": -3, "days_left": 4}).json()
    assert round(crush["value"], 1) == 45.6 and round(crush["pnl"]) == -2821
    combo = c.post("/api/options/scenario", json={**CALL, "gap": 150, "iv_change": -2, "days_left": 2}).json()
    assert round(combo["value"], 1) == 69.5
    att = combo["attribution"]
    assert set(att["parts"]) == {"Theta", "Vega", "Gamma", "Delta", "Residual"}
    assert abs(sum(att["parts"].values()) - att["actual"]) < 0.05
    legs = c.post("/api/options/preset", json={"name": "Bull put spread", "symbol": "NIFTY"}).json()["legs"]
    multi = c.post("/api/options/scenario", json={"symbol": "NIFTY", "legs": legs, "gap": -500}).json()
    assert not multi["single"] and "Your scenario" in multi["tiles"]


def test_stress_table_with_own_row():
    legs = c.post("/api/options/preset", json={"name": "Iron condor", "symbol": "NIFTY"}).json()["legs"]
    s = c.post("/api/options/stress", json={"symbol": "NIFTY", "legs": legs,
                                            "extra": [{"label": "Crash", "gap_pct": -12, "iv_pts": 20}]}).json()
    assert len(s["rows"]) == 7 and s["rows"][0]["label"].startswith("Gap −3%")
    assert s["rows"][-1]["label"].startswith("Crash") and s["worst"] == s["rows"][-1]["pnl"]
    us = c.post("/api/options/stress", json={"symbol": "SPY", "market": "US", "legs": [
        {"kind": "put", "strike": 540, "side": "sell", "expiry": "monthly"}]}).json()
    assert len(us["rows"]) == 5
    bad = c.post("/api/options/stress", json={"symbol": "NIFTY", "legs": legs, "extra": [{"gap_pct": "x"}]})
    assert bad.status_code == 400


def test_save_to_plan_history_and_send_to_paper():
    body = {**CALL, "facts": ["Breakeven: 25,089"], "ai_explanation": "text", "exit_rule": "Exit Friday"}
    a = c.post("/api/options/plan", json=body).json()
    b = c.post("/api/options/plan", json=body).json()
    assert (a["version"], b["version"]) == (1, 2) and len(b["history"]) == 2
    assert c.get(f"/api/options/plans?name={a['name']}").json()["plans"][0]["version"] == 2
    p = c.post("/api/options/paper", json=CALL).json()
    assert p["status"] == "pending"
    pend = c.get("/api/paper/state?market=IN").json()["pending"]
    assert any(o.get("source") == "Options Strategy Builder" for o in pend)


# ------------------------------------------------------------------ futures & roll
def test_choices_and_contract_tab():
    ch = c.get("/api/derivatives/choices?market=US").json()
    assert ch["default"] == "MES" and "MCL" in ch["contracts"]
    assert c.get("/api/derivatives/choices?market=XX").status_code == 400
    r = c.post("/api/derivatives/contracts", json={"market": "IN", "symbols": ["NIFTY", "CRUDEOIL"]}).json()
    assert r["rows"][0]["multiplier"] == 65 and r["mcx"] == ["CRUDEOIL"]
    assert r["rows"][1]["settlement"] and len(r["oi"]) == 2
    assert r["oi"][0]["label"] in ("Long build-up", "Short covering", "Short build-up",
                                   "Long unwinding", "No clear label")
    assert c.post("/api/derivatives/contracts", json={"symbols": ["NOPE"]}).status_code == 400


def test_usdinr_split():
    s = c.post("/api/derivatives/usdinr-split", json={"symbol": "CRUDEOIL"}).json()
    assert s["tiles"]["Currency part / lot"] == "₹5,600" and s["benchmark_part"] == 0
    assert c.post("/api/derivatives/usdinr-split", json={"symbol": "NIFTY"}).status_code == 400


def test_basis_tab():
    b = c.post("/api/derivatives/basis", json={"symbol": "NIFTY", "market": "IN"}).json()
    assert len(b["fair"]) == 3 and b["label"] in ("near fair value", "premium to fair value",
                                                  "discount to fair value")
    assert b["series"][-1]["basis"] == 0
    assert c.post("/api/derivatives/basis", json={"symbol": "SPY", "market": "US", "rate_pct": 4}).status_code == 200


def test_roll_tab_and_actions():
    r = c.post("/api/derivatives/roll", json={"symbol": "NIFTY", "market": "IN", "before": 5}).json()
    assert len(r["calendar"]) == 3 and r["costs"]["total"] > 0 and r["series"]
    slip = c.post("/api/derivatives/roll", json={"symbol": "NIFTY", "market": "IN", "slippage": 1}).json()
    assert slip["costs"]["slippage"] == 130
    us = c.post("/api/derivatives/roll", json={"symbol": "MES", "market": "US"}).json()
    assert all(date[5:7] in ("03", "06", "09", "12") for date in (x["expiry"] for x in us["calendar"]))
    assert c.post("/api/derivatives/roll", json={"symbol": "NIFTY", "before": 20}).status_code == 400
    a = c.post("/api/derivatives/roll/alert", json={"symbol": "NIFTY", "before": 5}).json()
    assert a["id"] and a["date"]
    t = c.post("/api/derivatives/roll/trend-lab", json={"symbol": "NIFTY", "before": 5}).json()
    assert t["rows"] > 0 and t["roll_dates"]


def test_margin_mtm_book_numbers_ch24():
    d = c.get("/api/derivatives/margin/defaults?symbol=NIFTY&market=IN").json()
    assert (d["entry"], d["cash"], d["has_book"]) == (25000, 240000, True)
    body = {"symbol": "NIFTY", "market": "IN", "entry": 25000, "cash": 240000, "margin_pct": 12}
    p = c.post("/api/derivatives/margin", json=body).json()
    assert p["position_tiles"] == {"Notional": "₹16,25,000", "Margin (illustrative)": "₹1,95,000",
                                   "Leverage": "8.3×", "One point": "₹65"}
    r = c.post("/api/derivatives/margin", json={**body, "replay": True, "shock_pct": -3}).json()
    assert r["day"] == 4 and r["tiles"] == {"MTM today": "−₹14,300", "Free cash": "₹19,832",
                                            "Move to margin call": "≈ −347 pts"}
    assert r["shock"]["label"] == "−3.0% gap: short" and r["shock"]["value"] == "₹22,313"
    assert r["shock"]["tiles"]["MTM hit"] == "−₹47,892"
    us = c.get("/api/derivatives/margin/defaults?symbol=MES&market=US").json()
    ur = c.post("/api/derivatives/margin", json={"symbol": "MES", "market": "US", "entry": us["entry"],
                                                 "cash": us["cash"], "initial": us["initial"],
                                                 "maintenance": us["maintenance"], "replay": True,
                                                 "day": 5}).json()
    assert ur["rows"][-1]["mtm"] == -125 and ur["rows"][-1]["status"].startswith("call")
    syn = c.post("/api/derivatives/margin", json={**body, "replay": True, "path": "synthetic"}).json()
    assert syn["path"] == "synthetic" and syn["day"] == 10
    assert c.post("/api/derivatives/margin", json={"symbol": "MES", "market": "US", "entry": 1,
                                                   "cash": 1}).status_code == 400
    s = c.post("/api/derivatives/plan", json={"symbol": "NIFTY", "entry": 25000,
                                              "call_price": 24213.29}).json()
    assert s["version"] == 1


# ------------------------------------------------------------------ contract table
def test_contract_table():
    t = c.get("/api/derivatives/contract-table").json()
    assert t["as_of"] == "2026-09-24"
    usd = next(r for r in t["rows"] if r["Symbol"] == "USDINR")
    assert usd["Exposure required"] is True and usd["Asset"] == "Currency" and usd["Settlement"] == "cash"
    keys = [(r["Market"], r["Symbol"]) for r in t["rows"]]
    assert len(keys) == len(set(keys))          # pending book rows drop out once the table has them
    assert next(r for r in t["rows"] if r["Symbol"] == "CRUDEOIL")["Exchange"] == "MCX"
    assert {s["Market"] for s in t["sessions"]} == {"IN", "US"} and len(t["fees"]) == 6
