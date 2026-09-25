"""Plan & Risk › Position Sizer — size is arithmetic, done in code.

    from plugai_trade import sizing
    r = sizing.fixed_risk(1_500_000, 0.01, entry=24850, stop=24700, lot=65, cost_per_lot=1200)
    r.size, r.actual_risk      # 1 lot, 10,950.0

Every method follows Chapter 12: size = risk budget ÷ risk per unit, rounded
*down*, then checked against every cap; the smallest answer wins. A size of 0
comes with the list of choices, never a silent round-up. Lot sizes come from
the dated reference tables; costs from ``costs.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np

from . import costs, reference

TRADING_DAYS_SQRT = 16  # √256: annual vol ≈ daily vol × 16 (Carver's rule of thumb)

ZERO_CHOICES_RISK = [
    "Tighten the idea so that a nearer stop makes sense",
    "Use a smaller instrument (for example an index ETF traded in units)",
    "Raise the budget for this one trade deliberately, and write down why",
    "Pass on this trade",
]

# Correlation groups used by the correlated-group check (market structure, not dated facts).
GROUPS = {
    "NIFTY": "India index", "BANKNIFTY": "India index", "FINNIFTY": "India index",
    "MIDCPNIFTY": "India index", "SENSEX": "India index",
    "SPY": "US equity index", "QQQ": "US equity index", "DIA": "US equity index",
    "IWM": "US equity index", "SPX": "US equity index", "NDX": "US equity index",
    "MES": "US equity index", "MNQ": "US equity index",
    "BTC": "Crypto", "ETH": "Crypto", "USDINR": "Currency",
}


def money(x: float, market: str, decimals: int = 0) -> str:
    """₹15,00,000 (Indian grouping) or $40,000."""
    if market != "IN":
        return f"{'-' if x < 0 else ''}${abs(x):,.{decimals}f}"
    neg, x = x < 0, abs(x)
    whole, _, frac = f"{x:.{decimals}f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    s = ",".join([*groups, tail]) if groups else tail
    return f"{'-' if neg else ''}₹{s}{'.' + frac if frac else ''}"


def _floor(x: float) -> int:
    """Round down, tolerant of float noise (2.0000000001 → 2, 1.9999999999 → 2)."""
    return int(math.floor(round(x, 9)))


def round_price(x: float, tick: float = 0.01) -> float:
    """Round half-up to the nearest tick (597.315 → 597.32)."""
    q = Decimal(str(tick))
    steps = (Decimal(repr(x)) / q).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return float(steps * q)


def base_symbol(symbol: str) -> str:
    """'NIFTY FUT' → 'NIFTY'; 'BTC-PERP' → 'BTC'."""
    s = symbol.upper().replace(" FUT", "").replace("-PERP", "").replace("/USDT", "")
    return s.split()[0] if s else s


def group_of(symbol: str) -> str:
    return GROUPS.get(base_symbol(symbol), base_symbol(symbol))


def lot_for(symbol: str, market: str) -> int:
    """Units per contract from the dated tables: lot (IN F&O), multiplier (US futures), else 1."""
    b = base_symbol(symbol)
    if market == "IN" and "FUT" in symbol.upper():
        return int(reference.lot_size(b) or 1)
    row = reference.lookup(f"us.contracts.{b}") or {}
    if market == "US" and "expiry" in row:  # futures rows carry an expiry; ETF rows an option style
        return reference.multiplier(b)
    return 1


def cost_allowance(symbol: str, market: str, entry: float, stop: float, lot: int = 1,
                   slippage: float | None = None) -> float:
    """Round-trip cost + slippage allowance per lot (or per share), from the dated cost table.

    India F&O: charges for buying at entry and exiting at the stop, plus slippage
    on both sides (default 2 points a side), rounded to the nearest ₹100 — the
    Chapter 12 NIFTY example gives ₹1,200. US shares: spread + slippage per share
    (default $0.05) plus the modelled regulatory fee, rounded to the nearest $0.05.
    """
    if market == "IN" and "FUT" in symbol.upper():
        slip = 2.0 if slippage is None else slippage
        c = costs.round_trip("IN-futures", entry * lot, stop * lot)["total"] + 2 * slip * lot
        return float(round(c, -2))
    if market == "IN":
        slip = 0.05 if slippage is None else slippage
        c = costs.round_trip("IN-equity-delivery", entry, stop)["total"] + 2 * slip
        return round(c, 2)
    slip = 0.05 if slippage is None else slippage
    fee = costs.us_round_trip(entry, stop)["regulatory"]
    return round(round((slip + fee) / 0.05) * 0.05, 2)


@dataclass
class SizeResult:
    """One Position Sizer answer. Every number is computed here, never by a model."""

    method: str
    market: str
    symbol: str
    account: float
    risk_pct: float
    budget: float
    entry: float
    stop: float | None
    lot: int
    risk_per_lot: float
    raw_size: float
    size: int                      # lots (F&O) or shares
    actual_risk: float
    notional: float
    cap_pct: float | None = None
    cap_size: int | None = None
    risk_size: int | None = None
    binding: str = "risk budget"
    choices: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def unit(self) -> str:
        return "lot" if self.lot > 1 else "share"

    @property
    def quantity(self) -> int:
        """Units traded: lots × lot size, or shares."""
        return self.size * self.lot

    @property
    def actual_risk_pct(self) -> float:
        return self.actual_risk / self.account if self.account else 0.0

    @property
    def notional_x(self) -> float:
        """Notional exposure as a multiple of the account (1.08× for one NIFTY lot)."""
        return self.notional / self.account if self.account else 0.0

    @property
    def cur(self) -> str:
        return "₹" if self.market == "IN" else "$"

    def size_text(self) -> str:
        u = self.unit + ("s" if self.size != 1 else "")
        return (f"{self.size} {u} · risk {self.cur}{self.actual_risk:,.2f} "
                f"= {self.actual_risk_pct:.2%} of account")

    def facts(self) -> list[str]:
        c = self.cur
        out = [f"Method: {self.method}", f"Account: {c}{self.account:,.0f}",
               f"Risk per trade: {self.risk_pct:.2%}", f"Risk budget: {c}{self.budget:,.2f}",
               f"Entry: {self.entry:,.2f}"]
        if self.stop is not None:
            out.append(f"Stop: {self.stop:,.2f}")
        if self.lot > 1:
            out.append(f"Lot size: {self.lot} (dated table, as of {reference.as_of()})")
        out += [f"Risk per {self.unit}: {c}{self.risk_per_lot:,.2f}",
                f"Raw size: {self.raw_size:.2f} {self.unit}s",
                f"Size (rounded down): {self.size} {self.unit}s",
                f"Actual risk: {c}{self.actual_risk:,.2f} ({self.actual_risk_pct:.2%} of account)",
                f"Notional exposure: {c}{self.notional:,.2f} ({self.notional_x:.2f}× account)",
                f"Binding rule: {self.binding}"]
        if self.cap_size is not None:
            out.append(f"Position cap {self.cap_pct:.0%} allows {self.cap_size} {self.unit}s")
        out += [f"Choice if 0: {ch}" for ch in self.choices]
        out += self.notes
        return out


def _apply_cap(res: SizeResult, cap_pct: float | None) -> SizeResult:
    if cap_pct is None or res.entry <= 0:
        return res
    if res.lot > 1:  # contracts: the cap is a cash-position rule; notional is shown as a warning
        res.notes.append(f"Position cap {cap_pct:.0%} applies to cash positions; for contracts "
                         "watch the notional exposure tile")
        return res
    cap_size = _floor(res.account * cap_pct / (res.entry * res.lot))
    res.cap_pct, res.cap_size, res.risk_size = cap_pct, cap_size, res.size
    if cap_size < res.size:
        res.size, res.binding = cap_size, "position cap"
    return res


def _finish(res: SizeResult) -> SizeResult:
    res.actual_risk = round(res.size * res.risk_per_lot, 2)
    res.notional = round(max(res.size, 1 if res.lot > 1 else res.size) * res.lot * res.entry, 2)
    if res.size == 0 and res.method != "Vol target":
        res.choices = list(ZERO_CHOICES_RISK)
        res.notes.append(f"1 {res.unit} would risk {res.cur}{res.risk_per_lot:,.2f}, "
                         f"more than the {res.cur}{res.budget:,.2f} budget")
    return res


def fixed_risk(account: float, risk_pct: float, entry: float, stop: float, lot: int = 1,
               cost_per_lot: float = 0.0, cap_pct: float | None = None, symbol: str = "",
               market: str = "IN") -> SizeResult:
    """Fixed-fractional sizing: budget ÷ ((|entry − stop|) × lot + costs per lot), rounded down.

    ``cost_per_lot`` is the cost-and-slippage allowance per lot (or per share when lot = 1).
    """
    if entry == stop:
        raise ValueError("Entry and stop are the same price: there is no risk per unit to size.")
    budget = round(account * risk_pct, 2)
    rpl = round(abs(entry - stop) * lot + cost_per_lot, 2)
    raw = budget / rpl
    res = SizeResult("Fixed risk %", market, symbol, account, risk_pct, budget, entry, stop, lot,
                     rpl, raw, _floor(raw), 0.0, 0.0)
    return _finish(_apply_cap(res, cap_pct))


def atr_stop(account: float, risk_pct: float, entry: float, atr: float, multiple: float,
             lot: int = 1, cost_per_lot: float = 0.0, cap_pct: float | None = None,
             side: str = "long", tick: float = 0.01, stop_override: float | None = None,
             symbol: str = "", market: str = "IN") -> SizeResult:
    """ATR stop: stop = entry ∓ multiple × ATR(14), rounded to the tick; then fixed-risk sizing.

    ``stop_override`` lets the trader type the stop the tile suggested, rounded to a
    tick of their choice (Chapter 17: 597.32 → 597.30).
    """
    sign = -1 if side == "long" else 1
    stop = stop_override if stop_override is not None else round_price(entry + sign * multiple * atr, tick)
    res = fixed_risk(account, risk_pct, entry, stop, lot, cost_per_lot, cap_pct, symbol, market)
    res.method = "ATR stop"
    res.extra.update(atr=atr, atr_multiple=multiple, suggested_stop=round_price(entry + sign * multiple * atr, tick))
    res.notes.insert(0, f"ATR (14): {atr:,.4g} × {multiple:g} = {multiple * atr:,.2f} stop distance")
    return res


def vol_target(account: float, target_vol: float, price: float, daily_vol: float, lot: int = 1,
               cap_pct: float | None = None, symbol: str = "", market: str = "IN") -> SizeResult:
    """Volatility targeting: (account × target ÷ 16) ÷ (price × daily vol × lot), rounded down.

    A 0 comes with three choices: accept the known overshoot, a smaller instrument, or skip.
    """
    annual = account * target_vol
    daily_target = annual / TRADING_DAYS_SQRT
    move_per_lot = round(price * daily_vol, 2) * lot
    raw = daily_target / move_per_lot
    res = SizeResult("Vol target", market, symbol, account, 0.0, round(daily_target, 2), price, None,
                     lot, round(move_per_lot, 2), raw, _floor(raw), 0.0, 0.0,
                     binding="volatility target")
    res = _apply_cap(res, cap_pct)
    res.actual_risk = round(res.size * move_per_lot, 2)
    res.notional = round(max(res.size, 1 if lot > 1 else res.size) * lot * price, 2)
    one_unit_vol = move_per_lot * TRADING_DAYS_SQRT / account
    res.extra.update(target_vol=target_vol, annual_budget=annual, daily_vol=daily_vol,
                     one_unit_annual_vol=one_unit_vol)
    res.notes += [f"Annual volatility budget: {res.cur}{annual:,.0f}",
                  f"Daily risk target (÷16): {res.cur}{daily_target:,.2f}",
                  f"Daily move per {res.unit}: {res.cur}{move_per_lot:,.2f}"]
    if res.size == 0:
        res.choices = [f"Accept a known overshoot: 1 {res.unit} ≈ {one_unit_vol:.1%} a year, "
                       f"not {target_vol:.0%} — record it on the plan",
                       "Use a smaller instrument", "Skip"]
    return res


# ---------------------------------------------------------------- portfolio checks
def combined_risk(risks_r: list[float], correlation: float) -> float:
    """Combined risk (in R) of positions with one common pairwise correlation.

    Three 1R positions: √(3 + 6ρ) R — 1.7R at 0, 2.8R at 0.8, 3.0R at 1.
    """
    r = np.asarray(risks_r, float)
    total = (r ** 2).sum() + correlation * (r.sum() ** 2 - (r ** 2).sum())
    return float(math.sqrt(max(total, 0.0)))


@dataclass
class CapCheck:
    ok: bool
    total_open_r: float
    group: str
    group_r: float
    group_effective_r: float
    messages: list[str]

    def facts(self) -> list[str]:
        return [f"Open risk incl. this trade: {self.total_open_r:.2f}R",
                f"Group '{self.group}': {self.group_r:.2f}R "
                f"(behaves like {self.group_effective_r:.2f}R)", *self.messages]


def check_caps(open_positions: list[dict[str, Any]], symbol: str, new_risk_r: float,
               total_cap_r: float = 3.0, group_cap_r: float = 2.0,
               correlation: float = 0.8) -> CapCheck:
    """Total open risk and correlated-group checks before a size is shown (Chapter 12).

    ``open_positions``: dicts with ``symbol`` and ``risk_r``.
    """
    g = group_of(symbol)
    total = sum(float(p.get("risk_r", 0)) for p in open_positions) + new_risk_r
    same = [float(p.get("risk_r", 0)) for p in open_positions if group_of(p["symbol"]) == g]
    grp = sum(same) + new_risk_r
    eff = combined_risk([*same, new_risk_r], correlation)
    msgs = []
    if total > total_cap_r + 1e-9:
        msgs.append(f"Total open risk {total:.2f}R is above the {total_cap_r:g}R cap")
    if eff > group_cap_r + 1e-9:
        msgs.append(f"Correlated group '{g}' behaves like {eff:.2f}R, above the {group_cap_r:g}R cap")
    return CapCheck(not msgs, round(total, 4), g, round(grp, 4), round(eff, 4), msgs)


# ---------------------------------------------------------------- Hedge mode
@dataclass
class HedgeResult:
    exposure_usd: float
    side: str               # receivable | payable
    futures_price: float
    lot_usd: float
    lots: int
    futures_side: str       # sell | buy
    locked_inr: float
    scenarios: list[dict[str, float]]

    def facts(self) -> list[str]:
        out = [f"Exposure: ${self.exposure_usd:,.0f} ({self.side})",
               f"USDINR futures price: {self.futures_price:.2f}",
               f"Lot: ${self.lot_usd:,.0f} (dated table, as of {reference.as_of()})",
               f"Hedge: {self.futures_side} {self.lots} lots",
               f"Rupee value locked: ₹{self.locked_inr:,.0f}"]
        out += [f"At {s['rate']:.2f}: invoice ₹{s['invoice_inr']:,.0f}, futures "
                f"₹{s['futures_pnl']:+,.0f}, total ₹{s['total']:,.0f}" for s in self.scenarios]
        return out


def hedge(exposure_usd: float, futures_price: float, side: str = "receivable",
          symbol: str = "USDINR", hedge_ratio: float = 1.0,
          rates: tuple[float, ...] = (85, 86, 87, 88, 89, 90, 91, 92)) -> HedgeResult:
    """Hedge mode: an exposure → whole lots of currency futures, plus a scenario table.

    Receivables are hedged by *selling* futures; payables by buying. Costs ignored.
    """
    row = reference.lookup(f"india.contracts.{symbol.upper()}") or {}
    lot_usd = float(row.get("lot_usd") or 0)
    if not lot_usd:
        raise ValueError(f"No dated lot size for {symbol}; check Derivatives › Contract Table.")
    lots = _floor(exposure_usd * hedge_ratio / lot_usd)
    fut_side = "sell" if side == "receivable" else "buy"
    sign = 1 if fut_side == "sell" else -1
    hedged = lots * lot_usd
    scen = []
    for r in rates:
        invoice = exposure_usd * r * (1 if side == "receivable" else -1)
        pnl = sign * (futures_price - r) * hedged
        scen.append({"rate": float(r), "invoice_inr": round(invoice, 2),
                     "futures_pnl": round(pnl, 2), "total": round(invoice + pnl, 2)})
    return HedgeResult(exposure_usd, side, futures_price, lot_usd, lots, fut_side,
                       round(exposure_usd * futures_price, 2), scen)


# ---------------------------------------------------------------- Simulate streaks
@dataclass
class StreakResult:
    risk_pct: float
    win_rate: float
    win_r: float
    loss_r: float
    sequences: int
    trades: int
    seed: int
    typical_fall: float        # median of each path's max drawdown
    bad_luck_fall: float       # 95th percentile
    share_dd_30: float
    share_touch_50: float
    median_final: float
    p5_final: float
    streak_median: float
    streak_p10: float
    streak_p90: float
    fan: dict[str, list[float]]  # percentile bands every 5 trades, % of start

    def facts(self) -> list[str]:
        return [f"Setup: {self.win_rate:.0%} wins at +{self.win_r:g}R, losses at {self.loss_r:g}R",
                f"Risk per trade: {self.risk_pct:.2%}",
                f"{self.sequences:,} sequences of {self.trades} trades, seed {self.seed}",
                f"Typical fall (median max drawdown): {self.typical_fall:.1%}",
                f"Bad-luck fall (95th percentile): {self.bad_luck_fall:.1%}",
                f"Paths with a ≥30% fall: {self.share_dd_30:.1%}",
                f"Paths that touched 50%: {self.share_touch_50:.1%}",
                f"Median ending equity: {self.median_final:.1%} of start",
                f"5th percentile ending equity: {self.p5_final:.1%} of start",
                f"Longest losing streak: median {self.streak_median:g}, "
                f"10th–90th percentile {self.streak_p10:g}–{self.streak_p90:g}"]


def _longest_run(losses: np.ndarray) -> np.ndarray:
    run = np.zeros(losses.shape[0], int)
    best = np.zeros(losses.shape[0], int)
    for j in range(losses.shape[1]):
        run = np.where(losses[:, j], run + 1, 0)
        best = np.maximum(best, run)
    return best


def simulate_streaks(win_rate: float = 0.4, win_r: float = 1.6, loss_r: float = -1.0,
                     risk_pct: float = 0.01, sequences: int = 2000, trades: int = 100,
                     seed: int = 12, r_values: list[float] | None = None) -> StreakResult:
    """Monte Carlo of R-sequences, compounding at ``risk_pct`` per trade (Chapter 12).

    With the defaults it reproduces the book's table (seed 12): 1% → typical fall
    11.3%, bad-luck fall 21.8%. Pass ``r_values`` (your journal's R-multiples) to
    bootstrap from your own results instead of the two-outcome model.
    """
    rng = np.random.default_rng(seed)
    if r_values:
        r = rng.choice(np.asarray(r_values, float), size=(sequences, trades))
    else:
        wins = rng.random((sequences, trades)) < win_rate
        r = np.where(wins, win_r, loss_r)
    eq = np.cumprod(1 + risk_pct * r, axis=1)
    eq = np.concatenate([np.ones((sequences, 1)), eq], axis=1)
    peak = np.maximum.accumulate(eq, axis=1)
    dd = (1 - eq / peak).max(axis=1)
    streak = _longest_run(r < 0)
    idx = list(range(0, trades + 1, 5))
    fan = {f"p{p}": [round(float(v) * 100, 1) for v in np.percentile(eq[:, idx], p, axis=0)]
           for p in (5, 25, 50, 75, 95)}
    fan["trade"] = [float(i) for i in idx]
    return StreakResult(risk_pct, win_rate, win_r, loss_r, sequences, trades, seed,
                        float(np.median(dd)), float(np.percentile(dd, 95)),
                        float((dd >= 0.3).mean()), float((eq.min(axis=1) <= 0.5).mean()),
                        float(np.median(eq[:, -1])), float(np.percentile(eq[:, -1], 5)),
                        float(np.median(streak)), float(np.percentile(streak, 10)),
                        float(np.percentile(streak, 90)), fan)
