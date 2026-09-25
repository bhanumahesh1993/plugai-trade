"""What the Paper Desk needs to know about a contract: units, cost profile, fill assumptions.

Lot sizes come from the dated reference tables. Spread and slippage are *your*
assumptions (editable on the desk), not dated facts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .. import costs, reference
from ..sizing import base_symbol, lot_for


@dataclass(frozen=True)
class Instrument:
    symbol: str            # as shown on the ticket: "NIFTY FUT", "SPY", "BTC-PERP"
    market: str            # IN | US
    data_symbol: str       # what data.get() is asked for
    lot: int               # units per lot (1 for shares)
    profile: str | None    # costs.py profile; None = not in the dated cost table (crypto)
    kind: str              # future | equity | perp
    half_spread: float     # price units, per side (used when the feed has no quotes)
    slippage: float        # price units, per side
    funding_per_day: int = 0

    @property
    def cur(self) -> str:
        return "₹" if self.market == "IN" else "$"

    def with_assumptions(self, half_spread: float, slippage: float) -> Instrument:
        return replace(self, half_spread=half_spread, slippage=slippage)


def instrument(symbol: str, market: str, product: str = "intraday") -> Instrument:
    """Describe a paper contract. ``product`` (IN shares only): intraday | delivery."""
    s = symbol.upper().strip()
    base = base_symbol(s)
    if s.endswith("-PERP"):
        return Instrument(s, market, base, 1, None, "perp", 0.5, 0.5, funding_per_day=3)
    if market == "IN" and s.endswith("FUT"):
        return Instrument(s, market, base, lot_for(s, market), "IN-futures", "future", 1.0, 1.0)
    if market == "IN":
        prof = "IN-equity-intraday" if product == "intraday" else "IN-equity-delivery"
        return Instrument(s, market, base, 1, prof, "equity", 0.05, 0.05)
    lot = lot_for(s, market)
    kind = "future" if lot > 1 else "equity"
    return Instrument(s, market, base, lot, "US-equity", kind, 0.01, 0.01)


def default_symbols(market: str) -> list[str]:
    """Ticket choices: index futures with a dated lot, the watchlist ETFs, a crypto perp."""
    if market == "IN":
        futs = [f"{k} FUT" for k, v in (reference.lookup("india.contracts") or {}).items()
                if isinstance(v, dict) and v.get("lot")]
        return futs + ["SYNTH-P", "BTC-PERP"]
    return ["SPY", "QQQ", "DIA", "BTC-PERP"]


def round_trip_costs(inst: Instrument, buy_value: float, sell_value: float) -> dict[str, float]:
    """Itemised charges from the dated cost table (empty total for crypto perps)."""
    if inst.profile is None:
        return {"venue fees (not in the dated table)": 0.0, "total": 0.0}
    return costs.round_trip(inst.profile, buy_value, sell_value)


@dataclass
class CostPreview:
    """The ticket's Cost preview and Breakeven (pts) tile (Chapter 21)."""

    instrument: Instrument
    qty: int
    buy_price: float
    sell_price: float
    items: dict[str, float]
    slippage_per_side: float
    slippage_money: float
    all_in: float
    breakeven_pts: float
    target_pts: float | None
    amber: str | None

    def facts(self) -> list[str]:
        c = self.instrument.cur
        out = [f"{self.instrument.symbol}: {self.qty} units, buy {self.buy_price:,.2f}, "
               f"sell {self.sell_price:,.2f}"]
        out += [f"{k}: {c}{v:,.2f}" for k, v in self.items.items() if k != "total"]
        out += [f"Charges: {c}{self.items['total']:,.2f}",
                f"Assumed slippage {self.slippage_per_side:g} a side: {c}{self.slippage_money:,.2f}",
                f"All-in cost: {c}{self.all_in:,.2f}",
                f"Breakeven: {self.breakeven_pts:.2f} points (price units) per unit"]
        if self.amber:
            out.append(self.amber)
        return out


def cost_preview(inst: Instrument, price: float, qty: int, target: float | None = None,
                 slippage_per_side: float | None = None, side: str = "buy") -> CostPreview:
    """Every charge for one round trip at ``price`` (and ``target``, if typed), plus the toll.

    Breakeven (pts) = (charges + slippage both sides) ÷ units. NIFTY scalp in
    Chapter 21: (₹960.85 + ₹130) ÷ 65 = 16.8 points; SPY 100 shares: $5.68 ÷ 100 = 5.7¢.
    """
    slip = inst.half_spread + inst.slippage if slippage_per_side is None else slippage_per_side
    exit_px = target if target else price
    buy_px, sell_px = (price, exit_px) if side == "buy" else (exit_px, price)
    items = round_trip_costs(inst, buy_px * qty, sell_px * qty)
    slip_money = round(2 * slip * qty, 2)
    all_in = round(items["total"] + slip_money, 2)
    be = all_in / qty if qty else 0.0
    tgt_pts = abs(target - price) if target else None
    amber = None
    if tgt_pts is not None and tgt_pts < 2 * be:
        amber = (f"Target is {tgt_pts:,.2f} points away: less than twice the "
                 f"{be:,.2f}-point breakeven. (Note only; the paper order is not blocked.)")
    return CostPreview(inst, qty, buy_px, sell_px, items, slip, slip_money, all_in, be,
                       tgt_pts, amber)
