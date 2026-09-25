"""Fills → round trips, first in first out, with reversals and partial exits.

One NIFTY lot bought at 09:45 and sold at 10:17 is two fills and one round trip;
an order that filled in three pieces is three fills. Charges missing from the
tradebook are priced from the dated cost table (``plugai_trade.costs``).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import polars as pl

from .. import costs
from .schema import FILL_SCHEMA, conform_trades, empty_fills, empty_trades


@dataclass
class _Lot:
    time: object
    side: str
    qty: float
    price: float
    fee_per_unit: float | None
    source: str
    fill: dict = field(repr=False, default_factory=dict)


@dataclass
class PairResult:
    """Round trips plus the fills that could not be paired (still open)."""

    trades: pl.DataFrame
    unpaired: pl.DataFrame

    def facts(self) -> list[str]:
        return [f"Round trips: {self.trades.height}",
                f"Fills not paired (open positions): {self.unpaired.height}"]


def india_cost_kind(instrument: str, same_day: bool) -> str | None:
    """Which Indian charge schedule applies to a round trip (None: not priced here)."""
    if instrument == "FUT":
        return "futures"
    if instrument in ("CE", "PE"):
        return "options"
    if instrument == "EQ":
        return "intraday" if same_day else "delivery"
    return None


def price_charges(market: str, instrument: str, buy_value: float, sell_value: float,
                  same_day: bool, contracts: float = 0.0, orders: float = 2.0) -> float | None:
    """Charges for one round trip from the dated cost table; None if no schedule fits.

    ``orders`` is the share of broker orders this round trip used (a partial exit of one
    order uses a fraction of it), so per-order brokerage is not counted twice.
    """
    if market == "IN":
        kind = india_cost_kind(instrument, same_day)
        return None if kind is None else costs.india_round_trip(buy_value, sell_value, kind,
                                                                orders=orders)["total"]
    if market == "US":
        n = int(contracts) if instrument in ("CALL", "PUT") else 0
        return costs.us_round_trip(buy_value, sell_value, contracts=n)["total"]
    return None


def _round_trip(lot: _Lot, exit_fill: dict, qty: float, exit_fee_unit: float | None) -> dict:
    f = lot.fill
    mult = f["multiplier"] or 1.0
    long = lot.side == "BUY"
    entry, exit_ = lot.price, exit_fill["price"]
    gross = (exit_ - entry) * qty * mult * (1 if long else -1)
    buy_v = (entry if long else exit_) * qty * mult
    sell_v = (exit_ if long else entry) * qty * mult
    same_day = lot.time.date() == exit_fill["time"].date()
    if lot.fee_per_unit is not None or exit_fee_unit is not None:
        charges = (lot.fee_per_unit or 0.0) * qty + (exit_fee_unit or 0.0) * qty
        src = "tradebook"
    else:
        orders = qty / (f["qty"] or qty) + qty / (exit_fill["qty"] or qty)
        charges = price_charges(f["market"], f["instrument"], buy_v, sell_v, same_day, qty,
                                orders)
        src = "cost table" if charges is not None else "none"
        charges = charges or 0.0
    charges = round(charges, 2)
    return {
        "date": lot.time.strftime("%Y-%m-%d"), "entry_time": lot.time,
        "exit_time": exit_fill["time"], "symbol": f["symbol"], "underlying": f["underlying"],
        "instrument": f["instrument"], "side": "LONG" if long else "SHORT", "qty": qty,
        "multiplier": mult, "entry_price": entry, "exit_price": exit_, "gross": round(gross, 2),
        "charges": charges, "charges_source": src, "net": round(gross - charges, 2),
        "market": f["market"], "account": f["account"], "tags": [],
        "strike": f["strike"], "expiry": f["expiry"],
        "source": f"{lot.source} → {exit_fill['source']}",
    }


def pair_fills(fills: pl.DataFrame) -> PairResult:
    """Pair fills FIFO per (account, symbol) into round trips; return leftovers as unpaired."""
    if fills.is_empty():
        return PairResult(empty_trades(), empty_fills())
    books: dict[tuple, deque[_Lot]] = {}
    trips: list[dict] = []
    for f in fills.sort("time").iter_rows(named=True):
        key = (f["account"], f["symbol"])
        book = books.setdefault(key, deque())
        fee_unit = None if f["fees"] is None else f["fees"] / f["qty"] if f["qty"] else 0.0
        remaining = f["qty"]
        while remaining > 1e-9 and book and book[0].side != f["side"]:
            lot = book[0]
            take = min(lot.qty, remaining)
            trips.append(_round_trip(lot, f, take, fee_unit))
            lot.qty -= take
            remaining -= take
            if lot.qty <= 1e-9:
                book.popleft()
        if remaining > 1e-9:  # opens (or reverses into) a position
            book.append(_Lot(f["time"], f["side"], remaining, f["price"], fee_unit, f["source"], f))
    open_rows = [{**lot.fill, "qty": lot.qty} for book in books.values() for lot in book]
    unpaired = pl.DataFrame(open_rows, schema=FILL_SCHEMA) if open_rows else empty_fills()
    if not trips:
        return PairResult(empty_trades(), unpaired)
    trades = pl.DataFrame(trips).sort("entry_time")
    trades = trades.with_columns(pl.Series("trade_id", range(1, trades.height + 1), pl.Int64))
    return PairResult(conform_trades(trades), unpaired)
