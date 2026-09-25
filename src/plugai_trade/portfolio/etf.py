"""ETF check: Expense, Tracking difference, Tracking error, Trading cost, Cost of the gap.

Chapter 16's synthetic NIFTY 50 pair: index TR 12.40 %, ETF A 12.31 % (TD −0.09 %),
ETF B 12.02 % (TD −0.38 %). On ₹5,00,000 for ten years the gap is ₹40,747.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np

TRADING_DAYS = 252
PREMIUM_THRESHOLD = 0.005  # default flag level; the user can change it on screen


def tracking_difference(fund_returns: np.ndarray, index_returns: np.ndarray) -> float:
    """Fund total return minus index total return over the whole window (fractions)."""
    f = float(np.prod(1 + np.asarray(fund_returns)) - 1)
    i = float(np.prod(1 + np.asarray(index_returns)) - 1)
    return f - i


def tracking_error(fund_returns: np.ndarray, index_returns: np.ndarray) -> float:
    """Annualised standard deviation of daily return differences."""
    d = np.asarray(fund_returns) - np.asarray(index_returns)
    return float(np.std(d, ddof=1) * np.sqrt(TRADING_DAYS))


def annualised_td(fund_returns: np.ndarray, index_returns: np.ndarray, years: int) -> float | None:
    """Annualised tracking difference over the last ``years`` (None if history is shorter)."""
    n = years * TRADING_DAYS
    if len(fund_returns) < n:
        return None
    f = np.prod(1 + fund_returns[-n:]) ** (1 / years) - 1
    i = np.prod(1 + index_returns[-n:]) ** (1 / years) - 1
    return float(f - i)


def premium(price: float, inav: float) -> float:
    """Market price's premium (+) or discount (−) to iNAV."""
    return price / inav - 1


def premium_cost(amount: float, price: float, inav: float) -> float:
    """Money paid above fair value when buying ``amount`` at a premium (book convention)."""
    return amount * premium(price, inav)


def spread_pct(bid: float, ask: float) -> float:
    """Bid–ask spread as a fraction of the mid-price."""
    return (ask - bid) / ((ask + bid) / 2)


def cost_of_gap(amount: float, years: int, return_a: float, return_b: float) -> tuple[float, float, float]:
    """End values for two funds compounding at their own returns, and the gap."""
    a = amount * (1 + return_a) ** years
    b = amount * (1 + return_b) ** years
    return a, b, abs(a - b)


@dataclass
class EtfCheck:
    """The four tiles for one ETF, computed in code."""

    name: str
    expense: float  # fraction a year
    td: dict[int, float | None]  # years → annualised tracking difference
    te: float
    median_spread: float
    premium_today: float

    @property
    def trading_cost(self) -> float:
        """Median spread plus today's premium (the cost of one purchase right now)."""
        return self.median_spread + max(self.premium_today, 0.0)

    def tiles(self) -> dict[str, str]:
        """Tile label → value."""
        td = " · ".join(f"{y}y {v * 100:+.2f}%" for y, v in self.td.items() if v is not None)
        return {"Expense": f"{self.expense * 100:.2f}%", "Tracking difference": td or "n/a",
                "Tracking error": f"{self.te * 100:.2f}%",
                "Trading cost": f"{self.trading_cost * 100:.2f}% (spread {self.median_spread * 100:.2f}% "
                                f"+ premium {self.premium_today * 100:+.2f}%)"}

    def facts(self) -> list[str]:
        """Facts for Explain."""
        return [f"{self.name} {k}: {v}" for k, v in self.tiles().items()]


@dataclass
class SyntheticEtf:
    """A synthetic ETF and its index, for learning the screen offline."""

    name: str
    expense: float
    fund_returns: np.ndarray
    index_returns: np.ndarray
    median_spread: float
    intraday_premium: np.ndarray  # 5-minute points, fractions

    def check(self) -> EtfCheck:
        """Compute the four tiles."""
        td = {y: annualised_td(self.fund_returns, self.index_returns, y) for y in (1, 3, 5)}
        return EtfCheck(self.name, self.expense, td,
                        tracking_error(self.fund_returns[-TRADING_DAYS:], self.index_returns[-TRADING_DAYS:]),
                        self.median_spread, float(self.intraday_premium[-1]))


# The thin sector ETF's premium path through one synthetic NSE session (Chapter 16 figure, %).
THIN_ETF_PREMIUM_PCT = (
    0.4, 0.37, 0.22, 0.27, 0.34, 0.25, 0.13, 0.2, 0.07, 0.23, 0.22, 0.1, 0.29, 0.17, 0.03, 0.02,
    0.43, 0.41, 0.29, 0.42, 0.36, 0.35, 0.46, 0.65, 0.45, 0.4, 0.44, 0.75, 0.66, 0.9, 1.0, 1.04,
    1.3, 1.05, 1.53, 1.51, 1.71, 1.52, 1.53, 1.44, 1.29, 1.46, 1.46, 1.33, 1.38, 1.13, 1.15,
    1.27, 0.83, 0.85, 0.6, 0.59, 0.53, 0.6, 0.57, 0.4, 0.38, 0.44, 0.35, 0.28, 0.2, 0.18, 0.08,
    0.27, -0.01, 0.39, 0.2, 0.33, 0.37, 0.36, 0.22, 0.17, 0.33, 0.17, 0.37, 0.2)


def session_times(n: int = len(THIN_ETF_PREMIUM_PCT)) -> list[str]:
    """IST clock labels for 5-minute points from 09:15."""
    t0 = timedelta(hours=9, minutes=15)
    return [str(t0 + timedelta(minutes=5 * i))[:-3].rjust(5, "0") for i in range(n)]


def _index(seed: int, years: int, annual: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    idx = rng.normal(0, 0.011, years * TRADING_DAYS)
    return idx - idx.mean() + (1 + annual) ** (1 / TRADING_DAYS) - 1


def _fund(idx: np.ndarray, seed: int, td_annual: float, wobble: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, wobble / np.sqrt(TRADING_DAYS), len(idx))
    fund = (1 + idx) * (1 + noise - noise.mean())
    # scale the gap so every calendar year's tracking difference is exactly td_annual
    for y in range(len(idx) // TRADING_DAYS):
        sl = slice(y * TRADING_DAYS, (y + 1) * TRADING_DAYS)
        target = (np.prod(1 + idx[sl]) + td_annual) ** (1 / TRADING_DAYS)
        fund[sl] *= target / np.prod(fund[sl]) ** (1 / TRADING_DAYS)
    return fund - 1


def sample_etfs(market: str) -> list[SyntheticEtf]:
    """Two synthetic ETFs on the same index (IN: NIFTY 50; US: S&P 500)."""
    rng = np.random.default_rng(16)
    liquid = rng.normal(0, 0.03, len(THIN_ETF_PREMIUM_PCT)) / 100
    if market == "IN":
        ia = _index(161, 5, 0.1240)
        fa, fb = _fund(ia, 1611, -0.0009, 0.0006), _fund(ia, 1612, -0.0038, 0.0020)
        return [SyntheticEtf("SYN NIFTY 50 ETF A", 0.0005, fa, ia, 0.0008, liquid),
                SyntheticEtf("SYN NIFTY 50 ETF B (thinly traded)", 0.0030, fb, ia, 0.0074,
                             np.array(THIN_ETF_PREMIUM_PCT) / 100)]
    ia = _index(163, 5, 0.10)
    fa, fb = _fund(ia, 1631, -0.0004, 0.0003), _fund(ia, 1632, -0.0011, 0.0008)
    return [SyntheticEtf("SYN S&P 500 ETF A", 0.0003, fa, ia, 0.0001, liquid / 3),
            SyntheticEtf("SYN S&P 500 ETF B", 0.0009, fb, ia, 0.0002, liquid / 2)]



def stand_in(name: str, base: SyntheticEtf) -> SyntheticEtf:
    """A deterministic synthetic stand-in for an ETF with no free NAV / iNAV source yet."""
    import hashlib

    seed = int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)
    return SyntheticEtf(f"{name} (synthetic stand-in)", base.expense * 2,
                        _fund(base.index_returns, seed, -0.0025, 0.0015), base.index_returns,
                        base.median_spread * 3, base.intraday_premium)
