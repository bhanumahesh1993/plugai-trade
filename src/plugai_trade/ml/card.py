"""The model card: scores vs baselines on the sealed test, importance, overfit, grade.

It is the ML equivalent of the Backtest Report Card and uses the same grades:
*Robust*, *Fragile*, *Likely overfit*. All numbers are computed here; ``facts()``
hands them to ``ai.explain`` so the model can only narrate them.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .features import LABEL_QUESTION, NOISE
from .models import Model, accuracy, fit_quiet, ml_trials, overfit_curve, permutation_importance
from .split import Split

_RULE = re.compile(r"^\s*([a-z_0-9]+)\s*(>=|<=|>|<)\s*(-?[0-9.]+)\s*$")


def rule_baseline(rule: str, split: Split, block: str = "test") -> np.ndarray:
    """Predictions of a one-line rule such as ``"vol_20 > 1"`` (true → 1, false → 0)."""
    m = _RULE.match(rule)
    if not m:
        raise ValueError(f"a one-line rule looks like 'vol_20 > 1', not {rule!r}")
    col, op, val = m.group(1), m.group(2), float(m.group(3))
    if col not in split.ds.frame.columns:
        raise ValueError(f"unknown feature {col!r} in rule {rule!r}")
    x = split.ds.frame[col].to_numpy()[getattr(split, block)]
    hit = {">": x > val, "<": x < val, ">=": x >= val, "<=": x <= val}[op]
    return hit.astype(int)


def majority_baseline(split: Split, block: str = "test") -> tuple[int, np.ndarray]:
    """Always guess the class that was most common in the training block."""
    _, ytr = split.block("train")
    vals, counts = np.unique(ytr, return_counts=True)
    guess = int(vals[np.argmax(counts)])
    return guess, np.full(len(getattr(split, block)), guess)


@dataclass
class ModelCard:
    """Scores, baselines, importance, overfit curve and grade for one trained model."""

    model: Model
    split: Split
    scores: dict[str, float]
    baselines: dict[str, float]
    importance: dict[str, float]
    overfit: list[dict[str, float]]
    trials: int
    grade: str
    why: str
    notes: list[str] = field(default_factory=list)

    def facts(self) -> list[str]:
        s, ds = self.scores, self.split.ds
        out = ["All results are HYPOTHETICAL (a model tested on past or synthetic data).",
               f"Label: {LABEL_QUESTION[ds.label]}",
               *self.split.facts(),
               f"Model: {self.model.engine}",
               f"Accuracy on training years: {s['train']:.1f}% (flattering)",
               f"Accuracy on validation years: {s['valid']:.1f}%",
               f"Accuracy on sealed test years: {s['test']:.1f}%"]
        out += [f"Baseline '{k}' on test years: {v:.1f}%" for k, v in self.baselines.items()]
        top = ", ".join(f"{k} {v:+.1f}" for k, v in list(self.importance.items())[:4])
        out.append(f"Permutation importance on test years (points of accuracy lost): {top}")
        if NOISE in self.importance:
            out.append(f"Noise (control) importance: {self.importance[NOISE]:+.1f} points")
        out.append(f"Trials in this ML family: {self.trials}")
        out.append(f"Grade: {self.grade} — {self.why}")
        return out

    def text(self) -> str:
        s = self.scores
        lines = ["MODEL CARD · HYPOTHETICAL", "=" * 60,
                 f"{'Label':28}{LABEL_QUESTION[self.split.ds.label]}",
                 f"{'Model':28}{self.model.engine}",
                 f"{'Train':28}{self.split.span('train')} ({len(self.split.train):,} rows)",
                 f"{'Validation':28}{self.split.span('valid')} ({len(self.split.valid):,} rows)",
                 f"{'Sealed test':28}{self.split.span('test')} ({len(self.split.test):,} rows)",
                 f"{'Purge / embargo':28}{self.split.purge} / {self.split.embargo} rows",
                 "-" * 60, "Results vs baselines (accuracy, %)",
                 f"  {'Training years':26}{s['train']:6.1f}  (flattering)",
                 f"  {'Validation years':26}{s['valid']:6.1f}",
                 f"  {'Sealed test years':26}{s['test']:6.1f}"]
        lines += [f"  {k + ', test':26}{v:6.1f}" for k, v in self.baselines.items()]
        lines += ["-" * 60, "Feature importance (test years, points lost when shuffled)"]
        lines += [f"  {k:26}{v:+6.1f}" for k, v in self.importance.items()]
        lines += ["-" * 60, "Overfit curve (one decision tree): depth  train  validation"]
        lines += [f"  {int(r['depth']):>10}  {r['train']:5.1f}  {r['validation']:5.1f}"
                  for r in self.overfit]
        lines += ["-" * 60, f"Trials in this ML family  {self.trials}",
                  f"Grade: {self.grade}", f"Why:   {self.why}", *self.notes,
                  "Grades the test, not the idea. Not a forecast; not a recommendation."]
        return "\n".join(lines)

    def show(self) -> ModelCard:
        """Print the card (scores vs baselines, importance, overfit curve)."""
        print(self.text())
        return self

    def to_dict(self) -> dict[str, Any]:
        """What the journal keeps when you click Accept."""
        return {"label": self.split.ds.label, "features": self.split.ds.features,
                "split": self.split.facts(), "scores": self.scores, "baselines": self.baselines,
                "importance": self.importance, "trials": self.trials, "grade": self.grade,
                "why": self.why, "engine": self.model.engine}


def _grade(scores: dict[str, float], baselines: dict[str, float], n_test: int,
           trials: int) -> tuple[str, str]:
    test, valid = scores["test"], scores["valid"]
    maj = baselines.get("majority", 0.0)
    rules = [v for k, v in baselines.items() if k != "majority"]
    se = 100 * math.sqrt(0.25 / max(n_test, 1))
    bar = 2 * se * math.sqrt(1 + math.log(max(trials, 1)))
    if test <= maj + se:
        return "Likely overfit", (f"test {test:.1f}% does not clearly beat the majority guess "
                                  f"{maj:.1f}%")
    if valid - test > 10:
        return "Likely overfit", f"validation {valid:.1f}% vs test {test:.1f}%: the gap explains it"
    best = max([maj, *rules])
    if test - best > bar and abs(valid - test) <= 5:
        return "Robust", (f"test {test:.1f}% beats every baseline by more than {bar:.1f} points "
                          f"after {trials} trial(s)")
    if rules and test - max(rules) <= bar:
        return "Fragile", (f"beats the majority guess but not clearly the one-line rule "
                           f"({max(rules):.1f}%)")
    return "Fragile", f"margin over the baselines is small for {trials} trial(s)"


def report(model: Model, split: Split, baselines: list[str] | tuple[str, ...] = ("majority",)
           ) -> ModelCard:
    """Score ``model`` on all three blocks and against ``baselines`` on the sealed test.

    ``baselines`` holds ``"majority"`` and/or one-line rules such as ``"vol_20 > 1"``.
    """
    scores = {b: accuracy(model.predict(split.block(b)[0]), split.block(b)[1])
              for b in ("train", "valid", "test")}
    _, yte = split.block("test")
    base: dict[str, float] = {}
    notes = []
    for b in baselines:
        if b == "majority":
            guess, pred = majority_baseline(split)
            base["majority"] = accuracy(pred, yte)
            notes.append(f"Majority guess = always {guess}")
        else:
            base[b] = accuracy(rule_baseline(b, split), yte)
    trials = ml_trials(model.family)
    imp = permutation_importance(model, *split.block("test"))
    grade, why = _grade(scores, base, len(yte), trials)
    return ModelCard(model=model, split=split, scores=scores, baselines=base, importance=imp,
                     overfit=overfit_curve(split), trials=trials, grade=grade, why=why,
                     notes=notes)


@dataclass
class ShuffleResult:
    """The leaky, shuffled k-fold score, shown beside the honest one. For learning only."""

    score: float
    folds: int
    honest: float | None = None
    label: str = "for learning only"

    def facts(self) -> list[str]:
        out = [f"Shuffled {self.folds}-fold accuracy (leaky, {self.label}): {self.score:.1f}%"]
        if self.honest is not None:
            out.append(f"Time-ordered sealed-test accuracy: {self.honest:.1f}%")
        return out

    def text(self) -> str:
        warning = ("Shuffling puts the future into training and overlapping labels across the "
                   "split; this number is not a result.")
        return "\n".join(["SHUFFLE TEST · FOR LEARNING ONLY", *self.facts(), warning])


def shuffle_test(split_or_ds: Any, folds: int = 5, seed: int = 0,
                 honest: float | None = None) -> ShuffleResult:
    """The textbook shuffled k-fold score on the same data — labelled *for learning only*.

    Not counted as a trial: it is a demonstration of a leak, not a model you keep.
    """
    ds = getattr(split_or_ds, "ds", split_or_ds)
    X, y = ds.X, ds.y
    order = np.random.default_rng(seed).permutation(len(y))
    scores = []
    for k in range(folds):
        te = order[k::folds]
        tr = np.setdiff1d(order, te)
        scores.append(accuracy(fit_quiet(X[tr], y[tr])(X[te]), y[te]))
    return ShuffleResult(score=float(np.mean(scores)), folds=folds, honest=honest)
