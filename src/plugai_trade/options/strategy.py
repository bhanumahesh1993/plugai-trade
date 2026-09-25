"""Multi-leg strategies: summary tiles, payoff arrays, stress tests and P&L attribution."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

import numpy as np

from . import chain
from . import margin as margin_mod
from .leg import Leg

# Default stress sets (Chapter 23): (label, gap as a fraction, IV change in points or None).
DEFAULT_SCENARIOS = {
    "IN": [("Gap −3%", -0.03, None), ("Gap −5%", -0.05, None), ("Gap +3%", 0.03, None),
           ("IV spike", 0.0, 7.0), ("Gap −5% and IV spike", -0.05, 11.0),
           ("Gap −8% and IV spike", -0.08, 15.0)],
    "US": [("Gap −5%", -0.05, None), ("Gap −10%", -0.10, None), ("Gap +5%", 0.05, None),
           ("IV spike", 0.0, 14.0), ("Gap −10% and IV spike", -0.10, 19.0)],
}


@dataclass(frozen=True)
class Summary:
    """Credit/debit, max profit, max loss, breakevens and margin — per the whole position."""

    market: str
    net: float                      # option premium: + credit received / − debit paid
    stock_cost: float               # cash paid for share legs (covered call)
    max_profit: float | None        # None = unlimited
    max_loss: float | None          # positive number; None = unlimited
    breakevens: list[float]
    expected_move: float
    theta_day: float
    delta: float
    days_left: float
    margin: float | None
    margin_expiry_day: float | None
    margin_model: str = ""
    margin_parts: dict = field(default_factory=dict)

    @property
    def credit(self) -> float:
        """Credit received (0 for a debit position)."""
        return max(self.net, 0.0)

    def tiles(self) -> dict[str, str]:
        """Income tiles: Credit, Max profit, Max loss, Breakeven, 2nd Breakeven, Expected ±1σ,
        Theta/day, Delta, Margin estimate (formatted)."""
        m = self.market
        money = lambda v, d=2: "Unlimited" if v is None else chain.fmt_money(v, m, d)
        be_dec = 2
        out = {("Credit" if self.net >= 0 else "Debit"): money(abs(self.net)),
               "Max profit": money(self.max_profit), "Max loss": money(self.max_loss),
               "Breakeven": chain.fmt_num(self.breakevens[0], m, be_dec) if self.breakevens else "—"}
        if len(self.breakevens) > 1:
            out["2nd Breakeven"] = chain.fmt_num(self.breakevens[1], m, be_dec)
        out["Expected ±1σ"] = f"±{chain.fmt_num(self.expected_move, m, 0 if m == 'IN' else 2)}"
        out["Theta/day"] = money(self.theta_day, 0)
        out["Delta"] = f"{self.delta + 0.0:+.2f}".replace("-0.00", "+0.00")
        if self.margin is not None:
            label = "Margin estimate" + (" (expiry day)" if self.days_left <= 0 else "")
            out[label] = "≈ " + money(self.margin_expiry_day if self.days_left <= 0 else self.margin, 0)
        return out

    def facts(self) -> list[str]:
        """Numbers the AI may cite."""
        out = [f"{k}: {v}" for k, v in self.tiles().items()]
        if self.stock_cost:
            out.append(f"Shares bought: {chain.fmt_money(self.stock_cost, self.market)}")
        if self.margin is not None:
            out.append(f"Margin on expiry day: ≈ {chain.fmt_money(self.margin_expiry_day or 0, self.market, 0)}")
            out.append(f"Margin model: {self.margin_model} — an estimate, not your broker's figure")
        if self.max_loss and self.max_profit:
            out.append(f"Risk per 1 of reward: {self.max_loss / self.max_profit:.2f}")
        out.append(f"Days left: {self.days_left:g}")
        return out

    def __str__(self) -> str:
        return " · ".join(self.facts())


@dataclass(frozen=True)
class StressRow:
    """A position repriced under a gap and/or volatility change."""

    label: str
    spot: float
    iv: float
    days_left: float
    value: float
    pnl: float
    market: str

    def facts(self) -> list[str]:
        m = self.market
        return [f"{self.label}: spot {chain.fmt_num(self.spot, m, 0 if m == 'IN' else 2)}, "
                f"IV {self.iv * 100:.0f}%, {self.days_left:g} days left → P&L "
                f"{chain.fmt_money(self.pnl, m)}"]

    def __str__(self) -> str:
        return self.facts()[0]


@dataclass(frozen=True)
class Attribution:
    """P&L split into delta, gamma, theta, vega and residual (sums to ``actual``)."""

    market: str
    spot_from: float
    spot_to: float
    iv_from: float
    iv_to: float
    days: float
    delta: float
    gamma: float
    theta: float
    vega: float
    residual: float
    actual: float
    theta_per_day: float
    vega_per_point: float

    def parts(self) -> dict[str, float]:
        """Ordered parts for the attribution strip."""
        return {"Theta": self.theta, "Vega": self.vega, "Gamma": self.gamma,
                "Delta": self.delta, "Residual": self.residual}

    def facts(self) -> list[str]:
        m = self.market
        out = [f"Move: spot {chain.fmt_num(self.spot_from, m)} → {chain.fmt_num(self.spot_to, m)}, "
               f"IV {self.iv_from * 100:.0f}% → {self.iv_to * 100:.0f}%, {self.days:g} days"]
        out += [f"{k} (from entry Greeks): {chain.fmt_money(v, m)}" for k, v in self.parts().items()]
        out.append(f"Actual (full repricing): {chain.fmt_money(self.actual, m)}")
        out.append(f"Theta at entry: {chain.fmt_money(self.theta_per_day, m)}/day; "
                   f"vega {chain.fmt_money(self.vega_per_point, m)} per IV point")
        return out

    def __str__(self) -> str:
        return " · ".join(self.facts())


class Strategy:
    """A set of legs on one underlying. ``options.strategy(legs)`` builds one."""

    def __init__(self, legs: Iterable[Leg], name: str = ""):
        self.legs: list[Leg] = list(legs)
        if not self.legs:
            raise ValueError("a strategy needs at least one leg")
        first = self.legs[0]
        if any(lg.symbol != first.symbol or lg.market != first.market for lg in self.legs):
            raise ValueError("all legs must be on the same underlying and market")
        if any(abs(lg.spot - first.spot) > 1e-9 for lg in self.legs):
            raise ValueError("all legs must use the same spot")
        self.name = name or _auto_name(self.legs)

    # ------------------------------------------------------------------ basics
    symbol = property(lambda self: self.legs[0].symbol)
    market = property(lambda self: self.legs[0].market)
    spot = property(lambda self: self.legs[0].spot)
    lot = property(lambda self: self.legs[0].lot)

    @property
    def option_legs(self) -> list[Leg]:
        return [lg for lg in self.legs if lg.kind != "stock"]

    @property
    def days_left(self) -> float:
        """Days to the nearest option expiry."""
        return min((lg.days for lg in self.option_legs), default=0.0)

    @property
    def base_iv(self) -> float:
        opts = self.option_legs
        return float(np.mean([lg.iv for lg in opts])) if opts else 0.0

    @property
    def entry_value(self) -> float:
        """What the position cost to open (+ debit paid, − credit received)."""
        return float(sum(lg.sign * lg.premium * lg.units for lg in self.legs))

    def value(self, spot: float | np.ndarray | None = None, elapsed: float = 0.0,
              iv_shift: float = 0.0) -> np.ndarray:
        """Model value of the whole position; ``iv_shift`` is a parallel IV change (fraction)."""
        s = self.spot if spot is None else spot
        total = np.zeros_like(np.asarray(s, dtype=float))
        for lg in self.legs:
            v = lg.value(s, days=max(lg.days - elapsed, 0.0), iv=max(lg.iv + iv_shift, 0.001))
            total = total + lg.sign * v * lg.units
        return total

    def pnl(self, spot: float | np.ndarray | None = None, elapsed: float = 0.0,
            iv_shift: float = 0.0) -> np.ndarray:
        """Model P&L against the entry premiums."""
        return self.value(spot, elapsed, iv_shift) - self.entry_value

    def at(self, days_left: float) -> Strategy:
        """The position with ``days_left`` to the nearest expiry (later legs shift with it)."""
        shift = self.days_left - float(days_left)
        return Strategy([replace(lg, days=max(lg.days - shift, 0.0)) if lg.kind != "stock" else lg
                         for lg in self.legs], self.name)

    # ------------------------------------------------------------------ payoff
    def _kinks(self) -> np.ndarray:
        strikes = [lg.strike for lg in self.option_legs]
        hi = max([self.spot, *strikes]) * 3.0
        return np.unique(np.concatenate([[0.0], strikes, np.linspace(0.0, hi, 6001)]))

    def expiry_pnl(self, spot: np.ndarray) -> np.ndarray:
        """P&L at the nearest expiry (later-dated legs valued by the model)."""
        return self.pnl(spot, elapsed=self.days_left)

    def payoff(self, lo: float | None = None, hi: float | None = None,
               points: int = 301) -> dict[str, np.ndarray]:
        """Arrays for the payoff chart: ``spot``, ``expiry`` P&L and ``now`` P&L."""
        em = self.expected_move()
        strikes = [lg.strike for lg in self.option_legs] or [self.spot]
        lo = lo if lo is not None else min(min(strikes), self.spot - 2 * em) * 0.98
        hi = hi if hi is not None else max(max(strikes), self.spot + 2 * em) * 1.02
        grid = np.linspace(max(lo, 0.0), hi, points)
        return {"spot": grid, "expiry": self.expiry_pnl(grid), "now": self.pnl(grid)}

    def expected_move(self) -> float:
        """Spot × IV × √(days ÷ 365) to the nearest expiry."""
        return float(self.spot * self.base_iv * np.sqrt(max(self.days_left, 0.0) / 365.0))

    def breakevens(self) -> list[float]:
        """Prices at expiry where P&L crosses zero (exact between strikes)."""
        x = self._kinks()
        y = self.expiry_pnl(x)
        out: list[float] = []
        for i in range(len(x) - 1):
            a, b = y[i], y[i + 1]
            if a == 0 and (not out or abs(out[-1] - x[i]) > 1e-6):
                out.append(float(x[i]))
            elif a * b < 0:
                out.append(float(x[i] - a * (x[i + 1] - x[i]) / (b - a)))
        return [round(v, 2) for v in out]

    def _tail_slope(self) -> float:
        """P&L change per unit rise in price far above every strike (at expiry)."""
        return float(sum(lg.sign * lg.units for lg in self.legs if lg.kind in ("call", "stock")))

    def max_profit_loss(self) -> tuple[float | None, float | None]:
        """(max profit, max loss as a positive number); ``None`` = unlimited."""
        y = self.expiry_pnl(self._kinks())
        slope = self._tail_slope()
        mp = None if slope > 1e-9 else round(float(y.max()), 2)
        ml = None if slope < -1e-9 else round(float(-min(y.min(), 0.0)), 2)
        return mp, ml

    # ------------------------------------------------------------------ Greeks
    def greeks(self) -> dict[str, float]:
        """Position Greeks in money: delta/gamma per point, theta per day, vega per IV point;
        ``delta_lots`` is delta in lots (the Delta tile)."""
        tot = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "delta_lots": 0.0}
        for lg in self.legs:
            g = lg.greeks()
            for k in ("delta", "gamma", "theta", "vega"):
                tot[k] += g["per_lot"][k] * lg.qty
            tot["delta_lots"] += lg.sign * g["per_unit"]["delta"] * lg.qty
        return tot

    # ------------------------------------------------------------------ summary
    def margin_estimate(self, account: str = "cash") -> dict[str, float]:
        """Labelled margin estimate (see ``options.margin``)."""
        return margin_mod.estimate(self, account)

    def summary(self, account: str = "cash", with_margin: bool = True) -> Summary:
        """Credit/debit, max profit, max loss, breakevens, margin estimate and Greeks."""
        mp, ml = self.max_profit_loss()
        g = self.greeks()
        mg = self.margin_estimate(account) if with_margin else {}
        stock = sum(lg.sign * lg.premium * lg.units for lg in self.legs if lg.kind == "stock")
        return Summary(market=self.market, net=round(-(self.entry_value - stock), 2),
                       stock_cost=round(stock, 2), max_profit=mp,
                       max_loss=ml, breakevens=self.breakevens(),
                       expected_move=round(self.expected_move(), 2),
                       theta_day=round(g["theta"], 2), delta=round(g["delta_lots"], 4),
                       days_left=self.days_left, margin=mg.get("margin"),
                       margin_expiry_day=mg.get("margin_expiry_day"),
                       margin_model=str(mg.get("model", "")),
                       margin_parts={k: v for k, v in mg.items() if k != "model"})

    # ------------------------------------------------------------------ stress
    def stress(self, gap: float = 0.0, iv_to: float | None = None, days: float = 1.0,
               label: str = "") -> StressRow:
        """Reprice after ``days`` (default 1) with spot × (1 + gap) and IV moved to ``iv_to``."""
        shift = 0.0 if iv_to is None else iv_to - self.base_iv
        s = self.spot * (1.0 + gap)
        val = float(self.value(s, elapsed=days, iv_shift=shift))
        return StressRow(label=label or _stress_label(gap, iv_to, s, self.market),
                         spot=round(s, 2), iv=self.base_iv + shift,
                         days_left=max(self.days_left - days, 0.0), value=round(val, 2),
                         pnl=round(val - self.entry_value, 2), market=self.market)

    def stress_table(self, extra: Iterable[tuple[str, float, float | None]] = ()) -> list[StressRow]:
        """The chapter's default scenario set (plus your own ``(label, gap, iv_points)`` rows)."""
        rows = []
        for label, gap, iv_pts in [*DEFAULT_SCENARIOS[self.market], *extra]:
            iv_to = None if iv_pts is None else self.base_iv + iv_pts / 100.0
            rows.append(self.stress(gap, iv_to, label=f"{label} ({_stress_label(gap, iv_to, self.spot * (1 + gap), self.market)})"))
        return rows

    # ------------------------------------------------------------------ attribution
    def attribution(self, spot: float, iv: float, days: float) -> Attribution:
        """Split the P&L after ``days`` (to ``spot`` and ``iv``) using entry Greeks.

        Theta is the one-day decay at entry × days; delta and gamma use the price move;
        vega the IV change in points; the residual is whatever full repricing adds.
        """
        g = self.greeks()
        ds = spot - self.spot
        div = iv - self.base_iv
        theta_day = float(self.value(elapsed=1.0) - self.value())
        parts = {"delta": g["delta"] * ds, "gamma": 0.5 * g["gamma"] * ds * ds,
                 "theta": theta_day * days, "vega": g["vega"] * div * 100.0}
        actual = float(self.pnl(spot, elapsed=days, iv_shift=div))
        residual = actual - sum(parts.values())
        return Attribution(market=self.market, spot_from=self.spot, spot_to=spot,
                           iv_from=self.base_iv, iv_to=iv, days=days,
                           delta=round(parts["delta"], 2), gamma=round(parts["gamma"], 2),
                           theta=round(parts["theta"], 2), vega=round(parts["vega"], 2),
                           residual=round(residual, 2), actual=round(actual, 2),
                           theta_per_day=round(theta_day, 2), vega_per_point=round(g["vega"], 2))

    # ------------------------------------------------------------------ narration
    def facts(self) -> list[str]:
        """Legs, summary tiles and the stress table as citable strings."""
        out = [f"Strategy: {self.name} on {self.symbol} ({self.market})"]
        for lg in self.legs:
            out.append(f"Leg: {lg.describe()} × {lg.qty} @ "
                       f"{chain.fmt_money(lg.premium, self.market, 2)} ({lg.days:g} days)")
        out += self.summary().facts()
        out += [r.facts()[0] for r in self.stress_table()]
        return out

    def to_dict(self) -> dict:
        """Plain dict for saving to a plan or a paper order."""
        return {"name": self.name, "symbol": self.symbol, "market": self.market,
                "spot": self.spot,
                "legs": [{"kind": lg.kind, "strike": lg.strike, "side": lg.side, "qty": lg.qty,
                          "expiry": lg.expiry.isoformat(), "days": lg.days, "iv": lg.iv,
                          "rate": lg.rate, "premium": lg.premium, "lot": lg.lot}
                         for lg in self.legs]}

    def __str__(self) -> str:
        return f"{self.name}: {self.summary()}"

    def __repr__(self) -> str:
        return f"Strategy({self.name!r}, {len(self.legs)} legs)"


def _stress_label(gap: float, iv_to: float | None, s: float, market: str) -> str:
    bits = []
    if gap:
        bits.append(f"to {chain.fmt_num(s, market, 0)}")
    if iv_to is not None:
        bits.append(f"IV {iv_to * 100:.0f}%")
    return ", ".join(bits) or "no move"


def _auto_name(legs: list[Leg]) -> str:
    """Name common structures; anything else is "N-leg strategy"."""
    sig = sorted(f"{lg.side} {lg.kind}" for lg in legs)
    if len(legs) == 1:
        return legs[0].describe()
    by = {f"{lg.side} {lg.kind}": lg for lg in legs}
    if sig == ["buy call", "buy put", "sell call", "sell put"]:
        return "Iron condor"
    if sig == ["buy stock", "sell call"]:
        return "Covered call"
    if sig == ["buy put", "sell put"]:
        return "Bull put spread" if by["sell put"].strike > by["buy put"].strike else "Bear put spread"
    if sig == ["buy call", "sell call"]:
        return "Bear call spread" if by["sell call"].strike < by["buy call"].strike else "Bull call spread"
    return f"{len(legs)}-leg strategy"


def strategy(legs: Iterable[Leg], name: str = "") -> Strategy:
    """Combine legs into a strategy: ``.summary()``, ``.stress()``, ``.attribution()``, ``.payoff()``."""
    return Strategy(legs, name)
