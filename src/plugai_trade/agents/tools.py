"""The four tools an agent team may call, behind the as-of wall and the name mask.

``get_bars``, ``get_news``, ``get_filings`` and ``run_backtest``. Every tool
returns data dated on or before ``as_of`` only; with ``mask_names`` the model
sees "Index A" and relative dates (t-0 is the as-of session) instead of the
ticker and calendar dates. There is no order tool and no paper-order tool.
Every call is logged with its arguments for the Transcript's tool-call chips,
and every ``run_backtest`` adds to the Trials counter.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import polars as pl

TOOLS = ("get_bars", "get_news", "get_filings", "run_backtest")
INDEXES = {"NIFTY", "BANKNIFTY", "SENSEX", "NIFTY50", "FINNIFTY", "SPY", "QQQ", "DIA", "IWM",
           "VOO", "^NSEI", "^GSPC"}
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
PROFILE = {"IN": "IN-equity-delivery", "US": "US-equity"}


def as_date(d: str | date | None) -> date:
    if d is None:
        return datetime.now(UTC).date()
    return d if isinstance(d, date) else date.fromisoformat(str(d))


class Tools:
    """Tool box for one run. ``log`` receives one dict per call (a transcript chip)."""

    def __init__(self, symbol: str, market: str, as_of: date, mask_names: bool,
                 log: Callable[[dict[str, Any]], None], years: int = 10):
        self.symbol, self.market, self.as_of, self.mask = symbol, market, as_of, mask_names
        self.log, self.years = log, years
        self.alias = ("Index A" if symbol.upper() in INDEXES else "Stock A") if mask_names else symbol
        self._bars: pl.DataFrame | None = None

    # ------------------------------------------------------------ helpers
    def mask_text(self, text: str) -> str:
        """Replace the ticker with its alias, and calendar dates, when names are masked."""
        if not self.mask:
            return text
        return _DATE.sub("[date hidden]", text.replace(self.symbol, self.alias))

    def _chip(self, agent: str, tool: str, args: dict[str, Any], summary: str,
              data: list[str], ok: bool = True) -> None:
        self.log({"kind": "tool", "agent": agent, "tool": tool, "args": args, "ok": ok,
                  "summary": summary, "data": data})

    def bars(self) -> pl.DataFrame:
        """Bars up to and including ``as_of`` (never later)."""
        if self._bars is None:
            from .. import data
            start = self.as_of - timedelta(days=365 * self.years)
            df = data.get(self.symbol, market=self.market, start=start, end=self.as_of)
            self._bars = df.filter(pl.col("date") <= self.as_of).sort("date")
        return self._bars

    # ------------------------------------------------------------ tools
    def get_bars(self, agent: str = "Technical") -> list[str]:
        """Facts computed in code from daily bars up to ``as_of``."""
        facts = bar_facts(self.bars(), self.alias, self.mask)
        self._chip(agent, "get_bars", {"subject": self.alias, "until": "t-0" if self.mask
                                       else str(self.as_of)},
                   f"{self.bars().height} sessions up to the as-of date", facts)
        return facts

    def get_news(self, agent: str = "News") -> list[str]:
        """Headlines published on or before ``as_of`` (empty when no news source works)."""
        heads: list[str] = []
        note = "no news source available"
        try:
            from .. import news  # Chapter 28; offline it serves a labelled synthetic sample
            df = news.fetch(None, market=self.market, start=self.as_of - timedelta(days=30),
                            end=self.as_of)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            note = f"no news: {exc}"[:120]
        else:
            if not df.is_empty() and {"headline", "tradable_day"} <= set(df.columns):
                df = df.filter(pl.col("tradable_day") <= self.as_of).tail(10)
                heads = [self.mask_text(f"{h} ({s})") for h, s in
                         zip(df["headline"].to_list(), df["source"].to_list())]
                note = f"{len(heads)} headlines known by the as-of date"
        self._chip(agent, "get_news", {"subject": self.alias, "days": 30}, note, heads)
        return heads

    def get_filings(self, agent: str = "Fundamentals") -> list[str]:
        """Filings dated on or before ``as_of`` from the Document Desk library, if any."""
        from ..store import default as store
        found: list[str] = []
        for d in store().all("documents", limit=50):
            dated = str(d.get("date") or d.get("created", ""))[:10]
            if self.symbol.lower() in str(d.get("name", "")).lower() and dated <= str(self.as_of):
                found.append(self.mask_text(str(d.get("name"))))
        note = f"{len(found)} filings on file" if found else "no filings on file before the as-of date"
        self._chip(agent, "get_filings", {"subject": self.alias}, note, found)
        return found

    def run_backtest(self, spec: dict[str, Any], agent: str = "Rule proposer") -> dict[str, Any]:
        """Backtest a draft rule on bars up to ``as_of``. Counts one trial."""
        try:
            from .. import backtest
        except ImportError as exc:  # pragma: no cover - backtest ships with the app
            self._chip(agent, "run_backtest", {"rule": spec.get("text", "")}, str(exc), [], False)
            return {"ok": False, "error": str(exc)}
        try:
            res = backtest.run(spec, self.bars(), costs=PROFILE.get(self.market, "IN-equity-delivery"),
                               symbol=self.alias)
            grade = res.card().grade
            facts = [self.mask_text(f) for f in res.facts()[:8]]
            out = {"ok": True, "grade": grade, "trials": res.trials_at_run, "facts": facts}
            self._chip(agent, "run_backtest", {"rule": spec.get("text", "")},
                       f"grade {grade} · trial #{res.trials_at_run} in this family", facts)
            return out
        except Exception as exc:  # noqa: BLE001 - a bad draft is reported, never raised
            self._chip(agent, "run_backtest", {"rule": spec.get("text", "")}, str(exc)[:200], [],
                       False)
            return {"ok": False, "error": str(exc)}


def bar_facts(bars: pl.DataFrame, alias: str, mask: bool) -> list[str]:
    """Short, computed facts about the bars (the model may only quote these)."""
    c = bars["close"].to_numpy().astype(float)
    if len(c) < 60:
        return [f"{alias}: only {len(c)} sessions before the as-of date"]
    r = np.diff(np.log(c))

    def sma(n: int) -> float:
        return float(c[-n:].mean()) if len(c) >= n else float("nan")

    def ret(n: int) -> float:
        return (c[-1] / c[-n - 1] - 1) * 100 if len(c) > n else float("nan")

    vol20 = float(r[-20:].std(ddof=1) * np.sqrt(252) * 100)
    roll = np.array([r[i - 20:i].std(ddof=1) for i in range(max(20, len(r) - 252), len(r) + 1)])
    ratio = float(r[-20:].std(ddof=1) / np.median(roll)) if len(roll) else float("nan")
    peak = np.maximum.accumulate(c[-252:])
    when = "t-0" if mask else str(bars["date"][-1])
    facts = [f"{alias}: {len(c)} daily sessions up to {when}",
             f"Close vs 50-day average: {(c[-1] / sma(50) - 1) * 100:+.1f}%",
             f"Close vs 200-day average: {(c[-1] / sma(200) - 1) * 100:+.1f}%",
             f"Return over 21 sessions: {ret(21):+.1f}%",
             f"Return over 63 sessions: {ret(63):+.1f}%",
             f"Return over 252 sessions: {ret(252):+.1f}%",
             f"20-day volatility (annualised): {vol20:.1f}%",
             f"20-day volatility vs its past-year median: {ratio:.2f}×",
             f"Worst fall from a high in the last 252 sessions: {((c[-252:] / peak - 1).min()) * 100:.1f}%",
             f"Up sessions in the last 14: {int((r[-14:] > 0).sum())}"]
    return facts
