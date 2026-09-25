"""Compare with backtest: the shadow backtest and the drift report (Chapter 13).

The shadow backtest re-runs the same rule on the bars recorded during the paper
period, with the same fill and cost model. The drift report then splits the gap
between the shadow record and the paper record into *costs* and *rule breaks*
(skips, late entries, moved stops, off-plan trades). Every number is computed here.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

BREAKS = ("skip", "late entry", "stop moved away", "off-plan")


class ShadowUnavailable(RuntimeError):
    """The Backtest module is not available in this build."""


@dataclass
class DriftRow:
    signal: str
    kind: str                 # cost | skip | late entry | stop moved away | off-plan
    shadow_r: float | None
    paper_r: float | None
    cost_r: float
    break_r: float
    trade_id: Any = None
    note: str = ""


@dataclass
class DriftReport:
    shadow_r: float
    paper_r: float
    cost_gap_r: float
    break_gap_r: float
    signals: int
    taken: int
    rows: list[DriftRow] = field(default_factory=list)

    @property
    def gap_r(self) -> float:
        return round(self.shadow_r - self.paper_r, 4)

    def count(self, kind: str) -> int:
        return sum(1 for r in self.rows if r.kind == kind)

    @property
    def breaks(self) -> list[DriftRow]:
        return [r for r in self.rows if r.kind != "cost"]

    @property
    def adherence(self) -> float:
        """Decisions handled as the rules say ÷ all decisions (signals + off-plan trades)."""
        decisions = self.signals + self.count("off-plan")
        return (decisions - len(self.breaks)) / decisions if decisions else 1.0

    def facts(self) -> list[str]:
        out = [f"Signals: {self.signals}", f"Signals taken: {self.taken}",
               f"Skipped: {self.count('skip')}", f"Late entries: {self.count('late entry')}",
               f"Stops moved away: {self.count('stop moved away')}",
               f"Off-plan trades: {self.count('off-plan')}",
               f"Shadow backtest: {self.shadow_r:+.2f}R", f"Paper: {self.paper_r:+.2f}R",
               f"Gap: {self.gap_r:.2f}R",
               f"Cost gap: {self.cost_gap_r:.2f}R "
               f"({self.cost_gap_r / max(self.taken, 1):.2f}R per trade taken)",
               f"Rule-break gap: {self.break_gap_r:.2f}R",
               f"Rule adherence: {self.adherence:.1%}"]
        out += [f"Signal {r.signal}: {r.kind}, {r.break_r:+.2f}R" for r in self.breaks]
        return out


def _flags(p: dict[str, Any]) -> list[str]:
    out = [b for b in (p.get("rule_breaks") or []) if b in BREAKS]
    if p.get("late") and "late entry" not in out:
        out.append("late entry")
    if p.get("stop_moved") and "stop moved away" not in out:
        out.append("stop moved away")
    return out


def drift_report(paper: list[dict[str, Any]], shadow: list[dict[str, Any]]) -> DriftReport:
    """Split shadow-minus-paper R into costs and rule breaks.

    ``shadow``: dicts with ``signal``, ``r`` and optional ``cost_r``.
    ``paper``: dicts with ``signal`` (None/absent for off-plan trades), ``r``, optional
    ``cost_r`` and flags (``late``, ``stop_moved``, or ``rule_breaks`` list).
    Matched trades without a break count entirely as cost gap (live spread and
    slippage); with a break, the cost difference is costs and the rest is the break.
    """
    by_sig = {str(p["signal"]): p for p in paper if p.get("signal") not in (None, "")}
    rows: list[DriftRow] = []
    for s in shadow:
        sig = str(s["signal"])
        sr = float(s["r"])
        p = by_sig.pop(sig, None)
        if p is None:
            rows.append(DriftRow(sig, "skip", sr, None, 0.0, sr, note="signal not taken"))
            continue
        pr = float(p["r"])
        diff = sr - pr
        flags = _flags(p)
        if not flags:
            rows.append(DriftRow(sig, "cost", sr, pr, diff, 0.0, p.get("id")))
            continue
        cost = float(p.get("cost_r") or 0.0) - float(s.get("cost_r") or 0.0)
        rows.append(DriftRow(sig, flags[0], sr, pr, cost, diff - cost, p.get("id"),
                             ", ".join(flags)))
    for p in paper:
        if p.get("signal") in (None, "") or str(p["signal"]) in by_sig:
            pr = float(p["r"])
            rows.append(DriftRow(str(p.get("signal") or f"off-plan {p.get('id', '')}").strip(),
                                 "off-plan", None, pr, 0.0, -pr, p.get("id"), "no rule produced it"))
    shadow_r = sum(float(s["r"]) for s in shadow)
    paper_r = sum(float(p["r"]) for p in paper)
    taken = len(shadow) - sum(1 for r in rows if r.kind == "skip")
    return DriftReport(round(shadow_r, 4), round(paper_r, 4),
                       round(sum(r.cost_r for r in rows), 4),
                       round(sum(r.break_r for r in rows), 4), len(shadow), taken, rows)


# ---------------------------------------------------------------- shadow backtest
def run_shadow(rule_text: str, bars: Any, costs: str = "IN-equity-delivery") -> Any:
    """Re-run ``rule_text`` on the paper period's bars with the Backtest module."""
    try:
        backtest = importlib.import_module("plugai_trade.backtest")
        rules, run = backtest.rules, backtest.run
    except (ImportError, AttributeError) as exc:
        raise ShadowUnavailable(
            "The shadow backtest needs Strategy › Backtest Report (plugai_trade.backtest), "
            "which is not available in this build.") from exc
    try:  # same rule on the same bars: re-pricing, not a new trial
        return run(rules(rule_text), bars, costs=costs, count_trial=False)
    except TypeError:
        return run(rules(rule_text), bars, costs=costs)


def shadow_trades(result: Any, one_r: float | None = None) -> list[dict[str, Any]]:
    """Turn a backtest result's trade list into drift-report rows (signal = entry date)."""
    trades = getattr(result, "trades", None)
    if trades is None:
        return []
    if hasattr(trades, "to_dicts"):
        rows = trades.to_dicts()
    elif hasattr(trades, "to_dict"):
        rows = trades.to_dict("records")
    else:
        rows = list(trades)
    out = []
    for t in rows:
        if t.get("open"):
            continue
        sig = str(t.get("entry_date") or t.get("entry_time") or t.get("date") or "")[:10]
        if "r" in t and t["r"] is not None:
            r = float(t["r"])
        elif "pnl" in t and one_r:
            r = float(t["pnl"]) / one_r
        else:
            r = float(t.get("ret") or t.get("return") or 0.0) * 100  # % return when no R
        cost = t.get("cost_r")
        if cost is None and "costs" in t and one_r:
            cost = float(t["costs"]) / one_r
        out.append({"signal": sig, "r": r, "cost_r": float(cost or 0.0)})
    return out


def paper_rows_for_drift(journal_rows: list[dict[str, Any]],
                         signal_dates: set[str], late_sessions: int = 3) -> list[dict[str, Any]]:
    """Map Paper Desk journal rows to signals by entry date; later dates are late entries."""
    ordered = sorted(signal_dates)
    out = []
    for j in journal_rows:
        if j.get("kind") != "paper_trade" or j.get("r") is None:
            continue
        d = str(j.get("entry_time", ""))[:10]
        sig, late = None, False
        if d in signal_dates:
            sig = d
        else:
            earlier = [s for s in ordered if s < d]
            if earlier and len([s for s in ordered if earlier[-1] < s <= d]) == 0 \
                    and _sessions_between(earlier[-1], d) <= late_sessions:
                sig, late = earlier[-1], True
        out.append({"id": j.get("id"), "signal": sig, "r": j["r"],
                    "cost_r": j.get("cost_r") or 0.0, "late": late,
                    "rule_breaks": [b for b in j.get("rule_breaks", []) if b != "off-plan"]
                    if sig else j.get("rule_breaks", [])})
    return out


def _sessions_between(a: str, b: str) -> int:
    from datetime import date, timedelta
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    n, d = 0, d0
    while d < d1:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n
