"""One option (or share) leg: the "What you're paying for" tiles, Greeks, Days left and scenarios."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date

import numpy as np

from . import chain
from .pricing import bs_greeks, bs_price

KINDS = ("call", "put", "stock")
SIDES = ("buy", "sell")


class Tiles(dict):
    """The six "What you're paying for" tiles, per lot. Values are numbers; ``str()`` formats them."""

    market: str = "IN"

    def display(self) -> dict[str, str]:
        """Formatted tile text, exactly as the builder shows it."""
        m = self.market
        out: dict[str, str] = {}
        for k, v in self.items():
            if v is None:
                out[k] = "Unlimited" if k == "Max loss" else "—"
            elif k == "Breakeven":
                out[k] = chain.fmt_num(v, m, 0 if m == "IN" else 2)
            elif k == "Required move":
                pts = chain.fmt_num(abs(v), m, 0 if m == "IN" else 2)
                out[k] = (f"{'+' if v >= 0 else '−'}{pts} pts" if m == "IN"
                          else f"{'+' if v >= 0 else '−'}${pts}")
            elif k == "Expected ±1σ":
                out[k] = (f"±{chain.fmt_num(v, m)} pts" if m == "IN"
                          else f"±${chain.fmt_num(v, m, 2)}")
            elif k == "Delta":
                out[k] = f"{v:.2f}"
            else:
                out[k] = chain.fmt_money(v, m)
        return out

    def __str__(self) -> str:
        return " · ".join(f"{k}: {v}" for k, v in self.display().items())


class Greeks(dict):
    """``{"per_unit": {...}, "per_lot": {...}}``; theta per calendar day, vega per IV point."""

    def __str__(self) -> str:
        u, lot = self["per_unit"], self["per_lot"]
        return " · ".join(f"{k} {u[k]:+.4g}/unit ({lot[k]:+,.2f}/lot)" for k in u)


@dataclass(frozen=True)
class Scenario:
    """A leg repriced under a gap / IV change / days-left combination."""

    spot: float
    iv: float
    days_left: float
    price: float
    pnl: float
    max_loss: float | None
    market: str

    def facts(self) -> list[str]:
        """Numbers the AI may cite."""
        m = self.market
        out = [f"Scenario spot: {chain.fmt_num(self.spot, m, 2)}",
               f"Scenario IV: {self.iv * 100:.1f}%",
               f"Days left: {self.days_left:g}",
               f"Value per unit: {chain.fmt_money(self.price, m, 2)}",
               f"P&L per lot: {chain.fmt_money(self.pnl, m)}"]
        if self.max_loss is not None:
            out.append(f"Maximum loss per lot: {chain.fmt_money(self.max_loss, m)}")
        return out

    def __str__(self) -> str:
        return " · ".join(self.facts())


@dataclass(frozen=True)
class Leg:
    """One leg. ``qty`` is in lots (IN) or contracts (US); ``premium`` is the entry price per unit."""

    symbol: str
    kind: str
    strike: float
    side: str
    qty: int
    market: str
    lot: int
    lot_note: str
    expiry: date
    days: float
    spot: float
    iv: float
    rate: float
    premium: float
    chain_label: str

    # ------------------------------------------------------------------ basics
    @property
    def sign(self) -> int:
        """+1 for a bought leg, −1 for a sold one."""
        return 1 if self.side == "buy" else -1

    @property
    def units(self) -> int:
        """Units controlled: lots × lot size (or contracts × multiplier)."""
        return self.qty * self.lot

    @property
    def t(self) -> float:
        """Time to expiry in years (calendar days ÷ 365)."""
        return max(self.days, 0.0) / 365.0

    @property
    def price(self) -> float:
        """Model value per unit now (the Days left slider reads this)."""
        return round(float(self.value()), 2)

    @property
    def currency(self) -> str:
        return chain.CURRENCY[self.market]

    def value(self, spot: float | np.ndarray | None = None, days: float | None = None,
              iv: float | None = None) -> np.ndarray:
        """Per-unit model value; vectorised over ``spot``."""
        s = self.spot if spot is None else spot
        if self.kind == "stock":
            return np.asarray(s, dtype=float)
        d = self.days if days is None else days
        return bs_price(s, self.strike, max(d, 0.0) / 365.0, self.iv if iv is None else iv,
                        self.rate, self.kind)

    def payoff(self, spot: np.ndarray) -> np.ndarray:
        """P&L of the whole leg (all lots) at this leg's expiry, vectorised."""
        return self.sign * (self.value(spot, days=0.0) - self.premium) * self.units

    # ------------------------------------------------------------------ Greeks
    def greeks(self) -> Greeks:
        """Delta, gamma, theta/day and vega/IV-point: per unit (the option) and per lot (your side)."""
        if self.kind == "stock":
            unit = {"delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        else:
            g = bs_greeks(self.spot, self.strike, self.t, self.iv, self.rate, self.kind)
            unit = {k: float(v) for k, v in g.items()}
        per_lot = {k: self.sign * v * self.lot for k, v in unit.items()}
        return Greeks(per_unit=unit, per_lot=per_lot)

    # ------------------------------------------------------------------ tiles
    def breakeven(self) -> float | None:
        """Price at expiry where the leg's P&L is zero."""
        if self.kind == "call":
            return self.strike + self.premium
        if self.kind == "put":
            return self.strike - self.premium
        return self.premium

    def max_loss_per_lot(self) -> float | None:
        """Worst P&L per lot at expiry, as a positive number; ``None`` means unlimited."""
        if self.side == "buy":
            return self.premium * self.lot
        if self.kind == "put":
            return (self.strike - self.premium) * self.lot
        return None  # short call or short stock

    def expected_move(self) -> float:
        """One-standard-deviation move to expiry: spot × IV × √(days ÷ 365)."""
        return self.spot * self.iv * math.sqrt(self.t)

    def tiles(self) -> Tiles:
        """Breakeven, Max loss, Required move, Expected ±1σ, Theta/day, Delta — per lot."""
        g = self.greeks()
        be = self.breakeven()
        tiles = Tiles({
            "Breakeven": round(be, 2) if be is not None else None,
            "Max loss": None if self.max_loss_per_lot() is None else round(self.max_loss_per_lot(), 2),
            "Required move": round(be - self.spot, 2) if be is not None else None,
            "Expected ±1σ": round(self.expected_move(), 2),
            "Theta/day": round(g["per_lot"]["theta"], 2),
            "Delta": round(self.sign * g["per_unit"]["delta"], 2),
        })
        tiles.market = self.market
        return tiles

    # ------------------------------------------------------------------ what-ifs
    def at(self, days_left: float) -> Leg:
        """The same leg with ``days_left`` to expiry (entry premium unchanged)."""
        return replace(self, days=float(days_left))

    def scenario(self, gap: float = 0.0, iv: float = 0.0, days_left: float | None = None,
                 gap_pct: float | None = None) -> Scenario:
        """Reprice after a gap (points, or ``gap_pct`` as a fraction) and an IV change (points).

        Default timing is tomorrow's open: one day fewer than now.
        """
        move = self.spot * gap_pct if gap_pct is not None else gap
        s = self.spot + move
        v = max(self.iv + iv / 100.0, 0.001)
        d = max(self.days - 1, 0.0) if days_left is None else float(days_left)
        px = float(self.value(s, d, v))
        pnl = self.sign * (px - self.premium) * self.lot
        return Scenario(spot=s, iv=v, days_left=d, price=round(px, 2), pnl=round(pnl, 2),
                        max_loss=self.max_loss_per_lot(), market=self.market)

    # ------------------------------------------------------------------ narration
    def describe(self) -> str:
        """``Buy NIFTY 25000 CE`` / ``Sell SPY 540 put``."""
        if self.kind == "stock":
            return f"{self.side.title()} {self.units} {self.symbol} shares"
        k = f"{self.strike:g}"
        name = ("CE" if self.kind == "call" else "PE") if self.market == "IN" else self.kind
        return f"{self.side.title()} {self.symbol} {k} {name}"

    def facts(self) -> list[str]:
        """Short strings the AI may cite (numbers computed here, never by the model)."""
        m = self.market
        out = [f"Leg: {self.describe()} × {self.qty} ({self.lot_note})",
               f"Expiry: {self.expiry:%d %b %Y} ({self.days:g} days left; {self.chain_label})",
               f"Spot: {chain.fmt_num(self.spot, m, 2)} · IV {self.iv * 100:.1f}% · rate {self.rate * 100:.2f}%",
               f"Premium: {chain.fmt_money(self.premium, m, 2)} per unit "
               f"({chain.fmt_money(self.premium * self.lot, m)} per lot)",
               f"Model value now: {chain.fmt_money(self.price, m, 2)}"]
        out += [f"{k}: {v}" for k, v in self.tiles().display().items()]
        g = self.greeks()
        out.append(f"Vega per lot: {chain.fmt_money(g['per_lot']['vega'], m, 2)} per IV point")
        out.append(f"Gamma per unit: {g['per_unit']['gamma']:.6f}")
        return out

    def __str__(self) -> str:
        return f"{self.describe()} @ {chain.fmt_money(self.premium, self.market, 2)} — {self.tiles()}"


def leg(symbol: str, kind: str, strike: float | None = None,
        expiry: str | float | date = "weekly", side: str = "buy", qty: int = 1,
        spot: float | None = None, iv: float | None = None, rate: float | None = None,
        market: str | None = None, premium: float | None = None) -> Leg:
    """Build a leg from the lesson chain (or your own spot / IV / rate / premium).

    ``kind`` is ``"call"``, ``"put"`` or ``"stock"``; ``side`` ``"buy"`` or ``"sell"``;
    ``expiry`` ``"weekly"``, ``"monthly"``, a ``date`` or a number of days. ``iv`` and
    ``rate`` are fractions (0.14 = 14%). ``premium`` defaults to the model price
    rounded to the chain's tick.
    """
    kind, side = kind.lower(), side.lower()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}")
    if qty < 1:
        raise ValueError("qty is in lots and must be at least 1")
    sym = symbol.upper()
    mkt = chain.market_of(sym, market)
    snap, exp_date = chain.snapshot(mkt, expiry)
    lot, note = chain.units_per_lot(sym, mkt)
    s = float(spot) if spot is not None else chain.default_spot(sym, mkt)
    v = float(iv) if iv is not None else chain.default_iv(sym, mkt, snap)
    r = float(rate) if rate is not None else snap.rate
    k = float(strike) if strike is not None else (s if kind == "stock" else round(s))
    base = Leg(symbol=sym, kind=kind, strike=k, side=side, qty=int(qty), market=mkt, lot=lot,
               lot_note=note, expiry=exp_date, days=float(snap.days), spot=s, iv=v, rate=r,
               premium=0.0, chain_label=snap.label)
    if premium is None:
        premium = s if kind == "stock" else chain.round_tick(float(base.value()), snap.tick)
    return replace(base, premium=float(premium))
