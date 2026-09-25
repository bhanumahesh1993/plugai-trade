"""Pairs statistics in plain numpy: hedge ratio, z-score, half-life, Engle–Granger.

Everything is fitted on the *formation window* only and then frozen, exactly as
Chapter 26 prints it::

    beta, alpha = np.polyfit(np.log(b[:F]), np.log(a[:F]), 1)
    spread = np.log(a) - alpha - beta * np.log(b)
    z = (spread - spread[:F].mean()) / spread[:F].std(ddof=1)
    lam = np.polyfit(spread[:F-1], np.diff(spread[:F]), 1)[0]
    half_life = -np.log(2) / np.log(1 + lam)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# MacKinnon (2010), "Critical values for cointegration tests", Table 1:
# N = 2 variables, constant, no trend. crit(T) = tau_inf + b1 / T + b2 / T**2.
_MACKINNON_N2_C = {
    0.01: (-3.89644, -10.9519, -22.527),
    0.05: (-3.33613, -6.1101, -6.823),
    0.10: (-3.04445, -4.2412, -2.720),
}


def mackinnon_critical(nobs: int, level: float = 0.05) -> float:
    """Engle–Granger critical value (two variables, constant) for ``nobs`` observations."""
    tau, b1, b2 = _MACKINNON_N2_C[level]
    return tau + b1 / nobs + b2 / nobs**2


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OLS of ``y`` on the columns of ``x``; returns (coefficients, standard errors)."""
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ coef
    dof = max(1, len(y) - x.shape[1])
    s2 = float(resid @ resid) / dof
    cov = s2 * np.linalg.inv(x.T @ x)
    return coef, np.sqrt(np.diag(cov))


def adf_stat(series: np.ndarray, lags: int = 0) -> float:
    """Augmented Dickey–Fuller t-statistic (with constant) on ``series``.

    With ``lags=0`` this is the Dickey–Fuller regression Δs_t = c + λ s_{t−1} + e,
    the Engle–Granger-style test the book uses on the formation-window residuals.
    """
    s = np.asarray(series, dtype=float)
    ds = np.diff(s)
    rows = len(ds) - lags
    cols = [np.ones(rows), s[lags:-1]]
    for k in range(1, lags + 1):
        cols.append(ds[lags - k:len(ds) - k])
    x = np.column_stack(cols)
    coef, se = _ols(ds[lags:], x)
    return float(coef[1] / se[1])


def half_life(spread: np.ndarray) -> float:
    """Sessions for a gap to halve, from the AR(1) slope of Δspread on spread."""
    s = np.asarray(spread, dtype=float)
    lam = np.polyfit(s[:-1], np.diff(s), 1)[0]
    if lam >= 0 or lam <= -1:
        return float("inf")
    return float(-np.log(2) / np.log(1 + lam))


@dataclass
class PairFit:
    """A pair fitted on its formation window; the numbers are frozen after fitting."""

    a: str
    b: str
    formation: int
    beta: float
    alpha: float
    mean: float
    sd: float
    half_life: float
    adf_t: float
    critical_5: float
    correlation: float
    spread: np.ndarray = field(repr=False)
    z: np.ndarray = field(repr=False)

    @property
    def cointegrated(self) -> bool:
        """True when the Engle–Granger statistic is below the 5% critical value."""
        return self.adf_t < self.critical_5

    def facts(self) -> list[str]:
        """Short numbered facts for ``ai.explain`` (computed in code)."""
        verdict = "passes" if self.cointegrated else "fails"
        return [
            f"Pair: {self.a} / {self.b}",
            f"Formation window: {self.formation} sessions (numbers frozen after it)",
            f"Hedge ratio (beta): {self.beta:.3f}",
            f"Spread standard deviation (log): {self.sd:.4f}",
            f"Half-life: {self.half_life:.1f} sessions",
            f"Engle–Granger t: {self.adf_t:.2f} vs 5% critical {self.critical_5:.2f} "
            f"({verdict})",
            f"Daily-return correlation: {self.correlation:.2f}",
            f"Latest z-score: {self.z[-1]:+.2f}",
        ]


def fit(a: np.ndarray, b: np.ndarray, formation: int = 250, names: tuple[str, str] = ("A", "B"),
        adf_lags: int = 0) -> PairFit:
    """Fit hedge ratio, normal level, width, half-life and cointegration on ``[:formation]``."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n = min(len(a), len(b))
    a, b = a[-n:], b[-n:]
    f = min(formation, n)
    la, lb = np.log(a), np.log(b)
    beta, alpha = np.polyfit(lb[:f], la[:f], 1)
    spread = la - alpha - beta * lb
    mean, sd = spread[:f].mean(), spread[:f].std(ddof=1)
    z = (spread - mean) / sd
    corr = float(np.corrcoef(np.diff(la[:f]), np.diff(lb[:f]))[0, 1])
    return PairFit(a=names[0], b=names[1], formation=f, beta=float(beta), alpha=float(alpha),
                   mean=float(mean), sd=float(sd), half_life=half_life(spread[:f]),
                   adf_t=adf_stat(spread[:f], adf_lags), critical_5=mackinnon_critical(f - 1),
                   correlation=corr, spread=spread, z=z)
