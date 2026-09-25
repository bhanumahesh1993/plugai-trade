"""The numbers behind every rule, computed in code from daily bars.

A value on the as-of date uses bars up to and including that date only.
"""

from __future__ import annotations

import hashlib
from datetime import date

import numpy as np
import polars as pl

from .. import indicators as ind


def _last(df: pl.DataFrame, col: str) -> float | None:
    v = df[col][-1] if df.height else None
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def _sma(close: np.ndarray, n: int, back: int = 0) -> float | None:
    end = len(close) - back
    if end < n:
        return None
    return float(close[end - n : end].mean())


def _atr(df: pl.DataFrame, n: int = 14) -> float | None:
    return _last(ind.atr(df, n), f"atr_{n}") if df.height > n else None


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def premarket(symbol: str, asof: date) -> dict[str, float | str | None]:
    """A synthetic pre-open snapshot for the session after ``asof``.

    Offline stand-in for the indicated price (India, ~09:08 IST) or pre-market
    quote (US): a heavy-tailed gap, relative volume and, sometimes, a
    time-stamped item. Labelled synthetic everywhere it is shown.
    """
    rng = np.random.default_rng(_seed(f"{symbol}{asof}"))
    gap = float(rng.standard_t(3) * 0.9)
    rvol = float(np.exp(rng.normal(0.0, 0.45)) * (1 + abs(gap) / 1.5))
    item = None
    if rng.random() < min(0.9, 0.15 + abs(gap) / 4):
        item = str(rng.choice(["Results", "Filing", "Block deal", "Rating change", "Contract win"]))
    return {"gap_pct": round(gap, 2), "rvol": round(rvol, 2), "item": item}


def compute(
    metric: str,
    df: pl.DataFrame,
    index_df: pl.DataFrame | None,
    market: str,
    symbol: str = "",
    asof: date | None = None,
) -> float | None:
    """Value of one metric (``name`` or ``name:arg``) on the last bar of ``df``."""
    base, _, arg = metric.partition(":")
    if df.height < 2:
        return None
    close = df["close"].to_numpy()
    vol = df["volume"].to_numpy()
    last = float(close[-1])
    if base == "close":
        return round(last, 2)
    if base == "below_high_pct":
        hi = float(df["high"].to_numpy()[-250:].max())
        return round((hi - last) / hi * 100, 2)
    if base == "vol_ratio":
        a, b = _sma(vol, 20), _sma(vol, 50)
        return round(a / b, 2) if a and b else None
    if base == "day_vol_ratio":
        return round(float(vol[-1] / vol[-21:-1].mean()), 2) if len(vol) > 21 else None
    if base == "dip_vol_ratio":
        if len(vol) < 25:
            return None
        return round(float(vol[-5:].mean() / vol[-25:-5].mean()), 2)
    if base == "traded_value":
        tv = np.median((close * vol)[-20:])
        return round(float(tv / (1e7 if market == "IN" else 1e6)), 1)
    if base == "close_vs_sma":
        m = _sma(close, int(arg))
        return round((last / m - 1) * 100, 2) if m else None
    if base == "sma_cross":
        a, b = (int(x) for x in arg.split(":"))
        ma, mb = _sma(close, a), _sma(close, b)
        return round((ma / mb - 1) * 100, 2) if ma and mb else None
    if base == "sma_slope":
        n = int(arg)
        now, then = _sma(close, n), _sma(close, n, back=10)
        return round((now / then - 1) * 100, 2) if now and then else None
    if base == "rsi":
        return round(_last(ind.rsi(df, int(arg or 14)), f"rsi_{int(arg or 14)}") or 0.0, 1)
    if base == "dist_sma_atr":
        m, a = _sma(close, int(arg or 20)), _atr(df)
        return round((last - m) / a, 2) if m and a else None
    if base == "lower_closes":
        return float(int((np.diff(close[-6:]) < 0).sum()))
    if base == "above_high":
        n = int(arg or 25)
        if len(close) <= n:
            return None
        prior = float(df["high"].to_numpy()[-n - 1 : -1].max())
        return round((last / prior - 1) * 100, 2)
    if base == "base_range_atr":
        n, a = int(arg or 25), _atr(df)
        if not a or df.height <= n:
            return None
        hi, lo = df["high"].to_numpy()[-n - 1 : -1], df["low"].to_numpy()[-n - 1 : -1]
        return round(float((hi.max() - lo.min()) / a), 2)
    if base == "rs_3m":
        if index_df is None or index_df.height < 64 or len(close) < 64:
            return None
        ic = index_df["close"].to_numpy()
        return round(((last / close[-64]) - (ic[-1] / ic[-64])) * 100, 2)
    if base in ("deliv_pct", "deliv_pct_20d", "deliv_ratio"):
        if "deliv_pct" not in df.columns:
            return None
        d = df["deliv_pct"].to_numpy()
        if base == "deliv_pct":
            return float(d[-1])
        if base == "deliv_pct_20d":
            return round(float(d[-20:].mean()), 1)
        return round(float(d[-1] / d[-21:-1].mean()), 2)
    if base in ("gap_pct", "gap_abs_pct", "rvol", "has_item"):
        pm = premarket(symbol, asof or df["date"][-1])
        if base == "gap_pct":
            return pm["gap_pct"]  # type: ignore[return-value]
        if base == "gap_abs_pct":
            return abs(pm["gap_pct"])  # type: ignore[arg-type]
        if base == "rvol":
            return pm["rvol"]  # type: ignore[return-value]
        return 1.0 if pm["item"] else 0.0
    raise KeyError(f"unknown metric {metric!r}")


def atr_value(df: pl.DataFrame) -> float | None:
    """ATR(14) on the last bar (shown with the swing presets)."""
    return _atr(df)
