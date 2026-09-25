"""What Settings › Data Sources needs to know about each source.

Display names, which keychain entries a source needs, where to get them, and a
small *Test connection* probe. Status checks read the key *index* only, so
drawing the screen never touches the OS keychain.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import polars as pl

from .. import config, keys
from . import _load, compare, get

TIERS = ("No signup", "Free key", "Your broker")

LABELS = {
    "synthetic": "Synthetic", "nse_bhavcopy": "NSE bhavcopy", "bse_bhavcopy": "BSE bhavcopy",
    "amfi_nav": "AMFI NAV", "yfinance": "yfinance", "sec_edgar": "SEC EDGAR",
    "frankfurter": "Frankfurter FX", "ccxt_public": "Crypto public (CCXT)", "alpaca": "Alpaca",
    "fred": "FRED", "finnhub": "Finnhub", "tiingo": "Tiingo", "massive": "Massive",
    "upstox": "Upstox", "fyers": "Fyers", "angel": "Angel One", "breeze": "ICICI Breeze",
    "cache": "local cache", "eod_replay": "EOD replay",
}
STRIP_LABELS = {**LABELS, "yfinance": "yfinance .NS"}  # the IN fallback strip wording

# keychain entries: (key name, field label); optional keys are not required for "set up"
KEY_FIELDS: dict[str, list[tuple[str, str]]] = {
    "alpaca": [("alpaca_key_id", "Key ID"), ("alpaca_secret", "Secret")],
    "fred": [("fred_api_key", "FRED API key (optional)")],
    "finnhub": [("finnhub_api_key", "Finnhub key")],
    "tiingo": [("tiingo_api_key", "Tiingo token")],
    "massive": [("massive_api_key", "Massive key")],
    "upstox": [("upstox_analytics_token", "Analytics Token")],
    "fyers": [("fyers_app_id", "App ID"), ("fyers_token", "Access token (daily)")],
    "angel": [("angel_api_key", "SmartAPI key"), ("angel_jwt", "Session token (daily)")],
    "breeze": [("breeze_api_key", "API key")],
}
OPTIONAL_KEYS = {"fred"}
OPTIONAL_PACKAGES = {"yfinance": "yfinance", "ccxt_public": "ccxt"}  # pip extras

CONNECT_URLS = {
    "upstox": "https://account.upstox.com/developer/apps",
    "alpaca": "https://app.alpaca.markets/signup",
    "fred": "https://fredaccount.stlouisfed.org/apikeys",
    "finnhub": "https://finnhub.io/register",
    "tiingo": "https://www.tiingo.com/account/api/token",
    "massive": "https://massive.com/dashboard",
    "fyers": "https://myapi.fyers.in/dashboard",
    "angel": "https://smartapi.angelone.in/",
    "breeze": "https://api.icicidirect.com/apiuser/home",
    "sec_edgar": "https://www.sec.gov/os/accessing-edgar-data",
}

PAID_BROKERS = "Kite · Dhan · Groww"
PROBE_SYMBOL = {"IN": "NIFTY", "US": "SPY", "FX": "USDINR", "CRYPTO": "BTC", "MACRO": "DGS10"}
LIVE_CAPABLE = ("upstox", "fyers", "angel", "breeze", "alpaca")


def label(name: str) -> str:
    return LABELS.get(name, name)


def needs_keys(name: str) -> bool:
    return name in KEY_FIELDS and name not in OPTIONAL_KEYS


def is_set_up(name: str) -> bool:
    """Hollow dot = not set up. Uses the key index, never the keychain itself."""
    if name == "sec_edgar":
        return "@" in str(config.get("data.edgar_contact", "") or "")
    if name in OPTIONAL_PACKAGES:
        return importlib.util.find_spec(OPTIONAL_PACKAGES[name]) is not None
    if not needs_keys(name):
        return True
    stored = set(keys.listed())
    return all(k in stored for k, _ in KEY_FIELDS[name])


def is_working(name: str) -> bool:
    """Filled dot: set up and the last Test connection (if any) passed."""
    last = last_test(name)
    return is_set_up(name) and (last is None or bool(last.get("ok")))


def last_test(name: str) -> dict | None:
    return config.get(f"data.tests.{name}")


def save_keys(name: str, values: dict[str, str]) -> list[str]:
    """Store the non-empty fields in the keychain; returns the names saved."""
    saved = []
    for key_name, value in values.items():
        if value.strip():
            keys.set_key(key_name, value.strip())
            config.set_value(f"data.saved_on.{key_name}", date.today().isoformat())
            saved.append(key_name)
    return saved


@dataclass
class Probe:
    """The result of Test connection; ``facts()`` feeds Explain / Show sources."""
    source: str
    ok: bool
    message: str
    frames: dict[str, pl.DataFrame] = field(default_factory=dict)

    def facts(self) -> list[str]:
        out = [f"Source: {label(self.source)}", f"Result: {self.message}"]
        for what, df in self.frames.items():
            if df.height:
                last = df.tail(1).row(0, named=True)
                stamp = last.get("time") or last.get("date")
                out.append(f"{what}: {df.height} bar(s), last {stamp} close {last['close']}")
        return out


def _market_for(name: str, market: str) -> str:
    info = _load(name)
    if info is None or market in info.markets or "ANY" in info.markets:
        return market
    return info.markets[0]


def _probe_frames(name: str, market: str) -> dict[str, pl.DataFrame]:
    info = _load(name)
    if info is None:
        raise RuntimeError("source not available")
    if name == "sec_edgar":
        from . import sec_edgar
        return {"Filings": sec_edgar.filings("AAPL").head(5).rename({"filed": "date"})
                .with_columns(pl.lit(None, dtype=pl.Float64).alias("close"))}
    if name == "amfi_nav":
        from . import amfi_nav
        navs = amfi_nav.latest()
        return {"NAVs": navs.rename({"nav": "close"})}
    mkt = _market_for(name, market)
    symbol = PROBE_SYMBOL.get(mkt, "NIFTY")
    end = date.today()
    frames = {"Daily": info.fetch(symbol=symbol, market=mkt, start=end - timedelta(days=10),
                                  end=end, interval="1d")}
    if name in ("upstox", "alpaca", "fyers", "angel"):
        frames["1-minute"] = info.fetch(symbol=symbol, market=mkt, start=end - timedelta(days=5),
                                        end=end, interval="1m").tail(1)
    return frames


def probe(name: str, market: str) -> Probe:
    """Fetch a tiny sample directly from one source and remember the outcome."""
    try:
        frames = _probe_frames(name, market)
        rows = sum(df.height for df in frames.values())
        result = Probe(name, rows > 0, f"{rows} row(s) received" if rows else "no rows returned",
                       frames)
    except Exception as exc:  # show the reason, never crash the screen
        result = Probe(name, False, f"{type(exc).__name__}: {exc}")
    config.set_value(f"data.tests.{name}", {
        "ok": result.ok, "message": result.message[:300],
        "at": datetime.now(UTC).isoformat(timespec="seconds")})
    return result


@dataclass
class SourceComparison:
    """Two sources side by side for one symbol and date range (Compare sources)."""
    symbol: str
    market: str
    source_a: str
    source_b: str
    a: pl.DataFrame
    b: pl.DataFrame
    table: pl.DataFrame  # data.compare output

    def count(self, status: str) -> int:
        return int((self.table["status"] == status).sum())

    def repeats(self, frame: pl.DataFrame) -> list[date]:
        """Dates whose close equals the previous close exactly — possible stale values."""
        if frame.height < 2:
            return []
        same = frame.filter(pl.col("close") == pl.col("close").shift(1))
        return same["date"].to_list()

    def summary(self) -> str:
        return (f"{self.table.height} rows compared · {self.count('missing')} missing dates · "
                f"{self.count('disagree')} rows over 0.5%")

    def provenance(self, day: date) -> dict[str, dict]:
        """Both sides' values and tags for one date."""
        out = {}
        for side, frame in (("A", self.a), ("B", self.b)):
            row = frame.filter(pl.col("date") == day)
            out[side] = (row.select("close", "source", "fetched_at", "license_class")
                         .row(0, named=True) if row.height else None)
        return out

    def facts(self) -> list[str]:
        out = [f"Symbol: {self.symbol} ({self.market})",
               f"Source A: {label(self.source_a)} · Source B: {label(self.source_b)}",
               f"Rows compared: {self.table.height}",
               f"Missing dates: {self.count('missing')}",
               f"Rows over 0.5%: {self.count('disagree')}"]
        for row in self.table.filter(pl.col("status") != "ok").head(10).iter_rows(named=True):
            gap = f" ({row['diff'] * 100:.2f}% apart)" if row["diff"] is not None else ""
            out.append(f"{row['date']}: A {row['close_a']} vs B {row['close_b']} "
                       f"— {row['status']}{gap}")
        for side, frame in (("A", self.a), ("B", self.b)):
            reps = self.repeats(frame)
            if reps:
                out.append(f"Source {side} repeats the previous close on: "
                           + ", ".join(str(d) for d in reps[:5]))
        return out


def compare_sources(symbol: str, market: str, start: date, end: date, source_a: str,
                    source_b: str, tol: float = 0.005) -> SourceComparison:
    """Fetch the same bars from two sources and flag disagreements (raises if one fails)."""
    a = get(symbol, market=market, start=start, end=end, source=source_a, fallback=False)
    b = get(symbol, market=market, start=start, end=end, source=source_b, fallback=False)
    return SourceComparison(symbol, market, source_a, source_b, a, b, compare(a, b, tol=tol))
