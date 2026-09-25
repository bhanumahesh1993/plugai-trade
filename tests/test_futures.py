"""Chapter 24: MTM ledger, margin call distance, basis, roll calendar, OI, USDINR, screen."""

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import futures


@pytest.fixture
def nifty_ledger():
    p = futures.BOOK_PATHS["NIFTY"]
    return futures.mtm_ledger("NIFTY", p["entry"], p["settles"], p["cash"])


def test_four_numbers():
    pos = futures.position("NIFTY", 25000)
    assert pos.notional == 1625000 and pos.margin == 195000
    assert round(pos.leverage, 1) == 8.3 and pos.one_point == 65


def test_mtm_ledger_book(nifty_ledger):
    rows = nifty_ledger.rows
    assert rows["mtm"].to_list() == [3900, -9750, -8450, -14300, 3900, 14950, 9100, 9100, -3250, 8450]
    assert rows["cash"].to_list()[3] == 211400 and rows["margin_required"].to_list()[3] == 191568
    assert rows["mtm"].sum() == 13650 and rows["mtm"].abs().sum() == 85150
    day4 = nifty_ledger.upto(4)
    assert day4.last["free_cash"] == 19832
    pts, _ = day4.move_to_margin_call()
    assert round(pts) == -347
    assert round(day4.shock(-0.03).shortfall) == 22313


def test_us_two_level_margin():
    p = futures.BOOK_PATHS["MES"]
    led = futures.mtm_ledger("MES", p["entry"], p["settles"], p["cash"], initial=p["initial"],
                             maintenance=p["maintenance"])
    assert led.rows["cash"].to_list() == [2860, 2650, 2400, 2275, 2150]
    assert led.rows["status"].to_list()[2] == "at initial"
    assert led.rows["status"].to_list()[-1] == "call: add $250"


def test_basis_and_fair_value():
    assert round(futures.fair_value(25000, 30)) == 25107
    assert round(futures.fair_value(25000, 10) - 25000) == 36
    assert futures.fair_value(25000, 1) - 25000 < 4
    df = futures.basis_series("NIFTY")
    assert df["basis"][-1] == 0 and df.height == 23
    assert futures.basis_label(120, 100) == "premium to fair value"


def test_roll_calendar_and_cost():
    assert futures.expiries("NIFTY", 1, after=date(2026, 10, 1)) == [date(2026, 10, 27)]
    assert futures.expiries("MES", 2, after=date(2026, 10, 1)) == [date(2026, 12, 18), date(2027, 3, 19)]
    w0, w1 = futures.roll_window(date(2026, 10, 27), 5)
    assert w0 == date(2026, 10, 20) and w1 < date(2026, 10, 27)
    plan = futures.roll_cost("NIFTY", 25040, 25140, 25020)
    assert plan.spread == 100 and plan.costs["stt"] == 813.80
    assert abs(plan.fair_spread - 100) < 1


def test_back_adjusted_series_removes_roll_jumps():
    df = futures.contract_series("NIFTY")
    assert df["roll"].sum() >= 2
    adj, joined = df["adjusted"].to_list(), df["joined"].to_list()
    assert adj[-1] == joined[-1]
    assert adj[0] != joined[0]


def test_oi_labels_and_roll_check():
    assert futures.oi_label(0.8, 6) == "Long build-up"
    assert futures.oi_label(0.5, -2) == "Short covering"
    assert futures.oi_label(-0.5, 3) == "Short build-up"
    assert futures.oi_label(-0.5, -3) == "Long unwinding"
    assert futures.roll_check(-5, 7).startswith("Looks like a roll")


def test_usdinr_split_book():
    sp = futures.usdinr_split(70, 70, 88.0, 88.8)
    assert round(sp.inr_from) == 6160 and round(sp.inr_to) == 6216
    assert round(sp.currency_part * sp.units) == 5600 and sp.benchmark_part == 0
    assert any("pending" in r["Source"] for r in futures.contract_rows())


def test_futures_screen_walkthrough():
    at = AppTest.from_string("from plugai_trade.app.pages import futures_roll as m\nm.render()\n",
                             default_timeout=60)
    at.run()
    assert not at.exception

    def click(label):
        next(b for b in at.button if b.label == label).click()
        at.run()
        assert not at.exception, [e.value for e in at.exception]

    click("Replay path")
    m = {x.label: x.value for x in at.metric}
    assert m["Free cash"] == "₹19,832" and m["Move to margin call"] == "≈ −347 pts"
    click("Add shock")
    assert {x.label: x.value for x in at.metric}["−3.0% gap: short"] == "₹22,313"
    at.selectbox(key="fr_pick_IN").set_value("CRUDEOIL")
    click("Add contract")
    click("USDINR split")
    assert {x.label: x.value for x in at.metric}["Currency part / lot"] == "₹5,600"
    click("Set roll alert")
    click("Send to Trend Lab")
    from plugai_trade import store
    assert store.default().count("alerts", tag="roll") == 1
    assert store.default().count("notes", tag="trend_lab") == 1
