"""Chapter 22 numbers, put-call parity and the pricing primitives."""

import math

import numpy as np
import pytest

from plugai_trade import options
from plugai_trade.options import pricing


@pytest.fixture
def nifty_call():
    return options.leg("NIFTY", kind="call", strike=25000, expiry="weekly", side="buy")


def test_book_nifty_call_tiles(nifty_call):
    t = nifty_call.tiles()
    assert nifty_call.premium == 89.0 and nifty_call.lot == 65
    assert t["Breakeven"] == 25089
    assert t["Max loss"] == 5785
    assert t["Required move"] == 289
    assert round(t["Expected ±1σ"]) == 406
    assert round(t["Theta/day"]) == -1057
    assert t["Delta"] == 0.33
    assert str(t) == ("Breakeven: 25,089 · Max loss: ₹5,785 · Required move: +289 pts · "
                      "Expected ±1σ: ±406 pts · Theta/day: −₹1,057 · Delta: 0.33")


def test_book_greeks(nifty_call):
    g = nifty_call.greeks()
    assert round(g["per_unit"]["theta"], 2) == -16.26
    assert round(g["per_unit"]["vega"], 2) == 10.57
    assert round(g["per_lot"]["delta"], 1) == 21.7
    assert round(g["per_lot"]["vega"]) == 687


def test_days_left_slider(nifty_call):
    prices = [round(nifty_call.at(days_left=d).price, 1) for d in (5, 4, 3, 2, 1)]
    assert prices == [89.0, 72.2, 54.1, 34.4, 13.2]
    thetas = [round(nifty_call.at(d).tiles()["Theta/day"]) for d in (5, 4, 3, 2, 1)]
    assert thetas == [-1057, -1132, -1226, -1337, -1373]
    assert nifty_call.at(1).tiles()["Delta"] == 0.14


def test_book_scenarios(nifty_call):
    gap = nifty_call.scenario(gap=-300)
    assert round(gap.price, 1) == 15.5 and round(gap.pnl) == -4778
    crush = nifty_call.scenario(iv=-3)            # tomorrow: 4 days left
    assert round(crush.price, 1) == 45.6 and round(crush.pnl) == -2821
    combo = nifty_call.scenario(gap=150, iv=-2, days_left=2)
    assert round(combo.price, 1) == 69.5
    assert round(nifty_call.scenario(gap=250).price, 1) == 182.7
    assert round(float(nifty_call.value(iv=0.18)), 1) == 132.2


def test_book_put_and_strike_table():
    put = options.leg("NIFTY", kind="put", strike=24600)
    t = put.tiles()
    assert put.premium == 74 and t["Breakeven"] == 24526 and t["Max loss"] == 4810
    assert round(t["Theta/day"]) == -819 and t["Delta"] == -0.29
    rows = {(25200, 5): (39, 0.18), (24800, 5): (173, 0.52), (25000, 12): (185, 0.41),
            (25000, 26): (330, 0.47)}
    for (k, d), (prem, delta) in rows.items():
        lg = options.leg("NIFTY", "call", k, expiry=d)
        assert lg.premium == prem and lg.tiles()["Delta"] == delta


def test_book_spy_call():
    spy = options.leg("SPY", kind="call", strike=565)
    t = spy.tiles()
    assert spy.market == "US" and spy.lot == 100 and spy.premium == 2.27
    assert t["Breakeven"] == 567.27 and t["Max loss"] == 227
    assert round(t["Expected ±1σ"], 2) == 10.49 and round(t["Theta/day"]) == -40
    assert round(spy.greeks()["per_lot"]["vega"], 2) == 23.78
    assert [round(spy.at(d).price, 2) for d in (5, 4, 3, 2, 1)] == [2.27, 1.85, 1.40, 0.90, 0.36]
    spx = options.leg("SPX", kind="call", strike=5650)
    assert round(float(spx.value()), 2) == 22.66


@pytest.mark.parametrize("s,k,days,iv,r", [(24800, 25000, 5, 0.14, 0.065), (560, 540, 30, 0.16, 0.04),
                                           (100, 130, 200, 0.5, 0.01)])
def test_put_call_parity(s, k, days, iv, r):
    t = days / 365
    c = float(pricing.bs_price(s, k, t, iv, r, "call"))
    p = float(pricing.bs_price(s, k, t, iv, r, "put"))
    assert math.isclose(c - p, s - k * math.exp(-r * t), abs_tol=1e-8)
    f = s * math.exp(r * t)
    c76 = float(pricing.black76_price(f, k, t, iv, r, "call"))
    p76 = float(pricing.black76_price(f, k, t, iv, r, "put"))
    assert math.isclose(c76, c, rel_tol=1e-10) and math.isclose(p76, p, rel_tol=1e-10)


def test_vectorised_and_expiry():
    grid = np.array([24000.0, 25000.0, 26000.0])
    v = pricing.bs_price(grid, 25000, 0.0, 0.14, 0.065, "call")
    assert v.tolist() == [0.0, 0.0, 1000.0]
    assert pricing.bs_price(grid, 25000, 5 / 365, 0.14, 0.065, "call").shape == (3,)


def test_implied_vol_round_trip():
    iv = pricing.implied_vol(89.034, 24800, 25000, 5 / 365, 0.065, "call")
    assert abs(iv - 0.14) < 1e-4


def test_iv_rank_book():
    r = options.iv_rank("NIFTY", window=252)
    assert (r.iv, r.low, r.high) == (14.0, 9.7, 24.6)
    assert round(r.rank) == 29 and round(r.percentile) == 61 and r.below_days == 152
    assert len(r.series) == 252 and "IV rank: 29" in " ".join(r.facts())
    assert options.iv_rank("NIFTY").series == r.series  # deterministic


def test_leg_validation():
    with pytest.raises(ValueError):
        options.leg("NIFTY", kind="straddle", strike=25000)
    with pytest.raises(ValueError):
        options.leg("NIFTY", kind="call", strike=25000, expiry="yearly")


def test_implied_move_ch19():
    assert round(options.implied_move(3.35, 3.15, 84.20) * 100, 1) == 7.7
