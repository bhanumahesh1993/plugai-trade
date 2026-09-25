"""Screener: the deterministic parser, presets, metrics, run, triage and Save as watchlist."""

from datetime import date, timedelta

import polars as pl
import pytest

from plugai_trade import config, screener
from plugai_trade.screener import metrics, universe


@pytest.fixture(autouse=True)
def offline_ai():
    config.set_value("ai.ollama_host", "http://127.0.0.1:9")


def _rule(parsed, metric):
    return next(r for r in parsed.rules if r.metric == metric)


def test_parser_near_high_and_volume_are_interpreted():
    p = screener.parse("stocks near their 52-week high with volume picking up", "IN")
    hi, vol = _rule(p, "below_high_pct"), _rule(p, "vol_ratio")
    assert (hi.op, hi.value) == ("<=", 5.0) and hi.interpreted
    assert (vol.op, vol.value) == (">=", 1.2) and vol.interpreted
    assert p.unparsed == []


def test_parser_explicit_numbers():
    p = screener.parse(
        "within 3% of the 52-week high; volume at least 1.5x the 50-day average; "
        "above the 50-day average; RSI below 30; gap at least 2% either way; "
        "RVOL at least 2; delivery above 45%",
        "IN",
    )
    hi = _rule(p, "below_high_pct")
    assert (
        hi.value == 3 and "intraday" in hi.interpreted
    )  # closing or intraday high: still a choice
    assert not _rule(p, "vol_ratio").interpreted
    assert _rule(p, "vol_ratio").value == 1.5
    assert _rule(p, "close_vs_sma:50").op == ">"
    assert (_rule(p, "rsi:14").op, _rule(p, "rsi:14").value) == ("<", 30)
    assert _rule(p, "gap_abs_pct").value == 2 and _rule(p, "rvol").value == 2
    assert _rule(p, "deliv_pct_20d").value == 45


def test_parser_liquidity_units_rs_and_exclusion():
    inr = screener.parse("liquid enough, exclude events within 5 sessions", "IN")
    assert _rule(inr, "traded_value").value == 10 and inr.exclude_events == 5
    usd = screener.parse("traded value at least $50 m; relative strength positive", "US")
    assert _rule(usd, "traded_value").value == 50 and not _rule(usd, "traded_value").interpreted
    assert _rule(usd, "rs_3m").interpreted  # RS is not RSI
    assert screener.parse("delivery % rising", "US").unparsed == ["delivery % rising"]


def test_parser_keeps_unreadable_clauses():
    p = screener.parse("above the 200-day average and the CEO is charismatic", "US")
    assert len(p.rules) == 1 and p.unparsed == ["the CEO is charismatic"]
    assert "Not understood" in p.read_back()


@pytest.mark.parametrize(
    "name, metrics_",
    [
        (
            "Swing · Pullback",
            {
                "sma_cross:50:200",
                "sma_slope:50",
                "dist_sma_atr:20",
                "lower_closes",
                "dip_vol_ratio",
                "traded_value",
            },
        ),
        (
            "Swing · Breakout",
            {"sma_cross:50:200", "above_high:25", "day_vol_ratio", "rs_3m", "traded_value"},
        ),
        ("Gap scan", {"gap_abs_pct", "rvol", "has_item"}),
    ],
)
def test_presets_parse_completely(name, metrics_):
    for mkt in ("IN", "US"):
        p = screener.parse(screener.preset(name, mkt), mkt)
        assert metrics_ <= {r.metric for r in p.rules} and p.unparsed == []


def _bars(closes, vols=None):
    n = len(closes)
    start = date(2026, 1, 1)
    return pl.DataFrame(
        {
            "date": pl.date_range(start, start + timedelta(days=n - 1), eager=True),
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": vols or [1000.0] * n,
        }
    )


def test_metrics_below_high_and_volume_ratio():
    closes = [100.0] * 249 + [96.2]
    df = _bars(closes, [1000.0] * 230 + [2000.0] * 20)
    assert metrics.compute("below_high_pct", df, None, "IN") == pytest.approx(
        (101 - 96.2) / 101 * 100, abs=0.01
    )
    assert metrics.compute("vol_ratio", df, None, "IN") == pytest.approx(2000 / 1400, abs=0.01)
    assert metrics.compute("lower_closes", _bars([10.0, 9.0, 8.0, 9.0, 8.0, 7.0]), None, "IN") == 4


def test_run_values_next_event_and_exclusion():
    p = screener.parse(screener.preset("Swing · Pullback", "IN"), "IN")
    res = screener.run(p, "NIFTY 50", "IN", asof=date(2026, 5, 29))
    assert res.rows and all(r.next_event for r in res.rows)
    for r in res.passed:
        assert all(rule.passes(r.values[rule.metric]) for rule in p.rules)
    for r in res.excluded:
        assert r.event_sessions is not None and r.event_sessions <= 5
    tbl = res.table("all")
    assert {"Symbol", "Next event", "To 20d avg (ATR)", "RS 3m"} <= set(tbl.columns)


def test_delisted_names_are_not_screened():
    gone = [s for s in universe.names("NIFTY 500", "IN") if universe.delisted_on(s)]
    assert gone
    res = screener.run(
        screener.parse("above the 20-day average", "IN"),
        "NIFTY 500",
        "IN",
        asof=date(2026, 5, 29),
        symbols=gone[:3] + ["SYN-IN-001"],
    )
    assert [r.symbol for r in res.rows] == ["SYN-IN-001"]


def test_triage_bins():
    rule = screener.Rule("rvol", ">=", 2.0, "RVOL at least 2")

    def mk(**kw):
        return screener.Row(
            "X",
            {"rvol": kw.get("v", 3.0)},
            kw.get("ok", True),
            "—",
            None,
            kw.get("k"),
            near_misses=kw.get("near", []),
        )

    assert screener.suggest_triage(mk(ok=False), [rule]) == "Drop"
    assert screener.suggest_triage(mk(k=3), [rule]) == "Research first"
    assert screener.suggest_triage(mk(near=["RVOL"]), [rule]) == "Wait for the setup"
    assert screener.suggest_triage(mk(), [rule]) == "Watch closely"
    assert rule.near_miss(2.1) and not rule.near_miss(3.0)


def test_save_watchlist_requires_reason():
    with pytest.raises(ValueError, match="Reason required for: SYN-IN-002"):
        screener.save_watchlist(
            "Swing · week 39",
            "IN",
            ["SYN-IN-001", "SYN-IN-002"],
            {"SYN-IN-001": "near high, volume 1.5x"},
            "2026-10-03",
        )
    screener.save_watchlist("Swing · week 39", "IN", ["SYN-IN-001"], "near high", "2026-10-03")
    saved = screener.watchlists("IN")[0]
    assert saved["symbols"] == ["SYN-IN-001"] and saved["review_by"] == "2026-10-03"


def test_schedule_gap_scan_job():
    screener.schedule("Gap scan", "IN", "09:08", screener.preset("Gap scan", "IN"), "NIFTY 500")
    from plugai_trade.store import default as store

    job = store().all("jobs", tag="screener")[0]
    assert job["run_time"] == "09:08" and job["kind"] == "Screener"
