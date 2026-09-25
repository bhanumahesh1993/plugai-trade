"""The 30-minute Weekly Review: tiles with last week beside them, rule breaks, patterns.

Everything on the screen is computed here, in code, with a query behind it; the
local model only narrates ``WeeklyReview.facts()`` (Generate review).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import polars as pl

from .. import ai
from ..store import default as store
from .detectors import Finding, RuleCard, enrich, finding, n_label
from .query import Answer, QuerySpec, run_pinned, week_bounds

REVIEW_QUESTION = (
    "Write this week's review from the numbers only, in this order, one short paragraph each, "
    "citing the [n] facts: 1. Do the totals look complete? 2. Adherence this week vs last. "
    "3. What the rule breaks cost. 4. Charges as % of gross, and the trend. 5. For each break, "
    "what the row before it shows. 6. One pattern to watch, with its n; say 'too few to "
    "conclude' if n < 30. End with two questions that would help choose one change for next "
    "week. No trade, instrument, size or market-direction suggestions.")


@dataclass
class WeekStats:
    """Counted totals for one week."""

    start: str
    end: str
    n: int = 0
    wins: int = 0
    total_r: float = 0.0
    gross: float = 0.0
    charges: float = 0.0
    net: float = 0.0
    followed: int = 0
    followed_r: float = 0.0
    broke: int = 0
    broke_r: float = 0.0
    rows: list[int] = field(default_factory=list)

    @property
    def charges_pct(self) -> float | None:
        return round(self.charges / self.gross * 100, 1) if self.gross > 0 else None


def week_stats(e: pl.DataFrame, start: str, end: str) -> WeekStats:
    w = e.filter((pl.col("date") >= start) & (pl.col("date") <= end)) if e.height else e
    if w.is_empty():
        return WeekStats(start, end)
    ok, bad = w.filter(~pl.col("broke_rule")), w.filter(pl.col("broke_rule"))
    return WeekStats(
        start, end, n=w.height, wins=int(w["win"].sum()), total_r=round(float(w["r"].sum()), 2),
        gross=round(float(w["gross"].sum()), 2), charges=round(float(w["charges"].sum()), 2),
        net=round(float(w["net"].sum()), 2), followed=ok.height,
        followed_r=round(float(ok["r"].sum() or 0), 2), broke=bad.height,
        broke_r=round(float(bad["r"].sum() or 0), 2), rows=w["trade_id"].to_list())


def _signed(x: float, unit: str = "R") -> str:
    return f"{x:+.2f}{unit}".replace("-", "−")


def _money(x: float, cur: str) -> str:
    return f"{'−' if x < 0 else ''}{cur}{abs(x):,.0f}"


def _pct(x: float | None) -> str:
    return "n/a (gross ≤ 0)" if x is None else f"{x}%"


@dataclass
class WeeklyReview:
    """One week's review, the week before for comparison, and the queries behind each tile."""

    start: str
    end: str
    market: str
    card: RuleCard
    this: WeekStats
    last: WeekStats
    rule_breaks: list[Finding]
    patterns: list[Finding]
    queries: dict[str, str]
    pinned: list[Answer] = field(default_factory=list)
    last_decision: str | None = None

    @property
    def currency(self) -> str:
        return "₹" if self.market == "IN" else "$"

    def tiles(self) -> list[dict[str, str]]:
        """The six tiles (label, value, sub-line, last week, query key)."""
        t, lw, cur = self.this, self.last, self.currency
        pct = f"{t.charges_pct}%" if t.charges_pct is not None else "n/a"
        lpct = f"{lw.charges_pct}%" if lw.charges_pct is not None else "n/a"
        return [
            {"label": "TRADES", "value": str(t.n), "sub": f"{t.wins} won",
             "last": f"last week {lw.n}", "q": "q1"},
            {"label": "RESULT", "value": _signed(t.total_r), "sub": "before charges",
             "last": f"last week {_signed(lw.total_r)}", "q": "q1"},
            {"label": "CHARGES", "value": pct, "sub": f"of gross · {cur}{t.charges:,.0f}",
             "last": f"last week {lpct}", "q": "q4"},
            {"label": "NET", "value": _money(t.net, cur), "sub": "after charges",
             "last": f"last week {_money(lw.net, cur)}", "q": "q4"},
            {"label": "ADHERENCE", "value": f"{t.followed} / {t.n}", "sub": "broke no line",
             "last": f"last week {lw.followed} / {lw.n}", "q": "q2"},
            {"label": "BREAKS COST", "value": _signed(t.broke_r), "sub": f"{t.broke} trades",
             "last": f"last week {_signed(lw.broke_r)}", "q": "q3"},
        ]

    def facts(self) -> list[str]:
        t, lw, cur = self.this, self.last, self.currency
        out = [
            f"Week {self.start} to {self.end}: {t.n} trades, {t.wins} won, {_signed(t.total_r)} "
            f"before charges (q1; {n_label(t.n)})",
            f"Previous week: {lw.n} trades, {_signed(lw.total_r)}; adherence {lw.followed} / "
            f"{lw.n}",
            f"Followed every Rule Card line: {t.followed} trades, {_signed(t.followed_r)} (q2)",
            f"Broke at least one line: {t.broke} trades, {_signed(t.broke_r)} (q3)",
            f"Charges {cur}{t.charges:,.2f} = {_pct(t.charges_pct)} of gross "
            f"{cur}{t.gross:,.2f}; last week {_pct(lw.charges_pct)} (q4)",
            f"Net after charges: {cur}{t.net:,.2f}",
        ]
        for f in self.rule_breaks:
            if f.n:
                out.append(f"Rule break '{f.label}': rows {', '.join(map(str, f.rows))}, "
                           f"{_signed(f.total_r)}")
        for f in self.patterns:
            if f.n:
                out.append(f"Not yet a rule — {f.label}: rows {', '.join(map(str, f.rows))}, "
                           f"{_signed(f.total_r)} ({n_label(f.n)})")
        for a in self.pinned:
            out.append(f"Pinned question '{a.spec.label}': {a.text}")
        if self.last_decision:
            out.append(f"Last week you decided: {self.last_decision}")
        return out

    def to_record(self, narration: str = "", decision: str = "") -> dict[str, Any]:
        return {"week_start": self.start, "week_end": self.end, "market": self.market,
                "rule_card": self.card.version, "tiles": self.tiles(), "facts": self.facts(),
                "queries": self.queries, "narration": narration, "decision": decision}


def _week_spec(start: str, end: str, extra: list[list[Any]] | None = None,
               label: str = "") -> QuerySpec:
    return QuerySpec(filters=[["date", ">=", start], ["date", "<=", end], *(extra or [])],
                     label=label)


def build(trades: pl.DataFrame, week_of: str | None = None, card: RuleCard | None = None,
          pinned: list[QuerySpec] | None = None) -> WeeklyReview:
    """Compute the review for the week containing ``week_of`` (default: the latest trade)."""
    card = card or RuleCard()
    e = enrich(trades, card)
    if week_of is None:
        week_of = str(e["date"].max()) if e.height else date.today().isoformat()
    start, end = week_bounds(week_of)
    lstart = (date.fromisoformat(start) - timedelta(days=7)).isoformat()
    lend = (date.fromisoformat(end) - timedelta(days=7)).isoformat()
    w = e.filter((pl.col("date") >= start) & (pl.col("date") <= end)) if e.height else e
    breaks, patterns = [], []
    if w.height:
        for key, line in card.lines():
            breaks.append(finding(w, pl.col(f"br_{key}"), line.split(" → ")[0],
                                  f"WHERE {line.split(' → ')[1]}"))
        if not card.cooldown_minutes:
            patterns.append(finding(w, pl.col("reentry_after_loss"),
                                    "Re-entry ≤ 30 min after a loss", "reentry_after_loss"))
        patterns.append(finding(w, pl.col("after_two_losses"), "After two losses in a row",
                                "after_two_losses"))
        patterns.append(finding(w, ~pl.col("win") & (pl.col("hold_minutes") > 60),
                                "Losers held over an hour", "NOT win AND hold_minutes > 60"))
        skip = {"", f"first {card.no_trade_first_minutes} min"}
        for win in sorted(set(w["window"].to_list()) - skip):
            patterns.append(finding(w, pl.col("window") == win, f"Window: {win}",
                                    f"window = '{win}'"))
    queries = {
        "q1": _week_spec(start, end, label="this week's trades").to_sql(),
        "q2": _week_spec(start, end, [["broke_rule", "is", False]], "followed").to_sql(),
        "q3": _week_spec(start, end, [["broke_rule", "is", True]], "broke").to_sql(),
        "q4": _week_spec(start, end, label="charges").to_sql(),
    }
    answers = [run_pinned(s, trades, start, end, card) for s in (pinned or [])]
    market = (trades["market"][0] if trades.height else None) or "IN"
    return WeeklyReview(start, end, market, card, week_stats(e, start, end),
                        week_stats(e, lstart, lend), breaks, patterns, queries, answers,
                        last_decision())


def generate(review: WeeklyReview) -> ai.Explanation:
    """Generate review: the local model narrates the computed facts (sensitive, Journal)."""
    return ai.explain(review, REVIEW_QUESTION, section="Journal", sensitive=True)


def save(review: WeeklyReview, narration: str = "", decision: str = "") -> int:
    """Save review: tiles, narration and the decision stored together."""
    return store().add("reviews", review.to_record(narration, decision), tag="weekly")


def last_decision() -> str | None:
    """The decision saved with the most recent weekly review, if any."""
    rows = store().all("reviews", tag="weekly", limit=1)
    return (rows[0].get("decision") or None) if rows else None


def pin(answer: Answer) -> int:
    """Pin an Ask My Journal question so it runs in every Weekly Review."""
    return store().add("reviews", {"question": answer.question, "spec": answer.spec.to_json(),
                                   "sql": answer.sql}, tag="pinned")


def pinned_specs() -> list[QuerySpec]:
    out = []
    for r in store().all("reviews", tag="pinned"):
        try:
            out.append(QuerySpec.from_json(r["spec"]))
        except (ValueError, KeyError):
            continue
    return out
