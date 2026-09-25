"""Strategy › Pairs Lab: pair finder, frozen formation fit, sizing, hand-offs.

    from plugai_trade import pairs
    fit = pairs.fit_symbols("SYN-A", "SYN-B")      # β 1.168 · half-life 6.1 · t −3.71
    trades, suspended = pairs.run_rule(fit.z, fit.spread, fit.formation)

Numbers are computed here in numpy; the AI only writes the *Check link* note,
and that note is kept only when the user clicks Accept. Nothing here places an
order: Send to Paper Desk writes linked *pending paper orders*.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import numpy as np

from .. import ai, data
from ..store import default as store
from . import sample
from .rules import PairRule, PairTrade, run_rule
from .stats import PairFit, adf_stat, fit, half_life, mackinnon_critical

__all__ = ["PairFit", "PairRule", "PairTrade", "fit", "fit_symbols", "run_rule", "adf_stat",
           "half_life", "mackinnon_critical", "load_closes", "find_pairs", "LotSizing",
           "ShareSizing", "size_lots", "size_shares", "lots_within", "check_link",
           "link_rating", "send_to_paper_desk", "send_to_backtest", "SAMPLE_UNIVERSE"]

SAMPLE_UNIVERSE = sample.SYMBOLS


def load_closes(symbol: str, market: str = "US", start: date | None = None,
                end: date | None = None) -> tuple[list[date], np.ndarray]:
    """Dates and closes. The lesson symbols SYN-A…SYN-D come from the sample pair."""
    if symbol.upper() in sample.SYMBOLS:
        f = sample.closes(symbol, start, end)
    else:
        f = data.get(symbol, market=market, start=start, end=end)
    return f["date"].to_list(), f["close"].to_numpy()


def fit_symbols(a: str, b: str, market: str = "US", formation: int = 250,
                start: date | None = None, end: date | None = None) -> PairFit:
    """Load two symbols, align their dates and fit on the first ``formation`` sessions."""
    da, ca = load_closes(a, market, start, end)
    db, cb = load_closes(b, market, start, end)
    common = sorted(set(da) & set(db))
    ia = {d: i for i, d in enumerate(da)}
    ib = {d: i for i, d in enumerate(db)}
    xa = np.array([ca[ia[d]] for d in common])
    xb = np.array([cb[ib[d]] for d in common])
    return fit(xa, xb, formation, names=(a, b))


@dataclass(frozen=True)
class Candidate:
    """One row of the Pair finder: correlation and cointegration side by side."""

    a: str
    b: str
    correlation: float
    adf_t: float
    critical_5: float
    half_life: float
    beta: float

    @property
    def passes(self) -> bool:
        """Engle–Granger test passed at 5%."""
        return self.adf_t < self.critical_5


def find_pairs(symbols: Iterable[str], market: str = "US", formation: int = 250,
               start: date | None = None, end: date | None = None) -> list[Candidate]:
    """Test every pair in ``symbols`` on the formation window; sorted by the test statistic."""
    out = []
    for a, b in itertools.combinations(list(dict.fromkeys(symbols)), 2):
        try:
            f = fit_symbols(a, b, market, formation, start, end)
        except Exception:  # a symbol with no data is skipped, not fatal
            continue
        out.append(Candidate(a, b, f.correlation, f.adf_t, f.critical_5, f.half_life, f.beta))
    return sorted(out, key=lambda c: c.adf_t)


# ------------------------------------------------------------------ sizing
@dataclass(frozen=True)
class LotSizing:
    """India: both legs in whole futures lots."""

    lots_a: int
    lots_b: int
    value_a: float
    value_b: float
    target_b: float
    target_lots_b: float
    achieved: float
    beta: float

    @property
    def error(self) -> float:
        """Hedge-ratio error as a fraction of the target (negative = under-hedged)."""
        return self.achieved / self.beta - 1

    def facts(self) -> list[str]:
        """Facts for Explain."""
        return [f"Long A: {self.lots_a} lot(s) = {self.value_a:,.0f}",
                f"Target short B = {self.beta:.3f} × long A = {self.target_b:,.0f} "
                f"= {self.target_lots_b:.2f} lots",
                f"Rounded: {self.lots_b} lot(s) = {self.value_b:,.0f}",
                f"Hedge ratio achieved: {self.achieved:.3f} ({self.error:+.1%} vs target)"]


def size_lots(price_a: float, price_b: float, lot_a: int, lot_b: int, beta: float,
              lots_a: int = 1) -> LotSizing:
    """Round the short leg to whole lots and report the hedge-ratio error."""
    value_a = lots_a * lot_a * price_a
    target_b = beta * value_a
    per_lot_b = lot_b * price_b
    lots_b = max(1, round(target_b / per_lot_b))
    value_b = lots_b * per_lot_b
    return LotSizing(lots_a, lots_b, value_a, value_b, target_b, target_b / per_lot_b,
                     value_b / value_a, beta)


def lots_within(price_a: float, price_b: float, lot_a: int, lot_b: int, beta: float,
                tol: float = 0.05, max_lots: int = 200) -> LotSizing | None:
    """Smallest number of A lots whose rounded B leg is within ``tol`` of the hedge ratio."""
    for n in range(1, max_lots + 1):
        s = size_lots(price_a, price_b, lot_a, lot_b, beta, n)
        if abs(s.error) <= tol:
            return s
    return None


@dataclass(frozen=True)
class ShareSizing:
    """US: both legs in whole shares, plus the borrow fee on the short leg."""

    shares_a: int
    shares_b: int
    value_a: float
    value_b: float
    target_b: float
    achieved: float
    beta: float
    borrow_fee: float
    borrow_rate: float
    days: int

    @property
    def error(self) -> float:
        """Hedge-ratio error as a fraction of the target."""
        return self.achieved / self.beta - 1

    def facts(self) -> list[str]:
        """Facts for Explain."""
        return [f"Long A: {self.shares_a} shares = ${self.value_a:,.2f}",
                f"Target short B: ${self.target_b:,.2f} = {self.target_b / (self.value_b / self.shares_b):.1f} shares",
                f"Rounded: {self.shares_b} shares = ${self.value_b:,.2f}",
                f"Hedge ratio achieved: {self.achieved:.3f} ({self.error:+.1%})",
                f"Borrow fee at {self.borrow_rate:.1%} a year for {self.days} days: "
                f"${self.borrow_fee:,.2f}"]


def size_shares(capital: float, price_a: float, price_b: float, beta: float,
                borrow_rate: float = 0.03, days: int = 16) -> ShareSizing:
    """Spend up to ``capital`` on the long leg; round the short leg to shares (ACT/360 fee)."""
    shares_a = int(capital // price_a)
    value_a = shares_a * price_a
    target_b = beta * value_a
    shares_b = max(1, round(target_b / price_b))
    value_b = shares_b * price_b
    fee = value_b * borrow_rate * days / 360
    return ShareSizing(shares_a, shares_b, round(value_a, 2), round(value_b, 2), target_b,
                       value_b / value_a if value_a else math.nan, beta, round(fee, 2),
                       borrow_rate, days)


# ------------------------------------------------------------------ AI link check
LINK_PROMPT = (
    "Candidate pair: {a} and {b}, both listed on {venue}.\n"
    "My description of each business: {desc}\n\n"
    "Do NOT recommend trading this pair or either stock, and do NOT compute any "
    "statistics or predict prices.\n"
    "1. List the drivers these businesses share (demand, costs, regulation, region).\n"
    "2. List the differences that could make their prices drift apart for good.\n"
    "3. List events that would break the pair: mergers, demergers, index changes, new "
    "segments, legal cases. Say what I should watch for each.\n"
    "4. Rate the business link Strong / Weak / None, with one sentence of reasoning.\n"
    "End with a line 'Rating: Strong', 'Rating: Weak' or 'Rating: None'."
)


def link_rating(text: str) -> str | None:
    """Pull Strong / Weak / None out of the model's note (None → unrated)."""
    m = re.search(r"rating\s*[:\-]\s*\**\s*(strong|weak|none)\b", text, re.I)
    if not m:
        m = re.search(r"^\W*(strong|weak|none)\W*$", text, re.I | re.M)
    return m.group(1).capitalize() if m else None


def check_link(a: str, b: str, description: str = "", venue: str = "NYSE") -> ai.Explanation:
    """Ask the model for the economic-link note. Kept only when the user accepts it."""
    prompt = LINK_PROMPT.format(a=a, b=b, venue=venue,
                                desc=ai.fence_untrusted(description or "(none given)"))
    out = ai.complete(prompt, section="Strategy")
    if not out.text:
        out.text = ("No AI model is connected, so there is no link note. Answer the four "
                    "questions yourself: shared drivers, differences, break events, and a "
                    "Strong / Weak / None rating.")
    return out


# ------------------------------------------------------------------ hand-offs
def send_to_paper_desk(f: PairFit, side: int, qty_a: float, qty_b: float,
                       rule: PairRule, events: str = "", market: str = "US") -> list[int]:
    """Create the two legs as linked *pending paper orders*. Nothing fills until Accept."""
    from ..paper.pending import draft_pending

    link = f"pair:{f.a}/{f.b}:{store().count('paper_orders') + 1}"
    exits = (f"exits: |z| <= {rule.exit} · {rule.time_stop} sessions · |z| >= {rule.stop} or event "
             f"({events or 'none listed'})")
    legs = [(f.a, "buy" if side > 0 else "sell", qty_a), (f.b, "sell" if side > 0 else "buy", qty_b)]
    ids = []
    for n, (sym, direction, qty) in enumerate(legs, 1):
        note = f"Pairs leg {n}/2 · {link} · hedge ratio {f.beta:.3f} · {exits}"
        rid = draft_pending({"symbol": sym, "market": market, "side": direction, "qty": qty,
                             "kind": "market", "note": note}, "Pairs Lab")
        row = store().get("paper_orders", rid) or {}
        body = {k: v for k, v in row.items() if k not in ("id", "created", "tag")}
        body.update(link_id=link, hedge_ratio=round(f.beta, 4), events=events,
                    exits={"target": rule.exit, "time": rule.time_stop, "stop": rule.stop})
        store().update("paper_orders", rid, body, tag="pending")
        ids.append(rid)
    store().audit("pairs_send_paper", {"pair": f"{f.a}/{f.b}", "orders": ids})
    return ids


def send_to_backtest(f: PairFit, rule: PairRule, trades: list[PairTrade],
                     suspended: int | None, cost_per_trade: float = 0.0) -> int:
    """Store the pair run for the Backtest Report and add one to the Trials counter."""
    net = [t.spread_pnl - cost_per_trade for t in trades]
    body = {"source": "Pairs Lab", "name": f"Pair {f.a}/{f.b}", "hedge_ratio": f.beta,
            "formation": f.formation, "half_life": f.half_life, "adf_t": f.adf_t,
            "rule": rule.__dict__, "suspended_at": suspended,
            "trades": [t.__dict__ for t in trades], "net_log_returns": net,
            "z": [round(float(x), 4) for x in f.z], "hypothetical": True}
    store().add("trials", {"source": "Pairs Lab", "pair": f"{f.a}/{f.b}"}, tag="pairs")
    return store().add("backtests", body, tag="pairs")
