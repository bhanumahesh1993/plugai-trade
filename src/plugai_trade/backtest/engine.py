"""The event-driven engine: decide on a completed bar, fill at the next open.

For each bar *t* the engine builds a :class:`DataView` that ends at *t*, asks
the strategy for target weights, and fills any change at bar *t+1*'s open with
slippage and the charges from ``plugai_trade.costs``. The strategy cannot move
the fill earlier: the engine owns the clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import numpy as np
import polars as pl

from .. import costs as _costs
from .spec import (
    DAYS_PER_MONTH,
    DEFAULT_CAPITAL,
    DEFAULT_SLEEVE,
    DEFAULT_SLIPPAGE_PCT,
    Condition,
    Operand,
    Spec,
)
from .view import DataView, Series

TRADING_DAYS = 252
SQRT_256 = 16.0  # Chapter 12/18: annual vol ≈ daily vol × 16


@dataclass
class State:
    """What a strategy may know about its own book (never about the future)."""

    units: dict[str, int]
    equity: float
    entry_fill: dict[str, float]
    bars_held: dict[str, int]


class Strategy(Protocol):
    """Anything with ``decide(views, state) -> {symbol: weight} | None``."""

    def decide(self, views: dict[str, DataView], state: State) -> dict[str, float] | None: ...


# ------------------------------------------------------------------ rule strategies
def _operand_value(view: DataView, op: Operand, ago: int = 0) -> float:
    if op.kind == "close":
        return view.close(ago)
    if op.kind == "value":
        return float(op.value)
    return view.indicator(op.kind, int(op.n), ago)


def _holds(view: DataView, c: Condition) -> bool:
    l, r = _operand_value(view, c.left), _operand_value(view, c.right)
    if math.isnan(l) or math.isnan(r):
        return False
    if c.op == "above":
        return l > r
    if c.op == "below":
        return l < r
    l1, r1 = _operand_value(view, c.left, 1), _operand_value(view, c.right, 1)
    if math.isnan(l1) or math.isnan(r1):
        return False
    if c.op == "cross_above":
        return l > r and l1 <= r1
    return l < r and l1 >= r1  # cross_below


class RuleStrategy:
    """Runs a single-instrument :class:`Spec` through the wall."""

    def __init__(self, spec: Spec, symbol: str):
        self.spec, self.symbol = spec, symbol

    def _weight_in(self, view: DataView) -> float | None:
        s = self.spec.size
        if s.method != "vol_target":
            return s.cap
        dv = view.daily_vol(s.vol_lookback)
        if math.isnan(dv) or dv <= 0:
            return None
        return min(s.cap, s.target_vol / SQRT_256 / dv)

    def decide(self, views: dict[str, DataView], state: State) -> dict[str, float] | None:
        view, sym, sp = views[self.symbol], self.symbol, self.spec
        held = state.units.get(sym, 0) > 0
        if sp.mode == "hold_while":
            if all(_holds(view, c) for c in sp.entry):
                w = self._weight_in(view)
                return None if w is None else {sym: w}
            return {sym: 0.0}
        if not held:
            if all(_holds(view, c) for c in sp.entry):
                w = self._weight_in(view)
                return None if w is None else {sym: w}
            return None
        if any(_holds(view, c) for c in sp.exit):
            return {sym: 0.0}
        if sp.time_stop and state.bars_held.get(sym, 0) >= sp.time_stop:
            return {sym: 0.0}
        if sp.stop_loss_pct and view.close() <= state.entry_fill[sym] * (1 - sp.stop_loss_pct / 100):
            return {sym: 0.0}
        if sp.size.method == "vol_target":
            w = self._weight_in(view)
            return None if w is None else {sym: w}
        return None


class RotationStrategy:
    """Monthly relative-strength rotation (Chapter 16): hold the top N by lookback return."""

    def __init__(self, spec: Spec):
        self.spec = spec

    def decide(self, views: dict[str, DataView], state: State) -> dict[str, float] | None:
        lb = self.spec.lookback_months * DAYS_PER_MONTH
        scores = {}
        for sym, v in views.items():
            now, then = v.close(), v.close(lb)
            if not (math.isnan(now) or math.isnan(then)) and then > 0:
                scores[sym] = now / then - 1
        if len(scores) < len(views):
            return None  # not enough history yet
        top = sorted(scores, key=lambda s: (-scores[s], s))[: self.spec.top_n]
        w = self.spec.size.cap / self.spec.top_n
        return {s: (w if s in top else 0.0) for s in views}


# ------------------------------------------------------------------ costs
def leg_cost(profile: str, buy_value: float, sell_value: float) -> dict[str, float]:
    """Charges for one leg (a buy or a sell), from the dated tables via ``costs``."""
    if profile.startswith("IN-"):
        kind = {"IN-equity-delivery": "delivery", "IN-equity-intraday": "intraday",
                "IN-futures": "futures", "IN-options": "options"}[profile]
        items = _costs.india_round_trip(buy_value, sell_value, kind, orders=1)
        if sell_value == 0 and items.get("dp"):
            items["total"] = round(items["total"] - items["dp"], 2)
            items["dp"] = 0.0
        return items
    items = _costs.us_round_trip(buy_value, sell_value)
    half = items["commission"] / 2
    items["commission"] -= half
    items["total"] = round(items["total"] - half, 2)
    return items


# ------------------------------------------------------------------ calendar
def check_bars(dates: list[date], check: str) -> np.ndarray:
    """Which bars are decision bars. The engine knows the calendar; strategies do not."""
    n = len(dates)
    if check == "daily":
        return np.ones(n, dtype=bool)
    out = np.zeros(n, dtype=bool)
    for i, d in enumerate(dates):
        nxt = dates[i + 1] if i + 1 < n else None
        if check == "weekly":
            out[i] = d.weekday() == 4 or (nxt is not None and nxt.isocalendar()[:2] != d.isocalendar()[:2])
        else:
            out[i] = nxt is not None and (nxt.year, nxt.month) != (d.year, d.month)
    return out


# ------------------------------------------------------------------ the loop
@dataclass
class Book:
    """Raw output of one pass of the engine."""

    dates: list[date]
    equity: np.ndarray
    benchmark: np.ndarray
    exposure: np.ndarray
    fills: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    capital: float = 0.0
    final_units: dict[str, int] = field(default_factory=dict)


def align(bars: dict[str, pl.DataFrame]) -> dict[str, pl.DataFrame]:
    """Keep only dates every instrument has, so one clock drives them all."""
    common: set | None = None
    for df in bars.values():
        ds = set(df["date"].to_list())
        common = ds if common is None else common & ds
    keep = sorted(common or [])
    return {s: df.filter(pl.col("date").is_in(keep)).sort("date") for s, df in bars.items()}


def simulate(strategy: Strategy, bars: dict[str, pl.DataFrame], spec: Spec, profile: str,
             frictionless: bool = False) -> Book:
    """Run ``strategy`` over aligned bars. Decisions at bar t, fills at bar t+1's open."""
    series = {s: Series(df) for s, df in align(bars).items()}
    syms = list(series)
    first = series[syms[0]]
    dates, n = first.dates, len(first)
    if n < 3:
        raise ValueError("need at least three bars to test")
    market = spec.market_of(profile)
    default_cap = DEFAULT_SLEEVE if spec.size.method == "vol_target" else DEFAULT_CAPITAL
    capital = float(spec.size.capital or default_cap[market])
    slip = 0.0 if frictionless else (spec.cost.slippage_pct if spec.cost.slippage_pct is not None
                                     else DEFAULT_SLIPPAGE_PCT[market]) / 100
    buy_rate = 0.0 if frictionless else leg_cost(profile, 1e6, 0)["total"] / 1e6
    checks = check_bars(dates, spec.check)
    opens = {s: series[s].cols["open"] for s in syms}
    closes = {s: series[s].cols["close"] for s in syms}

    cash, units = capital, {s: 0 for s in syms}
    entry_fill = {s: 0.0 for s in syms}
    bars_held = {s: 0 for s in syms}
    open_trades: dict[str, dict[str, Any]] = {}
    book = Book(dates=dates, equity=np.empty(n), benchmark=np.empty(n), exposure=np.zeros(n),
                capital=capital)
    book.equity[0] = capital

    def fill(sym: str, delta: int, t: int) -> None:
        nonlocal cash
        px = float(opens[sym][t])
        fpx = px * (1 + slip) if delta > 0 else px * (1 - slip)
        value = abs(delta) * fpx
        items = {} if frictionless else (
            leg_cost(profile, value, 0) if delta > 0 else leg_cost(profile, 0, value))
        charges = items.get("total", 0.0)
        slippage = abs(delta) * px * slip
        cash += -value - charges if delta > 0 else value - charges
        units[sym] += delta
        book.fills.append({"date": dates[t], "symbol": sym, "side": "BUY" if delta > 0 else "SELL",
                           "units": abs(delta), "price": round(fpx, 4), "value": round(value, 2),
                           "charges": charges, "slippage": round(slippage, 2),
                           "items": {k: v for k, v in items.items() if k != "total"}})
        tr = open_trades.get(sym)
        if tr is None:
            tr = open_trades[sym] = {"symbol": sym, "entry_date": dates[t], "entry_bar": t,
                                     "buy_value": 0.0, "sell_value": 0.0, "buy_raw": 0.0,
                                     "sell_raw": 0.0, "bought": 0, "charges": 0.0,
                                     "slippage": 0.0, "max_units": 0}
            entry_fill[sym] = fpx
            bars_held[sym] = 0
        side = "buy" if delta > 0 else "sell"
        tr[f"{side}_value"] += value
        tr[f"{side}_raw"] += abs(delta) * px
        tr["bought"] += max(delta, 0)
        tr["charges"] += charges
        tr["slippage"] += slippage
        tr["max_units"] = max(tr["max_units"], units[sym])
        if units[sym] == 0:
            book.trades.append(_close_trade(open_trades.pop(sym), dates[t], t))

    for t in range(n - 1):
        equity_t = cash + sum(units[s] * closes[s][t] for s in syms)
        if checks[t]:
            views = {s: DataView(series[s], t, s) for s in syms}
            state = State(dict(units), equity_t, dict(entry_fill), dict(bars_held))
            target = strategy.decide(views, state)
            if target:
                orders = _orders(target, units, closes, t, equity_t, spec)
                for sym, delta in sorted(orders.items(), key=lambda kv: kv[1]):  # sells first
                    if delta > 0:
                        afford = int(max(cash, 0) // (opens[sym][t + 1] * (1 + slip) * (1 + buy_rate)))
                        delta = min(delta, afford)
                    if delta:
                        fill(sym, delta, t + 1)
        for s in syms:
            if units[s] > 0:
                bars_held[s] += 1
        mv = sum(units[s] * closes[s][t + 1] for s in syms)
        book.equity[t + 1] = cash + mv
        book.exposure[t + 1] = mv / book.equity[t + 1] if book.equity[t + 1] > 0 else 0.0
    for sym, tr in open_trades.items():  # marked to market, not a completed round trip
        rec = _close_trade(tr, dates[-1], n - 1, mark=float(units[sym] * closes[sym][-1]))
        rec["open"] = True
        book.trades.append(rec)
    book.final_units = dict(units)
    book.benchmark = _buy_and_hold(opens, closes, capital, slip, buy_rate, n)
    return book


def _orders(target: dict[str, float], units: dict[str, int], closes: dict[str, np.ndarray],
            t: int, equity: float, spec: Spec) -> dict[str, int]:
    out: dict[str, int] = {}
    for sym, w in target.items():
        px = closes[sym][t]
        want = int(max(w, 0) * equity // px) if px > 0 else 0
        have = units[sym]
        if want == have:
            continue
        if have > 0 and want > 0:
            if spec.size.method != "vol_target":
                continue  # all-capital / equal-weight: no resizing while held
            if abs(want - have) * px < spec.size.buffer * equity:
                continue  # inside the buffer: not worth the costs
        out[sym] = want - have
    return out


def _close_trade(tr: dict[str, Any], when: date, t: int, mark: float = 0.0) -> dict[str, Any]:
    sell_raw = tr["sell_raw"] + mark
    sell_val = tr["sell_value"] + mark
    gross = sell_raw - tr["buy_raw"]
    net = sell_val - tr["buy_value"] - tr["charges"]
    return {"symbol": tr["symbol"], "entry_date": tr["entry_date"], "exit_date": when,
            "bars": t - tr["entry_bar"], "units": tr["max_units"],
            "entry_price": round(tr["buy_raw"] / max(tr["bought"], 1), 4),
            "buy_value": round(tr["buy_value"], 2), "sell_value": round(sell_val, 2),
            "gross_pnl": round(gross, 2), "charges": round(tr["charges"], 2),
            "slippage": round(tr["slippage"], 2), "net_pnl": round(net, 2),
            "return_pct": round(net / tr["buy_value"] * 100, 3) if tr["buy_value"] else 0.0,
            # aliases read by Paper Desk › Compare with backtest (drift report)
            "pnl": round(net, 2), "costs": round(tr["charges"] + tr["slippage"], 2),
            "ret": round(net / tr["buy_value"], 6) if tr["buy_value"] else 0.0,
            "open": False}


def _buy_and_hold(opens: dict[str, np.ndarray], closes: dict[str, np.ndarray], capital: float,
                  slip: float, buy_rate: float, n: int) -> np.ndarray:
    """Buy on the first possible fill (bar 1's open), equal weight, and hold."""
    per = capital / len(opens)
    cash = capital
    held = {}
    for s, o in opens.items():
        u = int(per // (o[1] * (1 + slip) * (1 + buy_rate)))
        held[s] = u
        cash -= u * o[1] * (1 + slip) * (1 + buy_rate)
    out = np.empty(n)
    out[0] = capital
    mv = sum(held[s] * closes[s][1:] for s in held)
    out[1:] = cash + mv
    return out


def strategy_for(spec: Spec, symbols: list[str]) -> Strategy:
    return RotationStrategy(spec) if spec.mode == "rotation" else RuleStrategy(spec, symbols[0])


def as_bar_map(bars: pl.DataFrame | dict[str, pl.DataFrame], symbol: str | None = None
               ) -> dict[str, pl.DataFrame]:
    if isinstance(bars, dict):
        return bars
    name = symbol or (str(bars["symbol"][0]) if "symbol" in bars.columns else "instrument")
    return {name: bars}



def next_session_orders(spec: Spec, bars: dict[str, pl.DataFrame], profile: str,
                        units: dict[str, int], equity: float) -> dict[str, int]:
    """Changes the rule asks for on the latest completed bar, to fill at the next open.

    Used to draft *pending paper orders*; nothing here can place an order.
    """
    series = {s: Series(df) for s, df in align(bars).items()}
    syms = list(series)
    t = len(series[syms[0]]) - 1
    views = {s: DataView(series[s], t, s) for s in syms}
    closes = {s: series[s].cols["close"] for s in syms}
    held = {s: int(units.get(s, 0)) for s in syms}
    state = State(held, equity, {s: 0.0 for s in syms}, {s: 0 for s in syms})
    target = strategy_for(spec, syms).decide(views, state)
    return _orders(target, held, closes, t, equity, spec) if target else {}
