"""Unseen data and nearby settings: walk-forward, neighbours and the parameter heatmap.

Walk-forward (Chapter 11): choose settings on two years, score them on the next
six months, slide both windows forward, stitch the scored pieces together.
Each variant's return on day *t* depends only on bars before *t*, so choosing
from its training slice and scoring its test slice is an honest replay.

The parameter heatmap (Chapters 16 and 18) runs one cell per setting, scores
each on the tuning years and on the later years the choice never saw, and
counts every cell as a trial.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np
import polars as pl

from . import metrics, trials
from .engine import simulate, strategy_for
from .spec import Spec, SpecError

if TYPE_CHECKING:
    from .result import Result

TRAIN_BARS = 2 * 252
TEST_BARS = 126
WF_FACTORS = (0.8, 1.0, 1.25)
NEIGHBOUR_STEP = 0.10


def _variant_equity(spec: Spec, bars: dict[str, pl.DataFrame], profile: str) -> np.ndarray:
    return simulate(strategy_for(spec, list(bars)), bars, spec, profile).equity


def _scaled(v: int, f: float, path: str) -> int:
    if path == "top_n":
        return max(1, v + (0 if f == 1.0 else (1 if f > 1 else -1)))
    return max(2 if path != "lookback_months" else 1, round(v * f))


def grid_variants(spec: Spec, factors: tuple[float, ...] = WF_FACTORS, limit: int = 27
                  ) -> list[dict[str, int]]:
    """Settings around the spec's own, base first (for walk-forward choice)."""
    params = spec.params()
    if not params:
        return [{}]
    axes = [[_scaled(v, f, p) for f in factors] for p, v in params.items()]
    combos = [dict(zip(params, c)) for c in itertools.product(*axes)]
    base = dict(params)
    uniq = [base] + [c for c in combos if c != base]
    seen, out = set(), []
    for c in uniq:
        key = tuple(sorted(c.items()))
        if key not in seen and _valid(spec, c):
            seen.add(key)
            out.append(c)
    return out[:limit]


def _valid(spec: Spec, values: dict[str, int]) -> bool:
    try:
        s = spec.with_params(values)
        s.validate()
    except (SpecError, ValueError, IndexError, AttributeError):
        return False
    if s.mode == "hold_while" and len(s.entry) == 1:
        c = s.entry[0]
        if c.left.kind == c.right.kind and c.left.n and c.right.n and c.left.n >= c.right.n:
            return False  # a "fast" average that is not faster than the "slow" one
    return True


@dataclass
class WalkForward:
    windows: list[dict[str, Any]] = field(default_factory=list)
    in_sample_sharpe: float = 0.0
    oos_sharpe: float = 0.0
    oos_return: float = 0.0
    oos_dates: list[date] = field(default_factory=list)
    oos_equity: list[float] = field(default_factory=list)
    variants: int = 0

    def facts(self) -> list[str]:
        out = [f"Walk-forward windows: {len(self.windows)} (2 years choose, 6 months score)",
               f"Average Sharpe in the choosing windows: {self.in_sample_sharpe:.2f}",
               f"Sharpe on the stitched unseen windows: {self.oos_sharpe:.2f}",
               f"Result on the unseen windows: {self.oos_return * 100:+.1f}%"]
        return out


def walk_forward(spec: Spec | dict, bars: pl.DataFrame | dict[str, pl.DataFrame],
                 costs: str = "IN-equity-delivery", train_bars: int = TRAIN_BARS,
                 test_bars: int = TEST_BARS, grid: list[dict[str, int]] | None = None
                 ) -> WalkForward:
    """Choose settings on each training window, score them on the next test window."""
    from .engine import as_bar_map
    spec = Spec.from_dict(spec).validate()
    bmap = as_bar_map(bars)
    grid = grid if grid is not None else grid_variants(spec)
    curves = [_variant_equity(spec.with_params(g), bmap, costs) for g in grid]
    rets = [metrics.returns(c) for c in curves]
    dates = next(iter(bmap.values())).sort("date")["date"].to_list()
    wf = WalkForward(variants=len(grid))
    oos: list[float] = []
    is_scores: list[float] = []
    start = 0
    while start + train_bars + test_bars <= len(rets[0]):
        tr = slice(start, start + train_bars)
        te = slice(start + train_bars, start + train_bars + test_bars)
        scores = [metrics.sharpe(r[tr]) for r in rets]
        best = int(np.argmax(scores))
        piece = rets[best][te]
        oos.extend(piece.tolist())
        is_scores.append(scores[best])
        wf.windows.append({
            "choose_from": dates[tr.start], "choose_to": dates[tr.stop],
            "score_from": dates[te.start + 1], "score_to": dates[te.stop],
            "chosen": grid[best] or "as written", "sharpe_choosing": round(scores[best], 2),
            "sharpe_unseen": round(metrics.sharpe(piece), 2),
            "return_unseen": round(float(np.prod(1 + piece) - 1), 4)})
        start += test_bars
    if wf.windows:
        o = np.array(oos)
        wf.in_sample_sharpe = round(float(np.mean(is_scores)), 2)
        wf.oos_sharpe = round(metrics.sharpe(o), 2)
        wf.oos_return = float(np.prod(1 + o) - 1)
        first = train_bars + 1
        wf.oos_dates = dates[first: first + len(o)]
        wf.oos_equity = (100 * np.cumprod(1 + o)).tolist()
    return wf


def neighbours(res: Result) -> list[dict[str, Any]]:
    """The same rule with each setting nudged ±10% (45 or 55 days instead of 50)."""
    spec = res.spec
    out = []
    for path, v in spec.params().items():
        for f in (1 - NEIGHBOUR_STEP, 1 + NEIGHBOUR_STEP):
            nv = _scaled(v, f, path)
            if nv == v:
                nv = v + (1 if f > 1 else -1)
            if nv < 1 or not _valid(spec, {path: nv}):
                continue
            eq = _variant_equity(spec.with_params({path: nv}), res.bar_map, res.profile)
            r = metrics.returns(eq)
            out.append({"label": f"{spec.param_label(path)} {v}→{nv}", "path": path, "value": nv,
                        "total_return": float(eq[-1] / eq[0] - 1),
                        "sharpe": round(metrics.sharpe(r), 2)})
    return out


@dataclass
class Heatmap:
    row_path: str
    col_path: str
    rows: list[int]
    cols: list[int]
    tuning: list[list[float | None]]
    unseen: list[list[float | None]]
    split_date: date
    benchmark_tuning: float
    benchmark_unseen: float
    trials: int
    cells: int
    base: tuple[int, int] | None = None
    row_label: str = "rows"
    col_label: str = "columns"

    def best_tuning(self) -> tuple[int, int, float] | None:
        best = None
        for i, r in enumerate(self.rows):
            for j, c in enumerate(self.cols):
                v = self.tuning[i][j]
                if v is not None and (best is None or v > best[2]):
                    best = (r, c, v)
        return best

    def text(self) -> str:
        """Both grids as text, one row per line (for the "Read my parameter heatmap" prompt)."""
        def grid(g: list[list[float | None]]) -> list[str]:
            head = f"{self.row_label} \\ {self.col_label}: " + " ".join(f"{c:>6}"
                                                                        for c in self.cols)
            return [head] + [f"{r:>9} " + " ".join("     —" if v is None else f"{v:6.2f}"
                                                   for v in row) for r, row in zip(self.rows, g)]
        return "\n".join([f"Tuning years (to {self.split_date}):", *grid(self.tuning),
                          f"Unseen years (after {self.split_date}):", *grid(self.unseen),
                          (f"Buy-and-hold: {self.benchmark_tuning:.2f} tuning, "
                           f"{self.benchmark_unseen:.2f} unseen. Settings tried: {self.cells}.")])

    def facts(self) -> list[str]:
        out = [f"Settings in the sweep: {self.cells}", f"Trials in this family: {self.trials}",
               (f"Buy-and-hold Sharpe: {self.benchmark_tuning:.2f} tuning years, "
                f"{self.benchmark_unseen:.2f} unseen years")]
        b = self.best_tuning()
        if b:
            i, j = self.rows.index(b[0]), self.cols.index(b[1])
            out.append(f"Best tuning cell {b[0]}/{b[1]}: {b[2]:.2f} tuning, "
                       f"{self.unseen[i][j]:.2f} unseen")
        vals = [v for row in self.tuning for v in row if v is not None]
        if vals:
            out.append(f"Tuning Sharpe range across settings: {min(vals):.2f} to {max(vals):.2f}")
        return out


def heatmap(spec: Spec | dict, bars: pl.DataFrame | dict[str, pl.DataFrame],
            rows: tuple[str, list[int]], cols: tuple[str, list[int]] | None = None,
            costs: str = "IN-equity-delivery", split: float = 2 / 3,
            skip: Callable[[int, int], bool] | None = None, count_trials: bool = True,
            symbol: str | None = None) -> Heatmap:
    """Sweep two settings; score every cell on the tuning years and on the unseen years.

    Every cell counts as one trial in the spec's family (re-running a cell does not).
    """
    from .engine import as_bar_map
    spec = Spec.from_dict(spec).validate()
    bmap = as_bar_map(bars, symbol)
    (rp, rv), (cp, cv) = rows, cols or ("", [0])
    first = next(iter(bmap.values())).sort("date")
    n = first.height
    cut = int(n * split)
    split_date = first["date"][cut]
    tuning: list[list[float | None]] = []
    unseen: list[list[float | None]] = []
    cells = 0
    bench = None
    for r in rv:
        trow, urow = [], []
        for c in cv:
            values = {rp: r, cp: c} if cp else {rp: r}
            if (skip and skip(r, c)) or not _valid(spec, values):
                trow.append(None)
                urow.append(None)
                continue
            variant = spec.with_params(values)
            book = simulate(strategy_for(variant, list(bmap)), bmap, variant, costs)
            ret = metrics.returns(book.equity)
            trow.append(round(metrics.sharpe(ret[:cut]), 2))
            urow.append(round(metrics.sharpe(ret[cut:]), 2))
            cells += 1
            if bench is None:
                bench = metrics.returns(book.benchmark)
            if count_trials:
                trials.record(variant.family_key(), variant.digest(), metrics.sharpe(ret),
                              metrics.sharpe_daily(ret), len(ret),
                              {"symbol": ",".join(bmap), "origin": variant.origin})
        tuning.append(trow)
        unseen.append(urow)
    params = spec.params()
    base = ((params[rp], params.get(cp, 0)) if rp in params and (not cp or cp in params)
            else None)
    b = bench if bench is not None else np.zeros(1)
    return Heatmap(rp, cp, list(rv), list(cv), tuning, unseen, split_date,
                   round(metrics.sharpe(b[:cut]), 2), round(metrics.sharpe(b[cut:]), 2),
                   trials.count(spec.family_key()), cells, base,
                   spec.param_label(rp), spec.param_label(cp) if cp else "")
