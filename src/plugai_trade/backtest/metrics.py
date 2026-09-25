"""Performance arithmetic, computed in code (never by a model)."""

from __future__ import annotations

import math
from datetime import date

import numpy as np

TRADING_DAYS = 252


def returns(equity: np.ndarray) -> np.ndarray:
    """Period returns of an equity curve (length n-1)."""
    e = np.asarray(equity, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = e[1:] / e[:-1] - 1
    return np.nan_to_num(r)


def sharpe_daily(r: np.ndarray) -> float:
    """Per-period Sharpe (mean / standard deviation), 0 when flat."""
    r = np.asarray(r, dtype=float)
    if len(r) < 2:
        return 0.0
    sd = r.std(ddof=1)
    return 0.0 if sd < 1e-12 else float(r.mean() / sd)


def sharpe(r: np.ndarray) -> float:
    """Annualised Sharpe ratio (cash earns nothing, as in the book's tests)."""
    return sharpe_daily(r) * math.sqrt(TRADING_DAYS)


def drawdown(equity: np.ndarray) -> np.ndarray:
    """Fraction below the running high (0 at a new high, negative below)."""
    e = np.asarray(equity, dtype=float)
    peak = np.maximum.accumulate(e)
    return e / peak - 1


def worst_drawdown_story(dates: list[date], equity: np.ndarray) -> dict:
    """Depth, start, trough and months below the earlier high for the deepest drawdown."""
    dd = drawdown(equity)
    trough = int(np.argmin(dd))
    if dd[trough] >= 0:
        return {"depth": 0.0, "start": None, "trough": None, "recovered": None, "months_below": 0}
    start = int(np.argmax(equity[: trough + 1]))
    after = np.where(equity[trough:] >= equity[start])[0]
    end = trough + int(after[0]) if len(after) else len(equity) - 1
    return {"depth": float(dd[trough]), "start": dates[start], "trough": dates[trough],
            "recovered": dates[end] if len(after) else None,
            "months_below": _months(dates[start], dates[end])}


def longest_underwater_months(dates: list[date], equity: np.ndarray) -> int:
    """Longest stretch, in months, spent below a previous high."""
    e = np.asarray(equity, dtype=float)
    peak_i, best = 0, 0
    for i in range(1, len(e)):
        if e[i] >= e[peak_i]:
            best = max(best, _months(dates[peak_i], dates[i]))
            peak_i = i
    return max(best, _months(dates[peak_i], dates[-1]))


def _months(a: date, b: date) -> int:
    return max(0, round((b - a).days / 30.44))


def years(dates: list[date]) -> float:
    return max((dates[-1] - dates[0]).days / 365.25, 1e-9)


def cagr(equity: np.ndarray, dates: list[date]) -> float:
    e0, e1 = float(equity[0]), float(equity[-1])
    if e0 <= 0 or e1 <= 0:
        return -1.0
    return (e1 / e0) ** (1 / years(dates)) - 1


def moments(r: np.ndarray) -> tuple[float, float]:
    """Skewness and (non-excess) kurtosis of returns, for the deflated Sharpe."""
    r = np.asarray(r, dtype=float)
    if len(r) < 4 or r.std() < 1e-12:
        return 0.0, 3.0
    z = (r - r.mean()) / r.std()
    return float((z ** 3).mean()), float((z ** 4).mean())


def yearly_pnl(dates: list[date], equity: np.ndarray) -> dict[int, float]:
    """Money made or lost in each calendar year."""
    out: dict[int, float] = {}
    prev = float(equity[0])
    for i, d in enumerate(dates):
        nxt = dates[i + 1] if i + 1 < len(dates) else None
        if nxt is None or nxt.year != d.year:
            out[d.year] = float(equity[i]) - prev
            prev = float(equity[i])
    return out


def yearly_returns(dates: list[date], equity: np.ndarray) -> dict[int, float]:
    out: dict[int, float] = {}
    prev = float(equity[0])
    for i, d in enumerate(dates):
        nxt = dates[i + 1] if i + 1 < len(dates) else None
        if nxt is None or nxt.year != d.year:
            out[d.year] = float(equity[i]) / prev - 1 if prev else 0.0
            prev = float(equity[i])
    return out
