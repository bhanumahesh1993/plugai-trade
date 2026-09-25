"""Synthetic OHLCV — the offline default. Deterministic per symbol.

Same symbol, same dates → same bars, on every machine, forever. Levels are
roughly realistic (NIFTY near 24,000, SPY near 560) so lessons read naturally,
but the series is random: it contains no real market information.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from datetime import date, timedelta

import numpy as np
import polars as pl

from . import SourceInfo, register

LEVELS = {
    "NIFTY": 24000.0, "BANKNIFTY": 52000.0, "SENSEX": 79000.0, "FINNIFTY": 23500.0,
    "MIDCPNIFTY": 12500.0, "INDIAVIX": 13.0, "SPY": 560.0, "QQQ": 480.0, "DIA": 420.0,
    "IWM": 215.0, "SPX": 5600.0, "NDX": 19800.0, "VIX": 16.0, "BTC": 60000.0, "ETH": 2600.0,
    "USDINR": 84.0, "SYN-A": 100.0, "SYN-B": 85.0,
}


def _seed(symbol: str) -> int:
    return int(hashlib.sha256(symbol.upper().encode()).hexdigest()[:8], 16)


def _business_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


HORIZON_END = date(2035, 12, 31)


@lru_cache(maxsize=64)
def _master(symbol: str, vol: float, drift: float) -> pl.DataFrame:
    """The whole 2015–2035 series for a symbol, generated once. Windows are slices of it,
    so the same date has the same price whatever window you ask for."""
    anchor = date(2015, 1, 1)
    all_days = _business_days(anchor, HORIZON_END)
    rng = np.random.default_rng(_seed(symbol))
    n = len(all_days)
    rets = rng.normal(drift, vol, n)
    # volatility clustering so ATR/vol features behave like markets
    regime = np.repeat(rng.choice([0.7, 1.0, 1.6], size=n // 40 + 1, p=[0.4, 0.45, 0.15]), 40)[:n]
    rets = rets * regime
    level = LEVELS.get(symbol.upper(), 100.0 + _seed(symbol) % 900)
    path = np.cumsum(rets)
    # Pin the series so it sits at `level` on the first business day of 2026.
    pin = sum(1 for d in all_days if d < date(2026, 1, 1))
    close = level * np.exp(path - path[pin])
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, vol / 4, n))
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    volume = (rng.lognormal(13, 0.35, n) * regime).round()
    return pl.DataFrame({"date": all_days, "open": open_, "high": hi, "low": lo, "close": close,
                         "volume": volume})


def bars(symbol: str, start: date, end: date, vol: float = 0.011, drift: float = 0.0003) -> pl.DataFrame:
    """Random-walk bars; any window is an exact slice of one fixed master series."""
    df = _master(symbol.upper(), vol, drift)
    return df.filter((pl.col("date") >= start) & (pl.col("date") <= end))


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    if symbol.upper() in ("SYN-A", "SYN-B", "SYN-C", "SYN-D") and interval == "1d":
        # The book's cointegrated / broken teaching pairs (Chapter 26).
        from ..pairs.sample import bars as pair_bars
        return pair_bars(symbol.upper(), start, end)
    if interval != "1d":
        return intraday(symbol, end, interval)
    return bars(symbol, start, end)


def intraday(symbol: str, day: date, interval: str = "5m") -> pl.DataFrame:
    """One synthetic session of intraday bars (IST 09:15–15:30 or ET 09:30–16:00)."""
    mins = int(interval.rstrip("m")) if interval.endswith("m") else 5
    daily = bars(symbol, day - timedelta(days=10), day)
    ref = float(daily["close"][-1]) if len(daily) else LEVELS.get(symbol.upper(), 100.0)
    rng = np.random.default_rng(_seed(symbol + str(day) + interval))
    n = max(1, 375 // mins)
    r = rng.normal(0, 0.0012, n)
    c = ref * np.exp(np.cumsum(r))
    o = np.concatenate([[ref], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0006, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0006, n)))
    v = rng.lognormal(10, 0.5, n).round()
    stamps = [f"{day.isoformat()}T{9 + (15 + i * mins) // 60:02d}:{(15 + i * mins) % 60:02d}"
              for i in range(n)]
    return pl.DataFrame({"date": [day] * n, "time": stamps, "open": o, "high": h, "low": lo,
                         "close": c, "volume": v})


register(SourceInfo(
    name="synthetic", tier="No signup", markets=("IN", "US", "FX", "CRYPTO", "ANY"),
    license_class="public", needs="Nothing", fetch=_fetch,
    description="Offline, deterministic random series. Every chapter runs on it.",
))
