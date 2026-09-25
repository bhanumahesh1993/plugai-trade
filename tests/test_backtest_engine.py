"""Backtest engine: the look-ahead wall, next-open fills, costs, trials, determinism."""

from __future__ import annotations

import json
import math
import textwrap
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from plugai_trade import ai, costs, data
from plugai_trade.backtest import (
    DataView,
    LookAheadError,
    Spec,
    SpecError,
    State,
    chart_check,
    leg_cost,
    rules,
    run,
    run_strategy,
    trials,
)
from plugai_trade.backtest.engine import check_bars

ARJUN = ("Buy at the next open on the first close above the 50-day average; sell at the next "
         "open when the close is below the 20-day average")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def _no_model(*a, **k):
        raise ConnectionError("offline test")
    monkeypatch.setattr(ai, "_ollama_chat", _no_model)
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)


@pytest.fixture(scope="module")
def bars() -> pl.DataFrame:
    return data.get("NIFTY", "IN", "2021-01-01", "2025-12-31", source="synthetic")


# ------------------------------------------------------------------ the wall
class Peeker:
    """A strategy that tries to read tomorrow's close."""

    def decide(self, views, state):
        v = next(iter(views.values()))
        v.close(-1)


class IndexPeeker:
    def decide(self, views, state):
        v = next(iter(views.values()))
        v[len(v)]  # one past the last completed bar


class DatePeeker:
    def decide(self, views, state):
        v = next(iter(views.values()))
        v.at(date(2099, 1, 1))


@pytest.mark.parametrize("cls", [Peeker, IndexPeeker, DatePeeker])
def test_reading_the_future_raises(bars, cls):
    with pytest.raises(LookAheadError):
        run_strategy(cls(), bars, symbol="NIFTY")


class Recorder:
    """Buys on the first check, records what it could see."""

    def __init__(self):
        self.seen: list[tuple[date, int, float]] = []

    def decide(self, views, state):
        v = views["NIFTY"]
        col = v.column("close")
        self.seen.append((v.today, len(col), float(col[-1])))
        assert len(col) == len(v)
        with pytest.raises(ValueError):
            col[0] = 1.0  # read-only copy
        return {"NIFTY": 1.0} if len(self.seen) == 30 else None


def test_window_ends_at_last_completed_bar_and_fills_next_open(bars):
    rec = Recorder()
    res = run_strategy(rec, bars, symbol="NIFTY")
    dates = bars["date"].to_list()
    for i, (d, n, last) in enumerate(rec.seen):
        assert d == dates[i] and n == i + 1
        assert last == pytest.approx(float(bars["close"][i]))
    buy = res.fills[0]
    decided_on = rec.seen[29][0]
    assert buy["date"] == dates[dates.index(decided_on) + 1]
    open_next = float(bars["open"][dates.index(decided_on) + 1])
    assert buy["price"] == pytest.approx(open_next * 1.0005, rel=1e-6)


def test_future_bars_cannot_change_past_results(bars):
    """Structural causality: truncating the data leaves every earlier equity value unchanged."""
    spec = rules(ARJUN)
    full = run(spec, bars, count_trial=False)
    cut = bars.filter(pl.col("date") <= date(2024, 6, 28))
    part = run(spec, cut, count_trial=False)
    n = cut.height
    assert np.allclose(full.equity[: n - 1], part.equity[: n - 1])


def test_every_fill_is_at_a_next_open(bars):
    res = run(rules(ARJUN), bars, count_trial=False)
    opens = dict(zip(bars["date"].to_list(), bars["open"].to_list()))
    for f in res.fills:
        mult = 1.0005 if f["side"] == "BUY" else 0.9995
        assert f["price"] == pytest.approx(opens[f["date"]] * mult, rel=1e-6)
    assert res.fills and res.fills[0]["date"] > bars["date"][50]


def test_fill_cannot_be_set_earlier():
    d = rules(ARJUN).to_dict()
    d["fill"] = "same_close"
    with pytest.raises(SpecError, match="next session's open"):
        Spec.from_dict(d).validate()


def test_same_day_wording_is_moved_to_next_open():
    spec = rules("Buy at today's close when close > 50-day average; sell when close < 20-day average")
    assert spec.fill == "next_open" and spec.notes


# ------------------------------------------------------------------ costs
def test_costs_are_applied(bars):
    res = run(rules(ARJUN), bars, costs="IN-equity-delivery", count_trial=False)
    s, g = res.stats(), res.gross_stats()
    assert s["charges"] > 0 and s["slippage"] > 0
    assert g["charges"] == 0 and g["final"] > s["final"]
    closed = [t for t in res.trades if not t["open"]]
    t = closed[0]
    rt = costs.round_trip("IN-equity-delivery", t["buy_value"], t["sell_value"])["total"]
    assert t["charges"] == pytest.approx(rt, abs=0.05)
    assert t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["charges"] - t["slippage"], abs=0.05)


def test_intraday_profile_changes_costs(bars):
    spec = rules(ARJUN)
    d = run(spec, bars, costs="IN-equity-delivery", count_trial=False)
    i = d.with_costs("IN-equity-intraday")
    assert i.stats()["charges"] != d.stats()["charges"]
    us = run(spec, data.get("SPY", "US", "2021-01-01", "2025-12-31", source="synthetic"),
             costs="US-equity", count_trial=False)
    assert us.market == "US" and us.capital == 10_000


def test_leg_costs_sum_to_round_trip():
    b, s = leg_cost("IN-equity-delivery", 400_000, 0), leg_cost("IN-equity-delivery", 0, 410_000)
    rt = costs.round_trip("IN-equity-delivery", 400_000, 410_000)["total"]
    assert b["total"] + s["total"] == pytest.approx(rt, abs=0.03)
    assert rt == pytest.approx(915.28, abs=0.02)  # Chapter 11's worked example


# ------------------------------------------------------------------ trials
def test_trials_increment_per_distinct_variant(bars):
    fam = None
    for n, (fast, slow) in enumerate([(20, 150), (50, 200), (100, 250)], start=1):
        spec = rules(f"Hold while the {fast}-day average is above the {slow}-day average; "
                     "check Fridays; fill next open")
        res = run(spec, bars)
        fam = res.family
        assert res.trials_at_run == n
    again = run(rules("Hold while the 50-day average is above the 200-day average; check Fridays; "
                      "fill next open"), bars)
    assert again.trials_at_run == 3  # identical rule: not a new trial
    assert trials.count(fam) == 3
    assert run(rules(ARJUN), bars).trials_at_run == 1  # a different idea has its own counter


def test_edit_from_above_to_cross_is_same_family(bars):
    a = run(rules("Buy when the close is above the 50-day average; sell when the close is below "
                  "the 20-day average"), bars)
    b = run(rules(ARJUN), bars)
    assert a.family == b.family and b.trials_at_run == 2


def test_chart_check_does_not_count(bars):
    spec = rules(ARJUN)
    out = chart_check(spec, bars)
    assert out["buys"] and trials.count(spec.family_key()) == 0
    assert set(out) >= {"buys", "sells", "chip", "round_trips"}


# ------------------------------------------------------------------ determinism & sizing
def test_deterministic(bars):
    a = run(rules(ARJUN), bars, count_trial=False)
    b = run(rules(ARJUN), bars, count_trial=False)
    assert a.equity.tolist() == b.equity.tolist()
    assert a.stats() == b.stats()


def test_vol_target_size_matches_hand_formula(bars):
    spec = rules("Hold while the 20-day average is above the 50-day average; fill next open; "
                 "size to 12% volatility, 10% buffer, no borrowing")
    res = run(spec, bars, count_trial=False)
    first = res.fills[0]
    i = bars["date"].to_list().index(first["date"]) - 1  # the decision bar
    close = bars["close"].to_numpy()
    r = close[i - 19: i + 1] / close[i - 20: i] - 1
    dv = float(np.std(r, ddof=1))
    sleeve = 800_000
    want = math.floor(min(1.0, 0.12 / 16 / dv) * sleeve / close[i])
    assert first["units"] == want


def test_rotation_runs_and_counts(bars):
    uni = ["SEC-A", "SEC-B", "SEC-C", "SEC-D"]
    bm = {s: data.get(s, "IN", "2019-01-01", "2025-12-31", source="synthetic") for s in uni}
    from plugai_trade.backtest import rotation
    res = run(rotation(uni, 6, 2), bm)
    assert res.family == "rotation" and res.trials_at_run == 1
    assert res.stats()["round_trips"] > 0
    assert max(res.book.exposure) <= 1.0


def test_dict_spec_from_agent_runs(bars):
    d = json.loads(rules(ARJUN).to_json())
    d["origin"] = "agent"
    res = run(d, bars)
    card = res.report(echo=False)
    assert any("Training-cutoff guard" in w for w in card.warnings)


def test_check_bars_weekly_uses_fridays():
    days = [date(2025, 1, d) for d in (6, 7, 8, 9, 10, 13, 14, 15, 16)]  # Fri 10th; 17th missing
    wk = check_bars(days, "weekly")
    assert wk.tolist() == [False, False, False, False, True, False, False, False, False]


def test_state_is_passed(bars):
    class Once:
        def decide(self, views, state: State):
            assert isinstance(views["NIFTY"], DataView) and state.equity > 0
    run_strategy(Once(), bars, symbol="NIFTY")


# ------------------------------------------------------------------ book snippets
def _snippet(i: int) -> str:
    snips = json.loads((Path(__file__).parent / "book_snippets.json").read_text())
    return textwrap.dedent(snips[i]["code"])


@pytest.mark.parametrize("idx", [10, 11])
def test_book_snippets_run_offline(idx, capsys):
    exec(compile(_snippet(idx), f"snippet-{idx}", "exec"), {})  # noqa: S102 - book snippet
    out = capsys.readouterr().out
    assert "REPORT CARD" in out and "Grade:" in out
    if idx == 11:
        assert "Trials in this family       3" in out
