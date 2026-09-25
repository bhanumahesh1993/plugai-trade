"""Options: legs, strategies, IV rank, stress tests, attribution and margin estimates.

The book's API (Chapters 22–23)::

    from plugai_trade import options
    opt = options.leg("NIFTY", kind="call", strike=25000, expiry="weekly", side="buy")
    opt.tiles(); opt.greeks(); opt.at(days_left=3).price; opt.scenario(gap=-300, iv=-3)
    options.iv_rank("NIFTY", window=252)
    ic = options.strategy(legs); ic.summary(); ic.stress(gap=-0.05, iv_to=0.24)
    ic.attribution(spot=24560, iv=0.15, days=5)

Every number is computed here (Black–Scholes, vectorised numpy); the AI only narrates.
"""

from __future__ import annotations

from .ivrank import IVRank, iv_rank
from .leg import Greeks, Leg, Scenario, Tiles, leg
from .presets import PRESETS, preset
from .pricing import black76_price, bs_greeks, bs_price, implied_vol
from .strategy import Attribution, Strategy, StressRow, Summary, strategy


def implied_move(call_price: float, put_price: float, spot: float) -> float:
    """Chapter 19: implied move ≈ at-the-money straddle ÷ price (a fraction)."""
    return (call_price + put_price) / spot


__all__ = [
    "PRESETS",
    "Attribution",
    "Greeks",
    "IVRank",
    "Leg",
    "Scenario",
    "Strategy",
    "StressRow",
    "Summary",
    "Tiles",
    "black76_price",
    "bs_greeks",
    "bs_price",
    "implied_move",
    "implied_vol",
    "iv_rank",
    "leg",
    "preset",
    "strategy",
]
