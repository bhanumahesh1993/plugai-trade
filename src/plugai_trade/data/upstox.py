"""Upstox — historical candles with the read-only Analytics Token.

The Analytics Token (free, one per account, valid a year) cannot place orders
at the broker's end; this module only calls the V3 historical-candle endpoint.
Minute candles from Jan 2022, daily from Jan 2000; requests are split to stay
inside Upstox's per-request windows. Licence class ``broker``.
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta
from urllib.parse import quote

import polars as pl

from .. import config, keys
from . import SourceInfo, register
from .httpkit import get, raw_path, require_key, windows

BASE = "https://api.upstox.com/v3/historical-candle"
TOKEN_KEY = "upstox_analytics_token"
TOKEN_DAYS = 365  # Analytics Token validity per Upstox docs
INDEX_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service", "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "INDIAVIX": "NSE_INDEX|India VIX", "SENSEX": "BSE_INDEX|SENSEX",
}
UNITS = {"1d": ("days", "1", 3650), "1m": ("minutes", "1", 28), "5m": ("minutes", "5", 28),
         "15m": ("minutes", "15", 28), "1h": ("hours", "1", 90)}


def instrument_key(symbol: str) -> str:
    """``NIFTY`` → ``NSE_INDEX|Nifty 50``; equities via the ISIN in a cached NSE bhavcopy."""
    if "|" in symbol:
        return symbol
    sym = symbol.upper().removesuffix(".NS")
    if sym in INDEX_KEYS:
        return INDEX_KEYS[sym]
    from .nse_bhavcopy import parse_cm
    for f in sorted(raw_path("nse", "cm", "x").parent.glob("cm_*.csv.zip"), reverse=True)[:5]:
        day = datetime.strptime(f.name[3:11], "%Y%m%d").date()
        hit = parse_cm(f.read_bytes(), day).filter(pl.col("symbol") == sym)
        if not hit.is_empty() and hit["isin"][0]:
            return f"NSE_EQ|{hit['isin'][0]}"
    raise ValueError(f"{sym}: unknown instrument. Fetch one NSE bhavcopy first, or pass an "
                     "Upstox instrument key such as NSE_EQ|INE002A01018.")


def candles(symbol: str, start: date, end: date, interval: str = "1d") -> list[list]:
    """Raw candles ``[ts, o, h, l, c, v, oi]``, oldest first."""
    token = require_key(TOKEN_KEY, "Upstox Analytics Token")
    unit, step, window = UNITS.get(interval, UNITS["1d"])
    key = quote(instrument_key(symbol), safe="")
    hdrs = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    out: list[list] = []
    for lo, hi in windows(start, end, window):
        url = f"{BASE}/{key}/{unit}/{step}/{hi.isoformat()}/{lo.isoformat()}"
        body = get(url, headers=hdrs, min_interval=0.2).json()
        out.extend(body.get("data", {}).get("candles") or [])
    return sorted(out, key=lambda c: c[0])


def to_frame(rows: list[list], intraday: bool) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    df = pl.DataFrame({"ts": [r[0] for r in rows], "open": [r[1] for r in rows],
                       "high": [r[2] for r in rows], "low": [r[3] for r in rows],
                       "close": [r[4] for r in rows], "volume": [r[5] for r in rows]},
                      strict=False)
    df = df.with_columns(pl.col("ts").str.slice(0, 16).str.to_datetime("%Y-%m-%dT%H:%M")
                         .alias("dt"))
    df = df.with_columns(pl.col("dt").dt.date().alias("date"))
    if intraday:
        df = df.with_columns(pl.col("dt").dt.strftime("%Y-%m-%dT%H:%M").alias("time"))
    return df.drop("ts", "dt")


def token_expiry() -> date | None:
    """When the saved token expires: the JWT ``exp`` claim, else saved date + 1 year."""
    token = keys.get_key(TOKEN_KEY)
    if not token:
        return None
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return datetime.fromtimestamp(int(claims["exp"])).date()
    except (IndexError, KeyError, ValueError, TypeError):
        saved = config.get(f"data.saved_on.{TOKEN_KEY}")
        return date.fromisoformat(saved) + timedelta(days=TOKEN_DAYS) if saved else None


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    return to_frame(candles(symbol, start, end, interval), intraday=interval != "1d")


register(SourceInfo(
    name="upstox", tier="Your broker", markets=("IN",), license_class="broker",
    needs="Upstox account + Analytics Token", fetch=_fetch,
    description="Read-only Analytics Token (₹0, valid 1 year): daily bars since 2000, "
                "intraday since 2022, live stream.",
))
