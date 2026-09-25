"""Score-Tester: column mapper, point-in-time alignment, buckets, spread, hit share, warnings."""

from datetime import date, timedelta

import polars as pl
import pytest

from plugai_trade import scoretest
from plugai_trade.screener import universe


def _future_return(sym: str, d: date, horizon: int = 63) -> float:
    df = universe.bars(sym, "IN", d - timedelta(days=5), d + timedelta(days=horizon + 10))
    entry = df.filter(pl.col("date") > d)
    exit_ = df.filter(pl.col("date") <= entry["date"][0] + timedelta(days=horizon))
    return float(exit_["close"][-1] / entry["close"][0] - 1)


def _perfect_scores(n_dates: int = 6, names: int = 40) -> pl.DataFrame:
    """Scores 1–10 ranked by the *actual* next-quarter return: a score that knows the future."""
    syms = [s for s in universe.names("NIFTY 500", "IN") if not universe.delisted_on(s)][:names]
    rows = []
    for m in range(n_dates):
        d = date(2024, 1 + m, 10)
        rets = sorted((_future_return(s, d), s) for s in syms)
        for i, (_, s) in enumerate(rets):
            rows.append({"date": d, "symbol": s, "score": float(1 + i * 10 // len(rets))})
    return pl.DataFrame(rows)


def test_guess_mapping_and_map_columns():
    raw = "As of,Ticker,Rating,Published\n2024-01-31,SYN-IN-001,7,2024-02-01\n"
    df = scoretest.read_csv(raw)
    m = scoretest.guess_mapping(df.columns)
    assert m == {
        "Date": "As of",
        "Symbol": "Ticker",
        "Score": "Rating",
        "Published at": "Published",
    }
    out = scoretest.map_columns(df, m)
    assert out.columns == ["date", "symbol", "score", "published_at"]
    assert out["published_at"][0] == date(2024, 2, 1)
    with pytest.raises(ValueError):
        scoretest.map_columns(df, {**m, "Score": None})


def test_perfect_score_has_a_staircase():
    rep = scoretest.run(_perfect_scores(), "IN", horizon_days=63)
    rets = [b["return"] for b in rep.buckets]
    assert [b["label"] for b in rep.buckets] == ["1–2", "3–4", "5–6", "7–8", "9–10"]
    assert rets == sorted(rets) and rep.spread > 0
    assert rep.hit_share == 100.0 and rep.n_dates == 6
    assert rep.coverage["median"] == 40
    assert "No Published at column: assumed next-day use for every score." in rep.warnings


def test_random_score_sample_and_warnings():
    scores = scoretest.map_columns(
        scoretest.read_csv(scoretest.sample_csv("IN", months=6)),
        {"Date": "date", "Symbol": "symbol", "Score": "score", "Published at": "published_at"},
    )
    rep = scoretest.run(scores, "IN", 91)
    assert len(rep.buckets) == 5 and rep.n_dates == 6
    assert any("unmatched symbols" in w for w in rep.warnings)
    assert any("published after the date" in w for w in rep.warnings)
    assert rep.cost_preset == "IN-equity-delivery" and rep.cost_pct > 0
    assert any(f.startswith("Top-minus-bottom spread") for f in rep.facts())


def test_include_delisted_off_warns_about_survivorship():
    gone = next(s for s in universe.names("NIFTY 500", "IN") if universe.delisted_on(s))
    d = universe.delisted_on(gone) - timedelta(days=30)
    scores = pl.DataFrame({"date": [d, d], "symbol": [gone, "SYN-IN-001"], "score": [9.0, 2.0]})
    on = scoretest.run(scores, "IN", 91, include_delisted=True)
    off = scoretest.run(scores, "IN", 91, include_delisted=False)
    assert sum(b["names"] for b in on.buckets) == 2
    assert sum(b["names"] for b in off.buckets) == 1
    assert any("survivorship" in w for w in off.warnings)
