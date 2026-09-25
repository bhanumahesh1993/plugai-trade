"""Alpaca market data — free Basic plan, IEX feed, keys from the OS keychain.

Read-only: this module calls only the market-data host (``data.alpaca.markets``),
never the trading API. Bars are raw (unadjusted) from the IEX exchange alone,
so small differences from consolidated data are expected.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import polars as pl

from . import SourceInfo, register
from .httpkit import get, require_key

DATA_HOST = "https://data.alpaca.markets"
TIMEFRAMES = {"1d": "1Day", "1m": "1Min", "5m": "5Min", "15m": "15Min", "1h": "1Hour"}
FREE_STREAM_SYMBOLS = 30  # Basic plan websocket limit (shown on the Live stream counter)


def headers() -> dict[str, str]:
    return {"APCA-API-KEY-ID": require_key("alpaca_key_id", "Alpaca key ID"),
            "APCA-API-SECRET-KEY": require_key("alpaca_secret", "Alpaca secret")}


def bars(symbol: str, start: date, end: date, interval: str = "1d") -> list[dict]:
    """Raw IEX bars, following ``next_page_token`` until done."""
    url = f"{DATA_HOST}/v2/stocks/{symbol.upper()}/bars"
    params = {"timeframe": TIMEFRAMES.get(interval, "1Day"), "feed": "iex", "adjustment": "raw",
              "limit": 10000, "start": datetime.combine(start, time(), UTC).isoformat(),
              "end": datetime.combine(end + timedelta(days=1), time(), UTC).isoformat()}
    hdrs, out = headers(), []
    while True:
        body = get(url, params=params, headers=hdrs, min_interval=0.35).json()
        out.extend(body.get("bars") or [])
        token = body.get("next_page_token")
        if not token:
            return out
        params["page_token"] = token


def to_frame(rows: list[dict], intraday: bool) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    df = pl.DataFrame({"ts": [r["t"] for r in rows], "open": [r["o"] for r in rows],
                       "high": [r["h"] for r in rows], "low": [r["l"] for r in rows],
                       "close": [r["c"] for r in rows], "volume": [r["v"] for r in rows]},
                      strict=False)
    df = df.with_columns(pl.col("ts").str.to_datetime(time_zone="UTC")
                         .dt.convert_time_zone("America/New_York").alias("dt"))
    df = df.with_columns(pl.col("dt").dt.date().alias("date"))
    if intraday:
        df = df.with_columns(pl.col("dt").dt.strftime("%Y-%m-%dT%H:%M").alias("time"))
    return df.drop("ts", "dt")


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    return to_frame(bars(symbol, start, end, interval), intraday=interval != "1d")


register(SourceInfo(
    name="alpaca", tier="Free key", markets=("US",), license_class="broker",
    needs="Free key (paper account)", fetch=_fetch,
    description="US bars from Alpaca's free Basic plan (IEX feed, 200 calls/min, since 2016). "
                "Live stream: up to 30 symbols.",
))
