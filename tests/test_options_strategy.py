"""Chapter 23: income structures, stress table, margin estimate, attribution."""

import numpy as np
import pytest

from plugai_trade import options

SPEC = [("put", 24100, "buy"), ("put", 24300, "sell"), ("call", 25400, "sell"), ("call", 25600, "buy")]


def _nifty(legs):
    return options.strategy([options.leg("NIFTY", kind=k, strike=s, expiry="monthly", side=d)
                             for k, s, d in legs])


@pytest.fixture
def ic():
    return _nifty(SPEC)


def test_condor_premiums_and_summary(ic):
    assert [lg.premium for lg in ic.legs] == [33.80, 63.80, 70.35, 39.25]
    s = ic.summary()
    assert s.net == 3971.50 and s.max_profit == 3971.50 and s.max_loss == 9028.50
    assert s.breakevens == [24238.90, 25461.10]
    assert round(s.expected_move) == 631
    assert round(s.margin) == 41235 and round(s.margin_expiry_day) == 73475
    tiles = s.tiles()
    assert tiles["Credit"] == "₹3,971.50" and tiles["2nd Breakeven"] == "25,461.10"
    assert ic.name == "Iron condor"


def test_payoff_breakevens_are_zeros(ic):
    for be in ic.breakevens():
        assert abs(float(ic.expiry_pnl(np.array([be]))[0])) < 1e-6
    arr = ic.payoff()
    assert arr["spot"].shape == arr["expiry"].shape == arr["now"].shape
    assert np.isclose(arr["expiry"].max(), 3971.5) and np.isclose(arr["expiry"].min(), -9028.5)


INDIA_STRESS = {  # naked put, bull put, iron condor — Chapter 23 table
    "naked": [-18263, -42839, 3906, -6062, -51776, -93937],
    "bps": [-5399, -9004, 1798, -1249, -7318, -9260],
    "ic": [-3520, -6993, -3412, -2372, -5850, -7477],
}


@pytest.mark.parametrize("name,legs", [("naked", [("put", 24300, "sell")]),
                                       ("bps", [("put", 24300, "sell"), ("put", 24100, "buy")]),
                                       ("ic", SPEC)])
def test_india_stress_table(name, legs):
    rows = _nifty(legs).stress_table()
    assert [round(r.pnl) for r in rows] == INDIA_STRESS[name]
    assert all(r.days_left == 13 for r in rows)


def test_snippet_stress_row(ic):
    assert round(ic.stress(gap=-0.05, iv_to=0.24).pnl) == -5850


def test_india_margin_naked_put():
    s = _nifty([("put", 24300, "sell")]).summary()
    assert round(s.margin) == 121727 and round(s.margin_expiry_day) == 153967
    assert s.max_loss == 1575353


def test_us_structures_and_stress():
    cc = options.strategy(options.preset("Covered call", "SPY"))
    csp = options.strategy(options.preset("Cash-secured put", "SPY"))
    bps = options.strategy(options.preset("Bull put spread", "SPY"))
    assert [lg.premium for lg in cc.legs] == [560.0, 2.73]
    s = cc.summary()
    assert s.credit == 273 and s.max_profit == 2773 and s.max_loss == 55727 and s.breakevens == [557.27]
    assert round(s.margin) == 56000
    s = csp.summary()
    assert s.credit == 270 and s.breakevens == [537.30] and s.max_loss == 53730 and s.margin == 54000
    assert round(csp.summary(account="margin").margin) == 9470
    s = bps.summary()
    assert s.credit == 150 and s.max_loss == 850 and s.breakevens == [538.50] and s.margin == 850
    assert [round(r.pnl) for r in csp.stress_table()] == [-1040, -3234, 246, -695, -3934]
    assert [round(r.pnl) for r in bps.stress_table()] == [-379, -744, 133, -146, -580]
    assert [round(r.pnl) for r in cc.stress_table()] == [-2546, -5327, 1759, -714, -5491]


def test_attribution_book_and_sum(ic):
    a = ic.attribution(spot=24560, iv=0.15, days=5)
    assert round(a.theta) == 1149 and round(a.gamma) == -449 and round(a.delta) == 29
    assert abs(a.vega - (-956)) <= 1.5          # book: −478 × 2 from rounded vega
    assert abs(a.residual - 147) <= 1.5 and round(a.actual) == -81
    assert round(a.theta_per_day) == 230 and round(a.vega_per_point) == -478
    assert abs(sum(a.parts().values()) - a.actual) < 0.05


def test_attribution_sums_for_single_leg():
    st = options.strategy([options.leg("NIFTY", "call", 25000)])
    a = st.attribution(spot=24950, iv=0.12, days=3)
    assert abs(sum(a.parts().values()) - a.actual) < 0.05
    assert round(st.legs[0].premium + a.actual / 65, 1) == 69.5


def test_presets_nifty_strikes():
    strikes = {n: [lg.strike for lg in options.preset(n, "NIFTY")] for n in options.PRESETS}
    assert strikes["Iron condor"] == [24100, 24300, 25400, 25600]
    assert strikes["Bull put spread"] == [24300, 24100]
    for name in options.PRESETS:
        s = options.strategy(options.preset(name, "NIFTY")).summary()
        assert s.margin is not None and s.margin > 0


def test_unlimited_loss_and_long_margin():
    naked_call = _nifty([("call", 25400, "sell")])
    assert naked_call.max_profit_loss()[1] is None
    assert naked_call.summary().tiles()["Max loss"] == "Unlimited"
    long_call = options.strategy([options.leg("NIFTY", "call", 25000)])
    assert long_call.summary().margin == 5785


def test_at_shifts_days_and_facts(ic):
    later = ic.at(1)
    assert later.days_left == 1 and ic.days_left == 14
    facts = ic.facts()
    assert any("Margin estimate" in f for f in facts) and any("Gap −5%" in f for f in facts)
    assert ic.to_dict()["legs"][0]["premium"] == 33.80


def test_mixed_underlyings_rejected():
    with pytest.raises(ValueError):
        options.strategy([options.leg("NIFTY", "call", 25000), options.leg("SPY", "call", 565)])
