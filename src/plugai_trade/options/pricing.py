"""Vectorised Black–Scholes (European, no dividends) and Black-76 pricing.

Every function accepts numpy arrays or scalars for ``spot``/``forward`` so the
payoff chart and the stress grid are one call each. Time is in years
(calendar days ÷ 365, the convention the book uses throughout).
"""

from __future__ import annotations

import math

import numpy as np

_ERF = np.frompyfunc(math.erf, 1, 1)
_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)

ArrayLike = float | np.ndarray


def norm_cdf(x: ArrayLike) -> np.ndarray:
    """Standard normal CDF (exact, via math.erf)."""
    x = np.asarray(x, dtype=float)
    return 0.5 * (1.0 + np.asarray(_ERF(x / _SQRT2), dtype=float))


def norm_pdf(x: ArrayLike) -> np.ndarray:
    """Standard normal density."""
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / _SQRT2PI


def intrinsic(spot: ArrayLike, strike: float, kind: str) -> np.ndarray:
    """Value at expiry per unit."""
    s = np.asarray(spot, dtype=float)
    return np.maximum(s - strike, 0.0) if kind == "call" else np.maximum(strike - s, 0.0)


def _d1_d2(s: np.ndarray, k: float, t: float, iv: float, r: float) -> tuple[np.ndarray, np.ndarray]:
    s = np.maximum(s, 1e-12)
    vt = iv * math.sqrt(t)
    d1 = (np.log(s / k) + (r + 0.5 * iv * iv) * t) / vt
    return d1, d1 - vt


def bs_price(spot: ArrayLike, strike: float, t: float, iv: float, r: float, kind: str) -> np.ndarray:
    """Black–Scholes price per unit. ``t`` in years; at ``t <= 0`` returns intrinsic value."""
    s = np.asarray(spot, dtype=float)
    if t <= 0 or iv <= 0:
        return intrinsic(s, strike, kind)
    d1, d2 = _d1_d2(s, strike, t, iv, r)
    disc = strike * math.exp(-r * t)
    if kind == "call":
        return s * norm_cdf(d1) - disc * norm_cdf(d2)
    return disc * norm_cdf(-d2) - s * norm_cdf(-d1)


def bs_greeks(spot: ArrayLike, strike: float, t: float, iv: float, r: float,
              kind: str) -> dict[str, np.ndarray]:
    """Analytic Greeks per unit: delta, gamma, theta per calendar day, vega per 1 IV point."""
    s = np.asarray(spot, dtype=float)
    if t <= 0 or iv <= 0:
        itm = (s > strike) if kind == "call" else (s < strike)
        sign = 1.0 if kind == "call" else -1.0
        z = np.zeros_like(s)
        return {"delta": np.where(itm, sign, 0.0), "gamma": z, "theta": z, "vega": z}
    d1, d2 = _d1_d2(s, strike, t, iv, r)
    pdf = norm_pdf(d1)
    disc = strike * math.exp(-r * t)
    decay = -s * pdf * iv / (2.0 * math.sqrt(t))
    if kind == "call":
        delta = norm_cdf(d1)
        theta = decay - r * disc * norm_cdf(d2)
    else:
        delta = norm_cdf(d1) - 1.0
        theta = decay + r * disc * norm_cdf(-d2)
    return {"delta": delta, "gamma": pdf / (s * iv * math.sqrt(t)),
            "theta": theta / 365.0, "vega": s * pdf * math.sqrt(t) / 100.0}


def black76_price(forward: ArrayLike, strike: float, t: float, iv: float, r: float,
                  kind: str) -> np.ndarray:
    """Black-76 price per unit for an option on a futures contract (e.g. MCX, USDINR)."""
    f = np.asarray(forward, dtype=float)
    if t <= 0 or iv <= 0:
        return intrinsic(f, strike, kind)
    vt = iv * math.sqrt(t)
    d1 = (np.log(np.maximum(f, 1e-12) / strike) + 0.5 * iv * iv * t) / vt
    d2 = d1 - vt
    disc = math.exp(-r * t)
    if kind == "call":
        return disc * (f * norm_cdf(d1) - strike * norm_cdf(d2))
    return disc * (strike * norm_cdf(-d2) - f * norm_cdf(-d1))


def implied_vol(price: float, spot: float, strike: float, t: float, r: float, kind: str,
                lo: float = 0.001, hi: float = 5.0) -> float:
    """Solve Black–Scholes for IV by bisection (the book's "trial and error", done in code)."""
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if float(bs_price(spot, strike, t, mid, r, kind)) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
