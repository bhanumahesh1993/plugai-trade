"""The wall: a window on the bars that ends at the last completed bar.

A strategy never receives the price table. It receives a :class:`DataView`
whose every accessor stops at the current bar. There is no method that returns
a later bar, so a rule cannot ask for one — asking raises :class:`LookAheadError`.
Indicators are read through the same window, and each value at bar *t* is built
only from bars up to *t* (see ``plugai_trade.indicators``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import numpy as np
import polars as pl


class LookAheadError(LookupError):
    """Raised when strategy code asks for a bar after the last completed one."""


_FIELDS = ("open", "high", "low", "close", "volume")


def _rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(x.shape, np.nan)
    if n <= len(x):
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    alpha = 2.0 / (n + 1)
    out = np.empty_like(x)
    acc = x[0]
    for i, v in enumerate(x):
        acc = v if i == 0 else alpha * v + (1 - alpha) * acc
        out[i] = acc
    out[: n - 1] = np.nan
    return out


def _prior_extreme(x: np.ndarray, n: int, fn: Callable) -> np.ndarray:
    """Max/min of the ``n`` bars *before* bar t (so "a new 52-week high" can be tested)."""
    out = np.full(x.shape, np.nan)
    if len(x) > n:
        win = np.lib.stride_tricks.sliding_window_view(x, n)[:-1]
        out[n:] = fn(win, axis=1)
    return out


def _rsi(close: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(close, prepend=close[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    a = 1.0 / n
    ru = np.empty_like(close)
    rd = np.empty_like(close)
    u = v = 0.0
    for i in range(len(close)):
        u = a * up[i] + (1 - a) * u
        v = a * dn[i] + (1 - a) * v
        ru[i], rd[i] = u, v
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + ru / rd)
    out[rd == 0] = 100.0
    out[:n] = np.nan
    return out


def _vol(close: np.ndarray, n: int) -> np.ndarray:
    """Standard deviation of daily returns over the last ``n`` sessions (daily units)."""
    r = np.full(close.shape, np.nan)
    r[1:] = close[1:] / close[:-1] - 1
    out = np.full(close.shape, np.nan)
    if len(close) > n:
        win = np.lib.stride_tricks.sliding_window_view(r[1:], n)
        out[n:] = win.std(axis=1, ddof=1)
    return out


class Series:
    """Precomputed columns for one instrument. Private to the engine; never given to strategies."""

    def __init__(self, bars: pl.DataFrame):
        if bars.is_empty():
            raise ValueError("no bars to test")
        bars = bars.sort("date")
        self.dates: list[date] = bars["date"].to_list()
        self.cols = {f: bars[f].cast(pl.Float64).to_numpy().astype(float) for f in _FIELDS
                     if f in bars.columns}
        self._cache: dict[tuple[str, int], np.ndarray] = {}

    def __len__(self) -> int:
        return len(self.dates)

    def indicator(self, kind: str, n: int) -> np.ndarray:
        key = (kind, int(n))
        if key not in self._cache:
            c = self.cols["close"]
            build = {
                "sma": lambda: _rolling_mean(c, n),
                "ema": lambda: _ema(c, n),
                "high_n": lambda: _prior_extreme(self.cols.get("high", c), n, np.max),
                "low_n": lambda: _prior_extreme(self.cols.get("low", c), n, np.min),
                "rsi": lambda: _rsi(c, n),
                "close_ago": lambda: np.concatenate([np.full(min(n, len(c)), np.nan), c[:-n]])
                if n < len(c) else np.full(c.shape, np.nan),
                "vol": lambda: _vol(c, n),
            }[kind]
            arr = build()
            arr.setflags(write=False)
            self._cache[key] = arr
        return self._cache[key]


class DataView:
    """What a strategy sees: bars ``0..t`` of one instrument, and nothing after.

    ``view.close()`` is the last completed close; ``view.close(1)`` the one
    before. ``view.sma(50)`` is the 50-day average *as of* the last completed
    bar. Negative look-backs, dates after ``view.today`` and positional
    indexing past the end all raise :class:`LookAheadError`.
    """

    __slots__ = ("_s", "_t", "symbol")

    def __init__(self, series: Series, t: int, symbol: str = ""):
        self._s = series
        self._t = int(t)
        self.symbol = symbol

    # ---------------------------------------------------------------- basics
    def __len__(self) -> int:
        return self._t + 1

    @property
    def today(self) -> date:
        """Date of the last completed bar (the newest thing a strategy may know)."""
        return self._s.dates[self._t]

    def _idx(self, ago: int) -> int:
        ago = int(ago)
        if ago < 0:
            raise LookAheadError(f"{-ago} bar(s) into the future requested on {self.today}; "
                                 "strategies see only completed bars")
        i = self._t - ago
        return i if i >= 0 else -1

    def _get(self, arr: np.ndarray, ago: int) -> float:
        i = self._idx(ago)
        return float("nan") if i < 0 else float(arr[i])

    def value(self, field: str, ago: int = 0) -> float:
        if field not in self._s.cols:
            raise KeyError(field)
        return self._get(self._s.cols[field], ago)

    def open(self, ago: int = 0) -> float:
        return self.value("open", ago)

    def high(self, ago: int = 0) -> float:
        return self.value("high", ago)

    def low(self, ago: int = 0) -> float:
        return self.value("low", ago)

    def close(self, ago: int = 0) -> float:
        return self.value("close", ago)

    def column(self, field: str) -> np.ndarray:
        """A read-only copy of one column up to the last completed bar."""
        out = self._s.cols[field][: self._t + 1].copy()
        out.setflags(write=False)
        return out

    def __getitem__(self, key: str | int) -> np.ndarray | dict[str, float]:
        if isinstance(key, str):
            return self.column(key)
        i = int(key)
        if i > self._t or i < -(self._t + 1):
            raise LookAheadError(f"bar {i} is not in the window (last completed bar is {self._t})")
        i = i % (self._t + 1)
        return {f: float(a[i]) for f, a in self._s.cols.items()}

    def at(self, when: date) -> dict[str, float]:
        """The bar on a given date; later dates raise :class:`LookAheadError`."""
        if when > self.today:
            raise LookAheadError(f"{when} is after the last completed bar ({self.today})")
        i = self._s.dates.index(when)
        return self[i]

    # ------------------------------------------------------------ indicators
    def indicator(self, kind: str, n: int, ago: int = 0) -> float:
        return self._get(self._s.indicator(kind, n), ago)

    def sma(self, n: int, ago: int = 0) -> float:
        return self.indicator("sma", n, ago)

    def ema(self, n: int, ago: int = 0) -> float:
        return self.indicator("ema", n, ago)

    def rsi(self, n: int = 14, ago: int = 0) -> float:
        return self.indicator("rsi", n, ago)

    def daily_vol(self, n: int = 20, ago: int = 0) -> float:
        """Standard deviation of daily returns over the last ``n`` sessions."""
        return self.indicator("vol", n, ago)
