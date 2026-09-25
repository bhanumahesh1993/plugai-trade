"""Volatility scenarios: low / middle / high bands for the next sessions' daily range.

A time-series foundation model (Chronos, TimesFM) is optional and never bundled.
The default engine is local and needs no download: it looks at how the next
``horizon`` sessions' average range compared with the trailing 20-session range
at every earlier date, and scales today's trailing range by those quantiles.
It is always shown beside the "last 20 sessions continue" baseline and scored
on past month-ends using only data available at each one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

ENGINE = "Empirical ratio bands (local; no model download)"


def _ranges(bars: pl.DataFrame) -> tuple[list, np.ndarray]:
    b = bars.sort("date")
    rng = ((b["high"] - b["low"]) / b["close"] * 100).to_numpy().astype(float)
    return b["date"].to_list(), rng


def _ratios(rng: np.ndarray, horizon: int, lookback: int) -> tuple[np.ndarray, np.ndarray]:
    """(trailing mean ending at i, next-``horizon`` mean ÷ trailing mean) for every row i."""
    n = len(rng)
    trail = np.full(n, np.nan)
    fut = np.full(n, np.nan)
    c = np.concatenate([[0.0], np.cumsum(rng)])
    i = np.arange(lookback - 1, n)
    trail[i] = (c[i + 1] - c[i + 1 - lookback]) / lookback
    j = np.arange(0, n - horizon)
    fut[j] = (c[j + horizon + 1] - c[j + 1]) / horizon
    return trail, fut / trail


def _bands_at(trail: np.ndarray, ratio: np.ndarray, t: int, horizon: int,
              q: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """Bands for sessions t+1..t+horizon using only ratios whose future ended by t."""
    known = ratio[:max(t - horizon + 1, 0)]
    known = known[np.isfinite(known)]
    baseline = float(trail[t])
    if len(known) < 50:
        return baseline, baseline, baseline, baseline
    lo, mid, hi = np.quantile(known, q)
    return baseline * lo, baseline * mid, baseline * hi, baseline


@dataclass
class Scenarios:
    """Calm / typical / stormy daily-range bands for the next ``horizon`` sessions."""

    as_of: object
    horizon: int
    low: float
    middle: float
    high: float
    baseline: float
    engine: str = ENGINE

    def facts(self) -> list[str]:
        return [(f"Volatility scenarios as of {self.as_of}, next {self.horizon} sessions "
                 "(average daily high–low range, % of close)"),
                f"Low (calm) band: {self.low:.2f}%", f"Middle band: {self.middle:.2f}%",
                f"High (stormy) band: {self.high:.2f}%",
                f"Baseline 'last 20 sessions continue': {self.baseline:.2f}%",
                f"Engine: {self.engine}"]

    def to_dict(self) -> dict[str, object]:
        return {"as_of": str(self.as_of), "horizon": self.horizon, "low_pct": self.low,
                "middle_pct": self.middle, "high_pct": self.high, "baseline_pct": self.baseline,
                "engine": self.engine}


def vol_scenarios(bars: pl.DataFrame, horizon: int = 10, lookback: int = 20,
                  quantiles: tuple[float, float, float] = (0.1, 0.5, 0.9)) -> Scenarios:
    """Low / middle / high bands for the next ``horizon`` sessions' daily range."""
    dates, rng = _ranges(bars)
    t = len(rng) - 1
    if t < lookback + horizon:
        raise ValueError("need more history for volatility scenarios")
    trail, ratio = _ratios(rng, horizon, lookback)
    lo, mid, hi, base = _bands_at(trail, ratio, t, horizon, quantiles)
    return Scenarios(as_of=dates[t], horizon=horizon, low=lo, middle=mid, high=hi, baseline=base)


def scored_history(bars: pl.DataFrame, horizon: int = 10, lookback: int = 20,
                   min_history: int = 252) -> pl.DataFrame:
    """The same forecast made at every past month-end, scored against what happened.

    Columns: date, low, middle, high, baseline, realised, inside (band hit),
    err_model and err_baseline (absolute error of the middle band / baseline).
    """
    dates, rng = _ranges(bars)
    trail, ratio = _ratios(rng, horizon, lookback)
    rows = []
    for t in range(min_history, len(rng) - horizon):
        if dates[t].month == dates[t + 1].month:
            continue  # month-ends only
        lo, mid, hi, base = _bands_at(trail, ratio, t, horizon, (0.1, 0.5, 0.9))
        real = float(rng[t + 1:t + horizon + 1].mean())
        rows.append({"date": dates[t], "low": lo, "middle": mid, "high": hi, "baseline": base,
                     "realised": real, "inside": lo <= real <= hi,
                     "err_model": abs(mid - real), "err_baseline": abs(base - real)})
    return pl.DataFrame(rows)


def history_facts(hist: pl.DataFrame) -> list[str]:
    """Summary of :func:`scored_history` for Explain."""
    if hist.is_empty():
        return ["No scored history yet: need more than a year of data."]
    return [f"Month-ends scored: {hist.height}",
            f"Realised range inside the low–high band: {hist['inside'].mean() * 100:.0f}% of months",
            f"Average error, middle band: {hist['err_model'].mean():.2f} points",
            f"Average error, 'last 20 sessions continue': {hist['err_baseline'].mean():.2f} points"]
