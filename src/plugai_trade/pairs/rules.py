"""The written pairs rule from Chapter 26, run on frozen formation numbers.

Enter at |z| ≥ entry, exit at |z| ≤ exit, give up after ``time_stop`` sessions,
stop at |z| ≥ stop and then *suspend* the pair (a break means the old fit
describes a pair that no longer exists).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PairRule:
    """Entry / exit / stop z-levels and a time stop in sessions."""

    entry: float = 2.0
    exit: float = 0.5
    stop: float = 3.5
    time_stop: int = 18


@dataclass(frozen=True)
class PairTrade:
    """One round trip on the spread. ``side`` +1 = long A / short B, −1 = short A / long B."""

    number: int
    side: int
    entry_session: int
    entry_z: float
    exit_session: int
    exit_z: float
    exit_type: str  # "exit" | "time stop" | "stop" | "open"
    spread_pnl: float  # change in log spread times side (≈ return on the A leg's notional)

    @property
    def sessions(self) -> int:
        """Sessions held."""
        return self.exit_session - self.entry_session


def run_rule(z: np.ndarray, spread: np.ndarray, formation: int,
             rule: PairRule | None = None) -> tuple[list[PairTrade], int | None]:
    """Walk the trading window (sessions after ``formation``) and return (trades, suspended_at).

    Sessions are 1-based in the output so they match the book's figure.
    """
    rule = rule or PairRule()
    trades: list[PairTrade] = []
    side, start = 0, -1
    for t in range(formation, len(z)):
        zt = float(z[t])
        if side == 0:
            if rule.entry <= abs(zt) < rule.stop:
                side, start = (-1 if zt > 0 else 1), t
            continue
        kind = None
        if abs(zt) >= rule.stop:
            kind = "stop"
        elif abs(zt) <= rule.exit:
            kind = "exit"
        elif t - start >= rule.time_stop:
            kind = "time stop"
        if kind:
            trades.append(PairTrade(len(trades) + 1, side, start + 1, float(z[start]), t + 1, zt,
                                    kind, float(side * (spread[t] - spread[start]))))
            side = 0
            if kind == "stop":
                return trades, t + 1
    if side:
        t = len(z) - 1
        trades.append(PairTrade(len(trades) + 1, side, start + 1, float(z[start]), t + 1,
                                float(z[t]), "open", float(side * (spread[t] - spread[start]))))
    return trades, None
