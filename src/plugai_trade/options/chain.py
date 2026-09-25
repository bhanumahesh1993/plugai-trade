"""The lesson option chain: spot, IV, rate and quote tick for each underlying.

Offline, the builder prices every strike from a synthetic *lesson chain* — a
fixed snapshot that reproduces the book's worked examples (Chapter 22: NIFTY
24,800, 5 days, IV 14%, r 6.5%; Chapter 23: 14 days, IV 13%, r 6%; SPY 560,
IV 16%, r 4%). These are model inputs, not dated market facts; lot sizes and
multipliers always come from ``plugai_trade.reference``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .. import config, reference


@dataclass(frozen=True)
class Snapshot:
    """One expiry of the lesson chain."""

    days: float
    iv: float
    rate: float
    tick: float
    label: str


# (market, expiry) -> snapshot. Weekly = Chapter 22's Thursday-morning chain (quotes in
# whole rupees, as printed); monthly = Chapter 23's chain (0.05 tick).
_SNAPSHOTS: dict[tuple[str, str], Snapshot] = {
    ("IN", "weekly"): Snapshot(5, 0.14, 0.065, 1.0, "weekly · 5 days (lesson chain)"),
    ("IN", "monthly"): Snapshot(14, 0.13, 0.06, 0.05, "monthly · 14 days (lesson chain)"),
    ("US", "weekly"): Snapshot(5, 0.16, 0.04, 0.01, "weekly · 5 days (lesson chain)"),
    ("US", "monthly"): Snapshot(30, 0.16, 0.04, 0.01, "monthly · 30 days (lesson chain)"),
}

# Illustrative lesson spots used by the book's examples. Other symbols use the last
# synthetic close from plugai_trade.data.
_LESSON_SPOT = {"NIFTY": 24800.0, "SPY": 560.0, "SPX": 5600.0}
_US_DEFAULT_IV = {"SPY": 0.16, "SPX": 0.16, "QQQ": 0.20}
_IN_DEFAULT_IV = {"NIFTY": 0.14, "BANKNIFTY": 0.16, "FINNIFTY": 0.15, "MIDCPNIFTY": 0.18,
                  "SENSEX": 0.14}

CURRENCY = {"IN": "₹", "US": "$"}


def market_of(symbol: str, market: str | None = None) -> str:
    """IN if the symbol is in the India contract table, US if in the US table, else the setting."""
    if market in ("IN", "US"):
        return market
    s = symbol.upper()
    if reference.lookup(f"india.contracts.{s}") is not None:
        return "IN"
    if reference.lookup(f"us.contracts.{s}") is not None:
        return "US"
    return str(config.get("market", "IN"))


def units_per_lot(symbol: str, market: str) -> tuple[int, str]:
    """Lot size (IN) or multiplier (US) from the dated reference table, with a note."""
    if market == "IN":
        lot = reference.lot_size(symbol)
        if lot:
            return int(lot), f"lot {lot} (Contract Table, as of {reference.as_of()})"
        return 1, "lot size not in the Contract Table: priced per unit — check the exchange"
    mult = reference.multiplier(symbol)
    return mult, f"multiplier {mult} (Contract Table, as of {reference.as_of()})"


def snapshot(market: str, expiry: str | float | date) -> tuple[Snapshot, date]:
    """Resolve an expiry spec (``"weekly"``, ``"monthly"``, a date or a number of days)."""
    today = date.today()
    if isinstance(expiry, str):
        key = expiry.lower()
        if (market, key) not in _SNAPSHOTS:
            raise ValueError(f"expiry must be 'weekly', 'monthly', a date or days, got {expiry!r}")
        snap = _SNAPSHOTS[(market, key)]
        return snap, today + timedelta(days=int(round(snap.days)))
    base = _SNAPSHOTS[(market, "weekly")]
    if isinstance(expiry, date):
        days = max((expiry - today).days, 0)
        return Snapshot(days, base.iv, base.rate, base.tick, f"{expiry:%d %b %Y} · {days} days"), expiry
    days = float(expiry)
    return (Snapshot(days, base.iv, base.rate, base.tick, f"{days:g} days"),
            today + timedelta(days=int(round(days))))


def default_iv(symbol: str, market: str, snap: Snapshot) -> float:
    """IV for an underlying: the snapshot's IV for the book's examples, a per-index default otherwise."""
    s = symbol.upper()
    if s in _LESSON_SPOT:
        return snap.iv
    table = _IN_DEFAULT_IV if market == "IN" else _US_DEFAULT_IV
    return table.get(s, 0.25)


def default_spot(symbol: str, market: str) -> float:
    """Lesson spot for the book's examples, else the last synthetic close (offline)."""
    s = symbol.upper()
    if s in _LESSON_SPOT:
        return _LESSON_SPOT[s]
    from .. import data  # local import: data is heavier and only needed here

    df = data.get(s, market=market, source="synthetic")
    return float(df["close"][-1])


def round_tick(price: float, tick: float) -> float:
    """Round a model price to the chain's quote tick."""
    return round(round(price / tick) * tick, 2)


def fmt_num(x: float, market: str = "IN", decimals: int = 0) -> str:
    """Group digits the way each market writes them (Indian lakh grouping for IN)."""
    neg = x < 0
    s = f"{abs(x):,.{decimals}f}"
    if market == "IN":
        whole, _, frac = f"{abs(x):.{decimals}f}".partition(".")
        if len(whole) > 3:
            head, tail = whole[:-3], whole[-3:]
            parts = []
            while len(head) > 2:
                parts.insert(0, head[-2:])
                head = head[:-2]
            if head:
                parts.insert(0, head)
            whole = ",".join(parts) + "," + tail
        s = whole + ("." + frac if frac else "")
    return ("−" if neg else "") + s


def fmt_money(x: float, market: str = "IN", decimals: int = 0) -> str:
    """₹1,21,727 or $9,470 — sign first, then currency."""
    body = fmt_num(abs(x), market, decimals)
    return ("−" if x < 0 else "") + CURRENCY.get(market, "") + body
