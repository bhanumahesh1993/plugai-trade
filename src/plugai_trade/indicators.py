"""Indicators computed in code (never by a language model). Polars in, Polars out.

Every function adds columns and never looks ahead: a value on day t uses bars up
to and including day t. Strategies then act on the *next* bar (see backtest).
"""

from __future__ import annotations

import polars as pl


def sma(df: pl.DataFrame, n: int, col: str = "close") -> pl.DataFrame:
    return df.with_columns(pl.col(col).rolling_mean(n).alias(f"sma_{n}"))


def ema(df: pl.DataFrame, n: int, col: str = "close") -> pl.DataFrame:
    return df.with_columns(pl.col(col).ewm_mean(span=n, adjust=False).alias(f"ema_{n}"))


def rsi(df: pl.DataFrame, n: int = 14) -> pl.DataFrame:
    d = pl.col("close").diff()
    up = pl.when(d > 0).then(d).otherwise(0.0).ewm_mean(alpha=1 / n, adjust=False)
    dn = pl.when(d < 0).then(-d).otherwise(0.0).ewm_mean(alpha=1 / n, adjust=False)
    return df.with_columns((100 - 100 / (1 + up / dn)).alias(f"rsi_{n}"))


def true_range(df: pl.DataFrame) -> pl.DataFrame:
    pc = pl.col("close").shift(1)
    tr = pl.max_horizontal(pl.col("high") - pl.col("low"), (pl.col("high") - pc).abs(),
                           (pl.col("low") - pc).abs())
    return df.with_columns(tr.alias("tr"))


def atr(df: pl.DataFrame, n: int = 14) -> pl.DataFrame:
    return true_range(df).with_columns(
        pl.col("tr").ewm_mean(alpha=1 / n, adjust=False).alias(f"atr_{n}"))


def macd(df: pl.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pl.DataFrame:
    m = pl.col("close").ewm_mean(span=fast, adjust=False) - pl.col("close").ewm_mean(span=slow, adjust=False)
    df = df.with_columns(m.alias("macd"))
    return df.with_columns(pl.col("macd").ewm_mean(span=signal, adjust=False).alias("macd_signal"))


def bollinger(df: pl.DataFrame, n: int = 20, k: float = 2.0) -> pl.DataFrame:
    mid = pl.col("close").rolling_mean(n)
    sd = pl.col("close").rolling_std(n)
    return df.with_columns(mid.alias("bb_mid"), (mid + k * sd).alias("bb_up"),
                           (mid - k * sd).alias("bb_dn"))


def vwap(df: pl.DataFrame) -> pl.DataFrame:
    """Session VWAP for intraday frames (typical price × volume, cumulative)."""
    tp = (pl.col("high") + pl.col("low") + pl.col("close")) / 3
    return df.with_columns(((tp * pl.col("volume")).cum_sum() / pl.col("volume").cum_sum()).alias("vwap"))


def returns(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("ret"))


def realised_vol(df: pl.DataFrame, n: int = 20, periods: int = 252) -> pl.DataFrame:
    df = returns(df)
    return df.with_columns((pl.col("ret").rolling_std(n) * periods ** 0.5).alias(f"vol_{n}"))


def high_n(df: pl.DataFrame, n: int = 252) -> pl.DataFrame:
    return df.with_columns(pl.col("high").rolling_max(n).alias(f"high_{n}"))
