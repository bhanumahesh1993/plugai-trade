"""Income presets (Chapter 23): the legs with Sell and Buy already set.

Strikes sit at fixed distances from spot, rounded to a sensible strike step. At the
lesson spots they reproduce the book's examples: NIFTY 24,100/24,300/25,400/25,600
and SPY 585 covered call, 540 cash-secured put, 540/530 bull put spread.
"""

from __future__ import annotations

import math

from . import chain
from .leg import Leg, leg

PRESETS = ("Covered call", "Cash-secured put", "Bull put spread", "Bear call spread", "Iron condor")

# Distances from spot as fractions: (short put, long put, short call, long call).
_OFFSETS = {"IN": (-0.02, -0.028, 0.024, 0.032), "US": (-0.0357, -0.0536, 0.0357, 0.0536)}
_COVERED_CALL = {"IN": 0.024, "US": 0.0446}


def strike_step(spot: float) -> float:
    """1, 2 or 5 × a power of ten, near 0.2% of spot (NIFTY → 50, SPY → 1)."""
    raw = spot * 0.002
    mag = 10 ** math.floor(math.log10(raw))
    return max(s * mag for s in (1, 2, 5) if s * mag <= raw)


def _k(spot: float, frac: float) -> float:
    step = strike_step(spot)
    return round(spot * (1 + frac) / step) * step


def preset(name: str, symbol: str, market: str | None = None, spot: float | None = None,
           expiry: str = "monthly", qty: int = 1, iv: float | None = None) -> list[Leg]:
    """Legs for one of ``PRESETS`` on ``symbol``."""
    if name not in PRESETS:
        raise ValueError(f"preset must be one of {PRESETS}")
    mkt = chain.market_of(symbol, market)
    s = spot if spot is not None else chain.default_spot(symbol, mkt)
    sp, lp, sc, lc = (_k(s, f) for f in _OFFSETS[mkt])
    common = {"expiry": expiry, "qty": qty, "spot": s, "iv": iv, "market": mkt}
    mk = lambda kind, k, side: leg(symbol, kind=kind, strike=k, side=side, **common)
    if name == "Covered call":
        return [mk("stock", s, "buy"), mk("call", _k(s, _COVERED_CALL[mkt]), "sell")]
    if name == "Cash-secured put":
        return [mk("put", sp, "sell")]
    if name == "Bull put spread":
        return [mk("put", sp, "sell"), mk("put", lp, "buy")]
    if name == "Bear call spread":
        return [mk("call", sc, "sell"), mk("call", lc, "buy")]
    return [mk("put", lp, "buy"), mk("put", sp, "sell"), mk("call", sc, "sell"), mk("call", lc, "buy")]
