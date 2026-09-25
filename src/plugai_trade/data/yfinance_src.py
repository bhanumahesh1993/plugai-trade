"""yfinance (Yahoo Finance) — convenient, unofficial, personal use only.

Optional extra: ``pip install "plugai-trade[yahoo]"``. Indian names get the
``.NS`` suffix; indices map to Yahoo's codes (NIFTY → ``^NSEI``). Rate-limit
errors are retried with backoff. Prices are requested *unadjusted* so they line
up with the exchange files.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import polars as pl

from . import SourceInfo, register

TICKERS = {
    "IN": {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "SENSEX": "^BSESN", "INDIAVIX": "^INDIAVIX",
           "FINNIFTY": "NIFTY_FIN_SERVICE.NS", "MIDCPNIFTY": "NIFTY_MID_SELECT.NS"},
    "US": {"SPX": "^GSPC", "NDX": "^NDX", "VIX": "^VIX", "DJI": "^DJI"},
}
INTERVALS = {"1d": "1d", "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m"}
RETRIES = 3


def ticker(symbol: str, market: str) -> str:
    """Yahoo's code for a lab symbol."""
    sym = symbol.upper()
    mapped = TICKERS.get(market, {}).get(sym)
    if mapped:
        return mapped
    if market == "IN" and not sym.startswith("^") and "." not in sym:
        return f"{sym}.NS"
    if market == "FX" and not sym.endswith("=X"):
        return sym.replace("/", "") + "=X"
    if market == "CRYPTO" and "-" not in sym:
        return f"{sym.split('/')[0]}-USD"
    return sym


def _module() -> Any:
    try:
        import yfinance
    except ImportError as exc:
        raise RuntimeError('yfinance is not installed. Run: pip install "plugai-trade[yahoo]"') \
            from exc
    return yfinance


def _download(yf: Any, code: str, start: date, end: date, interval: str):
    delay = 2.0
    for attempt in range(RETRIES):
        try:
            return yf.download(code, start=start.isoformat(),
                               end=(end + timedelta(days=1)).isoformat(),
                               interval=INTERVALS.get(interval, "1d"), auto_adjust=False,
                               progress=False, threads=False)
        except Exception as exc:  # yfinance raises its own rate-limit error type
            if "rate" not in str(exc).lower() or attempt == RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2
    return None


def to_polars(pdf, intraday: bool = False) -> pl.DataFrame:
    """yfinance's pandas frame (single or multi-level columns) → lab columns."""
    if pdf is None or len(pdf) == 0:
        return pl.DataFrame()
    if getattr(pdf.columns, "nlevels", 1) > 1:
        pdf = pdf.copy()
        pdf.columns = pdf.columns.get_level_values(0)
    pdf = pdf.reset_index()
    stamp = pdf.columns[0]
    out = pl.from_pandas(pdf.rename(columns={stamp: "ts", "Open": "open", "High": "high",
                                             "Low": "low", "Close": "close",
                                             "Volume": "volume"})[
        ["ts", "open", "high", "low", "close", "volume"]])
    out = out.with_columns(pl.col("ts").cast(pl.Datetime).dt.date().alias("date"))
    if intraday:
        out = out.with_columns(pl.col("ts").dt.strftime("%Y-%m-%dT%H:%M").alias("time"))
    return out.drop("ts")


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    yf = _module()
    return to_polars(_download(yf, ticker(symbol, market), start, end, interval),
                     intraday=interval != "1d")


register(SourceInfo(
    name="yfinance", tier="No signup", markets=("IN", "US", "FX", "CRYPTO"),
    license_class="personal-use", needs="Nothing (optional extra)", fetch=_fetch,
    description="Yahoo Finance via yfinance: US, .NS/.BO, indices, FX. Unofficial; patchy "
                "for India; personal use only.",
))
