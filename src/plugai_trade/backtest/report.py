"""The Report Card (Chapter 11): it grades the *test*, not the idea.

Checks: Costs, Sample size, Unseen data, Trial count, Neighbours, Concentration.
Survivorship and the training-cutoff guard show as separate warnings.

Grade: *Likely overfit* if the unseen-data or trial-count check fails; else
*Fragile* if any other check fails; else *Robust*. Robust is a statement about
the evidence, never a forecast or a recommendation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from statistics import NormalDist
from typing import TYPE_CHECKING

from .. import config

if TYPE_CHECKING:
    from .result import Result

EULER_GAMMA = 0.5772156649015329
MIN_TRADES = 30
ROBUST, FRAGILE, OVERFIT = "Robust", "Fragile", "Likely overfit"

_N = NormalDist()


# ------------------------------------------------------------------ deflated Sharpe
def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Expected best per-period Sharpe among ``n_trials`` tries on pure noise (Bailey & López de Prado)."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    n = float(n_trials)
    return math.sqrt(var_sr) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n)
                                + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n * math.e)))


def deflated_sharpe(sr: float, n_obs: int, n_trials: int, trial_sharpes: list[float] | None = None,
                    skew: float = 0.0, kurtosis: float = 3.0) -> tuple[float, float]:
    """Deflated Sharpe ratio (Bailey & López de Prado, 2014).

    ``sr`` is the per-period (daily) Sharpe of the tested variant; ``n_obs`` its
    number of returns. Returns ``(probability, sr0)``: the probability that the
    true Sharpe beats ``sr0``, the best Sharpe expected from ``n_trials`` tries
    on noise. The variance across trials is floored at the noise variance 1/T.
    """
    if n_obs < 3:
        return 0.5, 0.0
    var = 1.0 / (n_obs - 1)
    xs = [x for x in (trial_sharpes or []) if not math.isnan(x)]
    if len(xs) >= 2:
        m = sum(xs) / len(xs)
        var = max(var, sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    sr0 = expected_max_sharpe(max(n_trials, 1), var)
    denom = 1 - skew * sr + (kurtosis - 1) / 4 * sr ** 2
    denom = math.sqrt(denom) if denom > 1e-12 else 1e-6
    z = (sr - sr0) * math.sqrt(n_obs - 1) / denom
    return _N.cdf(z), sr0


# ------------------------------------------------------------------ the card
@dataclass
class Check:
    name: str
    status: str          # pass | fail | warn | info
    measured: str
    why: str = ""
    pulls_to: str = ""   # Fragile | Likely overfit | ""


@dataclass
class ReportCard:
    grade: str
    reason: str
    checks: list[Check]
    warnings: list[str] = field(default_factory=list)
    trials: int = 1
    sharpe: float = 0.0
    deflated_sharpe: float = 0.0
    dsr_probability: float = 0.5
    headline: list[tuple[str, str]] = field(default_factory=list)

    def text(self) -> str:
        """The card as plain text (what ``res.report()`` prints)."""
        w = max(len(k) for k, _ in self.headline) if self.headline else 10
        out = ["REPORT CARD · HYPOTHETICAL", "=" * 60]
        out += [f"{k:<{w}}  {v}" for k, v in self.headline]
        out += ["-" * 60, f"Grade: {self.grade}", f"Why:   {self.reason}", "-" * 60]
        mark = {"pass": "✓", "fail": "✗", "warn": "!", "info": "·"}
        for c in self.checks:
            line = f"{mark[c.status]} {c.name:<14} {c.measured}"
            if c.status in ("fail", "warn") and c.why:
                line += f"  → {c.why}"
            out.append(line)
        out.append("-" * 60)
        out += [f"⚠ {x}" for x in self.warnings]
        out.append("Grades the test, not the idea. Not a forecast; not a recommendation.")
        return "\n".join(out)

    def __str__(self) -> str:
        return self.text()

    def __repr__(self) -> str:
        return f"<ReportCard grade={self.grade!r} trials={self.trials}>"

    def to_dict(self) -> dict:
        return {"grade": self.grade, "reason": self.reason, "trials": self.trials,
                "sharpe": self.sharpe, "deflated_sharpe": self.deflated_sharpe,
                "dsr_probability": self.dsr_probability, "warnings": self.warnings,
                "checks": [c.__dict__ for c in self.checks], "headline": self.headline}


def build(res: Result) -> ReportCard:
    """Run every check on a result and grade it."""
    s = res.stats()
    checks = [_costs(res, s), _sample(s), _unseen(res), _trials(res, s), _neighbours(res, s),
              _concentration(res, s)]
    fails = [c for c in checks if c.status in ("fail", "warn") and c.pulls_to]
    overfit = [c for c in fails if c.pulls_to == OVERFIT]
    if overfit:
        grade, reason = OVERFIT, "; ".join(c.why for c in overfit)
    elif fails:
        grade, reason = FRAGILE, "; ".join(c.why for c in fails)
    else:
        grade, reason = ROBUST, ("the test was honest, costs are in, and the result held up on "
                                 "unseen windows, nearby settings and after counting trials")
    prob, sr0 = res.deflated()
    return ReportCard(
        grade=grade, reason=reason, checks=checks, warnings=_warnings(res),
        trials=res.trial_count(), sharpe=s["sharpe"],
        deflated_sharpe=round((s["sharpe_daily"] - sr0) * math.sqrt(252), 2),
        dsr_probability=round(prob, 3), headline=res.headline())


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _costs(res: Result, s: dict) -> Check:
    g = res.gross_stats()["total_return"]
    n = s["total_return"]
    measured = f"before costs {_pct(g)} · after costs {_pct(n)}"
    if g > 0 and (g - n) >= 0.5 * g:
        return Check("Costs", "fail", measured,
                     f"costs erase {min((g - n) / g, 9.99) * 100:.0f}% of the gross result", FRAGILE)
    return Check("Costs", "pass", measured)


def _sample(s: dict) -> Check:
    n = s["round_trips"]
    if n < MIN_TRADES:
        return Check("Sample size", "fail", f"{n} round trips",
                     f"fewer than {MIN_TRADES} trades", FRAGILE)
    return Check("Sample size", "pass", f"{n} round trips")


def _unseen(res: Result) -> Check:
    wf = res.walk_forward()
    if len(wf.windows) < 2:
        return Check("Unseen data", "warn", f"{len(wf.windows)} walk-forward window(s)",
                     "too little history for walk-forward windows", FRAGILE)
    measured = (f"{len(wf.windows)} windows · Sharpe choosing {wf.in_sample_sharpe:.2f} "
                f"→ unseen {wf.oos_sharpe:.2f}")
    if (wf.in_sample_sharpe > 0.3 and wf.oos_sharpe < 0) or wf.oos_sharpe < wf.in_sample_sharpe - 1.0:
        return Check("Unseen data", "fail", measured, "results collapse on unseen windows", OVERFIT)
    return Check("Unseen data", "pass", measured)


def _trials(res: Result, s: dict) -> Check:
    n = res.trial_count()
    prob, sr0 = res.deflated()
    sr0_ann = sr0 * math.sqrt(252)
    measured = (f"{n} trial(s) · Sharpe {s['sharpe']:.2f} vs best-of-{n} on noise "
                f"{sr0_ann:.2f} · deflated probability {prob:.0%}")
    if n >= 2 and s["sharpe_daily"] > 0 and s["sharpe_daily"] <= sr0:
        return Check("Trial count", "fail", measured,
                     f"no better than the best of {n} tries on noise", OVERFIT)
    return Check("Trial count", "pass" if s["sharpe"] > 0 else "info", measured)


def _neighbours(res: Result, s: dict) -> Check:
    nb = res.neighbours()
    if not nb:
        return Check("Neighbours", "info", "no numeric settings to vary")
    base_r, base_sr = s["total_return"], s["sharpe"]
    measured = (f"{len(nb)} nearby settings · Sharpe {min(r['sharpe'] for r in nb):.2f} "
                f"to {max(r['sharpe'] for r in nb):.2f} (this one {base_sr:.2f})")
    for r in nb:
        flipped = (r["total_return"] > 0.02 and base_r < -0.02) or \
                  (r["total_return"] < -0.02 and base_r > 0.02)
        if flipped or abs(r["sharpe"] - base_sr) > 0.5:
            return Check("Neighbours", "fail", measured,
                         f"a small change ({r['label']}) flips the result", FRAGILE)
    return Check("Neighbours", "pass", measured)


def _concentration(res: Result, s: dict) -> Check:
    years = res.yearly()
    total = sum(v for v in years.values())
    if total <= 0 or not years:
        return Check("Concentration", "info", "no overall gain to concentrate")
    best_y, best = max(years.items(), key=lambda kv: kv[1])
    share = best / total
    measured = f"best year {best_y} = {share * 100:.0f}% of the result"
    if share > 0.6 and len(years) > 1:
        return Check("Concentration", "fail", measured, "one year carries the result", FRAGILE)
    return Check("Concentration", "pass", measured)


def _warnings(res: Result) -> list[str]:
    out = []
    src = res.source
    if src == "synthetic":
        out.append("Survivorship: not applicable — synthetic data, no real instruments.")
    elif len(res.symbols) == 1:
        out.append(f"Survivorship: not controlled — {src} has no membership history; a single-"
                   "instrument test chosen today may flatter the rule.")
    else:
        out.append(f"Survivorship: not controlled — the universe is today's list from {src}; "
                   "instruments that shrank or were delisted are missing.")
    origin = res.spec.origin
    if origin in ("model", "agent"):
        cutoff = config.get("ai.training_cutoff")
        start = res.dates[0]
        inside = cutoff is None or start < date.fromisoformat(str(cutoff)[:10])
        if inside:
            out.append("Training-cutoff guard: an AI model chose these rules and the test period "
                       f"falls inside its training years (cutoff {cutoff or 'unknown'}); it may "
                       "have remembered what worked. Judge it on data after the cutoff.")
    return out
