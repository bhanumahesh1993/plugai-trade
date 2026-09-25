from datetime import date
from pathlib import Path

import polars as pl

from plugai_trade import costs, data, paper_guard, reference


def test_synthetic_deterministic():
    a = data.get("NIFTY", "IN", "2025-01-01", "2025-06-30", source="synthetic")
    b = data.get("NIFTY", "IN", "2025-01-01", "2025-06-30", source="synthetic")
    assert a.height > 100 and a["close"].to_list() == b["close"].to_list()
    assert set(data.PROVENANCE) <= set(a.columns)
    assert (a["high"] >= a["low"]).all()


def test_synthetic_levels_realistic():
    df = data.get("NIFTY", "IN", "2025-12-20", "2026-01-10", source="synthetic")
    assert 18000 < df["close"].mean() < 30000


def test_compare_flags():
    a = data.get("SPY", "US", "2025-01-01", "2025-02-28", source="synthetic")
    b = a.with_columns((pl.col("close") * 1.01).alias("close"))
    out = data.compare(a, b)
    assert (out["status"] == "disagree").all()


def test_india_futures_cost_matches_book_ch14():
    # Chapter 14: one NIFTY futures lot round trip priced at ₹960.14 with the book's assumptions.
    lot = reference.lot_size("NIFTY")
    assert lot == 65
    buy = 24800 * lot
    sell = 24800 * lot
    c = costs.india_round_trip(buy, sell, "futures")
    assert c["brokerage"] == 40.0
    assert abs(c["stt"] - sell * 0.0005) < 0.01
    assert 900 < c["total"] < 1000


def test_no_order_code():
    root = Path(paper_guard.__file__).parent
    assert paper_guard.scan_path(root) == []


def test_education_cutoff():
    assert data.education_cutoff("NIFTY", "IN") is None
    assert data.education_cutoff("SOMESTOCK", "IN") <= date.today()
