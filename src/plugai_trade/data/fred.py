"""FRED — US macro series (DGS10, CPIAUCSL, UNRATE …).

With a free key (``fred_api_key`` in the keychain) the official API is used;
without one, FRED's keyless ``fredgraph.csv`` download. Some series carry a
third-party copyright note: check the series page before you share them.
"""

from __future__ import annotations

import io
from datetime import date

import polars as pl

from .. import keys
from . import SourceInfo, register
from .httpkit import get

API = "https://api.stlouisfed.org/fred/series/observations"
CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
NOTICE = ("This product uses the FRED® API but is not endorsed or certified by the Federal "
          "Reserve Bank of St. Louis.")


def _num(values: pl.Series) -> pl.Series:
    return values.cast(pl.Utf8).str.strip_chars().cast(pl.Float64, strict=False)


def from_api(series: str, start: date, end: date, api_key: str) -> pl.DataFrame:
    params = {"series_id": series, "api_key": api_key, "file_type": "json",
              "observation_start": start.isoformat(), "observation_end": end.isoformat()}
    obs = get(API, params=params, min_interval=0.5).json().get("observations", [])
    df = pl.DataFrame({"date": [o["date"] for o in obs], "value": [o["value"] for o in obs]},
                      schema={"date": pl.Utf8, "value": pl.Utf8})
    return df.with_columns(pl.col("date").str.to_date(), _num(df["value"]).alias("value"))


def from_csv(series: str, start: date, end: date) -> pl.DataFrame:
    params = {"id": series, "cosd": start.isoformat(), "coed": end.isoformat()}
    df = pl.read_csv(io.BytesIO(get(CSV, params=params, min_interval=0.5).content),
                     infer_schema_length=0)
    date_col, value_col = df.columns[0], df.columns[1]  # "observation_date"/"DATE", series id
    return df.select(pl.col(date_col).str.to_date().alias("date"),
                     _num(df[value_col]).alias("value"))


def series(series_id: str, start: date, end: date) -> pl.DataFrame:
    """``date, value`` — API when keyed, keyless CSV otherwise. Missing values dropped."""
    api_key = keys.get_key("fred_api_key")
    df = (from_api(series_id, start, end, api_key) if api_key
          else from_csv(series_id, start, end))
    return df.drop_nulls("value").filter((pl.col("date") >= start) & (pl.col("date") <= end))


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    df = series(symbol.upper(), start, end)
    return df.select("date", *[pl.col("value").alias(c) for c in ("open", "high", "low", "close")],
                     pl.lit(0.0).alias("volume"))


register(SourceInfo(
    name="fred", tier="Free key", markets=("MACRO", "US", "ANY"), license_class="public",
    needs="Free key (optional — keyless CSV works)", fetch=_fetch,
    description="US macro series from FRED. " + NOTICE,
))
