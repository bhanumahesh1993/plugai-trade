"""Tradebook importers: one small parser per broker, all producing the same fills.

India: Zerodha Console, Upstox, Groww, Dhan, Angel One. US: IBKR Flex, Schwab,
Robinhood, Webull. Anything else: the generic CSV with a column mapper.

Exports change often; each parser reads columns by name (case- and space-
insensitive) and ignores columns it does not need, including identifiers such as
client codes, order numbers and PAN, which are never copied into the journal.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import polars as pl

from .. import reference
from .schema import FILL_SCHEMA, empty_fills

INDIA_BROKERS = ("Zerodha", "Upstox", "Groww", "Dhan", "Angel One")
US_BROKERS = ("IBKR", "Schwab", "Robinhood", "Webull")
BROKERS = (*INDIA_BROKERS, *US_BROKERS, "Generic CSV")

#: Fields the generic CSV mapper asks for. Required ones first.
GENERIC_FIELDS = ("time", "symbol", "side", "qty", "price", "fees", "market", "account",
                  "instrument", "multiplier")
GENERIC_REQUIRED = ("time", "symbol", "side", "qty", "price")

CRYPTO_COINS = ("BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "MATIC", "DOT", "LTC",
                "USDT", "USDC", "AVAX", "LINK", "TRX", "SHIB")

_IN_FO = re.compile(
    r"^(?P<u>[A-Z&-]+?)(?P<exp>\d{2}[A-Z]{3}|\d{5})(?P<strike>\d+(?:\.\d+)?)?(?P<kind>FUT|CE|PE)$")
_OCC = re.compile(r"^(?P<u>[A-Z.]+)\s*(?P<exp>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")
_RH_OPT = re.compile(r"^(?P<u>[A-Z.]+)\s+(?P<exp>\d{1,2}/\d{1,2}/\d{4})\s+(?P<cp>Call|Put)\s+\$?"
                     r"(?P<strike>[\d,.]+)$", re.I)


class ImportError_(ValueError):
    """A tradebook the importer cannot read, with a message fit for the screen."""


@dataclass
class ParsedSymbol:
    underlying: str
    instrument: str
    strike: float | None = None
    expiry: str | None = None


# ------------------------------------------------------------------ small helpers
def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _num(v: object) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "").replace("₹", "")
    if s in ("", "-", "--", "nan", "None"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


_DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M", "%Y%m%d;%H%M%S", "%Y%m%d %H%M%S", "%d-%b-%Y %H:%M:%S",
    "%d %b %Y %H:%M:%S", "%d %b %Y, %I:%M %p", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y",
    "%m/%d/%Y", "%Y%m%d", "%d-%b-%Y", "%d %b %Y",
)


def parse_time(value: str, us: bool = False) -> datetime:
    """Parse a broker timestamp. ``us`` prefers month-first dates (MM/DD/YYYY)."""
    s = re.sub(r"\s+(IST|EDT|EST|ET|UTC)$", "", str(value).strip())
    s = s.replace("T", " ") if re.match(r"^\d{4}-\d{2}-\d{2}T", s) else s
    month_first = tuple(f for f in _DT_FORMATS if f.startswith("%m"))
    day_first = tuple(f for f in _DT_FORMATS if not f.startswith("%m"))
    # the US prints month first (09/04/2026 = 4 Sep); India prints day first
    formats = month_first + day_first if us else day_first + month_first
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt.replace("T", " ") if "T" in fmt else fmt)
        except ValueError:
            continue
    raise ImportError_(f"Could not read the date/time {value!r}")


def _combine(date_s: str, time_s: str | None, us: bool = False) -> datetime:
    if time_s and str(time_s).strip():
        return parse_time(f"{str(date_s).strip()} {str(time_s).strip()}", us=us)
    return parse_time(date_s, us=us)


def _side(v: str) -> str:
    s = str(v).strip().upper()
    if s.startswith(("B", "BTO", "BTC")) or s in ("BOT", "BUY TO OPEN", "BUY TO CLOSE"):
        return "BUY"
    if s.startswith(("S", "STO", "STC")) or s in ("SLD",):
        return "SELL"
    raise ImportError_(f"Unknown side {v!r} (expected buy or sell)")


def parse_india_symbol(symbol: str, instrument_hint: str | None = None) -> ParsedSymbol:
    """NIFTY26SEPFUT → (NIFTY, FUT); NIFTY26SEP25000CE → (NIFTY, CE, 25000); INFY → EQ."""
    sym = symbol.strip().upper().replace(" ", "")
    base = sym.split("/")[0].replace("INR", "").replace("USDT", "")
    if "/" in sym or sym.endswith(("INR", "USDT")) and base in CRYPTO_COINS or sym in CRYPTO_COINS:
        return ParsedSymbol(base, "CRYPTO")
    m = _IN_FO.match(sym)
    if m:
        strike = float(m["strike"]) if m["strike"] else None
        return ParsedSymbol(m["u"], m["kind"], strike, m["exp"])
    hint = (instrument_hint or "").upper()
    if hint.startswith("FUT"):
        return ParsedSymbol(sym, "FUT")
    return ParsedSymbol(sym.replace("-EQ", ""), "EQ")


def parse_us_symbol(symbol: str, description: str = "") -> ParsedSymbol:
    """SPY / OCC 'SPY 260918C00560000' / 'SPY 9/18/2026 Call $560.00' / BTC → parsed."""
    sym = symbol.strip().upper()
    m = _OCC.match(sym.replace(" ", "")) if sym else None
    if m:
        exp = f"20{m['exp'][:2]}-{m['exp'][2:4]}-{m['exp'][4:]}"
        return ParsedSymbol(m["u"], "CALL" if m["cp"] == "C" else "PUT",
                            int(m["strike"]) / 1000, exp)
    m = _RH_OPT.match(description.strip()) if description else None
    if m:
        exp = datetime.strptime(m["exp"], "%m/%d/%Y").strftime("%Y-%m-%d")
        return ParsedSymbol(m["u"].upper(), m["cp"].upper(), float(m["strike"].replace(",", "")),
                            exp)
    base = sym.split("/")[0].split("-")[0]
    if base in CRYPTO_COINS and sym != base or sym in CRYPTO_COINS:
        return ParsedSymbol(base, "CRYPTO")
    if (reference.lookup(f"us.contracts.{sym}") or {}).get("expiry"):
        return ParsedSymbol(sym, "FUT")
    return ParsedSymbol(sym, "EQ")


def multiplier_for(market: str, parsed: ParsedSymbol) -> float:
    """Value per point per unit: US options and futures use the dated contract table."""
    if market == "US" and parsed.instrument in ("CALL", "PUT", "FUT"):
        return float(reference.multiplier(parsed.underlying))
    return 1.0


# ------------------------------------------------------------------ reading
def read_rows(source: str | Path | bytes) -> tuple[list[dict[str, str]], str]:
    """Read a CSV (path, bytes or text) into dict rows keyed by normalised header."""
    if isinstance(source, bytes):
        text, name = source.decode("utf-8-sig"), "upload.csv"
    elif isinstance(source, Path) or (isinstance(source, str) and "\n" not in source
                                      and Path(source).exists()):
        text, name = Path(source).read_text(encoding="utf-8-sig"), Path(source).name
    else:
        text, name = str(source), "pasted.csv"
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    rows = [{_key(k): (v or "").strip() for k, v in r.items() if k is not None} for r in reader]
    if not rows:
        raise ImportError_(f"{name}: no rows found")
    return rows, name


def _get(row: dict[str, str], *names: str) -> str:
    for n in names:
        v = row.get(_key(n))
        if v not in (None, ""):
            return v
    return ""


def _need(row: dict[str, str], *names: str) -> str:
    v = _get(row, *names)
    if v == "":
        raise ImportError_(f"Missing column: one of {', '.join(names)}")
    return v


def _fill(time: datetime, symbol: str, parsed: ParsedSymbol, side: str, qty: float,
          price: float, fees: float | None, market: str, account: str, source: str) -> dict:
    if parsed.instrument in ("FUT", "CE", "PE", "CALL", "PUT") and \
            symbol.strip().upper() == parsed.underlying:
        # one contract per pairing key: 'NIFTY 2026-09-29 25000CE', 'SPY 2026-09-18 560CALL'
        strike = f"{parsed.strike:g}" if parsed.strike else ""
        symbol = f"{parsed.underlying} {parsed.expiry or ''} {strike}{parsed.instrument}".replace(
            "  ", " ")
    return {"time": time, "symbol": symbol, "underlying": parsed.underlying,
            "instrument": parsed.instrument, "side": side, "qty": abs(qty), "price": price,
            "fees": fees, "multiplier": multiplier_for(market, parsed), "market": market,
            "account": account, "strike": parsed.strike, "expiry": parsed.expiry,
            "source": source}


# ------------------------------------------------------------------ India
def _zerodha(row: dict, src: str, account: str) -> dict:
    sym = _need(row, "symbol", "tradingsymbol")
    t = _get(row, "order_execution_time", "trade_time")
    when = parse_time(t) if t else parse_time(_need(row, "trade_date"))
    seg = _get(row, "segment")
    parsed = parse_india_symbol(sym, "FUT" if seg.upper() == "FO" and sym.endswith("FUT") else None)
    return _fill(when, sym, parsed, _side(_need(row, "trade_type")), _num(_need(row, "quantity")),
                 _num(_need(row, "price")), None, "IN", account, src)


def _upstox(row: dict, src: str, account: str) -> dict:
    sym = _need(row, "scrip code", "symbol", "company")
    kind = _get(row, "instrument type").upper()
    parsed = parse_india_symbol(sym)
    if kind.startswith("OPT"):
        parsed = ParsedSymbol(parsed.underlying, _get(row, "option type").upper() or "CE",
                              _num(_get(row, "strike price")), _get(row, "expiry") or None)
    elif kind.startswith("FUT"):
        parsed = ParsedSymbol(parsed.underlying, "FUT", None, _get(row, "expiry") or None)
    when = _combine(_need(row, "date", "trade date"), _get(row, "trade time", "time"))
    return _fill(when, sym, parsed, _side(_need(row, "side", "transaction type")),
                 _num(_need(row, "quantity")), _num(_need(row, "price", "rate")), None, "IN",
                 account, src)


def _groww(row: dict, src: str, account: str) -> dict:
    sym = _need(row, "symbol", "stock name")
    qty = _num(_need(row, "quantity"))
    price = _num(_get(row, "price"))
    if price is None:
        price = _num(_need(row, "value")) / qty
    when = parse_time(_need(row, "execution date and time", "date"))
    return _fill(when, sym, parse_india_symbol(sym), _side(_need(row, "type", "side")), qty, price,
                 None, "IN", account, src)


def _dhan(row: dict, src: str, account: str) -> dict:
    sym = _need(row, "name", "symbol", "trading symbol")
    when = _combine(_need(row, "date"), _get(row, "time"))
    return _fill(when, sym, parse_india_symbol(sym), _side(_need(row, "buy/sell", "side")),
                 _num(_need(row, "quantity/lot", "quantity")),
                 _num(_need(row, "trade price", "price")), None, "IN", account, src)


def _angel(row: dict, src: str, account: str) -> dict:
    sym = _need(row, "symbol", "scrip name")
    when = _combine(_need(row, "trade date", "date"), _get(row, "trade time", "time"))
    return _fill(when, sym, parse_india_symbol(sym), _side(_need(row, "buy/sell", "trans type")),
                 _num(_need(row, "quantity", "qty")), _num(_need(row, "price", "trade price")),
                 None, "IN", account, src)


# ------------------------------------------------------------------ US
def _ibkr(row: dict, src: str, account: str) -> dict:
    sym = _need(row, "symbol")
    asset = _get(row, "assetclass").upper()
    under = _get(row, "underlyingsymbol") or sym.split()[0]
    if asset == "OPT":
        cp = _get(row, "put/call").upper()
        parsed = ParsedSymbol(under, "CALL" if cp.startswith("C") else "PUT",
                              _num(_get(row, "strike")), _get(row, "expiry") or None)
    elif asset == "FUT":
        parsed = ParsedSymbol(under, "FUT", None, _get(row, "expiry") or None)
    elif asset == "CRYPTO":
        parsed = ParsedSymbol(under, "CRYPTO")
    else:
        parsed = parse_us_symbol(sym)
    t = _get(row, "datetime", "date/time")
    when = parse_time(t, us=True) if t else parse_time(_need(row, "tradedate"), us=True)
    qty = _num(_need(row, "quantity"))
    side = _side(_get(row, "buy/sell") or ("BUY" if qty > 0 else "SELL"))
    fees = sum(abs(_num(_get(row, c)) or 0.0) for c in ("ibcommission", "commission", "fees"))
    fill = _fill(when, sym, parsed, side, qty, _num(_need(row, "tradeprice", "price")), fees,
                 "US", account, src)
    mult = _num(_get(row, "multiplier"))
    if mult:
        fill["multiplier"] = mult
    return fill


def _schwab(row: dict, src: str, account: str) -> dict:
    action = _need(row, "action")
    if not re.search(r"buy|sell", action, re.I):
        raise _Skip
    sym = _need(row, "symbol")
    parsed = parse_us_symbol(sym, _get(row, "description"))
    date_s = _need(row, "date").split(" as of ")[0]
    fees = _num(_get(row, "fees & comm", "fees")) or 0.0
    return _fill(parse_time(date_s, us=True), sym, parsed, _side(action),
                 _num(_need(row, "quantity")), _num(_need(row, "price")), abs(fees), "US",
                 account, src)


def _robinhood(row: dict, src: str, account: str) -> dict:
    code = _need(row, "trans code").upper()
    if code not in ("BUY", "SELL", "BTO", "STC", "STO", "BTC"):
        raise _Skip
    sym = _need(row, "instrument")
    parsed = parse_us_symbol(sym, _get(row, "description"))
    return _fill(parse_time(_need(row, "activity date"), us=True), sym, parsed, _side(code),
                 _num(_need(row, "quantity")), _num(_need(row, "price")), None, "US", account,
                 src)


def _webull(row: dict, src: str, account: str) -> dict:
    status = _get(row, "status").lower()
    if status and status != "filled":
        raise _Skip
    sym = _need(row, "symbol")
    parsed = parse_us_symbol(sym, _get(row, "name"))
    price = _num(_get(row, "avg price")) or _num(_need(row, "price"))
    return _fill(parse_time(_need(row, "filled time", "placed time"), us=True), sym, parsed,
                 _side(_need(row, "side")), _num(_need(row, "filled", "total qty")), price, None,
                 "US", account, src)


class _Skip(Exception):
    """Row is not a trade (dividend, transfer, cancelled order): skip it silently."""


_PARSERS: dict[str, Callable[[dict, str, str], dict]] = {
    "Zerodha": _zerodha, "Upstox": _upstox, "Groww": _groww, "Dhan": _dhan,
    "Angel One": _angel, "IBKR": _ibkr, "Schwab": _schwab, "Robinhood": _robinhood,
    "Webull": _webull,
}

#: Header signatures used by ``detect_broker`` (normalised column names).
_SIGNATURES: dict[str, tuple[str, ...]] = {
    "Zerodha": ("tradetype", "orderexecutiontime"),
    "Upstox": ("scripcode", "side"),
    "Groww": ("executiondateandtime",),
    "Dhan": ("buysell", "tradeprice", "quantitylot"),
    "Angel One": ("tradedate", "buysell"),
    "IBKR": ("tradeprice", "assetclass"),
    "Schwab": ("action", "feescomm"),
    "Robinhood": ("transcode", "activitydate"),
    "Webull": ("filledtime",),
}


def detect_broker(columns: list[str]) -> str | None:
    """Guess the broker from the header row; None means use the generic mapper."""
    keys = {_key(c) for c in columns}
    for broker, sig in _SIGNATURES.items():
        if all(s in keys for s in sig):
            return broker
    return None


def parse_fills(source: str | Path | bytes, broker: str | None = None, account: str = "Main",
                mapping: dict[str, str] | None = None, market: str | None = None) -> pl.DataFrame:
    """Read one tradebook into fills. ``broker=None`` detects it; generic CSV needs ``mapping``."""
    rows, name = read_rows(source)
    broker = broker or detect_broker(list(rows[0].keys()))
    if broker in (None, "Generic CSV"):
        return _generic(rows, name, mapping or {}, market or "IN", account)
    if broker not in _PARSERS:
        raise ImportError_(f"Unknown broker {broker!r}. Choose one of: {', '.join(BROKERS)}")
    fills = []
    for i, row in enumerate(rows, start=2):  # line 1 is the header
        try:
            fills.append(_PARSERS[broker](row, f"{name}:{i}", account))
        except _Skip:
            continue
        except ImportError_ as exc:
            raise ImportError_(f"{name} line {i}: {exc}") from None
    if not fills:
        return empty_fills()
    return pl.DataFrame(fills, schema=FILL_SCHEMA).sort("time")


def generic_template() -> str:
    """The generic CSV template the Trades screen offers for download."""
    return ("time,symbol,side,qty,price,fees,market,account,instrument,multiplier\n"
            "2026-09-08 09:47:00,SPY,BUY,60,560.00,0,US,Main,EQ,1\n"
            "2026-09-08 10:21:00,SPY,SELL,60,563.00,1.01,US,Main,EQ,1\n")


def _generic(rows: list[dict[str, str]], name: str, mapping: dict[str, str], market: str,
             account: str) -> pl.DataFrame:
    cols = {_key(k): _key(v) for k, v in mapping.items() if v}
    for f in GENERIC_FIELDS:
        cols.setdefault(f, f)
    missing = [f for f in GENERIC_REQUIRED if cols[f] not in rows[0]]
    if missing:
        raise ImportError_("Map these columns first: " + ", ".join(missing))
    fills = []
    for i, row in enumerate(rows, start=2):
        mkt = (row.get(cols["market"]) or market).upper()
        sym = row[cols["symbol"]]
        hint = (row.get(cols["instrument"]) or "").upper()
        parsed = parse_india_symbol(sym) if mkt == "IN" else parse_us_symbol(sym)
        if hint:
            parsed = ParsedSymbol(parsed.underlying, hint, parsed.strike, parsed.expiry)
        try:
            fill = _fill(parse_time(row[cols["time"]], us=mkt == "US"), sym, parsed,
                         _side(row[cols["side"]]), _num(row[cols["qty"]]),
                         _num(row[cols["price"]]), _num(row.get(cols["fees"])), mkt,
                         row.get(cols["account"]) or account, f"{name}:{i}")
        except (ImportError_, TypeError) as exc:
            raise ImportError_(f"{name} line {i}: {exc}") from None
        mult = _num(row.get(cols["multiplier"]))
        if mult:
            fill["multiplier"] = mult
        fills.append(fill)
    return pl.DataFrame(fills, schema=FILL_SCHEMA).sort("time")
