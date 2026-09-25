"""Split in time: train → validation → sealed test, with purge and embargo.

There is deliberately no shuffle option. The purge drops the last training (and
validation) rows whose label window reaches into the next block; it can never
be shorter than the label. The embargo drops a few rows at the start of each
later block, for features that carry information forward.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .features import Dataset


@dataclass
class Split:
    """Index arrays into ``ds.frame`` for the three blocks, in time order."""

    ds: Dataset
    train: np.ndarray
    valid: np.ndarray
    test: np.ndarray
    purge: int
    embargo: int

    def block(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        """(X, y) for ``"train"``, ``"valid"`` or ``"test"``."""
        idx = getattr(self, name)
        return self.ds.X[idx], self.ds.y[idx]

    def span(self, name: str) -> str:
        idx = getattr(self, name)
        d = self.ds.dates
        return f"{d[idx[0]]} to {d[idx[-1]]}" if len(idx) else "empty"

    def facts(self) -> list[str]:
        blocks = (f"Split in time order (no shuffle): train {self.span('train')} "
                  f"({len(self.train):,} rows), validation {self.span('valid')} "
                  f"({len(self.valid):,}), sealed test {self.span('test')} ({len(self.test):,})")
        purge = (f"Purge: {self.purge} rows at each boundary (label length {self.ds.horizon}); "
                 f"embargo: {self.embargo} rows")
        return [blocks, purge]


def time_split(ds: Dataset, train: float = 0.6, valid: float = 0.2, test: float = 0.2,
               purge: int | None = None, embargo: int = 0) -> Split:
    """Cut ``ds`` into train / validation / test blocks in time order.

    ``purge`` defaults to the label length and may not be lower; ``embargo``
    rows are dropped at the start of the validation and test blocks.
    """
    if min(train, valid, test) <= 0 or abs(train + valid + test - 1.0) > 1e-6:
        raise ValueError("train, valid and test must be positive shares that add up to 1")
    purge = ds.horizon if purge is None else int(purge)
    if purge < ds.horizon:
        raise ValueError(f"purge ({purge}) is shorter than the label ({ds.horizon} sessions); "
                         "a shorter purge lets training labels peek into the next block")
    if embargo < 0:
        raise ValueError("embargo cannot be negative")
    n = ds.frame.height
    a, b = round(n * train), round(n * (train + valid))
    tr = np.arange(0, max(a - purge, 0))
    va = np.arange(min(a + embargo, b), max(b - purge, a))
    te = np.arange(min(b + embargo, n), n)
    if min(len(tr), len(va), len(te)) < 30:
        raise ValueError("too few rows in a block after purge and embargo; use more history")
    return Split(ds=ds, train=tr, valid=va, test=te, purge=purge, embargo=embargo)
