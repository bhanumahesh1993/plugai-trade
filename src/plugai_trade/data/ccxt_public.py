"""Crypto public (CCXT) — exchange candles through CCXT's *public* functions only.

Optional extra: ``pip install "plugai-trade[crypto]"``. No keys are used, ever:
the exchange object is created without credentials. US users default to
Coinbase (Kraken as backup — it only returns the latest 720 candles); everyone
else to Binance.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import polars as pl

from .. import config
from . import SourceInfo, register
from .httpkit import Offline, offline

TIMEFRAMES = {"1d": "1d", "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h"}
PAGE = 300


def exchanges() -> list[str]:
    """Exchange ids to try, by the market switch (US → Coinbase, Kraken)."""
    if config.get("market", "IN") == "US":
        return ["coinbase", "kraken"]
    return ["binance"]


def pair(symbol: str, exchange: str) -> str:
    """``BTC`` → ``BTC/USD`` (Coinbase, Kraken) or ``BTC/USDT`` (Binance)."""
    if "/" in symbol:
        return symbol.upper()
    quote = "USDT" if exchange == "binance" else "USD"
    return f"{symbol.upper().removesuffix('-USD')}/{quote}"


def _module() -> Any:
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError('ccxt is not installed. Run: pip install "plugai-trade[crypto]"') \
            from exc
    return ccxt


def _ms(d: date) -> int:
    return int(datetime.combine(d, time(), tzinfo=UTC).timestamp() * 1000)


def candles(exchange: Any, symbol: str, timeframe: str, start: date, end: date) -> list[list]:
    """Page through public OHLCV between two dates."""
    since, stop, out = _ms(start), _ms(end + timedelta(days=1)), []
    while since < stop:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=PAGE)
        batch = [b for b in batch if b[0] < stop]
        if not batch:
            break
        out.extend(batch)
        since = batch[-1][0] + 1
    return out


def to_frame(rows: list[list], intraday: bool) -> pl.DataFrame:
    df = pl.DataFrame(rows, schema=["ts", "open", "high", "low", "close", "volume"], orient="row",
                      strict=False)
    df = df.with_columns(pl.from_epoch("ts", time_unit="ms").alias("dt"))
    df = df.with_columns(pl.col("dt").dt.date().alias("date"))
    if intraday:
        df = df.with_columns(pl.col("dt").dt.strftime("%Y-%m-%dT%H:%M").alias("time"))
    return df.drop("ts", "dt")


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    if offline():
        raise Offline("offline mode")
    ccxt = _module()
    errors = []
    for ex_id in exchanges():
        exchange = getattr(ccxt, ex_id)({"enableRateLimit": True})  # public: no credentials
        try:
            rows = candles(exchange, pair(symbol, ex_id), TIMEFRAMES.get(interval, "1d"),
                           start, end)
        except Exception as exc:  # try the next exchange
            errors.append(f"{ex_id}: {exc}")
            continue
        if rows:
            return to_frame(rows, intraday=interval != "1d")
    raise RuntimeError("; ".join(errors) or "no candles returned")


register(SourceInfo(
    name="ccxt_public", tier="No signup", markets=("CRYPTO",), license_class="personal-use",
    needs="Nothing (optional extra)", fetch=_fetch,
    description="Public exchange candles via CCXT: Coinbase/Kraken for US users, Binance "
                "elsewhere. Kraken returns only the latest 720 candles.",
))
