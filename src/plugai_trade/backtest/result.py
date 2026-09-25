"""A backtest result: equity, drawdown, trades, costs, and the Report Card.

Everything is HYPOTHETICAL. ``facts()`` returns short cited strings so
``ai.explain(res)`` can narrate without inventing a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from typing import Any

import numpy as np
import polars as pl

from .. import reference
from ..store import default as store
from . import metrics, robustness, trials
from . import report as _report
from .engine import Book, next_session_orders, simulate, strategy_for
from .spec import Spec


def fmt_money(x: float, market: str = "IN") -> str:
    """₹5,00,000 (Indian grouping) or $10,000, rounded to the unit."""
    neg, digits = x < 0, str(round(abs(float(x))))
    if market == "IN":
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while head:
            groups.insert(0, head[-2:])
            head = head[:-2]
        body = "₹" + ",".join([*groups, tail])
    else:
        body = f"${int(digits):,}"
    return f"−{body}" if neg else body


@dataclass
class Result:
    """One HYPOTHETICAL backtest. Create with ``backtest.run``."""

    spec: Spec
    book: Book
    bar_map: dict[str, pl.DataFrame]
    profile: str
    market: str
    source: str
    family: str
    trials_at_run: int
    strategy: Any = None  # custom strategy code (run_strategy); None for rule specs
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------ basics
    @property
    def symbols(self) -> list[str]:
        return list(self.bar_map)

    @property
    def symbol(self) -> str:
        return self.symbols[0] if len(self.symbols) == 1 else f"{len(self.symbols)} instruments"

    @property
    def dates(self) -> list[date]:
        return self.book.dates

    @property
    def equity(self) -> np.ndarray:
        return self.book.equity

    @property
    def benchmark(self) -> np.ndarray:
        return self.book.benchmark

    @property
    def trades(self) -> list[dict[str, Any]]:
        """Completed round trips (plus any position still open at the end, flagged ``open``)."""
        return self.book.trades

    @property
    def fills(self) -> list[dict[str, Any]]:
        return self.book.fills

    @property
    def capital(self) -> float:
        return self.book.capital

    def money(self, x: float) -> str:
        return fmt_money(x, self.market)

    def trial_count(self) -> int:
        """Distinct variants tried in this family so far (live, so later sweeps count)."""
        return max(trials.count(self.family), 1)

    # ------------------------------------------------------------ numbers
    def stats(self) -> dict[str, Any]:
        if "stats" not in self._cache:
            self._cache["stats"] = _stats(self.book, self.dates)
        return self._cache["stats"]

    @cached_property
    def gross_book(self) -> Book:
        """Same rule with no charges and no slippage (the "before costs" line)."""
        strat = self.strategy or strategy_for(self.spec, self.symbols)
        return simulate(strat, self.bar_map, self.spec, self.profile, frictionless=True)

    def gross_stats(self) -> dict[str, Any]:
        return _stats(self.gross_book, self.dates)

    def deflated(self) -> tuple[float, float]:
        """(probability, best-of-N-on-noise daily Sharpe) for this family's trial count."""
        s = self.stats()
        r = metrics.returns(self.equity)
        skew, kurt = metrics.moments(r)
        return _report.deflated_sharpe(s["sharpe_daily"], len(r), self.trial_count(),
                                      trials.sharpes(self.family), skew, kurt)

    def walk_forward(self) -> robustness.WalkForward:
        if "wf" not in self._cache:
            if self.strategy is not None:
                return robustness.WalkForward()
            self._cache["wf"] = robustness.walk_forward(self.spec, self.bar_map, self.profile)
        return self._cache["wf"]

    def neighbours(self) -> list[dict[str, Any]]:
        if "nb" not in self._cache:
            if self.strategy is not None:
                return []
            self._cache["nb"] = robustness.neighbours(self)
        return self._cache["nb"]

    def yearly(self) -> dict[int, float]:
        return metrics.yearly_pnl(self.dates, self.equity)

    def drawdown_story(self) -> dict[str, Any]:
        return metrics.worst_drawdown_story(self.dates, self.equity)

    def frame(self, gross: bool = False) -> pl.DataFrame:
        """date, equity, buy_and_hold, drawdown, bh_drawdown (+ before_costs), scaled to 100."""
        k = 100 / self.capital
        cols = {"date": self.dates, "equity": self.equity * k, "buy_and_hold": self.benchmark * k,
                "drawdown": metrics.drawdown(self.equity) * 100,
                "bh_drawdown": metrics.drawdown(self.benchmark) * 100}
        if gross:
            cols["before_costs"] = self.gross_book.equity * k
        return pl.DataFrame(cols)

    def trade_frame(self) -> pl.DataFrame:
        return pl.DataFrame(self.trades) if self.trades else pl.DataFrame()

    def with_costs(self, profile: str | None = None, slippage_pct: float | None = None) -> Result:
        """The same rule re-priced (Costs tab). Not a new trial: the rule did not change."""
        spec = Spec.from_dict(self.spec)
        if slippage_pct is not None:
            spec.cost.slippage_pct = slippage_pct
        prof = profile or self.profile
        from . import run
        return run(spec, self.bar_map, costs=prof, count_trial=False)

    def next_orders(self, start_empty: bool = True) -> list[dict[str, Any]]:
        """Paper-order drafts for the next session's open, from the latest completed bar.

        ``start_empty=True`` (Send to Paper Desk) sizes a fresh paper sleeve from nothing
        held; ``False`` gives only the change from the backtest's own final holdings.
        """
        if self.strategy is not None:
            return []
        held = {} if start_empty else self.book.final_units
        equity = self.capital if start_empty else float(self.equity[-1])
        deltas = next_session_orders(self.spec, self.bar_map, self.profile, held, equity)
        out = []
        for sym, d in deltas.items():
            close = float(self.bar_map[sym].sort("date")["close"][-1])
            out.append({"symbol": sym, "market": self.market, "side": "buy" if d > 0 else "sell",
                        "qty": abs(int(d)), "kind": "market", "price": round(close, 2)})
        return out

    # ------------------------------------------------------------ tax
    def after_tax(self, short_rate: float | None = None, long_rate: float | None = None
                  ) -> dict[str, Any]:
        """Tax each calendar year's realised gains (Chapter 16 *After-tax* toggle).

        Rates come from the dated tax table; for the US short-term rate (ordinary
        income) pass your own bracket as ``short_rate`` — the default is an
        assumption shown on screen. Losses offset gains within a year; carry-forward
        is not modelled. Buy-and-hold never sells, so it pays no tax here.
        """
        if self.market == "IN":
            t = reference.lookup("india.tax")
            s_rate = t["stcg_listed_equity"] if short_rate is None else short_rate
            l_rate = t["ltcg_listed_equity"] if long_rate is None else long_rate
            exempt = float(t["ltcg_exemption_inr"])
        else:
            lt = reference.lookup("us.tax.long_term")
            s_rate = 0.24 if short_rate is None else short_rate
            l_rate = float(lt[1]) if long_rate is None else long_rate
            exempt = 0.0
        by_year: dict[int, dict[str, float]] = {}
        for tr in self.trades:
            if tr.get("open"):
                continue
            y = tr["exit_date"].year
            row = by_year.setdefault(y, {"short": 0.0, "long": 0.0})
            held_days = (tr["exit_date"] - tr["entry_date"]).days
            row["long" if held_days > 365 else "short"] += float(tr["net_pnl"])
        taxes: dict[int, float] = {}
        for y, row in sorted(by_year.items()):
            short, long_ = row["short"], row["long"]
            if short < 0:
                long_, short = long_ + short, 0.0
            taxes[y] = round(float(max(short, 0) * s_rate + max(long_ - exempt, 0) * l_rate), 2)
        eq = self.equity.copy()
        paid = 0.0
        for i, d in enumerate(self.dates):
            nxt = self.dates[i + 1] if i + 1 < len(self.dates) else None
            eq[i] -= paid
            if (nxt is None or nxt.year != d.year) and d.year in taxes:
                paid += taxes[d.year]
                eq[i] -= taxes[d.year]
        return {"taxes": taxes, "total_tax": round(sum(taxes.values()), 2), "equity": eq,
                "short_rate": s_rate, "long_rate": l_rate,
                "after_tax_return": float(eq[-1] / eq[0] - 1),
                "short_rate_assumed": self.market == "US" and short_rate is None}

    # ------------------------------------------------------------ report
    def headline(self) -> list[tuple[str, str]]:
        s, g = self.stats(), self.gross_stats()
        wins = s["winners"]
        n = s["round_trips"]
        rows = [
            ("Instrument", f"{self.symbol} · {self.source} · {self.dates[0]} to {self.dates[-1]}"),
            ("Round trips", str(n)),
            ("Winning round trips", f"{wins} ({wins / n * 100:.1f}%)" if n else "0"),
            ("Result before costs", f"{g['total_return'] * 100:+.1f}%"),
            ("Result after costs", f"{s['total_return'] * 100:+.1f}%"),
            ("Charges / fees paid", self.money(s["charges"])),
            ("Assumed slippage", self.money(s["slippage"])),
            ("Worst drawdown after costs", f"{s['max_drawdown'] * 100:.1f}%"),
            ("Buy and hold, same period", f"{s['bh_return'] * 100:+.1f}%"),
            ("Sharpe (after costs)", f"{s['sharpe']:.2f}"),
            ("Trials in this family", str(self.trial_count())),
        ]
        return rows

    def report(self, echo: bool = True) -> _report.ReportCard:
        """Build (and print) the Report Card: Robust / Fragile / Likely overfit."""
        card = _report.build(self)
        self._cache["card"] = card
        if echo:
            print(card.text())
        return card

    def card(self) -> _report.ReportCard:
        return self._cache.get("card") or self.report(echo=False)

    def facts(self) -> list[str]:
        """Numbered facts for ``ai.explain`` — every number computed here, in code."""
        s, g = self.stats(), self.gross_stats()
        dd = self.drawdown_story()
        c = self.card()
        out = [
            "All results are HYPOTHETICAL (a backtest on past or synthetic data).",
            f"Rule: {self.spec.read_back()}",
            f"Data: {self.symbol}, source {self.source}, {self.dates[0]} to {self.dates[-1]}",
            f"Starting capital: {self.money(self.capital)}",
            f"Ending value after costs: {self.money(float(self.equity[-1]))}",
            f"Round trips: {s['round_trips']}",
            f"Winning round trips: {s['winners']}",
            f"Result before costs: {g['total_return'] * 100:+.1f}%",
            f"Result after costs: {s['total_return'] * 100:+.1f}%",
            f"Charges paid ({self.profile}): {self.money(s['charges'])}",
            f"Assumed slippage paid: {self.money(s['slippage'])}",
            f"Worst drawdown after costs: {s['max_drawdown'] * 100:.1f}%",
            f"Longest time below a previous high: {s['underwater_months']} months",
            f"Buy and hold over the same period: {s['bh_return'] * 100:+.1f}%",
            f"Buy and hold worst drawdown: {s['bh_max_drawdown'] * 100:.1f}%",
            f"Time in the market: {s['time_in_market'] * 100:.0f}%",
            f"Sharpe ratio after costs: {s['sharpe']:.2f}",
            f"Trials in this family: {c.trials}",
            f"Trial-adjusted (deflated) Sharpe: {c.deflated_sharpe:.2f}",
            f"Report Card grade: {c.grade} — {c.reason}",
        ]
        if dd["start"]:
            out.append(f"Deepest drawdown began {dd['start']}, bottomed {dd['trough']}, "
                       f"{dd['months_below']} months below the earlier high")
        out += [f"Check {ch.name}: {ch.measured}" for ch in c.checks]
        out += c.warnings
        return out

    def summary(self) -> dict[str, Any]:
        """A JSON-friendly record for the store (Backtest Report history, MCP get_backtest)."""
        c = self.card()
        return {"symbol": self.symbol, "symbols": self.symbols, "market": self.market,
                "profile": self.profile, "source": self.source, "family": self.family,
                "start": str(self.dates[0]), "end": str(self.dates[-1]),
                "spec": self.spec.to_dict(), "read_back": self.spec.read_back(),
                "stats": {k: v for k, v in self.stats().items()}, "report": c.to_dict()}

    def save(self, tag: str = "") -> int:
        """Store this report in the ``backtests`` table. Returns the row id."""
        return store().add("backtests", self.summary(), tag=tag or self.card().grade)


def _stats(book: Book, dates: list[date]) -> dict[str, Any]:
    eq, bh = book.equity, book.benchmark
    r = metrics.returns(eq)
    closed = [t for t in book.trades if not t.get("open")]
    return {
        "final": float(eq[-1]),
        "total_return": float(eq[-1] / eq[0] - 1),
        "cagr": metrics.cagr(eq, dates),
        "volatility": float(r.std(ddof=1) * np.sqrt(252)) if len(r) > 1 else 0.0,
        "sharpe": round(metrics.sharpe(r), 3),
        "sharpe_daily": metrics.sharpe_daily(r),
        "max_drawdown": float(metrics.drawdown(eq).min()),
        "underwater_months": metrics.longest_underwater_months(dates, eq),
        "round_trips": len(closed),
        "winners": sum(1 for t in closed if t["net_pnl"] > 0),
        "charges": round(sum(f["charges"] for f in book.fills), 2),
        "slippage": round(sum(f["slippage"] for f in book.fills), 2),
        "fills": len(book.fills),
        "time_in_market": float((book.exposure > 0).mean()),
        "bh_return": float(bh[-1] / bh[0] - 1),
        "bh_max_drawdown": float(metrics.drawdown(bh).min()),
        "bh_sharpe": round(metrics.sharpe(metrics.returns(bh)), 3),
        "losing_years": sum(1 for v in metrics.yearly_returns(dates, eq).values() if v < 0),
        "years": round(metrics.years(dates), 2),
    }
