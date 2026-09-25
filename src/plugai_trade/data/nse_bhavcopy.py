"""NSE bhavcopy — the official end-of-day file, one per trading day.

Downloads only the published archive files (never the website's JSON), with a
browser User-Agent, at most one request per second, and keeps every raw file in
``<lab>/raw/nse`` so a day is fetched once. Reads both the UDiFF format (from
8 Jul 2024) and the legacy ``cmDDMONYYYYbhav.csv.zip`` format, plus NSE's daily
index-close file for NIFTY, BANKNIFTY and friends.

Licence class ``personal-use``: NSE owns this data; never redistribute it.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from .. import config, reference
from . import SourceInfo, register
from .httpkit import BROWSER_UA, NotFound, get, raw_path

BASE = "https://nsearchives.nseindia.com/content"
UDIFF_FROM = date(2024, 7, 8)  # NSE circular 62424: first UDiFF bhavcopy day (format hint only)
MIN_INTERVAL = 1.0  # seconds between requests to NSE — be slow and polite
DEFAULT_MAX_DOWNLOADS = 40  # per call; longer histories come from the cache or the next source

INDEX_NAMES = {
    "NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "FINNIFTY": "Nifty Financial Services",
    "MIDCPNIFTY": "Nifty Midcap Select", "INDIAVIX": "India VIX", "NIFTYNXT50": "Nifty Next 50",
    "NIFTYIT": "Nifty IT",
}
HEADERS = {"User-Agent": BROWSER_UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}

UDIFF_COLS = {"TckrSymb": "symbol", "SctySrs": "series", "ISIN": "isin", "OpnPric": "open",
              "HghPric": "high", "LwPric": "low", "ClsPric": "close", "TtlTradgVol": "volume"}
LEGACY_COLS = {"SYMBOL": "symbol", "SERIES": "series", "ISIN": "isin", "OPEN": "open",
               "HIGH": "high", "LOW": "low", "CLOSE": "close", "TOTTRDQTY": "volume"}


# ------------------------------------------------------------------ calendar
def _learned_file(source: str) -> Path:
    return raw_path(source, "no_file_days.txt")


def holidays(source: str = "nse") -> set[date]:
    """Exchange holidays: the dated reference table plus days that had no file."""
    days = {date.fromisoformat(str(d)) for d in (reference.lookup("india.holidays", []) or [])}
    f = _learned_file(source)
    if f.exists():
        days |= {date.fromisoformat(x) for x in f.read_text().split() if x}
    return days


def remember_no_file(day: date, source: str = "nse") -> None:
    """Record a past weekday that had no bhavcopy (a holiday), so it is never re-requested."""
    if day >= date.today():
        return  # today's file may simply not be published yet
    f = _learned_file(source)
    known = set(f.read_text().split()) if f.exists() else set()
    known.add(day.isoformat())
    f.write_text("\n".join(sorted(known)))


def trading_days(start: date, end: date, source: str = "nse") -> list[date]:
    """Weekdays between ``start`` and ``end`` that are not known holidays."""
    skip = holidays(source)
    out, d = [], start
    while d <= min(end, date.today()):
        if d.weekday() < 5 and d not in skip:
            out.append(d)
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------ files
def cm_urls(day: date) -> list[str]:
    """Candidate CM bhavcopy URLs for a day, most likely format first."""
    udiff = f"{BASE}/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    mon = day.strftime("%b").upper()
    legacy = f"{BASE}/historical/EQUITIES/{day:%Y}/{mon}/cm{day:%d}{mon}{day:%Y}bhav.csv.zip"
    return [udiff, legacy] if day >= UDIFF_FROM else [legacy, udiff]


def index_url(day: date) -> str:
    return f"{BASE}/indices/ind_close_all_{day:%d%m%Y}.csv"


def download_first(urls: list[str], dest: Path, day: date, source: str,
              headers: dict[str, str], min_interval: float) -> Path | None:
    """Fetch the first URL that exists into ``dest``; ``None`` for a no-file day."""
    if dest.exists():
        return dest
    for url in urls:
        try:
            resp = get(url, headers=headers, min_interval=min_interval)
        except NotFound:
            continue
        dest.write_bytes(resp.content)
        return dest
    remember_no_file(day, source)
    return None


def download(day: date, kind: str = "cm") -> Path | None:
    """Download (or reuse) one raw NSE file. ``kind`` is ``cm`` or ``index``."""
    if kind == "index":
        dest = raw_path("nse", "indices", f"ind_close_all_{day:%d%m%Y}.csv")
        return download_first([index_url(day)], dest, day, "nse", HEADERS, MIN_INTERVAL)
    dest = raw_path("nse", "cm", f"cm_{day:%Y%m%d}.csv.zip")
    return download_first(cm_urls(day), dest, day, "nse", HEADERS, MIN_INTERVAL)


def is_cached(day: date, kind: str = "cm") -> bool:
    name = (f"indices/ind_close_all_{day:%d%m%Y}.csv" if kind == "index"
            else f"cm/cm_{day:%Y%m%d}.csv.zip")
    return raw_path("nse", *name.split("/")).exists()


def read_csv_bytes(blob: bytes) -> pl.DataFrame:
    """A CSV, or the first CSV inside a zip, as strings (columns trimmed)."""
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            blob = z.read(next(n for n in z.namelist() if n.lower().endswith(".csv")))
    df = pl.read_csv(io.BytesIO(blob), infer_schema_length=0, truncate_ragged_lines=True)
    return df.rename({c: c.strip() for c in df.columns})


def to_num(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    return df.with_columns([pl.col(c).str.strip_chars().str.replace_all(",", "")
                            .cast(pl.Float64, strict=False) for c in cols])


def parse_cm(blob: bytes, day: date) -> pl.DataFrame:
    """Whole-market CM bhavcopy → ``symbol, series, isin, date, open, high, low, close, volume``."""
    df = read_csv_bytes(blob)
    cols = UDIFF_COLS if "TckrSymb" in df.columns else LEGACY_COLS
    df = df.select([pl.col(k).alias(v) for k, v in cols.items() if k in df.columns])
    df = df.with_columns([pl.col(c).str.strip_chars() for c in ("symbol", "series", "isin")
                          if c in df.columns])
    return to_num(df, ["open", "high", "low", "close", "volume"]).with_columns(
        pl.lit(day).alias("date"))


def parse_index(blob: bytes, day: date) -> pl.DataFrame:
    """NSE index-close file → ``index, date, open, high, low, close, volume``."""
    df = read_csv_bytes(blob)
    pick = {"Index Name": "index", "Open Index Value": "open", "High Index Value": "high",
            "Low Index Value": "low", "Closing Index Value": "close", "Volume": "volume"}
    df = df.select([pl.col(k).alias(v) for k, v in pick.items() if k in df.columns])
    df = to_num(df.with_columns(pl.col("index").str.strip_chars()),
                 ["open", "high", "low", "close", "volume"])
    return df.with_columns(pl.lit(day).alias("date"))


def read_day(day: date) -> pl.DataFrame | None:
    """The whole-market CM frame for one day, or ``None`` on a holiday."""
    f = download(day, "cm")
    return parse_cm(f.read_bytes(), day) if f else None


# ------------------------------------------------------------------ router entry
def max_downloads() -> int:
    return int(config.get("data.nse_max_downloads", DEFAULT_MAX_DOWNLOADS))


def collect(days: list[date], is_cached_fn: Callable[[date], bool],
            load_day: Callable[[date], pl.DataFrame | None], label: str) -> pl.DataFrame:
    """Load many days, refusing up front if too many files would be downloaded."""
    missing = sum(1 for d in days if not is_cached_fn(d))
    limit = max_downloads()
    if missing > limit:
        raise RuntimeError(f"{label}: {missing} daily files to download (limit {limit} per "
                           "request). Fetch day by day with `plugai-trade fetch`, schedule a "
                           "Fetch EOD job, or let the next source answer.")
    frames = [f for f in (load_day(d) for d in days) if f is not None and not f.is_empty()]
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="diagonal_relaxed")


def _index_day(name: str) -> Callable[[date], pl.DataFrame | None]:
    def load(day: date) -> pl.DataFrame | None:
        f = download(day, "index")
        if not f:
            return None
        df = parse_index(f.read_bytes(), day)
        return df.filter(pl.col("index").str.to_lowercase() == name.lower())
    return load


def _equity_day(symbol: str) -> Callable[[date], pl.DataFrame | None]:
    def load(day: date) -> pl.DataFrame | None:
        df = read_day(day)
        if df is None:
            return None
        rows = df.filter(pl.col("symbol") == symbol)
        eq = rows.filter(pl.col("series").is_in(["EQ", "BE", "BZ", "SM", "ST"]))
        return (eq if not eq.is_empty() else rows).head(1)
    return load


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    if interval != "1d":
        raise ValueError("NSE bhavcopy is end-of-day only; intraday needs a broker source.")
    sym = symbol.upper().removesuffix(".NS")
    if sym == "SENSEX":
        raise ValueError("SENSEX is a BSE index; it is not in NSE files.")
    if sym in INDEX_NAMES:
        days = trading_days(start, end)
        df = collect(days, lambda d: is_cached(d, "index"), _index_day(INDEX_NAMES[sym]),
                     "NSE index close")
    else:
        days = trading_days(start, end)
        df = collect(days, is_cached, _equity_day(sym), "NSE bhavcopy")
    if df.is_empty():
        return df
    return df.select("date", "open", "high", "low", "close", "volume")


register(SourceInfo(
    name="nse_bhavcopy", tier="No signup", markets=("IN",), license_class="personal-use",
    needs="Nothing", fetch=_fetch,
    description="Official NSE end-of-day files (UDiFF + legacy) and index closes. "
                "Unadjusted prices; personal use only — never redistribute.",
))
