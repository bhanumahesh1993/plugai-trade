"""The trading journal (Chapter 14): import, pair, price, measure in R, review, ask.

    from plugai_trade import journal
    j = journal.load("zerodha_tradebook.csv")     # one row per round trip, charges priced
    k = journal.sample("kavita")                  # synthetic NIFTY futures journal
    rep = journal.detect(k)                       # the six detectors, computed in code
    ans = journal.ask("How did I do on trades I opened soon after a loss?", k)
    print(ans.sql)                                # Show query

Journal data is personal: every AI call from here uses ``sensitive=True`` (local model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from ..store import default as store
from . import detectors, importers, plans, query, replay, review
from .detectors import MIN_N, TOO_FEW, DetectorReport, RuleCard, n_label
from .importers import BROKERS, INDIA_BROKERS, US_BROKERS, ImportError_, detect_broker
from .pairing import PairResult, pair_fills
from .plans import match_plans, set_stop, with_r
from .query import Answer, QuerySpec, ask
from .samples import SAMPLES, sample, to_tradebook, write_tradebook
from .schema import TAGS, primary_tag, to_records, trades_from_records

__all__ = [
    "load", "import_tradebook", "ImportResult", "sample", "to_tradebook", "write_tradebook",
    "trades", "save", "set_tags", "detect", "ask", "RuleCard", "DetectorReport", "Answer",
    "QuerySpec", "BROKERS", "INDIA_BROKERS", "US_BROKERS", "SAMPLES", "TAGS", "MIN_N", "TOO_FEW",
    "n_label", "match_plans", "set_stop", "with_r", "pair_fills", "detect_broker", "ImportError_",
    "detectors", "importers", "plans", "query", "replay", "review", "PairResult",
]


@dataclass
class ImportResult:
    """What Import tradebook produced, before the trader clicks Accept."""

    broker: str
    fills: int
    trades: pl.DataFrame
    unpaired: pl.DataFrame
    unmatched_plans: list[int] = field(default_factory=list)

    def facts(self) -> list[str]:
        cur = "₹" if (self.trades["market"][0] if self.trades.height else "IN") == "IN" else "$"
        t = self.trades
        priced = t.filter(pl.col("charges_source") == "cost table").height if t.height else 0
        return [f"Broker file: {self.broker}", f"Fills read: {self.fills}",
                f"Round trips: {t.height}", f"Fills not paired: {self.unpaired.height}",
                f"Gross P&L: {cur}{float(t['gross'].sum() or 0):,.2f}",
                f"Charges: {cur}{float(t['charges'].sum() or 0):,.2f} "
                f"({priced} priced from the dated cost table)",
                f"Trades without a planned stop: {len(self.unmatched_plans)}"]


def import_tradebook(source: str | Path | bytes, broker: str | None = None,
                     account: str = "Main", mapping: dict[str, str] | None = None,
                     market: str | None = None, tags: list[str] | None = None,
                     plan_rows: list[dict] | None = None) -> ImportResult:
    """Read a broker tradebook, pair fills into round trips, price charges, match plans."""
    raw = importers.read_rows(source)[0] if broker is None else None
    name = broker or importers.detect_broker(list(raw[0].keys())) or "Generic CSV"
    fills = importers.parse_fills(source, name, account, mapping, market)
    paired = pair_fills(fills)
    t = paired.trades
    if tags:
        t = t.with_columns(tags=pl.lit(list(tags), dtype=pl.List(pl.Utf8)))
    t, unmatched = match_plans(t, plan_rows)
    return ImportResult(name, fills.height, t, paired.unpaired, unmatched)


def load(path: str | Path, broker: str | None = None, account: str = "Main",
         mapping: dict[str, str] | None = None, market: str | None = None) -> pl.DataFrame:
    """Journal rows (one per round trip) from a broker tradebook. Nothing is saved."""
    return import_tradebook(path, broker, account, mapping, market).trades


def _key(r: dict) -> tuple:
    return (r.get("account"), r.get("symbol"), str(r.get("entry_time"))[:19],
            str(r.get("exit_time"))[:19], float(r.get("qty") or 0),
            float(r.get("entry_price") or 0))


def save(t: pl.DataFrame, locked: bool = True) -> int:
    """Accept: store round trips in the journal (skips rows already there). Returns count."""
    existing = {_key(r) for r in store().all("journal")}
    n = 0
    for rec in to_records(t.sort("entry_time")):
        if _key(rec) in existing:
            continue
        rec.pop("trade_id", None)
        rec["locked"] = locked
        store().add("journal", rec, tag=primary_tag(rec.get("tags")))
        n += 1
    if n:
        store().audit("journal_import", {"rows": n})
    return n


def trades(market: str | None = None, include_simulated: bool = True) -> pl.DataFrame:
    """The saved journal (trade_id = journal row number), oldest first."""
    rows = sorted(store().all("journal"), key=lambda r: str(r.get("entry_time") or ""))
    t = trades_from_records([{**r, "trade_id": r["id"]} for r in rows])
    if market and t.height:
        t = t.filter(pl.col("market") == market)
    if not include_simulated and t.height:
        t = t.filter(~detectors.simulated_mask())
    return t


def set_tags(trade_id: int, tags: list[str], setup: str | None = None,
             stop_distance: float | None = None) -> None:
    """Edit one saved journal row's tags (and optionally setup or planned stop)."""
    row = store().get("journal", trade_id)
    if row is None:
        raise KeyError(f"No journal row {trade_id}")
    body = {k: v for k, v in row.items() if k not in ("id", "created", "tag")}
    body["tags"] = list(tags)
    if setup is not None:
        body["setup"] = setup
    if stop_distance is not None:
        body["stop_distance"] = float(stop_distance)
        risk = float(stop_distance) * float(body.get("qty") or 0) * float(
            body.get("multiplier") or 1)
        body["risk"] = round(risk, 2)
        body["r_multiple"] = round(float(body.get("gross") or 0) / risk, 2) if risk else None
    store().update("journal", trade_id, body, tag=primary_tag(tags))


def detect(t: pl.DataFrame, card: RuleCard | None = None) -> DetectorReport:
    """Run the six detectors on round trips (BLOCKED rows are counted, not traded)."""
    return detectors.run(t, card)
