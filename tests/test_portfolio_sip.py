"""SIP planner: the book's Chapter 15 numbers, computed exactly."""

import pytest

from plugai_trade.portfolio import sip


@pytest.mark.parametrize("rate, lakh", [(0.06, 45.6), (0.08, 57.3), (0.10, 72.4), (0.12, 92.0)])
def test_book_sip_projection(rate, lakh):
    assert round(sip.future_value(10_000, 20, rate) / 1e5, 1) == lakh


def test_invested_and_default_returns():
    plan = sip.SipPlan(10_000, 20)
    assert plan.returns == (0.06, 0.08, 0.10)
    assert plan.invested == 2_400_000


def test_us_projection():
    assert [round(sip.future_value(500, 25, r), -2) for r in (0.06, 0.08, 0.10)] == \
        [339_800, 457_400, 621_600]


def test_goal_mode():
    assert round(sip.required_monthly(5_000_000, 15, 0.10), -1) == 12_450
    assert round(sip.required_monthly(5_000_000, 15, 0.08), -1) == 14_720
    assert round(sip.required_monthly(300_000, 20, 0.08)) == 524
    assert round(sip.required_monthly(300_000, 20, 0.06)) == 658
    assert round(sip.future_value(524, 20, 0.06), -2) == 238_800


def test_step_up():
    assert round(sip.schedule(10_000, 20, 0.10).sum() / 1e5, 1) == 68.7
    assert round(sip.future_value(10_000, 20, 0.10, step_up=0.10) / 1e7, 2) == 1.55


def test_pause_and_inflation():
    base = sip.future_value(10_000, 10, 0.08)
    paused = sip.future_value(10_000, 10, 0.08, pause=(13, 12))
    assert paused < base
    assert sip.schedule(10_000, 10, pause=(13, 12))[12:24].sum() == 0
    plan = sip.SipPlan(10_000, 15, goal=5_000_000, inflation=0.05)
    assert plan.goal_nominal == pytest.approx(5_000_000 * 1.05 ** 15)
    assert plan.needed[0.10] > sip.required_monthly(5_000_000, 15, 0.10)


def test_path_matches_future_value():
    assert sip.path(10_000, 20, 0.08)[-1] == pytest.approx(sip.future_value(10_000, 20, 0.08))


def test_averaging_book_example():
    r = sip.averaging([100, 90, 80, 85, 95, 100], 10_000)
    assert round(r["units"], 2) == 659.02
    assert round(r["average_cost"], 2) == 91.04
    assert round(r["value_at_last"]) == 65_902


def test_facts_label_illustrative():
    facts = sip.SipPlan(10_000, 20).facts()
    assert any("illustrative" in f for f in facts)
