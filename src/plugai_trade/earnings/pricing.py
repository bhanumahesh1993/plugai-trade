"""Black–Scholes pricing for the implied-move tiles (no dividends; European).

Used only to value a straddle on the synthetic chain and in the Scenarios
panel. The Options Strategy Builder has the full option tools.
"""

from __future__ import annotations

import math


def _n(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(
    kind: str, spot: float, strike: float, years: float, vol: float, rate: float = 0.0
) -> float:
    """Price of a call or put."""
    if years <= 0 or vol <= 0:
        intrinsic = spot - strike if kind == "call" else strike - spot
        return max(0.0, intrinsic)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    if kind == "call":
        return spot * _n(d1) - strike * math.exp(-rate * years) * _n(d2)
    return strike * math.exp(-rate * years) * _n(-d2) - spot * _n(-d1)


def straddle(spot: float, strike: float, years: float, vol: float) -> tuple[float, float, float]:
    """(call, put, straddle) at one strike."""
    c = bs_price("call", spot, strike, years, vol)
    p = bs_price("put", spot, strike, years, vol)
    return c, p, c + p
