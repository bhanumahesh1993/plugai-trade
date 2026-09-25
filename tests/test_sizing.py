"""Position Sizer: every number printed in Chapters 12, 17, 26 and 34, reproduced in code."""

import pytest

from plugai_trade import reference, sizing

ACCT_IN, ACCT_US = 1_500_000, 40_000


def test_nifty_one_lot_ch12():
    lot = reference.lot_size("NIFTY")
    assert lot == 65
    allow = sizing.cost_allowance("NIFTY FUT", "IN", 24850, 24700, lot)
    assert allow == 1200                      # dated cost table + 2 pts a side, nearest ₹100
    r = sizing.fixed_risk(ACCT_IN, 0.01, 24850, 24700, lot=lot, cost_per_lot=allow,
                          symbol="NIFTY FUT", market="IN")
    assert r.budget == 15_000
    assert r.risk_per_lot == 10_950
    assert round(r.raw_size, 2) == 1.37
    assert r.size == 1 and r.quantity == 65
    assert r.actual_risk == 10_950 and round(r.actual_risk_pct, 4) == 0.0073
    assert round(r.notional_x, 2) == 1.08    # 24,850 × 65 = ₹16,15,250


@pytest.mark.parametrize("stop_pts,risk_lot,raw,size,actual", [
    (90, 7050, 2.13, 2, 14_100), (120, 9000, 1.67, 1, 9000),
    (150, 10_950, 1.37, 1, 10_950), (220, 15_500, 0.97, 0, 0)])
def test_lot_rounding_table_ch12(stop_pts, risk_lot, raw, size, actual):
    r = sizing.fixed_risk(ACCT_IN, 0.01, 24850, 24850 - stop_pts, lot=65, cost_per_lot=1200)
    assert (r.risk_per_lot, round(r.raw_size, 2), r.size, r.actual_risk) == (risk_lot, raw, size, actual)
    if size == 0:
        assert r.choices and "Pass on this trade" in r.choices   # never rounds up


def test_stock_atr_stop_with_cap_ch12():
    r = sizing.atr_stop(ACCT_IN, 0.01, 1240, atr=28, multiple=1.5, cost_per_lot=1.0, cap_pct=0.25)
    assert r.stop == 1198 and r.risk_per_lot == 43
    assert r.risk_size == 348 and r.cap_size == 302 and r.size == 302
    assert r.binding == "position cap"
    assert r.actual_risk == 12_986 and r.size * 1240 == 374_480


def test_spy_two_atr_ch12():
    allow = sizing.cost_allowance("SPY", "US", 560, 547.60)
    assert allow == 0.05
    r = sizing.atr_stop(ACCT_US, 0.01, 560.00, atr=6.20, multiple=2, cost_per_lot=allow,
                        cap_pct=0.50, market="US", symbol="SPY")
    assert r.stop == 547.60 and r.risk_per_lot == 12.45
    assert r.size == 32 and r.actual_risk == 398.40
    assert r.notional == 17_920 and round(r.notional / ACCT_US, 3) == 0.448
    assert 50 * r.risk_per_lot == 622.50     # the habitual 50 shares


def test_vol_target_ch12():
    n = sizing.vol_target(ACCT_IN, 0.12, 24850, 0.008, lot=65)
    assert n.budget == 11_250 and n.risk_per_lot == 12_922
    assert round(n.raw_size, 2) == 0.87 and n.size == 0
    assert round(n.extra["one_unit_annual_vol"], 3) == 0.138
    assert len(n.choices) == 3 and "13.8%" in n.choices[0]
    s = sizing.vol_target(ACCT_US, 0.12, 560, 0.01, market="US")
    assert s.budget == 300 and round(s.raw_size, 1) == 53.6 and s.size == 53 and s.notional == 29_680


def test_combined_risk_ch12():
    assert [round(sizing.combined_risk([1, 1, 1], c), 1) for c in (0, 0.5, 0.8, 1.0)] == [1.7, 2.4, 2.8, 3.0]
    assert round(sizing.combined_risk([1, 1], 0.8), 1) == 1.9    # NIFTY + BANKNIFTY


def test_correlated_group_check():
    open_pos = [{"symbol": "SPY", "risk_r": 1.0}, {"symbol": "QQQ", "risk_r": 1.0}]
    chk = sizing.check_caps(open_pos, "DIA", 1.0, total_cap_r=3, group_cap_r=2)
    assert not chk.ok and chk.group == "US equity index" and round(chk.group_effective_r, 1) == 2.8
    ok = sizing.check_caps([{"symbol": "NIFTY FUT", "risk_r": 1.0}], "SPY", 1.0)
    assert ok.ok and ok.total_open_r == 2.0


def test_swing_sizes_ch17():
    far = sizing.atr_stop(800_000, 0.005, 616.50, 12.79, 1.5, cost_per_lot=1.5, cap_pct=0.20)
    assert far.extra["suggested_stop"] == 597.32
    typed = sizing.atr_stop(800_000, 0.005, 616.50, 12.79, 1.5, cost_per_lot=1.5, cap_pct=0.20,
                            stop_override=597.30)
    assert typed.size == 193 and typed.actual_risk == 3995.10 and typed.binding == "risk budget"
    luis = sizing.atr_stop(30_000, 0.01, 41.15, 0.5771, 2, cost_per_lot=0.02, cap_pct=0.20, market="US")
    assert luis.stop == 40.00 and luis.risk_size == 256 and luis.size == 145
    assert luis.binding == "position cap" and luis.actual_risk == 169.65


def test_pilot_size_ch34():
    r = sizing.fixed_risk(100, 1.0, 560, 547.60, cost_per_lot=0.05, market="US")   # $100 pilot risk
    assert r.size == 8 and r.actual_risk == 99.60


def test_hedge_mode_ch26():
    h = sizing.hedge(20_000, 88.40, "receivable")
    assert h.lots == 20 and h.futures_side == "sell" and h.locked_inr == 1_768_000
    by = {s["rate"]: s for s in h.scenarios}
    assert by[92.0]["futures_pnl"] == -72_000 and by[85.0]["futures_pnl"] == 68_000
    assert all(s["total"] == 1_768_000 for s in h.scenarios)
    assert sizing.hedge(20_000, 88.40, "payable").futures_side == "buy"


@pytest.mark.parametrize("risk,typical,bad,dd30,touch50", [
    (0.005, 5.8, 11.4, 0.0, 0.0), (0.01, 11.3, 21.8, 0.2, 0.0), (0.02, 21.8, 39.4, 21.6, 0.2),
    (0.03, 31.4, 53.5, 54.4, 4.2), (0.05, 48.6, 73.6, 94.1, 23.8)])
def test_simulate_streaks_reproduces_book_table(risk, typical, bad, dd30, touch50):
    s = sizing.simulate_streaks(risk_pct=risk)            # 2,000 × 100, seed 12
    assert round(s.typical_fall * 100, 1) == typical
    assert round(s.bad_luck_fall * 100, 1) == bad
    assert round(s.share_dd_30 * 100, 1) == dd30
    assert round(s.share_touch_50 * 100, 1) == touch50


def test_streak_lengths_and_seed():
    s = sizing.simulate_streaks()
    assert (s.streak_median, s.streak_p10, s.streak_p90) == (7, 5, 11)
    assert round(s.median_final * 100) == 103 and round(s.p5_final * 100) == 84
    assert sizing.simulate_streaks(seed=3).typical_fall != s.typical_fall
    boot = sizing.simulate_streaks(r_values=[1.8, -1.0, -1.0, 0.6], sequences=200)
    assert 0 < boot.typical_fall < 1


def test_facts_cite_numbers_and_money_format():
    r = sizing.fixed_risk(ACCT_IN, 0.01, 24850, 24700, lot=65, cost_per_lot=1200)
    assert any("Size (rounded down): 1" in f for f in r.facts())
    assert sizing.money(1_500_000, "IN") == "₹15,00,000"
    assert sizing.money(1_615_250, "IN") == "₹16,15,250"
    assert sizing.money(398.4, "US", 2) == "$398.40"


def test_entry_equals_stop_rejected():
    with pytest.raises(ValueError):
        sizing.fixed_risk(ACCT_IN, 0.01, 100, 100)
