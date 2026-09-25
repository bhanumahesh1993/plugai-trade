"""The ML Lab (Chapter 29): features, labels and honest tests.

    from plugai_trade import data, ml, ai
    bars = data.get("NIFTY", market="IN", start="2010-01-01", end="2026-05-29")
    ds = ml.dataset(bars, label="high_vol_next_10", noise_column=True,
                    features=["range_5", "vol_20", "vol_5", "ret_5", "ret_20",
                              "dist_ma50", "volume_z", "weekday"])
    split = ml.time_split(ds, train=0.6, valid=0.2, test=0.2)  # purge = 10
    model = ml.boosting(split)            # gradient boosting, defaults
    card = ml.report(model, split, baselines=["majority", "vol_20 > 1"])
    card.show()        # scores vs baselines, importance, overfit curve
    ai.explain(card)   # narration with sources; no new numbers

The split is always in time order (there is no shuffle option), the purge can
never be shorter than the label, and every trained model adds one trial. The
ML Lab never produces a trade signal: a model's output can go to the Position
Sizer as a volatility estimate, or to the journal as a note.
"""

from __future__ import annotations

from .card import ModelCard, ShuffleResult, majority_baseline, report, rule_baseline, shuffle_test
from .features import FEATURES, KNOWN_AT, LABEL_QUESTION, LABELS, NOISE, Dataset, dataset
from .models import (
    Model,
    StumpBooster,
    Tree,
    accuracy,
    boosting,
    ml_trials,
    overfit_curve,
    permutation_importance,
    sklearn_available,
)
from .scenarios import Scenarios, history_facts, scored_history, vol_scenarios
from .split import Split, time_split

__all__ = [
    "FEATURES", "KNOWN_AT", "LABELS", "LABEL_QUESTION", "NOISE",
    "Dataset", "Model", "ModelCard", "Scenarios", "ShuffleResult", "Split", "StumpBooster", "Tree",
    "accuracy", "boosting", "dataset", "history_facts", "majority_baseline", "ml_trials",
    "overfit_curve", "permutation_importance", "report", "rule_baseline", "scored_history",
    "shuffle_test", "sklearn_available", "time_split", "vol_scenarios",
]
