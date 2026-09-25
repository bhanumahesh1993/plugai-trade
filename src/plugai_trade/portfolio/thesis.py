"""Thesis tracker: a written reason for each holding and the conditions that would break it.

A tripped condition means "look", not "sell". Figures arrive from the Document
Desk (Accept) or are typed in; the check itself is plain comparison in code.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field

from ..store import default as store

OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}


@dataclass
class Condition:
    """One measurable sign: metric, comparison and threshold."""

    metric: str
    op: str
    threshold: float
    label: str = ""

    def holds(self, value: float) -> bool:
        """True when the latest figure still satisfies the condition."""
        return OPS[self.op](value, self.threshold)

    def text(self) -> str:
        """Human-readable condition."""
        return self.label or f"{self.metric} {self.op} {self.threshold:g}"


@dataclass
class Thesis:
    """Why I own it, plus conditions and the figures reported each quarter."""

    holding: str
    why: str
    conditions: list[Condition]
    figures: list[dict] = field(default_factory=list)  # {"quarter", "metric", "value", "source"}
    kind: str = "stock"

    def latest(self, metric: str) -> tuple[dict | None, dict | None]:
        """(last quarter, this quarter) figure rows for a metric."""
        rows = [f for f in self.figures if f["metric"] == metric]
        rows.sort(key=lambda f: f["quarter"])
        return (rows[-2] if len(rows) > 1 else None, rows[-1] if rows else None)

    def check(self) -> list[dict]:
        """Each condition with last quarter, this quarter, source and status."""
        out = []
        for c in self.conditions:
            prev, cur = self.latest(c.metric)
            if cur is None:
                status = "no figure yet"
            else:
                status = "✓ holds" if c.holds(float(cur["value"])) else "⚠ review"
            out.append({"My condition": c.text(), "Last qtr": prev["value"] if prev else None,
                        "This qtr": cur["value"] if cur else None,
                        "Source": cur.get("source", "") if cur else "", "Status": status})
        return out

    @property
    def tripped(self) -> int:
        """Conditions that need a review."""
        return sum(1 for r in self.check() if r["Status"] == "⚠ review")

    def facts(self) -> list[str]:
        """Facts for Explain."""
        f = [f"Holding: {self.holding}", f"Why I own it: {self.why}"]
        for r in self.check():
            f.append(f"{r['My condition']}: last {r['Last qtr']}, this {r['This qtr']} "
                     f"({r['Source']}) → {r['Status']}")
        f.append(f"Conditions tripped: {self.tripped} (a prompt to look, not a sale)")
        return f

    def to_record(self) -> dict:
        """Body for the ``theses`` table."""
        return {"holding": self.holding, "why": self.why, "kind": self.kind,
                "conditions": [c.__dict__ for c in self.conditions], "figures": self.figures}

    @classmethod
    def from_record(cls, r: dict) -> "Thesis":
        """Rebuild from a stored row."""
        return cls(r["holding"], r.get("why", ""), [Condition(**c) for c in r.get("conditions", [])],
                   list(r.get("figures", [])), r.get("kind", "stock"))


def sample_thesis() -> Thesis:
    """Priya's thesis for the fictional Narmada Home Appliances (Chapter 15)."""
    conds = [Condition("revenue_growth_pct", ">=", 10, "Revenue growth (yoy) ≥ 10%"),
             Condition("operating_margin_pct", ">", 9, "Operating margin > 9%"),
             Condition("debt_to_equity", "<", 0.5, "Debt-to-equity < 0.5"),
             Condition("promoter_pledge_pct", "<", 5, "Promoter pledge < 5% of holding")]
    figs = []
    for q, vals in (("2026-Q1", (11.8, 9.6, 0.28, 3.1)), ("2026-Q2", (12.4, 9.3, 0.31, 7.8))):
        for c, v, src in zip(conds, vals, ("p. 3", "p. 3", "p. 7", "SHP"), strict=True):
            figs.append({"quarter": q, "metric": c.metric, "value": v, "source": src})
    return Thesis("Narmada Home Appliances (fictional)",
                  "Household brand, small-town dealer network · held since 2023", conds, figs)


def save(t: Thesis, thesis_id: int | None = None) -> int:
    """Insert or update a thesis in the lab store."""
    if thesis_id:
        store().update("theses", thesis_id, t.to_record())
        return thesis_id
    return store().add("theses", t.to_record(), tag="thesis")


def load_all() -> list[tuple[int, Thesis]]:
    """Every stored stock/fund thesis (ETF comparisons are listed separately)."""
    return [(r["id"], Thesis.from_record(r)) for r in store().all("theses")
            if r.get("kind", "stock") != "etf_comparison" and "holding" in r]


def add_note_to_journal(text: str, holding: str) -> int:
    """Record the decision in the journal (notes table, tag 'journal')."""
    return store().add("notes", {"screen": "Portfolio Reviewer", "holding": holding,
                                 "text": text}, tag="journal")
