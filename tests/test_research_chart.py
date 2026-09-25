"""Chart Helper: pivots, swing zones, ATR distances, intraday levels, screenshot checks, saving."""

from datetime import date, timedelta

import polars as pl
import pytest

from plugai_trade import charthelper as ch
from plugai_trade.store import default as store


def _daily(highs, lows, closes):
    n = len(closes)
    start = date(2026, 1, 5)
    return pl.DataFrame(
        {
            "date": [start + timedelta(days=i) for i in range(n)],
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


def test_pivots_match_the_book():
    p = ch.pivots(25095, 24743, 24788)  # Chapter 10 worked example
    assert (
        round(p["P"], 1) == 24875.3
        and round(p["R1"], 1) == 25007.7
        and round(p["S1"], 1) == 24655.7
    )


def test_swing_points_need_three_bars_each_side():
    highs = [10.0, 11, 12, 15, 12, 11, 10, 11, 12, 11, 10]
    lows = [h - 2.0 for h in highs]
    hi, lo = ch.swing_points(_daily([float(h) for h in highs], lows, [h - 1.0 for h in highs]))
    assert hi == [(3, 15.0)]
    assert lo == [(6, 8.0)]


def test_level_distance_in_atr():
    z = ch.Level("Resistance", 25048, 25095, 4, "swing highs", close=24788, atr=262.7)
    assert z.distance_text() == "+0.99 ATR" and z.within_one_atr()
    s = ch.Level("Support", 24376, 24411, 4, "swing lows", close=24788, atr=262.7)
    assert s.distance_text() == "-1.44 ATR" and not s.within_one_atr()
    inside = ch.Level("POC", 24700, 24800, 1, "volume profile", close=24788, atr=262.7)
    assert inside.distance_text() == "inside"


def test_levels_card_on_synthetic_nifty():
    bars = ch.load("NIFTY", "IN", "Daily", end=date(2026, 5, 29), source="synthetic")
    lv = ch.levels(bars, "NIFTY")
    kinds = {z.kind for z in lv.zones}
    assert {"Pivot P", "Pivot R1", "Pivot S1", "POC", "20-bar high", "20-bar low"} <= kinds
    tbl = lv.table()
    assert {"Level", "Zone", "Distance", "±1 ATR"} <= set(tbl.columns)
    poc = next(z for z in lv.zones if z.kind == "POC")
    assert poc.high > poc.low and "volume profile" in poc.source
    d = ch.describe(bars, "NIFTY")
    assert d.lines[0].startswith("Close ") and any("ATR(14)" in ln for ln in d.lines)
    assert d.values["close"] == pytest.approx(float(bars["close"][-1]))


def test_intraday_levels_opening_range_and_vwap():
    times = [f"2026-05-29T09:{15 + 5 * i:02d}" for i in range(6)]
    intra = pl.DataFrame(
        {
            "date": [date(2026, 5, 29)] * 6,
            "time": times,
            "open": [100.0, 101, 102, 103, 104, 105],
            "high": [101.0, 103, 103, 104, 106, 106],
            "low": [99.0, 100, 101, 102, 103, 104],
            "close": [101.0, 102, 103, 104, 105, 105],
            "volume": [10.0] * 6,
        }
    )
    lv = ch.intraday_levels(intra, {"high": 110.0, "low": 95.0}, or_minutes=15)
    assert lv.values["PDH"] == 110 and lv.values["PDL"] == 95
    assert lv.values["OR high"] == 103 and lv.values["OR low"] == 99
    tp = [(h + lo + c) / 3 for h, lo, c in zip(intra["high"], intra["low"], intra["close"])]
    assert lv.values["VWAP"] == pytest.approx(sum(tp) / 6)


def test_timeframes_table_and_intraday_load():
    tbl = ch.timeframes(
        "SPY", "US", ["Daily", "Weekly", "15-min"], end=date(2026, 5, 29), source="synthetic"
    )
    assert tbl["Timeframe"].to_list() == ["Daily", "Weekly", "15-min"]
    intra = ch.load("NIFTY FUT", "IN", "5-min", end=date(2026, 5, 29))
    assert "time" in intra.columns and intra["source"][0] == "synthetic"


def test_screenshot_claims_are_checked_against_the_table():
    bars = ch.load("SPY", "US", "Daily", end=date(2026, 5, 29), source="synthetic")
    d, lv = ch.describe(bars, "SPY"), ch.levels(bars, "SPY")
    claims = ch.screenshot_claims(d, lv)
    assert claims and all(c.check in ("✓", "✗") for c in claims)
    assert claims[-1].check == "✗" and "unverifiable" in claims[-1].why
    assert ch.screenshot_claims(d, lv) == claims  # deterministic


def test_save_and_send_levels():
    bars = ch.load("NIFTY", "IN", "Daily", end=date(2026, 5, 29), source="synthetic")
    lv = ch.levels(bars, "NIFTY")
    ch.save_levels_to_journal("NIFTY", "IN", "Daily", lv)
    note = store().all("notes", tag="journal")[0]
    assert note["kind"] == "levels" and note["asof"] == "2026-05-29" and note["levels"]
    ch.send_levels_to_paper_desk("NIFTY", "IN", lv)
    assert store().all("notes", tag="paper_levels")[0]["levels"]


def test_book_snippet_9_runs_offline(capsys):
    import json
    import textwrap
    from pathlib import Path

    from plugai_trade import config

    config.set_value("ai.ollama_host", "http://127.0.0.1:9")
    snips = json.loads((Path(__file__).parent / "book_snippets.json").read_text(encoding="utf-8"))
    code = textwrap.dedent(snips[9]["code"])
    assert "ai.explain(bars.tail(60))" in code
    exec(compile(code, "snippet-9", "exec"), {})  # noqa: S102 - book snippet, run as printed
    assert "sma20" in capsys.readouterr().out
