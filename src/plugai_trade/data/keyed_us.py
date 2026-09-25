"""Free-key US sources: Finnhub, Tiingo, Massive (formerly Polygon.io).

* Finnhub's free plan has no candles, so it answers with the latest daily bar
  from its quote endpoint.
* Tiingo: 30+ years of EOD, 50 requests/hour, internal use only.
* Massive: 2 years of EOD aggregates, 5 calls/minute.

Keys come from the OS keychain. All three are licence class ``personal-use``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl

from . import SourceInfo, register
from .httpkit import get, require_key

FINNHUB = "https://finnhub.io/api/v1/quote"
TIINGO = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
MASSIVE = "https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"


def _daily_only(interval: str, name: str) -> None:
    if interval != "1d":
        raise ValueError(f"{name}'s free plan is end-of-day only.")


def _frame(rows: list[dict]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, strict=False, infer_schema_length=None).select(
        "date", "open", "high", "low", "close", "volume")


def _finnhub(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    token = require_key("finnhub_api_key", "Finnhub key")
    q = get(FINNHUB, params={"symbol": symbol.upper(), "token": token}, min_interval=1.0).json()
    if not q.get("t"):
        return pl.DataFrame()
    day = datetime.fromtimestamp(int(q["t"]), tz=UTC).date()
    if not start <= day <= end:
        return pl.DataFrame()
    return _frame([{"date": day, "open": q["o"], "high": q["h"], "low": q["l"], "close": q["c"],
                    "volume": 0.0}])


def _tiingo(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    _daily_only(interval, "Tiingo")
    token = require_key("tiingo_api_key", "Tiingo key")
    rows = get(TIINGO.format(ticker=symbol.lower()), min_interval=1.0,
               params={"startDate": start.isoformat(), "endDate": end.isoformat(),
                       "token": token}).json()
    return _frame([{"date": date.fromisoformat(r["date"][:10]), "open": r["open"],
                    "high": r["high"], "low": r["low"], "close": r["close"],
                    "volume": r.get("volume", 0)} for r in rows])


def _massive(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    _daily_only(interval, "Massive")
    key = require_key("massive_api_key", "Massive key")
    url = MASSIVE.format(ticker=symbol.upper(), start=start.isoformat(), end=end.isoformat())
    body = get(url, params={"adjusted": "false", "sort": "asc", "limit": 50000, "apiKey": key},
               min_interval=12.0).json()
    return _frame([{"date": datetime.fromtimestamp(r["t"] / 1000, tz=UTC).date(),
                    "open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"],
                    "volume": r.get("v", 0)} for r in body.get("results") or []])


register(SourceInfo(
    name="finnhub", tier="Free key", markets=("US",), license_class="personal-use",
    needs="Free key", fetch=_finnhub,
    description="Real-time US quotes and news on the free plan (candles are premium).",
))
register(SourceInfo(
    name="tiingo", tier="Free key", markets=("US",), license_class="personal-use",
    needs="Free key", fetch=_tiingo,
    description="30+ years of US end-of-day prices; internal use only.",
))
register(SourceInfo(
    name="massive", tier="Free key", markets=("US",), license_class="personal-use",
    needs="Free key", fetch=_massive,
    description="Formerly Polygon.io: 2 years of US end-of-day bars, 5 calls/min.",
))
