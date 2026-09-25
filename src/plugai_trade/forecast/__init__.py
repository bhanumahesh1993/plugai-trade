"""Portfolio › Forecast Journal: your probabilities, the fee, the Brier score.

    from plugai_trade import forecast
    forecast.break_even(0.62, 0.01)          # 0.63 → a YES at 62¢ + 1¢ fee needs > 63 %
    forecast.brier([0.7, 0.7], [1, 0])       # (0.09 + 0.49) / 2 = 0.29

US only: in India prediction markets are treated as prohibited online money
games, so the screen is disabled for IN (the calibration maths still runs).
The journal records forecasts, never positions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import polars as pl

from ..store import default as store

MIN_FOR_CALIBRATION = 30
BASELINE = 0.25  # "50% about everything"
SAMPLE_SEED = 5


def break_even(price: float, fee: float = 0.0) -> float:
    """Fee-adjusted break-even probability for a $1 YES contract (price and fee in dollars)."""
    return price + fee


def brier(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean of (probability − outcome)²; lower is better, 0.25 is the coin-flip bar."""
    p = np.asarray(probs, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    if len(p) == 0:
        raise ValueError("no resolved forecasts")
    return float(np.mean((p - o) ** 2))


@dataclass(frozen=True)
class CalibrationBin:
    """One dot on the calibration chart."""

    lo: float
    hi: float
    mean_prob: float
    hit_rate: float
    n: int


def calibration(probs: Sequence[float], outcomes: Sequence[int], bins: int = 5) -> list[CalibrationBin]:
    """Group forecasts by stated probability; return how often each group happened."""
    p = np.asarray(probs, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & ((p < hi) if i < bins - 1 else (p <= hi))
        if m.any():
            out.append(CalibrationBin(float(lo), float(hi), float(p[m].mean()),
                                      float(o[m].mean()), int(m.sum())))
    return out


@dataclass
class Scorecard:
    """Brier score and calibration for a set of resolved forecasts."""

    probs: list[float]
    outcomes: list[int]

    @property
    def n(self) -> int:
        """Resolved forecasts."""
        return len(self.probs)

    @property
    def brier(self) -> float:
        """The Brier score."""
        return brier(self.probs, self.outcomes)

    @property
    def ready(self) -> bool:
        """The calibration chart is drawn after 30 resolved forecasts."""
        return self.n >= MIN_FOR_CALIBRATION

    def bins(self, k: int = 5) -> list[CalibrationBin]:
        """Calibration groups."""
        return calibration(self.probs, self.outcomes, k)

    def facts(self) -> list[str]:
        """Facts for Explain / Show sources."""
        f = [f"Resolved forecasts: {self.n}",
             f"Brier score: {self.brier:.3f} (coin-flip baseline {BASELINE:.2f}; lower is better)"]
        for b in self.bins():
            f.append(f"Said {b.lo:.0%}–{b.hi:.0%} (average {b.mean_prob:.0%}): happened "
                     f"{b.hit_rate:.0%} of {b.n}")
        return f


def sample_journal(n: int = 160, seed: int = SAMPLE_SEED) -> Scorecard:
    """A deliberately overconfident synthetic journal (Chapter 26: Brier ≈ 0.215)."""
    rng = np.random.default_rng(seed)
    true = rng.uniform(0.15, 0.85, n)
    stated = np.clip(0.5 + (true - 0.5) * 1.6 + rng.normal(0, 0.05, n), 0.02, 0.98)
    outcomes = (rng.uniform(0, 1, n) < true).astype(int)
    return Scorecard([round(float(x), 2) for x in stated], [int(x) for x in outcomes])


# ------------------------------------------------------------------ journal records
def add(question: str, rules: str, prob: float, reason: str, price: float | None = None,
        fee: float = 0.0, platform: str = "") -> int:
    """Commit a forecast. The probability is stored before the price is revealed."""
    if not 0 <= prob <= 1:
        raise ValueError("probability must be between 0 and 1")
    return store().add("forecasts", {"question": question, "rules": rules, "prob": prob,
                                     "reason": reason, "price": price, "fee": fee,
                                     "platform": platform, "outcome": None}, tag="US")


def set_price(forecast_id: int, price: float, fee: float) -> None:
    """Record the market price and fee after the forecast is committed."""
    row = store().get("forecasts", forecast_id) or {}
    body = {k: v for k, v in row.items() if k not in ("id", "created", "tag")}
    body.update(price=price, fee=fee)
    store().update("forecasts", forecast_id, body)


def resolve(forecast_id: int, outcome: int) -> None:
    """Record 1 (happened) or 0 (did not)."""
    if outcome not in (0, 1):
        raise ValueError("outcome is 1 or 0")
    row = store().get("forecasts", forecast_id) or {}
    body = {k: v for k, v in row.items() if k not in ("id", "created", "tag")}
    body["outcome"] = outcome
    store().update("forecasts", forecast_id, body)


def scorecard() -> Scorecard:
    """Scorecard over every resolved forecast in the journal."""
    rows = [r for r in store().all("forecasts") if r.get("outcome") in (0, 1)]
    return Scorecard([float(r["prob"]) for r in rows], [int(r["outcome"]) for r in rows])


def journal_frame() -> pl.DataFrame:
    """All forecasts, newest first."""
    rows = store().all("forecasts")
    return pl.DataFrame([{"id": r["id"], "question": r.get("question", ""),
                          "your %": round(float(r.get("prob", 0)) * 100),
                          "price": r.get("price"), "fee": r.get("fee"),
                          "outcome": r.get("outcome")} for r in rows]) if rows else pl.DataFrame()


# ------------------------------------------------------------------ resolution rules
_TIME = re.compile(r"\b\d{1,2}(:\d{2})?\s*(a\.?m\.?|p\.?m\.?)?\s*(ET|EST|EDT|UTC|GMT|CT|PT)\b", re.I)
_SOURCE = re.compile(r"\b(source|according to|as reported by|published by|settle[sd]?|"
                     r"resolv(e|es|ed|ution))\b", re.I)
_EDGE = re.compile(r"\b(if|unless|in the event|revis(ed|ion)|delay(ed)?|postpone|cancel|"
                   r"tie|round(ed|ing)?|ambigu)\w*", re.I)


def resolution_rules(text: str) -> dict[str, list[str]]:
    """Source / time / edge-case sentences, each quoted from the rules as written.

    A deterministic reader: it quotes, it does not interpret. The AI can add a
    plain-English reading on top (Explain), always linked back to these sentences.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\n+", text) if s.strip()]
    return {"Source": [s for s in sentences if _SOURCE.search(s)],
            "Time": [s for s in sentences if _TIME.search(s) or re.search(r"\bby\b.*\d", s)],
            "Edge cases": [s for s in sentences if _EDGE.search(s)]}
