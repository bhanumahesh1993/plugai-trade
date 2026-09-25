"""Frankfurter — daily FX reference rates (ECB and other central banks). No key.

Symbols are six letters (``USDINR``) or ``USD/INR``. One rate per day, shown as
O/H/L/C. Rates fall under each central bank's terms; we tag them ``public``.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from . import SourceInfo, register
from .httpkit import get

BASE = "https://api.frankfurter.dev/v1"


def split_pair(symbol: str) -> tuple[str, str]:
    """``USDINR`` / ``USD/INR`` / ``USDINR=X`` → ``("USD", "INR")``."""
    s = symbol.upper().replace("/", "").replace("=X", "")
    if len(s) != 6:
        raise ValueError(f"{symbol}: FX symbols look like USDINR or USD/INR.")
    return s[:3], s[3:]


def rates(base: str, quote: str, start: date, end: date) -> pl.DataFrame:
    """``date, rate`` for one currency pair."""
    resp = get(f"{BASE}/{start.isoformat()}..{end.isoformat()}",
               params={"base": base, "symbols": quote}, min_interval=0.5)
    body = resp.json().get("rates", {})
    rows = [{"date": date.fromisoformat(d), "rate": float(v[quote])}
            for d, v in sorted(body.items()) if quote in v]
    return pl.DataFrame(rows, schema={"date": pl.Date, "rate": pl.Float64})


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    if interval != "1d":
        raise ValueError("Frankfurter publishes one reference rate per day.")
    base, quote = split_pair(symbol)
    df = rates(base, quote, start, end)
    return df.select("date", *[pl.col("rate").alias(c) for c in ("open", "high", "low", "close")],
                     pl.lit(0.0).alias("volume"))


register(SourceInfo(
    name="frankfurter", tier="No signup", markets=("FX",), license_class="public",
    needs="Nothing", fetch=_fetch,
    description="Daily central-bank FX reference rates (USD/INR and 200+ currencies).",
))
