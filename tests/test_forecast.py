"""Forecast Journal: break-even, Brier score, calibration, journal records (Chapter 26)."""

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import forecast


def test_break_even():
    assert forecast.break_even(0.62, 0.01) == pytest.approx(0.63)
    assert forecast.break_even(0.05, 0.01) == pytest.approx(0.06)  # a fifth higher for a longshot


def test_brier_book_terms():
    assert forecast.brier([0.7], [1]) == pytest.approx(0.09)
    assert forecast.brier([0.7], [0]) == pytest.approx(0.49)
    assert forecast.brier([0.5] * 10, [1, 0] * 5) == pytest.approx(0.25)
    with pytest.raises(ValueError):
        forecast.brier([], [])


def test_calibration_bins():
    bins = forecast.calibration([0.1, 0.15, 0.9, 0.95], [0, 1, 1, 1], bins=5)
    assert [b.n for b in bins] == [2, 2]
    assert bins[0].hit_rate == 0.5 and bins[1].hit_rate == 1.0


def test_sample_journal_overconfident():
    card = forecast.sample_journal()
    assert card.n == 160 and round(card.brier, 3) == 0.215 and card.ready
    bins = card.bins()
    assert bins[-1].hit_rate < bins[-1].mean_prob  # sure things were less sure
    assert bins[0].hit_rate > bins[0].mean_prob  # long shots less long


def test_journal_add_resolve_score():
    ids = [forecast.add(f"Q{i}", "Settles on the BLS release at 8:30 ET.", 0.7, "why") for i in range(3)]
    forecast.resolve(ids[0], 1)
    forecast.resolve(ids[1], 0)
    card = forecast.scorecard()
    assert card.n == 2 and card.brier == pytest.approx((0.09 + 0.49) / 2) and not card.ready
    forecast.set_price(ids[2], 0.62, 0.01)
    with pytest.raises(ValueError):
        forecast.resolve(ids[2], 2)
    with pytest.raises(ValueError):
        forecast.add("bad", "", 1.5, "")


def test_resolution_rules_quotes_sentences():
    rules = ("This contract resolves YES if the CPI YoY print exceeds 3.0%. The source is the BLS "
             "release at 8:30 AM ET on 12 Nov 2026. If the release is delayed, the market "
             "settles on the first published figure. Revisions are ignored.")
    out = forecast.resolution_rules(rules)
    assert any("BLS" in s for s in out["Source"])
    assert any("8:30" in s for s in out["Time"])
    assert any("delayed" in s for s in out["Edge cases"])


def _page(market):
    at = AppTest.from_string(
        f"import streamlit as st\nst.session_state.setdefault('market', '{market}')\n"
        "from plugai_trade.app.pages import forecast_journal as m\nm.render()\n", default_timeout=60)
    at.run()
    assert not at.exception
    return at


def test_page_disabled_for_india():
    at = _page("IN")
    assert at.button(key="fj_add").disabled
    assert any("Disabled for IN" in w.value for w in at.warning)


def test_page_commit_hides_price_first():
    at = _page("US")
    at.button(key="fj_add").click().run()
    assert "fj_price" not in [n.key for n in at.number_input]  # hidden until commit
    at.text_input(key="fj_q").input("Will CPI YoY exceed 3.0%?").run()
    at.number_input(key="fj_prob").set_value(70.0).run()
    at.button(key="fj_commit").click().run()
    assert not at.exception
    assert "fj_price" in [n.key for n in at.number_input]
    assert any(m.label == "Fee-adjusted break-even" and m.value == "63%" for m in at.metric)
    at.button(key="fj_finish").click().run()
    at.button(key="fj_resolve").click().run()
    assert not at.exception
    assert forecast.scorecard().n == 1
