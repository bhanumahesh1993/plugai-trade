"""Indian broker data sources: Fyers, Angel One SmartAPI, ICICI Breeze — read-only.

Only historical-candle endpoints are called. These brokers' tokens are not
read-only in the Upstox sense, so the protection is that PlugAI-Trade contains
no order code at all (``paper_guard`` checks it). Fyers and Angel One tokens
expire daily: set *Remind me* in Settings › Data Sources to log in before the
open. Licence class ``broker``.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from . import SourceInfo, register
from .httpkit import NeedsKey, get, require_key, windows

FYERS_HISTORY = "https://api-t1.fyers.in/data/history"
FYERS_SYMBOLS = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
                 "FINNIFTY": "NSE:FINNIFTY-INDEX", "INDIAVIX": "NSE:INDIAVIX-INDEX",
                 "SENSEX": "BSE:SENSEX-INDEX"}
FYERS_RES = {"1d": ("D", 366), "1m": ("1", 100), "5m": ("5", 100), "15m": ("15", 100),
             "1h": ("60", 100)}

ANGEL_CANDLES = ("https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/"
                 "getCandleData")
ANGEL_TOKENS = {"NIFTY": ("NSE", "99926000"), "BANKNIFTY": ("NSE", "99926009")}
ANGEL_RES = {"1d": ("ONE_DAY", 2000), "1m": ("ONE_MINUTE", 30), "5m": ("FIVE_MINUTE", 100),
             "15m": ("FIFTEEN_MINUTE", 200), "1h": ("ONE_HOUR", 400)}
DAILY_LOGIN = ("fyers", "angel", "breeze")  # tokens that expire every day


def epoch_frame(rows: list[list], intraday: bool, ts_is_text: bool = False) -> pl.DataFrame:
    """Candles ``[ts, o, h, l, c, v]`` (epoch seconds or ISO text, IST) → lab columns."""
    if not rows:
        return pl.DataFrame()
    df = pl.DataFrame({"ts": [r[0] for r in rows], **{c: [r[i] for r in rows] for i, c in
                                                     enumerate(("open", "high", "low", "close",
                                                                "volume"), 1)}},
                      strict=False)
    if ts_is_text:
        dt = pl.col("ts").str.slice(0, 16).str.to_datetime("%Y-%m-%dT%H:%M")
    else:
        dt = (pl.from_epoch("ts", time_unit="s").dt.replace_time_zone("UTC")
              .dt.convert_time_zone("Asia/Kolkata").dt.replace_time_zone(None))
    df = df.with_columns(dt.alias("dt")).sort("dt")
    df = df.with_columns(pl.col("dt").dt.date().alias("date"))
    if intraday:
        df = df.with_columns(pl.col("dt").dt.strftime("%Y-%m-%dT%H:%M").alias("time"))
    return df.drop("ts", "dt")


# ------------------------------------------------------------------ Fyers
def fyers_symbol(symbol: str) -> str:
    if ":" in symbol:
        return symbol
    sym = symbol.upper().removesuffix(".NS")
    return FYERS_SYMBOLS.get(sym, f"NSE:{sym}-EQ")


def _fyers(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    app_id = require_key("fyers_app_id", "Fyers app ID")
    token = require_key("fyers_token", "Fyers access token (daily)")
    res, window = FYERS_RES.get(interval, FYERS_RES["1d"])
    rows: list[list] = []
    for lo, hi in windows(start, end, window):
        params = {"symbol": fyers_symbol(symbol), "resolution": res, "date_format": "1",
                  "range_from": lo.isoformat(), "range_to": hi.isoformat(), "cont_flag": "1"}
        body = get(FYERS_HISTORY, params=params, headers={"Authorization": f"{app_id}:{token}"},
                   min_interval=0.2).json()
        if body.get("s") not in ("ok", "no_data"):
            raise RuntimeError(f"Fyers: {body.get('message', 'error')} (log in again if the "
                               "daily token expired)")
        rows.extend(body.get("candles") or [])
    return epoch_frame(rows, intraday=interval != "1d")


# ------------------------------------------------------------------ Angel One
def angel_token(symbol: str) -> tuple[str, str]:
    """``NIFTY`` → ``("NSE", "99926000")``; or pass ``NSE|<symboltoken>`` directly."""
    if "|" in symbol:
        exch, tok = symbol.split("|", 1)
        return exch.upper(), tok
    hit = ANGEL_TOKENS.get(symbol.upper())
    if not hit:
        raise ValueError(f"{symbol}: Angel One needs its numeric symbol token; pass it as "
                         "NSE|<token> (see Angel's instrument list).")
    return hit


def _angel(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    api_key = require_key("angel_api_key", "Angel One SmartAPI key")
    jwt = require_key("angel_jwt", "Angel One session token (daily)")
    exch, tok = angel_token(symbol)
    res, window = ANGEL_RES.get(interval, ANGEL_RES["1d"])
    hdrs = {"Authorization": f"Bearer {jwt}", "X-PrivateKey": api_key, "Accept": "application/json",
            "Content-Type": "application/json", "X-UserType": "USER", "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00"}
    rows: list[list] = []
    for lo, hi in windows(start, end, window):
        body = {"exchange": exch, "symboltoken": tok, "interval": res,
                "fromdate": f"{lo.isoformat()} 09:15", "todate": f"{hi.isoformat()} 15:30"}
        reply = get(ANGEL_CANDLES, method="POST", json=body, headers=hdrs, min_interval=0.4).json()
        if not reply.get("status", False):
            raise RuntimeError(f"Angel One: {reply.get('message', 'error')} (log in again if "
                               "the daily session expired)")
        rows.extend(reply.get("data") or [])
    return epoch_frame(rows, intraday=interval != "1d", ts_is_text=True, encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ ICICI Breeze
def _breeze(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    require_key("breeze_api_key", "ICICI Breeze API key")
    raise NeedsKey("ICICI Breeze needs its checksum-signed daily session, which PlugAI-Trade "
                   "v1.0 does not sign yet. Use Upstox, Fyers or Angel One for Indian bars.")


def reminder_needed(name: str) -> bool:
    """True for brokers whose login expires every day."""
    return name in DAILY_LOGIN


register(SourceInfo(
    name="fyers", tier="Your broker", markets=("IN",), license_class="broker",
    needs="Fyers account + app ID + daily token", fetch=_fyers,
    description="₹0 history for Fyers clients: minute bars 100 days/request, daily 366.",
))
register(SourceInfo(
    name="angel", tier="Your broker", markets=("IN",), license_class="broker",
    needs="Angel One account + SmartAPI key + daily session", fetch=_angel,
    description="₹0 SmartAPI history: 1-min 30 days/request, daily 2,000 days.",
))
register(SourceInfo(
    name="breeze", tier="Your broker", markets=("IN",), license_class="broker",
    needs="ICICI Direct account + Breeze key", fetch=_breeze,
    description="₹0 for ICICI Direct clients; best free route to historical options data.",
))
