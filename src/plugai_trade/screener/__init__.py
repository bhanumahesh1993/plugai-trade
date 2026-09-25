"""Research › Screener: plain-English rules, computed on a dated universe.

    from plugai_trade import screener
    parsed = screener.parse("near the 52-week high with volume picking up", market="IN")
    print(parsed.read_back())                     # rule cards, "?" on interpreted words
    res = screener.run(parsed, universe="NIFTY 500", market="IN")
    print(res.table().head())                     # the value behind every rule + Next event

The model never sees a stock list it could pick from: rules are applied in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import polars as pl

from ..earnings import calendar
from ..store import default as store
from . import universe as uni
from .metrics import compute, premarket
from .rules import LABELS, Parsed, Rule, label, parse

TRIAGE = ("Watch closely", "Wait for the setup", "Research first", "Drop")

GAP_SCAN = "gap at least 2% either way; RVOL at least 2; a time-stamped item since the last close"
PRESETS: dict[str, dict[str, str]] = {
    "Swing · Pullback": {
        "IN": (
            "50-day average above the 200-day average, both rising; close within 1 ATR of the "
            "20-day average after at least 3 lower closes; dip volume at most 0.8x; "
            "median traded value at least ₹10 cr; exclude events within 5 sessions"
        ),
        "US": (
            "50-day average above the 200-day average, both rising; close within 1 ATR of the "
            "20-day average after at least 3 lower closes; dip volume at most 0.8x; "
            "median traded value at least $20 m; exclude events within 5 sessions"
        ),
    },
    "Swing · Breakout": {
        "IN": (
            "50-day average above the 200-day average; close above the 25-day high; "
            "volume at least 1.5x the 20-day average; relative strength positive; "
            "median traded value at least ₹10 cr; exclude events within 10 sessions"
        ),
        "US": (
            "50-day average above the 200-day average; close above the 25-day high; "
            "volume at least 1.5x the 20-day average; relative strength positive; "
            "median traded value at least $20 m; exclude events within 10 sessions"
        ),
    },
    "Gap scan": {m: GAP_SCAN for m in ("IN", "US")},
}

SWING_EXTRA = ("dist_sma_atr:20", "rs_3m")  # columns the swing presets always show


def preset(name: str, market: str) -> str:
    """The Describe-your-screen text for a preset."""
    return PRESETS[name][market]


def latest_asof(market: str) -> date:
    """The last bar in the data (the As of date default)."""
    df = uni.bars(uni.BENCHMARK[market], market, date.today() - timedelta(days=15), date.today())
    return df["date"][-1] if df.height else date.today()


@dataclass
class Row:
    """One stock's values and verdict."""

    symbol: str
    values: dict[str, float | None]
    passed: bool
    next_event: str
    event_date: date | None
    event_sessions: int | None = None
    excluded: str = ""
    triage: str = ""
    near_misses: list[str] = field(default_factory=list)
    item: str | None = None


@dataclass
class Result:
    """The results table from Run."""

    rules: list[Rule]
    market: str
    universe: str
    asof: date
    rows: list[Row]
    exclude_events: int | None = None
    source: str = "synthetic"

    @property
    def passed(self) -> list[Row]:
        return [r for r in self.rows if r.passed and not r.excluded]

    @property
    def excluded(self) -> list[Row]:
        return [r for r in self.rows if r.passed and r.excluded]

    def columns(self) -> list[str]:
        cols = [r.metric for r in self.rules]
        return cols + [c for c in SWING_EXTRA if c not in cols and self._is_swing()]

    def _is_swing(self) -> bool:
        return any(r.metric.startswith(("dist_sma_atr", "above_high")) for r in self.rules)

    def table(self, which: str = "passed") -> pl.DataFrame:
        """Rows as a frame: Symbol, one column per rule value, Next event, Triage."""
        rows = {"passed": self.passed, "excluded": self.excluded, "all": self.rows}[which]
        cols = self.columns()
        recs = []
        for r in rows:
            rec: dict[str, Any] = {"Symbol": r.symbol}
            for c in cols:
                rec[label(c, self.market)] = r.values.get(c)
            if any(x.metric in ("gap_pct", "gap_abs_pct", "has_item") for x in self.rules):
                rec["Latest item"] = r.item or "none found"
            rec["Next event"] = r.next_event
            if which == "excluded":
                rec["Excluded"] = r.excluded
            else:
                rec["Triage"] = r.triage
            recs.append(rec)
        return pl.DataFrame(recs) if recs else pl.DataFrame({"Symbol": []})

    def facts(self) -> list[str]:
        out = [
            f"Universe: {self.universe} ({self.market}), as of {self.asof}, source {self.source}",
            f"{len(self.rows)} names tested, {len(self.passed)} passed, "
            f"{len(self.excluded)} excluded by the event rule",
        ]
        out += [f"Rule {i}: {r.text}" for i, r in enumerate(self.rules, 1)]
        for r in self.passed[:15]:
            vals = ", ".join(f"{label(k, self.market)} {v}" for k, v in r.values.items())
            out.append(f"{r.symbol}: {vals}; next event {r.next_event}; triage {r.triage}")
        return out


def suggest_triage(row: Row, rules: list[Rule], window: int = 10) -> str:
    """The lab's first-pass bin; your tag always wins.

    Drop: fails a rule. Research first: an event inside the holding window.
    Wait for the setup: only just passes a rule (within 10% of the threshold).
    Watch closely: passes every rule comfortably with no event in the window.
    """
    if not row.passed:
        return "Drop"
    if row.event_sessions is not None and not row.excluded and row.event_sessions <= window:
        return "Research first"
    if row.near_misses:
        return "Wait for the setup"
    return "Watch closely"


def run(
    parsed: Parsed | list[Rule],
    universe: str,
    market: str,
    asof: date | None = None,
    exclude_events: int | None = None,
    symbols: list[str] | None = None,
    window: int = 10,
) -> Result:
    """Apply the rules to every name in the universe on the As of date."""
    rules = parsed.rules if isinstance(parsed, Parsed) else parsed
    if exclude_events is None and isinstance(parsed, Parsed):
        exclude_events = parsed.exclude_events
    asof = asof or latest_asof(market)
    start = asof - timedelta(days=420)
    index_df = uni.bars(uni.BENCHMARK[market], market, start, asof)
    rows: list[Row] = []
    for sym in symbols or uni.names(universe, market):
        df = uni.bars(sym, market, start, asof)
        if df.height < 30 or df["date"][-1] < asof - timedelta(days=7):
            continue  # delisted or no data on the As of date
        values = {r.metric: compute(r.metric, df, index_df, market, sym, asof) for r in rules}
        for extra in SWING_EXTRA:
            if extra not in values and any(
                r.metric.startswith(("dist_sma_atr", "above_high")) for r in rules
            ):
                values[extra] = compute(extra, df, index_df, market, sym, asof)
        passed = all(r.passes(values[r.metric]) for r in rules)
        ev = calendar.next_event(sym, market, asof)
        k = calendar.sessions_between(asof, ev.date) if ev else None
        nxt = f"results in {k} sessions ({ev.date:%d %b})" if ev else "—"
        row = Row(
            sym,
            values,
            passed,
            nxt,
            ev.date if ev else None,
            k,
            near_misses=[r.text for r in rules if r.near_miss(values[r.metric])],
            item=premarket(sym, asof)["item"]
            if any(r.metric in ("gap_pct", "gap_abs_pct", "has_item") for r in rules)
            else None,
        )
        if passed and exclude_events is not None and k is not None and k <= exclude_events:
            row.excluded = f"board meeting / results in {k} sessions ({ev.date:%d %b})"
        row.triage = suggest_triage(row, rules, window)
        rows.append(row)
    return Result(rules, market, universe, asof, rows, exclude_events)


def save_watchlist(
    name: str,
    market: str,
    symbols: list[str],
    reasons: dict[str, str] | str,
    review_by: date | str,
    rules_text: str = "",
    source: str = "Screener",
    triage: dict[str, str] | None = None,
) -> int:
    """Save as watchlist. Refuses any name with an empty Reason."""
    if not name.strip():
        raise ValueError("Give the watchlist a name.")
    if not symbols:
        raise ValueError("No names selected.")
    if isinstance(reasons, str):
        reasons = {s: reasons for s in symbols}
    missing = [s for s in symbols if not str(reasons.get(s, "")).strip()]
    if missing:
        raise ValueError("Reason required for: " + ", ".join(missing))
    body = {
        "name": name.strip(),
        "market": market,
        "symbols": list(symbols),
        "reasons": {s: reasons[s].strip() for s in symbols},
        "review_by": str(review_by),
        "rules": rules_text,
        "source": source,
        "triage": triage or {},
    }
    return store().add("watchlists", body, tag=market)


def watchlists(market: str | None = None) -> list[dict[str, Any]]:
    """Saved watchlists (newest first)."""
    return store().all("watchlists", tag=market)


def schedule(name: str, market: str, run_time: str, description: str, universe: str) -> int:
    """Schedule a screen (e.g. Gap scan at 09:08 IST / 09:15 ET) as a job."""
    body = {
        "kind": "Screener",
        "name": name,
        "market": market,
        "run_time": run_time,
        "days": "market days",
        "description": description,
        "universe": universe,
        "model": "local",
        "active": True,
    }
    return store().add("jobs", body, tag="screener")


__all__ = [
    "LABELS",
    "PRESETS",
    "TRIAGE",
    "Parsed",
    "Result",
    "Row",
    "Rule",
    "label",
    "latest_asof",
    "parse",
    "preset",
    "run",
    "save_watchlist",
    "schedule",
    "suggest_triage",
    "watchlists",
]
