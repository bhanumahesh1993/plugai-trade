"""Backtests you can trust a little more (Chapters 11, 16 and 18).

    from plugai_trade import data, backtest, ai
    bars = data.get("NIFTY", market="IN", start="2021-01-01", end="2025-12-31")
    spec = backtest.rules("Buy at the next open on the first close above the 50-day "
                          "average; sell at the next open when the close is below the "
                          "20-day average")
    print(spec.read_back())
    res = backtest.run(spec, bars, costs="IN-equity-delivery")
    res.report()          # the Report Card
    ai.explain(res)       # narration with sources

Strategies see only bars up to the last completed one (:class:`DataView`),
fills happen at the next bar's open, costs come from ``plugai_trade.costs``,
and every distinct variant adds one to the persistent trial counter.
All results are HYPOTHETICAL.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from .. import costs as _costs
from . import metrics, trials
from .engine import RotationStrategy, RuleStrategy, State, Strategy, as_bar_map, leg_cost, simulate
from .engine import strategy_for as _strategy_for
from .parser import parse, rules
from .report import ReportCard, deflated_sharpe, expected_max_sharpe
from .result import Result, fmt_money
from .robustness import Heatmap, WalkForward, heatmap, walk_forward
from .spec import (
    Condition,
    Cost,
    Operand,
    Size,
    Spec,
    SpecError,
    ma_crossover,
    rotation,
    ts_momentum,
)
from .view import DataView, LookAheadError

__all__ = [
    "Condition",
    "Cost",
    "DataView",
    "Heatmap",
    "LookAheadError",
    "Operand",
    "ReportCard",
    "Result",
    "RotationStrategy",
    "RuleStrategy",
    "Size",
    "Spec",
    "SpecError",
    "State",
    "Strategy",
    "WalkForward",
    "chart_check",
    "deflated_sharpe",
    "expected_max_sharpe",
    "fmt_money",
    "heatmap",
    "leg_cost",
    "ma_crossover",
    "parse",
    "rotation",
    "rules",
    "run",
    "run_strategy",
    "trials",
    "ts_momentum",
    "walk_forward",
]


def _as_spec(spec: Any) -> Spec:
    if isinstance(spec, str):
        return rules(spec)
    if hasattr(spec, "to_dict") and not isinstance(spec, Spec):
        spec = spec.to_dict()
    return Spec.from_dict(spec).validate()


def _source(bmap: dict[str, pl.DataFrame]) -> str:
    srcs = sorted({str(df["source"][0]) for df in bmap.values()
                   if "source" in df.columns and df.height})
    return ", ".join(srcs) or "your data"


def run(spec: Spec | dict | str, bars: pl.DataFrame | dict[str, pl.DataFrame],
        costs: str = "IN-equity-delivery", *, symbol: str | None = None,
        count_trial: bool = True) -> Result:
    """Backtest ``spec`` on ``bars`` and return a HYPOTHETICAL :class:`Result`.

    ``spec`` may be a :class:`Spec`, a dict (agents, plugins, saved reports) or
    plain English. ``bars`` is one DataFrame, or ``{symbol: DataFrame}`` for a
    rotation. The spec's own cost profile, if set, wins over ``costs``. Each
    distinct variant adds one trial to its family (``count_trial=False`` only for
    re-pricing the same rule, e.g. the Costs tab).
    """
    sp = _as_spec(spec)
    profile = sp.cost.profile or costs
    if profile not in _costs.PROFILES:
        raise SpecError(f"unknown cost profile {profile!r}; choose one of {', '.join(_costs.PROFILES)}")
    bmap = as_bar_map(bars, symbol)
    if sp.mode == "rotation":
        if len(bmap) < 2:
            raise SpecError("a rotation needs {symbol: bars} for at least two instruments")
        sp.universe = list(bmap)
        sp.validate()
    book = simulate(_strategy_for(sp, list(bmap)), bmap, sp, profile)
    family = sp.family_key()
    r = metrics.returns(book.equity)
    n = trials.count(family)
    if count_trial:
        n = trials.record(family, sp.digest(), metrics.sharpe(r), metrics.sharpe_daily(r), len(r),
                          {"symbol": ",".join(bmap), "origin": sp.origin, "profile": profile})
    return Result(spec=sp, book=book, bar_map=bmap, profile=profile, market=sp.market_of(profile),
                  source=_source(bmap), family=family, trials_at_run=n)


def run_strategy(strategy: Strategy, bars: pl.DataFrame | dict[str, pl.DataFrame],
                 costs: str = "IN-equity-delivery", *, symbol: str | None = None,
                 spec: Spec | None = None) -> Result:
    """Run custom strategy code (Builder track / plugins) behind the same wall.

    ``strategy.decide(views, state)`` receives :class:`DataView` objects that end
    at the last completed bar and returns target weights; fills are at the next
    open. Counts as a trial in the family ``custom:<class name>``.
    """
    sp = spec or Spec(text=f"Custom strategy code: {type(strategy).__name__}", mode="hold_while",
                      entry=[Condition("above", Operand("close"), Operand("value", value=0))],
                      family=f"custom:{type(strategy).__name__}", origin="user")
    bmap = as_bar_map(bars, symbol)
    book = simulate(strategy, bmap, sp, costs)
    r = metrics.returns(book.equity)
    n = trials.record(sp.family_key(), f"{sp.family_key()}:{id(strategy)}", metrics.sharpe(r),
                      metrics.sharpe_daily(r), len(r))
    return Result(spec=sp, book=book, bar_map=bmap, profile=costs, market=sp.market_of(costs),
                  source=_source(bmap), family=sp.family_key(), trials_at_run=n,
                  strategy=strategy)


def chart_check(spec: Spec | dict | str, bars: pl.DataFrame, costs: str = "IN-equity-delivery",
                window: int = 10) -> dict[str, Any]:
    """Entries and exits to draw on the chart, and the churn warning chip (check 2).

    Does not count as a trial: it shows *what the rule does*, not a result.
    """
    res = run(spec, bars, costs=costs, count_trial=False)
    buys = [f["date"] for f in res.fills if f["side"] == "BUY"]
    sells = [f["date"] for f in res.fills if f["side"] == "SELL"]
    dates = res.dates
    pos = {d: i for i, d in enumerate(dates)}
    worst = 0
    exits = sorted(pos[d] for d in sells)
    for i, e in enumerate(exits):
        j = i
        while j < len(exits) and exits[j] - e < window:
            j += 1
        worst = max(worst, j - i)
    chip = f"⚠ {worst} round trips in {window} sessions" if worst >= 3 else ""
    return {"buys": buys, "sells": sells, "chip": chip, "round_trips": res.stats()["round_trips"],
            "result": res}
