"""Portfolio Reviewer: overlap, look-through, costs, allocation, import, ETF, income, thesis."""

from datetime import date
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade.portfolio import allocation, etf, funds, holdings, income, money, thesis

BOOK_MATRIX = {("A", "B"): 40, ("A", "C"): 24, ("A", "D"): 45, ("A", "E"): 57, ("B", "C"): 32,
               ("B", "D"): 34, ("B", "E"): 49, ("C", "D"): 22, ("C", "E"): 27, ("D", "E"): 52}


def _priya():
    return {f.fund_id: f for f in funds.sample_funds_in()[:5]}


def test_overlap_matrix_matches_book():
    fs = _priya()
    for (a, b), want in BOOK_MATRIX.items():
        assert round(funds.overlap(fs[a].holdings, fs[b].holdings)) == want
    assert all(abs(sum(f.holdings.values()) - 100) < 1e-9 for f in fs.values())


def test_overlap_definition():
    assert funds.overlap({"X": 8, "Y": 2}, {"X": 5, "Z": 95}) == 5
    assert funds.overlap({"X": 100}, {"X": 100}) == 100
    assert funds.overlap({"X": 100}, {"Y": 100}) == 0


def test_look_through_concentration():
    pos = [(f, funds.PRIYA_FUNDS[f.fund_id][3]) for f in _priya().values()]
    lt = funds.look_through(pos)
    assert lt.companies == 138
    assert round(lt.top(1)[0][1] * 100, 1) == 8.7
    assert round(lt.top10_share * 100, 1) == 36.3


def test_cost_audit_direct_vs_regular():
    pos = [(f, funds.PRIYA_FUNDS[f.fund_id][3], "Regular") for f in _priya().values()]
    audit = funds.cost_audit(pos)
    assert round(audit.weighted_ter, 2) == 1.53 and round(audit.weighted_direct_ter, 2) == 0.64
    assert round(audit.annual) == 18_360 and round(audit.direct_annual) == 7_680
    assert round(audit.annual - audit.direct_annual) == 10_680


def test_fee_gap_book_table():
    a, b = funds.fee_gap(1_000_000, 15, 0.10, 0.006, 0.016)
    assert (round(a / 1e5, 2), round(b / 1e5, 2)) == (38.48, 33.53)
    a, b = funds.fee_gap(50_000, 25, 0.08, 0.0005, 0.0075)
    assert (round(a), round(b)) == (338_482, 287_675)


def test_drift_and_rebalance_book():
    alloc = allocation.drift({"Equity": 870_000, "Debt": 342_000, "Gold": 110_000},
                             {"Equity": 0.6, "Debt": 0.3, "Gold": 0.1}, 0.05, 20_000)
    rows = {r["Sleeve"]: r for r in alloc.rows()}
    assert rows["Equity"]["Now %"] == 65.8 and rows["Equity"]["Status"] == "OUTSIDE BAND"
    assert [rows[s]["To target"] for s in ("Equity", "Debt", "Gold")] == [-76_800, 54_600, 22_200]
    assert rows["Debt"]["Months of new money"] == pytest.approx(2.7, abs=0.05)
    us = allocation.drift({"US": 43_500, "Intl": 11_200, "Bonds": 10_600},
                          {"US": 0.6, "Intl": 0.2, "Bonds": 0.2}, currency="$")
    assert [round(s.to_target) for s in us.sleeves] == [-4_320, 1_860, 2_460]


def test_target_must_sum_to_100():
    with pytest.raises(ValueError):
        allocation.drift({"A": 1.0}, {"A": 0.5})


def test_sale_lots_fifo():
    lots = [allocation.Lot(date(2024, 1, 1), 100, 50), allocation.Lot(date(2026, 1, 1), 100, 55)]
    rows = allocation.sale_lots(lots, 150, 60, today=date(2026, 6, 1))
    assert [r["Type"] for r in rows] == ["LTCG", "STCG"]
    assert rows[0]["Gain"] == 1000 and rows[1]["Units"] == 50


CAS_TEXT = """Consolidated Account Statement
B92Z-Axis Bluechip Fund - Regular Plan - Growth (Advisor: ARN-1234) Registrar : CAMS
Folio No: 91234 / 0
Closing Unit Balance: 1,234.567 NAV on 29-May-2026: INR 56.7890 Total Cost Value: 50,000.00 Market Value on 29-May-2026: INR 70,108.42
P123-Some Flexi Cap Fund - Direct Plan - Growth ISIN: INF879O01027 Registrar : KFINTECH
Closing Unit Balance: 100.000 NAV on 29-May-2026: INR 80.00
"""


def test_parse_cas_text():
    rows = holdings.parse_cas_text(CAS_TEXT)
    assert len(rows) == 2
    assert rows[0].units == 1234.567 and rows[0].value == 70108.42 and rows[0].plan == "Regular"
    assert rows[1].plan == "Direct" and rows[1].value == 8000.0


def _encrypted_pdf(text_lines, password):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject(
        {NameObject("/F1"): w._add_object(font)})})
    ops = "BT /F1 8 Tf 20 760 Td 10 TL " + " ".join(
        f"({ln.replace('(', '[').replace(')', ']')}) Tj T*" for ln in text_lines) + " ET"
    stream = DecodedStreamObject()
    stream.set_data(ops.encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(stream)
    w.encrypt(password)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_read_cas_pdf_with_password():
    pdf = _encrypted_pdf(CAS_TEXT.replace("₹", "").splitlines(), "ABCDE1234F")
    with pytest.raises(holdings.CasPasswordError):
        holdings.read_cas_pdf(pdf, "wrong")
    rows = holdings.read_cas_pdf(pdf, "ABCDE1234F")
    assert [round(r.units, 3) for r in rows] == [1234.567, 100.0]


def test_broker_csv_and_matching():
    zerodha = "Instrument,Qty.,Avg. cost,LTP,Cur. val\nNIFTYBEES,100,250,262.5,26250\nTotal,,,,26250\n"
    rows = holdings.parse_holdings_csv(zerodha)
    assert len(rows) == 1 and rows[0].value == 26250 and rows[0].units == 100
    generic = "name,units,price,asset_class,account\nE · NIFTY 50 index,10,250,Equity,Demat\nMystery Fund,5,10,Equity,\n"
    rows = holdings.match(holdings.parse_holdings_csv(generic), funds.catalogue("IN"))
    assert rows[0].match == "E" and not rows[1].matched
    with pytest.raises(ValueError):
        holdings.parse_holdings_csv("foo,bar\n1,2\n")


def test_sample_holdings_mark_totals():
    rows = holdings.sample_holdings("US")
    assert round(sum(h.value for h in rows)) == 65_300


def test_fund_holdings_file():
    f = funds.parse_holdings_csv("Company,% to NAV,Sector\nX,60,IT\nY,40,Energy\n", "F1", "Mine")
    assert f.holdings == {"X": 60.0, "Y": 40.0} and f.sectors["Y"] == "Energy"


def test_etf_book_examples():
    a, b, gap = etf.cost_of_gap(500_000, 10, 0.1231, 0.1202)
    assert (round(a), round(b), round(gap)) == (1_596_446, 1_555_699, 40_747)
    assert round(etf.cost_of_gap(50_000, 10, 0.0996, 0.0989)[2]) == 820
    assert round(etf.premium(102.40, 100.90), 4) == 0.0149
    assert round(etf.premium_cost(200_000, 102.40, 100.90)) == 2_973
    assert round(etf.spread_pct(101.20, 101.95), 4) == 0.0074


def test_etf_synthetic_tiles():
    a, b = etf.sample_etfs("IN")
    ca, cb = a.check(), b.check()
    assert round(ca.td[1], 4) == -0.0009 and round(cb.td[1], 4) == -0.0038
    assert set(ca.tiles()) == {"Expense", "Tracking difference", "Tracking error", "Trading cost"}
    assert max(b.intraday_premium) == pytest.approx(0.0171)


def test_income_safety_and_tax():
    assert income.safety(18, 40, 30)["flag"] is False
    s = income.safety(22, 20, 15)
    assert s["flag"] and "payout" in s["why"] and "cash cover" in s["why"]
    assert [round(income.after_tax_india(100_000, r, 0.04)) for r in (0.05, 0.20, 0.30)] == \
        [94_800, 79_200, 68_800]
    assert round(income.after_tax_us(10_000, 0.12, False)) == 8_800
    assert round(income.after_tax_us(10_000, 0.37, False, niit=True)) == 5_920
    assert round(income.after_tax_us(10_000, 0.22, True, 0.15)) == 8_500
    assert round(income.after_tax_us(10_000, 0.37, True, 0.20, niit=True)) == 7_620


def test_holding_period_check():
    ex = date(2026, 3, 1)
    assert income.qualifies(date(2025, 12, 1), ex)
    assert not income.qualifies(date(2026, 2, 27), ex, sold=date(2026, 3, 10))
    assert income.days_held_in_window(date(2026, 2, 27), ex, date(2026, 3, 10)) == 11


def test_yield_trap_series():
    s = {r["month"]: r for r in income.yield_trap_series()}
    assert s[0]["yield_pct"] == 5.0 and s[29]["yield_pct"] == 9.26 and s[29]["price_driven"]
    assert round(8 / 216 * 100, 1) == 3.7


def test_thesis_check_trips_pledge():
    t = thesis.sample_thesis()
    rows = t.check()
    assert [r["Status"] for r in rows] == ["✓ holds"] * 3 + ["⚠ review"]
    assert rows[3]["Last qtr"] == 3.1 and rows[3]["This qtr"] == 7.8
    tid = thesis.save(t)
    assert thesis.load_all()[0][0] == tid
    assert thesis.add_note_to_journal("Reviewed pledge", t.holding) > 0


def test_money_format():
    assert money(1_596_446) == "₹15,96,446" and money(129_216, "$") == "$129,216"


def _page(market="IN"):
    at = AppTest.from_string(
        f"import streamlit as st\nst.session_state.setdefault('market', '{market}')\n"
        "from plugai_trade.app.pages import portfolio_reviewer as m\nm.render()\n",
        default_timeout=60)
    at.run()
    assert not at.exception
    return at


def test_page_buttons_and_flows():
    at = _page("IN")
    labels = {b.label for b in at.button}
    for need in ("Import holdings", "Set target", "Rebalance checklist", "Add ETF", "Save to thesis",
                 "Save plan", "Add thesis", "Check thesis", "Add note to journal", "Explain",
                 "Show sources", "Second opinion"):
        assert need in labels, need
    for key in ("pr_rebal_IN", "pr_sip_save_IN", "pr_check_thesis", "pr_etf_save_IN"):
        at.button(key=key).click().run()
        assert not at.exception, key
    from plugai_trade.store import default as store
    assert store().count("plans", tag="sip") == 1
    assert store().count("theses", tag="etf") == 1


def test_page_us_renders():
    _page("US")
