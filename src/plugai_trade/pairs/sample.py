"""The lesson-26 synthetic pairs: SYN-A / SYN-B (cointegrated) and SYN-C / SYN-D (not).

SYN-A / SYN-B follow the book's recipe: log A = c + 1.168 × log B + s, where B is
a random walk and s a mean-reverting spread; on session 453 the spread shifts by
−0.11 (the "demerger" break). The formation window (sessions 1–250) is built so
the frozen fit reads β 1.168, spread sd 0.0228, half-life 6.1 sessions and an
Engle–Granger t of −3.71, as printed in Chapter 26.

SYN-C / SYN-D move together (daily-return correlation 0.94) but their gap is a
random walk: the test fails (t ≈ −1.57) and the half-life is about 37 sessions.

The 500 book sessions end on 2026-05-29; later dates continue the same process
so any window up to today returns bars. Every series is deterministic.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import polars as pl

BOOK_END = date(2026, 5, 29)
SESSIONS = 500
FORMATION = 250
BREAK_SESSION = 453  # 1-based
SYMBOLS = ("SYN-A", "SYN-B", "SYN-C", "SYN-D")
_EXTRA = 1300  # continuation sessions after the book window (~5 years)


def _business_days_back(end: date, n: int) -> list[date]:
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


def _business_days_after(start: date, n: int) -> list[date]:
    days, d = [], start + timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _ar(e: np.ndarray, phi: float, s0: float = 0.0) -> np.ndarray:
    s = np.empty(len(e))
    prev = s0
    for t, x in enumerate(e):
        prev = phi * prev + x
        s[t] = prev
    return s


def _pair_ab() -> tuple[np.ndarray, np.ndarray]:
    """Log prices of SYN-A and SYN-B for the 500 book sessions plus continuation."""
    beta, phi, sd = 1.168, 0.90, 0.0228
    rng = np.random.default_rng(3353)
    lb = np.log(85.0) + np.cumsum(rng.normal(0.0002, 0.014, SESSIONS))
    e = rng.normal(0, 1, SESSIONS)
    s_raw = np.concatenate([[0.0], _ar(e[1:], phi)])
    x = np.column_stack([np.ones(FORMATION), lb[:FORMATION]])
    c, *_ = np.linalg.lstsq(x, s_raw[:FORMATION], rcond=None)
    scale = sd / (s_raw[:FORMATION] - x @ c).std(ddof=1)
    s = (s_raw - (c[0] + c[1] * lb)) * scale
    s[BREAK_SESSION - 1:] -= 0.11
    # continuation: same process after the book window
    rng2 = np.random.default_rng(33531)
    lb2 = lb[-1] + np.cumsum(rng2.normal(0.0002, 0.014, _EXTRA))
    s_cont = _ar(rng2.normal(0, 1, _EXTRA), phi, s_raw[-1]) - (c[0] + c[1] * lb2)
    s2 = s_cont * scale - 0.11
    lb_all = np.concatenate([lb, lb2])
    s_all = np.concatenate([s, s2])
    la_all = np.log(100.0) - beta * np.log(85.0) + beta * lb_all + s_all
    return la_all, lb_all


def _pair_cd() -> tuple[np.ndarray, np.ndarray]:
    """Log prices of SYN-C and SYN-D: correlated, not cointegrated."""
    rng = np.random.default_rng(10003)
    n = SESSIONS + _EXTRA
    ld = np.log(62.0) + np.cumsum(rng.normal(0.0002, 0.014, SESSIONS))
    s = np.cumsum(rng.normal(0, 0.0051, SESSIONS))
    rng2 = np.random.default_rng(100031)
    ld = np.concatenate([ld, ld[-1] + np.cumsum(rng2.normal(0.0002, 0.014, n - SESSIONS))])
    s = np.concatenate([s, s[-1] + np.cumsum(rng2.normal(0, 0.0051, n - SESSIONS))])
    lc = np.log(120.0) - np.log(62.0) + ld + s
    return lc, ld


@lru_cache(maxsize=1)
def _frame() -> pl.DataFrame:
    days = _business_days_back(BOOK_END, SESSIONS) + _business_days_after(BOOK_END, _EXTRA)
    la, lb = _pair_ab()
    lc, ld = _pair_cd()
    return pl.DataFrame({"date": days, "SYN-A": np.exp(la), "SYN-B": np.exp(lb),
                         "SYN-C": np.exp(lc), "SYN-D": np.exp(ld)})


def book_window() -> tuple[date, date]:
    """First and last date of the book's 500 sessions."""
    days = _frame()["date"]
    return days[0], days[SESSIONS - 1]


def closes(symbol: str, start: date | None = None, end: date | None = None) -> pl.DataFrame:
    """``date, close`` for one sample symbol (defaults to the book's 500 sessions)."""
    first, last = book_window()
    start, end = start or first, end or last
    f = _frame().select("date", pl.col(symbol.upper()).alias("close"))
    return f.filter((pl.col("date") >= start) & (pl.col("date") <= end))


def bars(symbol: str, start: date, end: date) -> pl.DataFrame:
    """OHLCV bars in the house schema, for ``data.synthetic`` to delegate SYN-A…SYN-D to."""
    c = closes(symbol, start, end)
    close = c["close"].to_numpy()
    open_ = np.concatenate([close[:1], close[:-1]])
    return pl.DataFrame({"date": c["date"], "open": open_,
                         "high": np.maximum(open_, close) * 1.004,
                         "low": np.minimum(open_, close) * 0.996,
                         "close": close, "volume": np.full(len(close), 250_000.0)})
