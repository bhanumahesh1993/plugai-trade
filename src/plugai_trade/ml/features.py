"""Features and labels for the ML Lab (Chapter 29).

Every feature for the row dated *t* uses prices up to and including the close
of *t* and nothing later; its *Known at* line says so. Labels look ``horizon``
sessions ahead, which is what makes them labels. Volatility features are
written relative to "normal for this market" (their own median over the past
year), because absolute levels mean nothing to a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

HORIZON = 10
NORMAL_WINDOW = 252  # "normal for this market": the past year's median
NOISE = "noise (control)"

KNOWN_AT: dict[str, str] = {
    "range_5": "close of the row's date · mean high–low range of the last 5 sessions ÷ its past-year median",
    "vol_20": "close of the row's date · 20-day volatility ÷ its past-year median",
    "vol_5": "close of the row's date · 5-day volatility ÷ its past-year median",
    "ret_5": "close of the row's date · return over the last 5 sessions, %",
    "ret_20": "close of the row's date · return over the last 20 sessions, %",
    "dist_ma50": "close of the row's date · distance from the 50-day average, %",
    "volume_z": "close of the row's date · volume vs its last 20 sessions (z-score)",
    "weekday": "known before the open · day of the week (0 = Monday)",
    NOISE: "random numbers · a control that carries no information",
}
FEATURES = [k for k in KNOWN_AT if k != NOISE]

LABELS: dict[str, str] = {
    "high_vol_next_10": "High volatility, next 10 sessions",
    "direction_next_10": "Direction, next 10 sessions",
    "triple_barrier": "Triple barrier",
}
LABEL_QUESTION: dict[str, str] = {
    "high_vol_next_10": "Will the next 10 sessions be more volatile than the past year's normal? (1 = yes)",
    "direction_next_10": "Will the close 10 sessions ahead be higher than today's close? (1 = yes)",
    "triple_barrier": ("Which fence is touched first in the next 10 sessions: profit (+1), loss (−1) "
                       "or time (0)? Fences = ± the typical 10-day move"),
}


@dataclass
class Dataset:
    """A feature table plus one label column, in time order. Build with :func:`dataset`."""

    frame: pl.DataFrame
    features: list[str]
    label: str
    horizon: int
    symbol: str = "instrument"
    source: str = "your data"
    known_at: dict[str, str] = field(default_factory=dict)

    @property
    def X(self) -> np.ndarray:
        return self.frame.select(self.features).to_numpy().astype(float)

    @property
    def y(self) -> np.ndarray:
        return self.frame["label"].to_numpy().astype(int)

    @property
    def dates(self) -> list[Any]:
        return self.frame["date"].to_list()

    @property
    def classes(self) -> list[int]:
        return sorted(int(c) for c in np.unique(self.y))

    def facts(self) -> list[str]:
        d = self.dates
        return [f"Label: {LABEL_QUESTION[self.label]}",
                f"Rows: {self.frame.height:,} ({d[0]} to {d[-1]}), source {self.source}",
                f"Features: {', '.join(self.features)}",
                f"Label length: {self.horizon} sessions"]


def _rel_to_normal(expr: pl.Expr) -> pl.Expr:
    """``expr`` divided by its own median over the past year (current row included)."""
    return expr / expr.rolling_median(NORMAL_WINDOW, min_samples=60)


def _feature_frame(bars: pl.DataFrame) -> pl.DataFrame:
    """All candidate features; each uses rows up to and including the current one."""
    ret = pl.col("close").log() - pl.col("close").shift(1).log()
    rng = (pl.col("high") - pl.col("low")) / pl.col("close")
    vol = pl.col("volume") if "volume" in bars.columns else pl.lit(0.0)
    df = bars.sort("date").with_columns(_ret=ret, _rng=rng, _vol=vol.cast(pl.Float64))
    return df.with_columns(
        range_5=_rel_to_normal(pl.col("_rng").rolling_mean(5)),
        vol_20=_rel_to_normal(pl.col("_ret").rolling_std(20)),
        vol_5=_rel_to_normal(pl.col("_ret").rolling_std(5)),
        ret_5=(pl.col("close") / pl.col("close").shift(5) - 1) * 100,
        ret_20=(pl.col("close") / pl.col("close").shift(20) - 1) * 100,
        dist_ma50=(pl.col("close") / pl.col("close").rolling_mean(50) - 1) * 100,
        volume_z=((pl.col("_vol") - pl.col("_vol").rolling_mean(20))
                  / pl.col("_vol").rolling_std(20)).fill_nan(0.0),
        weekday=(pl.col("date").cast(pl.Date).dt.weekday() - 1).cast(pl.Float64),
    )


def _labels(df: pl.DataFrame, label: str, h: int, barrier: float) -> np.ndarray:
    """The label for each row (NaN where the future is not yet known)."""
    close = df["close"].to_numpy().astype(float)
    ret = np.diff(np.log(close), prepend=np.nan)
    n = len(close)
    out = np.full(n, np.nan)
    if label == "direction_next_10":
        out[:n - h] = (close[h:] > close[:n - h]).astype(float)
        return out
    if label == "high_vol_next_10":
        past = pl.Series(ret).rolling_std(h).to_numpy()              # known at t
        normal = pl.Series(past).rolling_median(NORMAL_WINDOW, min_samples=60).to_numpy()
        for t in range(n - h):
            fut = np.std(ret[t + 1:t + h + 1], ddof=1)
            if not np.isnan(normal[t]):
                out[t] = float(fut > normal[t])
        return out
    if label == "triple_barrier":
        daily = pl.Series(ret).rolling_std(20).to_numpy()
        high, low = df["high"].to_numpy(), df["low"].to_numpy()
        for t in range(n - h):
            if np.isnan(daily[t]):
                continue
            width = barrier * daily[t] * np.sqrt(h)
            up, dn = close[t] * np.exp(width), close[t] * np.exp(-width)
            out[t] = 0.0
            for s in range(t + 1, t + h + 1):
                if high[s] >= up:
                    out[t] = 1.0
                    break
                if low[s] <= dn:
                    out[t] = -1.0
                    break
        return out
    raise ValueError(f"unknown label {label!r}; choose one of {', '.join(LABELS)}")


def dataset(bars: pl.DataFrame, label: str = "high_vol_next_10",
            features: list[str] | None = None, noise_column: bool = True,
            horizon: int = HORIZON, barrier: float = 1.0, seed: int = 29) -> Dataset:
    """Build a time-ordered feature table and label from daily ``bars``.

    ``features`` defaults to all eight book features; ``noise_column`` adds the
    random *Noise (control)* column the book asks you to keep on. Rows whose
    features are still warming up, or whose label reaches past the data, are
    dropped. ``barrier`` scales the triple-barrier fences (× the typical
    ``horizon``-day move).
    """
    feats = list(features or FEATURES)
    unknown = [f for f in feats if f not in FEATURES]
    if unknown:
        raise ValueError(f"unknown feature(s) {unknown}; choose from {', '.join(FEATURES)}")
    if label not in LABELS:
        raise ValueError(f"unknown label {label!r}; choose one of {', '.join(LABELS)}")
    df = _feature_frame(bars)
    df = df.with_columns(label=pl.Series(_labels(df, label, horizon, barrier)))
    if noise_column:
        rng = np.random.default_rng(seed)
        df = df.with_columns(pl.Series(NOISE, rng.standard_normal(df.height)))
        feats.append(NOISE)
    keep = ["date", "close", *FEATURES, *([NOISE] if noise_column else []), "label"]
    df = df.select(keep).drop_nulls().filter(pl.all_horizontal(pl.col(FEATURES).is_finite()))
    df = df.filter(pl.col("label").is_not_nan())
    source = str(bars["source"][0]) if "source" in bars.columns and bars.height else "your data"
    symbol = str(bars["symbol"][0]) if "symbol" in bars.columns and bars.height else "instrument"
    return Dataset(frame=df, features=feats, label=label, horizon=horizon, symbol=symbol,
                   source=source, known_at={f: KNOWN_AT[f] for f in feats})
