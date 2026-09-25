"""Models for the ML Lab: gradient boosting, a single decision tree, and scoring.

``boosting`` uses scikit-learn's ``HistGradientBoostingClassifier`` (library
defaults) when the optional ``ml`` extra is installed, and otherwise a small
NumPy gradient-boosted stumps model so the lab works with no extras. Every
trained model adds one to the ML Lab's trial counter.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..store import default as store
from .split import Split

N_BINS = 32


# ---------------------------------------------------------------- binning
def bin_edges(X: np.ndarray, n_bins: int = N_BINS) -> list[np.ndarray]:
    """Quantile cut points per column, learned on the rows given (training only)."""
    qs = np.linspace(0, 1, n_bins + 1)[1:-1]
    return [np.unique(np.quantile(X[:, j], qs)) for j in range(X.shape[1])]


def apply_bins(X: np.ndarray, edges: list[np.ndarray]) -> np.ndarray:
    return np.column_stack([np.searchsorted(e, X[:, j], side="right") for j, e in enumerate(edges)])


# ---------------------------------------------------------------- one tree
class Tree:
    """A small regression tree on binned data with vector-valued leaves.

    Fitted to one-hot labels it is a classification tree (leaf = class shares);
    fitted to gradients it is one step of gradient boosting.
    """

    def __init__(self, depth: int, min_leaf: int = 20):
        self.depth, self.min_leaf = depth, min_leaf
        self.nodes: list[list[Any]] = []  # [feature, bin, left, right, value]

    def fit(self, B: np.ndarray, Y: np.ndarray) -> Tree:
        self.nodes, self.nb = [], int(B.max()) + 2
        self._grow(B, Y, np.arange(len(B)), self.depth)
        return self

    def _grow(self, B: np.ndarray, Y: np.ndarray, idx: np.ndarray, depth: int) -> int:
        node = len(self.nodes)
        self.nodes.append([-1, -1, -1, -1, Y[idx].mean(0)])
        if depth == 0 or len(idx) < 2 * self.min_leaf:
            return node
        j, t = self._best(B, Y, idx)
        if j is None:
            return node
        go_left = B[idx, j] <= t
        self.nodes[node][:2] = [j, t]
        self.nodes[node][2] = self._grow(B, Y, idx[go_left], depth - 1)
        self.nodes[node][3] = self._grow(B, Y, idx[~go_left], depth - 1)
        return node

    def _best(self, B: np.ndarray, Y: np.ndarray, idx: np.ndarray) -> tuple[int | None, int]:
        Yi, n = Y[idx], len(idx)
        tot = Yi.sum(0)
        base = float((tot ** 2).sum() / n)
        best, bj, bt = 1e-12, None, -1
        for j in range(B.shape[1]):
            b = B[idx, j]
            cnt = np.bincount(b, minlength=self.nb)
            sums = np.stack([np.bincount(b, weights=Yi[:, c], minlength=self.nb)
                             for c in range(Y.shape[1])], 1)
            cl, sl = np.cumsum(cnt)[:-1], np.cumsum(sums, 0)[:-1]
            cr, sr = n - cl, tot - sl
            ok = (cl >= self.min_leaf) & (cr >= self.min_leaf)
            if not ok.any():
                continue
            gain = ((sl ** 2).sum(1) / np.maximum(cl, 1) + (sr ** 2).sum(1) / np.maximum(cr, 1)
                    - base)
            gain[~ok] = -np.inf
            t = int(np.argmax(gain))
            if gain[t] > best:
                best, bj, bt = float(gain[t]), j, t
        return bj, bt

    def apply(self, B: np.ndarray) -> np.ndarray:
        """Leaf node id for every row."""
        out = np.zeros(len(B), dtype=int)
        stack = [(0, np.arange(len(B)))]
        while stack:
            node, idx = stack.pop()
            j, t, left, right, _ = self.nodes[node]
            if left < 0:
                out[idx] = node
                continue
            m = B[idx, j] <= t
            stack += [(left, idx[m]), (right, idx[~m])]
        return out

    def predict(self, B: np.ndarray) -> np.ndarray:
        values = np.stack([n[4] for n in self.nodes])
        return values[self.apply(B)]


def _softmax(F: np.ndarray) -> np.ndarray:
    e = np.exp(F - F.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


class StumpBooster:
    """Gradient-boosted stumps (softmax loss, Newton leaf steps). NumPy only."""

    def __init__(self, n_estimators: int = 200, learning_rate: float = 0.1, depth: int = 1,
                 min_leaf: int = 20):
        self.n_estimators, self.lr, self.depth, self.min_leaf = (
            n_estimators, learning_rate, depth, min_leaf)

    def fit(self, X: np.ndarray, y: np.ndarray) -> StumpBooster:
        self.classes_ = np.unique(y)
        k = len(self.classes_)
        Y = (y[:, None] == self.classes_[None, :]).astype(float)
        self.edges = bin_edges(X)
        B = apply_bins(X, self.edges)
        self.init = np.log(np.clip(Y.mean(0), 1e-6, None))
        F = np.tile(self.init, (len(y), 1))
        self.trees: list[Tree] = []
        for _ in range(self.n_estimators):
            P = _softmax(F)
            G = Y - P
            tree = Tree(self.depth, self.min_leaf).fit(B, G)
            leaves = tree.apply(B)
            H = P * (1 - P)
            for leaf in np.unique(leaves):
                m = leaves == leaf
                tree.nodes[leaf][4] = G[m].sum(0) / np.maximum(H[m].sum(0), 1e-9) * (k - 1) / k
            F += self.lr * tree.predict(B)
            self.trees.append(tree)
        return self

    def decision(self, X: np.ndarray) -> np.ndarray:
        B = apply_bins(X, self.edges)
        F = np.tile(self.init, (len(X), 1))
        for tree in self.trees:
            F += self.lr * tree.predict(B)
        return F

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return _softmax(self.decision(X))

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.classes_[np.argmax(self.decision(X), 1)]


def sklearn_available() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- the model
@dataclass
class Model:
    """A trained classifier plus what it was trained on. Create with :func:`boosting`."""

    engine: str
    estimator: Any
    features: list[str]
    label: str
    family: str
    trial_no: int
    settings: dict[str, Any] = field(default_factory=dict)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.estimator.predict(X)).astype(int)

    def facts(self) -> list[str]:
        return [f"Model: {self.engine}", f"Trials in this ML family: {self.trial_no}"]


def accuracy(pred: np.ndarray, y: np.ndarray) -> float:
    """Share of correct answers, in percent."""
    return float((pred == y).mean() * 100) if len(y) else float("nan")


def ml_family(split: Split) -> str:
    return f"ml:{split.ds.symbol}:{split.ds.label}"


def ml_trials(family: str) -> int:
    return store().count("trials", tag=family)


def _record_trial(family: str, detail: dict[str, Any]) -> int:
    store().add("trials", {"family": family, "digest": uuid.uuid4().hex[:16], "sharpe": None,
                           "sharpe_daily": None, "n_obs": 0, "origin": "ml", **detail}, tag=family)
    return ml_trials(family)


def boosting(split: Split, engine: str = "auto", **settings: Any) -> Model:
    """Gradient boosting on the training block, library defaults. Counts one trial.

    ``engine``: ``"auto"`` (scikit-learn if installed, else NumPy stumps),
    ``"sklearn"`` or ``"numpy"``. Extra keyword ``settings`` go to the estimator.
    """
    X, y = split.block("train")
    use_sk = engine == "sklearn" or (engine == "auto" and sklearn_available())
    if use_sk:
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier
        except ImportError as exc:
            raise RuntimeError('scikit-learn is not installed. Run: pip install "plugai-trade[ml]"'
                               ) from exc
        est: Any = HistGradientBoostingClassifier(random_state=0, **settings).fit(X, y)
        name = "Gradient boosting (scikit-learn HistGradientBoosting, defaults)"
    else:
        est = StumpBooster(**settings).fit(X, y)
        name = "Gradient boosting (NumPy stumps, 200 rounds; install the ml extra for scikit-learn)"
    fam = ml_family(split)
    n = _record_trial(fam, {"label": split.ds.label, "features": split.ds.features,
                            "engine": name, "settings": settings})
    return Model(engine=name, estimator=est, features=list(split.ds.features),
                 label=split.ds.label, family=fam, trial_no=n, settings=settings)


def overfit_curve(split: Split, depths: range = range(1, 15)) -> list[dict[str, float]]:
    """One decision tree, allowed to go deeper: train vs validation accuracy per depth."""
    Xtr, ytr = split.block("train")
    Xva, yva = split.block("valid")
    classes = np.unique(ytr)
    Y = (ytr[:, None] == classes[None, :]).astype(float)
    edges = bin_edges(Xtr)
    Btr, Bva = apply_bins(Xtr, edges), apply_bins(Xva, edges)
    rows = []
    for d in depths:
        tree = Tree(d, min_leaf=2).fit(Btr, Y)
        rows.append({"depth": d,
                     "train": accuracy(classes[tree.predict(Btr).argmax(1)], ytr),
                     "validation": accuracy(classes[tree.predict(Bva).argmax(1)], yva)})
    return rows


def permutation_importance(model: Model, X: np.ndarray, y: np.ndarray, repeats: int = 5,
                           seed: int = 0) -> dict[str, float]:
    """Accuracy drop (percentage points) when each column is shuffled, on the given block."""
    rng = np.random.default_rng(seed)
    base = accuracy(model.predict(X), y)
    out: dict[str, float] = {}
    for j, name in enumerate(model.features):
        drops = []
        for _ in range(repeats):
            Xp = X.copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            drops.append(base - accuracy(model.predict(Xp), y))
        out[name] = float(np.mean(drops))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def fit_quiet(X: np.ndarray, y: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    """Train the same kind of model without counting a trial (shuffle test only)."""
    if sklearn_available():
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(random_state=0).fit(X, y).predict
    return StumpBooster().fit(X, y).predict
