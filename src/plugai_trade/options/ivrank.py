"""IV rank and IV percentile from a year of (synthetic) at-the-money implied volatility.

Offline, each underlying gets a deterministic synthetic IV year. For NIFTY it is
the book's year (Chapter 22): low 9.7%, one short spike to 24.6%, today 14.0%,
lower than today on 152 of the previous 251 sessions — IV rank 29, percentile 61.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

# symbol -> (today, low, high, share of previous sessions below today)
_PROFILE = {
    "NIFTY": (14.0, 9.7, 24.6, 152 / 251),
    "BANKNIFTY": (16.0, 11.5, 27.0, 0.55),
    "SENSEX": (13.8, 9.5, 24.0, 0.60),
    "SPY": (16.0, 11.0, 32.0, 0.58),
    "SPX": (16.0, 11.0, 32.0, 0.58),
    "QQQ": (20.0, 14.5, 36.0, 0.55),
}


@dataclass
class IVRank:
    """IV rank and percentile, the series they came from, and the events inside it."""

    symbol: str
    window: int
    iv: float
    low: float
    high: float
    rank: float
    percentile: float
    below_days: int
    dates: list[date] = field(repr=False)
    series: list[float] = field(repr=False)
    events: list[tuple[date, str]] = field(repr=False)
    source: str = "Synthetic ATM IV (offline lesson series)"

    def facts(self) -> list[str]:
        """Numbers the AI may cite."""
        return [f"IV today: {self.iv:.1f}%",
                f"IV range over {self.window} sessions: {self.low:.1f}% to {self.high:.1f}%",
                f"IV rank: {self.rank:.0f} = ({self.iv:.1f} − {self.low:.1f}) ÷ ({self.high:.1f} − {self.low:.1f})",
                f"IV percentile: {self.percentile:.0f} (IV lower on {self.below_days} of "
                f"{self.window - 1} previous sessions)",
                f"IV series: {self.source}, window {self.window} sessions"]

    def __str__(self) -> str:
        return (f"{self.symbol} IV {self.iv:.1f}% · IV rank {self.rank:.0f} · IV percentile "
                f"{self.percentile:.0f} (range {self.low:.1f}–{self.high:.1f}%, {self.window} sessions)")


def _seed(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)


def _profile(symbol: str) -> tuple[float, float, float, float]:
    if symbol in _PROFILE:
        return _PROFILE[symbol]
    rng = np.random.default_rng(_seed(symbol))
    low = float(rng.uniform(15, 25))
    return (round(low * 1.35, 1), round(low, 1), round(low * 2.4, 1), float(rng.uniform(0.3, 0.8)))


def synthetic_iv_series(symbol: str, window: int = 252) -> tuple[list[date], list[float], int]:
    """A deterministic IV year with the profile's low, high, today and below-today count.

    Returns (business dates, IV in %, index of the spike's first day).
    """
    today_iv, low, high, share = _profile(symbol.upper())
    n = window - 1  # previous sessions
    rng = np.random.default_rng(_seed(symbol.upper()))
    shape = np.cumsum(rng.normal(0, 1, n))
    shape -= np.linspace(shape[0], shape[-1], n) * 0.5
    spike = int(n * 0.35)
    shape[spike:spike + 4] += np.array([6.0, 9.0, 5.0, 2.0]) * shape.std() + shape.max()
    order = np.argsort(np.argsort(shape))  # rank of each day, 0 = lowest
    below = int(round(share * n))
    below = min(max(below, 1), n - 5)
    q = np.empty(n)
    lo_part = order < below
    q[lo_part] = low + (today_iv - 0.05 - low) * (order[lo_part] / max(below - 1, 1)) ** 1.3
    hi_rank = order[~lo_part] - below
    top = n - below - 1
    normal_high = today_iv + (high - today_iv) * 0.35
    frac = hi_rank / max(top, 1)
    q[~lo_part] = np.where(frac < 0.985, today_iv + 0.05 + (normal_high - today_iv) * frac / 0.985,
                           normal_high + (high - normal_high) * (frac - 0.985) / 0.015)
    q[order == n - 1] = high
    series = [round(float(x), 2) for x in q] + [today_iv]
    end = date.today()
    days: list[date] = []
    d = end
    while len(days) < window:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1], series, spike


def iv_rank(symbol: str, window: int = 252) -> IVRank:
    """IV rank = (today − low) ÷ (high − low); IV percentile = share of earlier sessions below today."""
    if window < 20:
        raise ValueError("window must be at least 20 sessions")
    dates, series, spike = synthetic_iv_series(symbol, window)
    arr = np.asarray(series)
    today, low, high = float(arr[-1]), float(arr.min()), float(arr.max())
    below = int((arr[:-1] < today).sum())
    rank = 100.0 * (today - low) / (high - low) if high > low else 0.0
    events = [(dates[spike], "IV spike (synthetic event)")]
    return IVRank(symbol=symbol.upper(), window=window, iv=today, low=low, high=high,
                  rank=round(rank, 1), percentile=round(100.0 * below / (window - 1), 1),
                  below_days=below, dates=dates, series=series, events=events)
