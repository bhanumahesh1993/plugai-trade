"""Replay one session from the journal (Chapter 21): fills, holding time, costs, gaps.

The numbers are measured here; Generate review only narrates ``SessionReplay.facts()``.
The Paper Desk reads ``handoff()`` to open the session in Replay mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from .detectors import RuleCard, enrich, real_trades


@dataclass
class SessionReplay:
    day: str
    market: str
    trades: pl.DataFrame
    blocked: int

    def facts(self) -> list[str]:
        t = self.trades
        cur = "₹" if self.market == "IN" else "$"
        if t.is_empty():
            return [f"Session {self.day}: no trades", f"Blocked tickets: {self.blocked}"]
        span_h = max((t["exit_time"].max() - t["entry_time"].min()).total_seconds() / 3600, 1 / 60)
        out = [f"Session {self.day}: {t.height} trades, {int(t['win'].sum())} won, "
               f"{float(t['r'].sum()):+.2f}R before charges",
               f"Charges {cur}{float(t['charges'].sum()):,.2f} on gross "
               f"{cur}{float(t['gross'].sum()):,.2f}",
               f"Trades per hour: {t.height / span_h:.2f}",
               f"Median holding time: {float(t['hold_minutes'].median()):.1f} min",
               f"Blocked tickets (tag BLOCKED): {self.blocked}"]
        for r in t.iter_rows(named=True):
            gap = "" if r["gap_minutes"] is None else f", {r['gap_minutes']:.0f} min after the " \
                  f"previous exit ({'loss' if r['prev_win'] is False else 'win'})"
            broke = f", broke: {r['rules_broken']}" if r["rules_broken"] else ""
            out.append(f"Row {r['trade_id']} {r['entry_time']:%H:%M}→{r['exit_time']:%H:%M} "
                       f"{r['side']} {r['symbol']} {r['r']:+.2f}R, held {r['hold_minutes']:.0f} "
                       f"min{gap}{broke}")
        return out

    def handoff(self, speed: int = 5) -> dict[str, Any]:
        """What the Paper Desk needs to open this session in Replay mode (REPLAY tag)."""
        return {"day": self.day, "market": self.market, "speed": speed, "tag": "REPLAY",
                "fills": [{"time": r["entry_time"].isoformat(), "side": r["side"],
                           "symbol": r["symbol"], "price": r["entry_price"], "kind": "entry"}
                          for r in self.trades.iter_rows(named=True)]
                + [{"time": r["exit_time"].isoformat(), "side": r["side"],
                    "symbol": r["symbol"], "price": r["exit_price"], "kind": "exit"}
                   for r in self.trades.iter_rows(named=True)]}


def session(trades: pl.DataFrame, day: str, card: RuleCard | None = None) -> SessionReplay:
    """One day's round trips with the detector columns (gap after a loss, rule breaks)."""
    day_rows = trades.filter(pl.col("date") == day) if trades.height else trades
    blocked = day_rows.height - real_trades(day_rows).height if day_rows.height else 0
    e = enrich(trades, card)
    e = e.filter(pl.col("date") == day) if e.height else e
    market = (trades["market"][0] if trades.height else None) or "IN"
    return SessionReplay(day, market, e, blocked)
