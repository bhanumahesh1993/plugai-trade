"""BSE bhavcopy — BSE's end-of-day equity file, one per trading day.

UDiFF CSV (from 8 Jul 2024) or the legacy ``EQDDMMYY_CSV.ZIP``. Symbols match
the ticker (``RELIANCE``) or the numeric scrip code (``500325``). Raw files are
cached in ``<lab>/raw/bse``. Licence class ``personal-use``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import polars as pl

from . import SourceInfo, register
from .httpkit import BROWSER_UA, raw_path
from .nse_bhavcopy import UDIFF_FROM, collect, download_first, read_csv_bytes, to_num, trading_days

BASE = "https://www.bseindia.com/download/BhavCopy/Equity"
MIN_INTERVAL = 1.0
HEADERS = {"User-Agent": BROWSER_UA, "Referer": "https://www.bseindia.com/"}

UDIFF_COLS = {"TckrSymb": "symbol", "FinInstrmId": "code", "OpnPric": "open", "HghPric": "high",
              "LwPric": "low", "ClsPric": "close", "TtlTradgVol": "volume"}
LEGACY_COLS = {"SC_NAME": "symbol", "SC_CODE": "code", "OPEN": "open", "HIGH": "high",
               "LOW": "low", "CLOSE": "close", "NO_OF_SHRS": "volume"}


def urls(day: date) -> list[str]:
    """Candidate BSE equity bhavcopy URLs, most likely format first."""
    udiff = f"{BASE}/BhavCopy_BSE_CM_0_0_0_{day:%Y%m%d}_F_0000.CSV"
    legacy = f"{BASE}/EQ{day:%d%m%y}_CSV.ZIP"
    return [udiff, legacy] if day >= UDIFF_FROM else [legacy, udiff]


def _dest(day: date):
    return raw_path("bse", "cm", f"bse_{day:%Y%m%d}.csv")


def parse(blob: bytes, day: date) -> pl.DataFrame:
    """Whole-market BSE file → ``symbol, code, date, open, high, low, close, volume``."""
    df = read_csv_bytes(blob)
    cols = UDIFF_COLS if "TckrSymb" in df.columns else LEGACY_COLS
    df = df.select([pl.col(k).alias(v) for k, v in cols.items() if k in df.columns])
    df = df.with_columns(pl.col("symbol").str.strip_chars(), pl.col("code").str.strip_chars())
    return to_num(df, ["open", "high", "low", "close", "volume"]).with_columns(
        pl.lit(day).alias("date"))


def read_day(day: date) -> pl.DataFrame | None:
    """The whole-market BSE frame for one day, or ``None`` on a holiday."""
    f = download_first(urls(day), _dest(day), day, "bse", HEADERS, MIN_INTERVAL)
    return parse(f.read_bytes(), day) if f else None


def _day_loader(symbol: str) -> Callable[[date], pl.DataFrame | None]:
    def load(day: date) -> pl.DataFrame | None:
        df = read_day(day)
        if df is None:
            return None
        return df.filter((pl.col("symbol").str.to_uppercase() == symbol)
                         | (pl.col("code") == symbol)).head(1)
    return load


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    if interval != "1d":
        raise ValueError("BSE bhavcopy is end-of-day only.")
    sym = symbol.upper().removesuffix(".BO")
    if sym == "SENSEX":
        raise ValueError("Index values are not in the BSE equity file; use yfinance (^BSESN).")
    days = trading_days(start, end, source="bse")
    df = collect(days, lambda d: _dest(d).exists(), _day_loader(sym), "BSE bhavcopy")
    return df if df.is_empty() else df.select("date", "open", "high", "low", "close", "volume")


register(SourceInfo(
    name="bse_bhavcopy", tier="No signup", markets=("IN",), license_class="personal-use",
    needs="Nothing", fetch=_fetch,
    description="Official BSE end-of-day equity files. Personal use only.",
))
