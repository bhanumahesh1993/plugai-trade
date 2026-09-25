"""Screening universes. Offline they are bundled synthetic lists of SYN- tickers.

``SYN-IN-001`` … and ``SYN-US-001`` … are random series from the synthetic data
source: they carry no real market information, so lessons can name them freely.
A few names in each list are marked *delisted* on a date, so the Score-Tester
can show what survivorship does to a test.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import polars as pl

from .. import data

UNIVERSES: dict[str, dict[str, int]] = {
    "IN": {"NIFTY 50": 50, "NIFTY 500": 500, "all NSE": 800},
    "US": {"S&P 500": 500, "Nasdaq-100": 100, "all US >$5": 800},
}
BENCHMARK = {"IN": "NIFTY", "US": "SPY"}
DELISTED_EVERY = 37  # one name in 37 is delisted in the synthetic lists


def names(universe: str, market: str) -> list[str]:
    """Members of a universe (synthetic, offline)."""
    n = UNIVERSES[market][universe]
    return [f"SYN-{market}-{i:03d}" for i in range(1, n + 1)]


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def delisted_on(symbol: str) -> date | None:
    """The synthetic delisting date of a name, or None if it is still listed."""
    try:
        i = int(symbol.rsplit("-", 1)[-1])
    except ValueError:
        return None
    if i % DELISTED_EVERY:
        return None
    return date(2021, 1, 4) + timedelta(days=_seed(symbol) % 1500)


@lru_cache(maxsize=4096)
def _bars(symbol: str, market: str, start: date, end: date) -> pl.DataFrame:
    return data.get(symbol, market=market, start=start, end=end, source="synthetic")


def bars(symbol: str, market: str, start: date, end: date) -> pl.DataFrame:
    """Daily bars with provenance; a delisted name stops at its delisting date.

    India names also get a synthetic ``deliv_pct`` column (delivery % of volume).
    """
    df = _bars(symbol, market, start, end)
    gone = delisted_on(symbol)
    if gone is not None:
        df = df.filter(pl.col("date") <= gone)
    if market == "IN" and df.height:
        rng = np.random.default_rng(_seed(symbol + "deliv"))
        base = 25 + _seed(symbol) % 45
        deliv = np.clip(base + rng.normal(0, 8, df.height), 5, 95)
        df = df.with_columns(pl.Series("deliv_pct", deliv.round(1)))
    return df
