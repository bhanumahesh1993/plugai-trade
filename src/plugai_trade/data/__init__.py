"""Market data: one entry point, many free sources, provenance on every bar.

    from plugai_trade import data
    bars = data.get("NIFTY", market="IN", start="2025-01-01", end="2026-05-29")

Every frame has the columns ``date, open, high, low, close, volume`` plus the
provenance columns ``source, fetched_at, license_class``. ``license_class`` is
``public`` (SEC, FRED, GDELT, synthetic), ``personal-use`` (yfinance, NSE files)
or ``broker`` (your broker's API) — personal-use and broker data are never
committed to git.

Sources register themselves in ``data.sources``; the router tries them in the
order configured in Settings › Data Sources and falls back to the local cache.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import polars as pl

from .. import config

COLUMNS = ["date", "open", "high", "low", "close", "volume"]
PROVENANCE = ["source", "fetched_at", "license_class"]

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY", "INDIAVIX",
                 "SPY", "QQQ", "DIA", "IWM", "SPX", "NDX", "VIX"}


@dataclass(frozen=True)
class SourceInfo:
    name: str
    tier: str  # "No signup" | "Free key" | "Your broker"
    markets: tuple[str, ...]
    license_class: str
    needs: str  # human-readable: "Nothing", "Free key", "Upstox account" …
    fetch: Callable[..., pl.DataFrame]
    description: str = ""


_REGISTRY: dict[str, SourceInfo] = {}

# module name -> import path; each module calls register() at import time.
_SOURCE_MODULES = {
    "synthetic": "plugai_trade.data.synthetic",
    "nse_bhavcopy": "plugai_trade.data.nse_bhavcopy",
    "bse_bhavcopy": "plugai_trade.data.bse_bhavcopy",
    "amfi_nav": "plugai_trade.data.amfi_nav",
    "yfinance": "plugai_trade.data.yfinance_src",
    "sec_edgar": "plugai_trade.data.sec_edgar",
    "frankfurter": "plugai_trade.data.frankfurter",
    "ccxt_public": "plugai_trade.data.ccxt_public",
    "fred": "plugai_trade.data.fred",
    "alpaca": "plugai_trade.data.alpaca",
    "upstox": "plugai_trade.data.upstox",
    "fyers": "plugai_trade.data.brokers",
    "angel": "plugai_trade.data.brokers",
    "breeze": "plugai_trade.data.brokers",
    "finnhub": "plugai_trade.data.keyed_us",
    "tiingo": "plugai_trade.data.keyed_us",
    "massive": "plugai_trade.data.keyed_us",
}


def register(info: SourceInfo) -> None:
    _REGISTRY[info.name] = info


def _load(name: str) -> SourceInfo | None:
    if name in _REGISTRY:
        return _REGISTRY[name]
    mod = _SOURCE_MODULES.get(name)
    if not mod:
        return None
    try:
        importlib.import_module(mod)
    except ImportError:
        return None
    return _REGISTRY.get(name)


def sources() -> list[SourceInfo]:
    for n in _SOURCE_MODULES:
        _load(n)
    return sorted(_REGISTRY.values(), key=lambda s: (s.tier, s.name))


class DataUnavailable(RuntimeError):
    pass


def _to_date(d: str | date | datetime | None, default: date) -> date:
    if d is None:
        return default
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def normalise(df: pl.DataFrame, source: str, license_class: str) -> pl.DataFrame:
    """Coerce a source's frame to the house schema and stamp provenance."""
    if df.is_empty():
        return pl.DataFrame(schema={**{c: pl.Float64 for c in COLUMNS}, "date": pl.Date,
                                    "source": pl.Utf8, "fetched_at": pl.Utf8,
                                    "license_class": pl.Utf8})
    out = df.select(
        pl.col("date").cast(pl.Date),
        *[pl.col(c).cast(pl.Float64) for c in COLUMNS[1:]],
    ).sort("date").unique("date", keep="last").sort("date")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out.with_columns(pl.lit(source).alias("source"), pl.lit(stamp).alias("fetched_at"),
                            pl.lit(license_class).alias("license_class"))


def _cache_file(symbol: str, market: str, interval: str):
    safe = symbol.replace("/", "_").replace("^", "")
    return config.path("cache", market, interval, f"{safe}.parquet")


def _cache_write(df: pl.DataFrame, symbol: str, market: str, interval: str) -> None:
    if df.is_empty():
        return
    f = _cache_file(symbol, market, interval)
    if f.exists():
        old = pl.read_parquet(f)
        df = pl.concat([old, df], how="diagonal_relaxed").unique("date", keep="last").sort("date")
    df.write_parquet(f)


def _cache_read(symbol: str, market: str, interval: str) -> pl.DataFrame | None:
    f = _cache_file(symbol, market, interval)
    return pl.read_parquet(f) if f.exists() else None


def chain(market: str, interval: str = "1d") -> list[str]:
    key = f"{market}-{'intraday' if interval != '1d' else 'eod'}"
    if market == "FX":
        key = "FX"
    if market == "CRYPTO":
        key = "crypto"
    return list(config.get(f"data.fallback.{key}", []) or [])


def get(symbol: str, market: str = "IN", start=None, end=None, interval: str = "1d",
        source: str | None = None, use_cache: bool = True) -> pl.DataFrame:
    """Daily (or intraday) bars with provenance, from the first source that works.

    ``source="synthetic"`` always works offline. When nothing live works, the
    last good cached copy is returned (source column shows the original source).
    """
    end_d = _to_date(end, date.today())
    start_d = _to_date(start, end_d - timedelta(days=365))
    order = [source] if source else chain(market, interval)
    errors: list[str] = []
    for name in order:
        if name in ("cache", "eod_replay"):
            cached = _cache_read(symbol, market, interval)
            if cached is not None:
                return cached.filter((pl.col("date") >= start_d) & (pl.col("date") <= end_d))
            continue
        info = _load(name)
        if info is None or market not in info.markets and "ANY" not in info.markets:
            continue
        try:
            raw = info.fetch(symbol=symbol, market=market, start=start_d, end=end_d,
                             interval=interval)
        except Exception as exc:  # a source failing is normal; try the next one
            errors.append(f"{name}: {exc}")
            continue
        if raw is None or raw.is_empty():
            errors.append(f"{name}: no rows")
            continue
        df = normalise(raw, name, info.license_class)
        if use_cache and name != "synthetic":
            _cache_write(df, symbol, market, interval)
        return df
    if source is None and market in ("IN", "US"):
        # Last resort so every lesson still runs offline.
        from . import synthetic  # noqa: F401
        return normalise(_REGISTRY["synthetic"].fetch(symbol=symbol, market=market,
                                                      start=start_d, end=end_d,
                                                      interval=interval),
                         "synthetic", "public")
    raise DataUnavailable(f"No source returned {symbol} ({market}). Tried: " + "; ".join(errors))


def compare(a: pl.DataFrame, b: pl.DataFrame, tol: float = 0.005) -> pl.DataFrame:
    """Join two sources on date; flag closes that disagree by more than ``tol``."""
    j = a.select("date", pl.col("close").alias("close_a")).join(
        b.select("date", pl.col("close").alias("close_b")), on="date", how="full", coalesce=True
    ).sort("date")
    return j.with_columns(
        ((pl.col("close_a") - pl.col("close_b")).abs() / pl.col("close_b")).alias("diff"),
    ).with_columns(
        pl.when(pl.col("close_a").is_null() | pl.col("close_b").is_null())
        .then(pl.lit("missing"))
        .when(pl.col("diff") > tol).then(pl.lit("disagree"))
        .otherwise(pl.lit("ok")).alias("status")
    )


def education_cutoff(symbol: str, market: str) -> date | None:
    """Latest date a *named Indian security* may be shown in lessons (house rule).

    Indices and synthetic series are exempt. Returns ``None`` when no lag applies.
    """
    if market != "IN" or symbol.upper() in INDEX_SYMBOLS or symbol.upper().startswith("SYN"):
        return None
    lag = max(30, int(config.get("education_lag_days", 90)))
    return date.today() - timedelta(days=lag)


# Always available offline.
from . import synthetic  # noqa: E402,F401
