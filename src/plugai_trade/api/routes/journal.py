"""API routes: journal (Trades, Weekly Review, Ask My Journal) and tax (Tax Export).

Thin: every number comes from ``plugai_trade.journal`` and ``plugai_trade.tax``. Journal and
tax data are personal, so every AI call here passes ``sensitive=True`` (local model only).
Files arrive as base64 inside JSON, so no multipart dependency is needed.

Per-market working state (an import waiting for Accept, a loaded lesson sample, the Ask My
Journal chat, the Tax Export rows) lives in this process, like the classic page's session.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date
from typing import Any

import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import ai, journal, reference, tax
from ...journal import importers
from ...journal import review as rv
from ...journal.detectors import RuleCard, enrich, n_label, simulated_mask
from ...journal.query import EXAMPLES
from ...journal.schema import SIMULATED, TAGS, empty_trades
from ...store import default as store
from ...tax import india, rates, us
from .. import clean as _clean

router = APIRouter()

LESSON_SAMPLE = {"IN": "kavita", "US": "marcus"}
TAX_SAMPLES = {"IN": ("meera", "farhan"), "US": ("dan",)}

# ------------------------------------------------------------------ working state
_pending: dict[str, journal.ImportResult] = {}
_samples: dict[str, pl.DataFrame] = {}
_replay: dict[str, dict[str, Any]] = {}
_handoff: dict[str, dict[str, Any]] = {}
_history: dict[str, list[journal.Answer]] = {}
_tax: dict[str, dict[str, Any]] = {}
_latest: dict[str, str] = {}


def reset_state() -> None:
    """Forget every working copy (tests; a fresh lab folder)."""
    for d in (_pending, _samples, _replay, _handoff, _history, _tax, _latest):
        d.clear()


def _mkt(market: str) -> str:
    if market not in ("IN", "US"):
        raise HTTPException(400, "market must be IN or US")
    return market


def _cur(market: str) -> str:
    return "₹" if market == "IN" else "$"


def _decode(b64: str | None, what: str = "file") -> bytes:
    if not b64:
        raise HTTPException(400, f"Choose a {what} first.")
    try:
        return base64.b64decode(b64.split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, f"That {what} could not be read. Upload the CSV again.") from exc


def _rows(df: pl.DataFrame | None, cols: list[str] | tuple[str, ...] | None = None) -> list[dict]:
    if df is None or df.is_empty():
        return []
    if cols:
        df = df.select([c for c in cols if c in df.columns])
    return _clean(df.to_dicts())


def _card() -> RuleCard:
    return RuleCard.from_store()


def _frame(market: str) -> tuple[pl.DataFrame, str, str]:
    """(trades, label, kind) — saved journal rows, else a loaded lesson sample."""
    saved = journal.trades(market=market)
    if saved.height:
        return saved, "your journal", "journal"
    if market in _samples:
        name = LESSON_SAMPLE[market].title()
        return _samples[market], f"lesson 14 sample, {name}, synthetic", "sample"
    return saved, "", "empty"


def _sum(df: pl.DataFrame, col: str) -> float:
    return float(df[col].sum() or 0) if df.height else 0.0


# ------------------------------------------------------------------ explain (local only)
class ExplainIn(BaseModel):
    facts: list[str]
    question: str | None = None
    section: str = "Journal"
    second_of: str | None = None     # text of a previous answer: ask for a second opinion


@router.post("/api/journal/explain")
def journal_explain(body: ExplainIn) -> dict[str, Any]:
    """Explain / Generate review / Second opinion, always on the local model."""
    section = body.section if body.section in ("Journal", "Tax") else "Journal"

    class _F:
        def facts(self_inner):
            return body.facts

    question = body.question
    if body.second_of is not None:
        question = ("Assume this answer is wrong and find the error. Check every claim against "
                    f"the facts; list any claim not supported by a fact, any arithmetic, and any "
                    f"advice-like wording:\n{body.second_of}")
    out = ai.explain(_F(), question, section=section, sensitive=True)
    return {"text": out.text, "sources": out.sources, "model": out.model, "where": out.where,
            "blocked": out.blocked}


# ------------------------------------------------------------------ meta
@router.get("/api/journal/meta")
def journal_meta(market: str = "IN") -> dict[str, Any]:
    m = _mkt(market)
    brokers = journal.INDIA_BROKERS if m == "IN" else journal.US_BROKERS
    t, label, kind = _frame(m)
    return {"market": m, "brokers": [*brokers, "Generic CSV"],
            "generic_fields": list(importers.GENERIC_FIELDS),
            "generic_required": list(importers.GENERIC_REQUIRED), "tags": list(TAGS),
            "simulated_tags": list(SIMULATED), "examples": list(EXAMPLES),
            "sample": LESSON_SAMPLE[m].title(), "as_of": reference.as_of(),
            "rule_card": _card().version, "label": label, "kind": kind, "rows": t.height}


@router.get("/api/journal/template")
def journal_template() -> dict[str, str]:
    return {"filename": "plugai_generic_tradebook.csv", "csv": importers.generic_template()}


class FileIn(BaseModel):
    file_b64: str


@router.post("/api/journal/columns")
def journal_columns(body: FileIn) -> dict[str, Any]:
    """Header of an uploaded CSV, for the Generic CSV column mapper."""
    try:
        rows, _ = importers.read_rows(_decode(body.file_b64))
    except importers.ImportError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    if not rows:
        raise HTTPException(400, "The file has a header but no rows. Export the tradebook again.")
    header = list(rows[0].keys())
    guess = {f: (f if f in header else "") for f in importers.GENERIC_FIELDS}
    return {"columns": header, "guess": guess}


@router.post("/api/journal/sample")
def journal_sample(market: str = "IN") -> dict[str, Any]:
    """Load lesson 14 sample: the Chapter 14 synthetic journal, kept out of the store."""
    m = _mkt(market)
    _samples[m] = journal.sample(LESSON_SAMPLE[m])
    return journal_meta(m)


# ------------------------------------------------------------------ Trades: import
class ImportIn(BaseModel):
    market: str = "IN"
    broker: str
    account: str = "Main"
    file_b64: str
    mapping: dict[str, str] | None = None
    paper: bool = False


PENDING_COLS = ("trade_id", "date", "symbol", "side", "qty", "entry_price", "exit_price", "gross",
                "charges", "charges_source", "stop_distance", "r_multiple", "setup", "tags",
                "source")


def _pending_state(m: str) -> dict[str, Any] | None:
    res = _pending.get(m)
    if res is None:
        return None
    t = res.trades
    gross, charges = _sum(t, "gross"), _sum(t, "charges")
    return _clean({
        "broker": res.broker, "fills": res.fills, "round_trips": t.height,
        "unpaired": res.unpaired.height, "gross": gross, "charges": charges,
        "net": gross - charges, "unmatched_plans": list(res.unmatched_plans),
        "rows": _rows(t, PENDING_COLS), "facts": res.facts(), "as_of": reference.as_of(),
    })


@router.post("/api/journal/import")
def journal_import(body: ImportIn) -> dict[str, Any]:
    """Import tradebook: pair fills into round trips, price charges. Nothing saved yet."""
    m = _mkt(body.market)
    data = _decode(body.file_b64)
    mapping = body.mapping if body.broker == "Generic CSV" else None
    try:
        res = journal.import_tradebook(data, body.broker, body.account or "Main", mapping, m,
                                       tags=["PAPER"] if body.paper else None)
    except importers.ImportError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, f"This file does not look like a {body.broker} tradebook "
                                 f"({exc}). Pick the right broker, or Generic CSV.") from exc
    _pending[m] = res
    return {"pending": _pending_state(m)}


@router.get("/api/journal/pending")
def journal_pending(market: str = "IN") -> dict[str, Any]:
    return {"pending": _pending_state(_mkt(market))}


@router.post("/api/journal/pending/match")
def journal_match(market: str = "IN") -> dict[str, Any]:
    """Match plans: link each round trip to the trade plan saved before it."""
    m = _mkt(market)
    res = _pending.get(m)
    if res is None:
        raise HTTPException(400, "Nothing to match. Import a tradebook first.")
    res.trades, res.unmatched_plans = journal.match_plans(res.trades)
    return {"pending": _pending_state(m)}


class RowEdit(BaseModel):
    trade_id: int
    stop_distance: float | None = None
    setup: str | None = None
    tags: list[str] = Field(default_factory=list)


class EditsIn(BaseModel):
    market: str = "IN"
    edits: list[RowEdit] = Field(default_factory=list)


def _apply_edits(t: pl.DataFrame, edits: list[RowEdit]) -> pl.DataFrame:
    """The classic page's edit step: typed stops, setups and tags, then R recomputed."""
    if not edits:
        return journal.with_r(t)
    by = {e.trade_id: e for e in edits}
    ids = [i for i in t["trade_id"].to_list() if i in by]
    upd = pl.DataFrame({
        "trade_id": ids,
        "_stop": [by[i].stop_distance for i in ids],
        "_setup": [(by[i].setup or None) for i in ids],
        "_tags": [[x.strip() for x in by[i].tags if x.strip()] for i in ids],
    }, schema={"trade_id": pl.Int64, "_stop": pl.Float64, "_setup": pl.Utf8,
               "_tags": pl.List(pl.Utf8)})
    out = t.join(upd, on="trade_id", how="left").with_columns(
        stop_distance=pl.when(pl.col("trade_id").is_in(ids)).then(pl.col("_stop"))
        .otherwise(pl.col("stop_distance")),
        setup=pl.when(pl.col("trade_id").is_in(ids)).then(pl.col("_setup"))
        .otherwise(pl.col("setup")),
        tags=pl.when(pl.col("trade_id").is_in(ids)).then(pl.col("_tags"))
        .otherwise(pl.col("tags")),
    ).drop("_stop", "_setup", "_tags")
    return journal.with_r(out)


@router.post("/api/journal/pending/preview")
def journal_preview(body: EditsIn) -> dict[str, Any]:
    """Apply typed stops / setups / tags to the pending import (R recomputed), not saved."""
    m = _mkt(body.market)
    res = _pending.get(m)
    if res is None:
        raise HTTPException(400, "Nothing to update. Import a tradebook first.")
    res.trades = _apply_edits(res.trades, body.edits)
    res.unmatched_plans = [i for i in res.unmatched_plans
                           if i not in {e.trade_id for e in body.edits if e.stop_distance}]
    return {"pending": _pending_state(m)}


@router.post("/api/journal/pending/accept")
def journal_accept(body: EditsIn) -> dict[str, Any]:
    """Accept: lock the round trips into the journal."""
    m = _mkt(body.market)
    res = _pending.get(m)
    if res is None:
        raise HTTPException(400, "Nothing to accept. Import a tradebook first.")
    n = journal.save(_apply_edits(res.trades, body.edits))
    _pending.pop(m, None)
    return {"saved": n}


@router.post("/api/journal/pending/discard")
def journal_discard(market: str = "IN") -> dict[str, Any]:
    _pending.pop(_mkt(market), None)
    return {"pending": None}


# ------------------------------------------------------------------ Trades: journal
JOURNAL_COLS = ("trade_id", "date", "entry_time", "exit_time", "symbol", "side", "qty",
                "entry_price", "exit_price", "gross", "charges", "net", "stop_distance",
                "r_multiple", "setup", "tags", "account", "charges_source")


def _view(t: pl.DataFrame, show_simulated: bool, tag: str | None) -> pl.DataFrame:
    if t.is_empty():
        return t
    view = t if show_simulated else t.filter(~simulated_mask())
    if tag and tag != "All":
        if tag == "REAL":
            view = view.filter(~pl.any_horizontal(
                [pl.col("tags").list.contains(x) for x in ("PAPER", "REPLAY", "PILOT", "BLOCKED")])
                .fill_null(False))
        else:
            view = view.filter(pl.col("tags").list.contains(tag).fill_null(False))
    return view


@router.get("/api/journal/trades")
def journal_trades(market: str = "IN", show_simulated: bool = True,
                   tag: str | None = None) -> dict[str, Any]:
    m = _mkt(market)
    t, label, kind = _frame(m)
    if t.is_empty():
        return {"kind": "empty", "label": "", "rows": [], "sample": LESSON_SAMPLE[m].title()}
    view = _view(t, show_simulated, tag)
    gross, charges = _sum(view, "gross"), _sum(view, "charges")
    rep = journal.detect(view, _card()) if view.height else None
    return _clean({
        "kind": kind, "label": label, "saved": kind == "journal",
        "round_trips": view.height, "gross": gross, "charges": charges, "net": gross - charges,
        "total_r": round(_sum(view, "r_multiple"), 2),
        "rows": _rows(view, JOURNAL_COLS),
        "histogram": _rows(rep.histogram) if rep else [],
        "beyond_stop": rep.beyond_stop.text() if rep else "",
        "avg_winner_r": rep.avg_winner_r if rep else None,
        "sessions": sorted(set(view["date"].to_list()), reverse=True) if view.height else [],
        "facts": rep.facts() if rep else [],
        "sample": LESSON_SAMPLE[m].title(),
    })


@router.post("/api/journal/tags")
def journal_tags(body: EditsIn) -> dict[str, Any]:
    """Save tags (setup, mistake, market mood, PAPER / PILOT) on saved journal rows."""
    m = _mkt(body.market)
    _, _, kind = _frame(m)
    if kind != "journal":
        raise HTTPException(400, "Tags are saved on your own journal. Import and Accept a "
                                 "tradebook first; the lesson sample is read-only.")
    for e in body.edits:
        try:
            journal.set_tags(e.trade_id, [x.strip() for x in e.tags if x.strip()],
                             e.setup, e.stop_distance)
        except KeyError as exc:
            raise HTTPException(400, f"No journal row {e.trade_id}.") from exc
    return {"saved": len(body.edits)}


class AddTagIn(BaseModel):
    market: str = "IN"
    rows: list[int]
    tag: str


@router.post("/api/journal/tags/add")
def journal_add_tag(body: AddTagIn) -> dict[str, Any]:
    """Add one tag (a mistake tag from the Weekly Review) to several saved rows."""
    m = _mkt(body.market)
    t, _, kind = _frame(m)
    tag = body.tag.strip()
    if not tag:
        raise HTTPException(400, "Type a tag first.")
    if kind != "journal":
        raise HTTPException(400, "Tags are saved on your own journal; the lesson sample is "
                                 "read-only.")
    tags = {r["trade_id"]: list(r["tags"] or []) for r in t.iter_rows(named=True)}
    n = 0
    for rid in body.rows:
        if rid in tags and tag not in tags[rid]:
            journal.set_tags(rid, [*tags[rid], tag])
            n += 1
    return {"tagged": n}


# ------------------------------------------------------------------ Trades: replay
class ReplayIn(BaseModel):
    market: str = "IN"
    day: str
    show_simulated: bool = True
    tag: str | None = None


REPLAY_COLS = ("trade_id", "entry_time", "exit_time", "side", "symbol", "qty", "entry_price",
               "exit_price", "r", "hold_minutes", "gap_minutes", "gross", "charges",
               "rules_broken", "tags")


def _replay_state(m: str) -> dict[str, Any] | None:
    d = _replay.get(m)
    if d is None:
        return None
    rep = d["rep"]
    return _clean({"day": rep.day, "blocked": rep.blocked, "rows": _rows(rep.trades, REPLAY_COLS),
                   "facts": rep.facts(), "handoff": _handoff.get(m), "note": d.get("note", ""),
                   "question": "Review this session from the numbers only; cite rows; end with "
                               "one question."})


@router.post("/api/journal/replay")
def journal_replay(body: ReplayIn) -> dict[str, Any]:
    """Replay: one session with its fills, handed to the Paper Desk in Replay mode at 5×."""
    m = _mkt(body.market)
    t, _, _ = _frame(m)
    view = _view(t, body.show_simulated, body.tag)
    if view.is_empty() or body.day not in set(view["date"].to_list()):
        raise HTTPException(400, f"No trades on {body.day} in this view. Pick a listed session.")
    rep = journal.replay.session(view, body.day, _card())
    _replay[m] = {"rep": rep}
    _handoff[m] = rep.handoff(speed=5)
    return {"replay": _replay_state(m)}


@router.get("/api/journal/replay")
def journal_replay_get(market: str = "IN") -> dict[str, Any]:
    return {"replay": _replay_state(_mkt(market))}


@router.get("/api/journal/replay/handoff")
def journal_handoff(market: str = "IN") -> dict[str, Any]:
    """What the Paper Desk reads to open the session in Replay mode (tag REPLAY)."""
    return {"handoff": _clean(_handoff.get(_mkt(market)))}


class NoteIn(BaseModel):
    market: str = "IN"
    day: str
    note: str


@router.post("/api/journal/replay/note")
def journal_replay_note(body: NoteIn) -> dict[str, Any]:
    """Notes: one sentence on what you will do differently (a Rule Card change to consider)."""
    m = _mkt(body.market)
    if not body.note.strip():
        raise HTTPException(400, "Write one sentence first.")
    rid = store().add("reviews", {"day": body.day, "market": m, "note": body.note.strip()},
                      tag="session")
    if m in _replay:
        _replay[m]["note"] = body.note.strip()
    return {"id": rid}


# ------------------------------------------------------------------ Weekly Review
def _account_filter(t: pl.DataFrame, choice: str) -> pl.DataFrame:
    if t.is_empty():
        return t
    sim = simulated_mask()
    if choice == "Real":
        return t.filter(~sim)
    if choice == "Paper":
        return t.filter(sim)
    return t


def _weekly(m: str, week_of: str | None, account: str) -> tuple[rv.WeeklyReview | None,
                                                                pl.DataFrame, str, str]:
    t, label, kind = _frame(m)
    if t.is_empty():
        return None, t, label, kind
    week_of = week_of or str(t["date"].max())
    _latest[m] = str(t["date"].max())
    try:
        date.fromisoformat(week_of)
    except ValueError as exc:
        raise HTTPException(400, "Week of must be a date like 2026-09-07.") from exc
    t = _account_filter(t, account)
    r = rv.build(t, week_of, _card(), rv.pinned_specs())
    return r, t, label, kind


BREAK_COLS = ("trade_id", "entry_time", "exit_time", "side", "r", "gap_minutes", "rules_broken")


@router.get("/api/journal/weekly")
def journal_weekly(market: str = "IN", week_of: str | None = None,
                   account: str = "Both") -> dict[str, Any]:
    m = _mkt(market)
    r, t, label, kind = _weekly(m, week_of, account)
    if r is None:
        return {"kind": "empty", "sample": LESSON_SAMPLE[m].title()}
    e = enrich(t, r.card)
    ids = set(e["trade_id"].to_list()) if e.height else set()

    def detail(rows: list[int]) -> list[dict]:
        out = []
        for row in rows:
            pick = [row - 1, row] if row - 1 in ids else [row]
            out.append({"row": row, "rows": _rows(e.filter(pl.col("trade_id").is_in(pick)),
                                                  BREAK_COLS)})
        return out

    w = e.filter(pl.col("date").is_between(pl.lit(r.start), pl.lit(r.end))) if e.height else e
    return _clean({
        "kind": kind, "label": label, "saved": kind == "journal", "start": r.start, "end": r.end,
        "latest": _latest.get(m),
        "account": account, "rule_card": r.card.version, "last_decision": r.last_decision,
        "tiles": r.tiles(), "this": r.this.__dict__, "last": r.last.__dict__,
        "rule_breaks": [{"label": f.label, "n": f.n, "rows": f.rows, "total_r": f.total_r,
                         "query": f.query, "n_label": n_label(f.n), "detail": detail(f.rows)}
                        for f in r.rule_breaks],
        "patterns": [{"label": f.label, "n": f.n, "rows": f.rows, "total_r": f.total_r,
                      "query": f.query, "n_label": n_label(f.n),
                      "too_few": f.n < journal.MIN_N} for f in r.patterns],
        "bars": _rows(w, ("trade_id", "r", "broke_rule")),
        "pinned": [{"label": a.spec.label, "text": a.text, "rows": a.rows} for a in r.pinned],
        "queries": r.queries, "facts": r.facts(), "question": rv.REVIEW_QUESTION,
        "currency": _cur(m),
    })


class WeekIn(BaseModel):
    market: str = "IN"
    week_of: str | None = None
    account: str = "Both"


@router.post("/api/journal/weekly/generate")
def journal_weekly_generate(body: WeekIn) -> dict[str, Any]:
    """Generate review: the local model narrates the computed facts."""
    r, _, _, _ = _weekly(_mkt(body.market), body.week_of, body.account)
    if r is None:
        raise HTTPException(400, "No journal rows yet. Import a tradebook or load the sample.")
    out = rv.generate(r)
    return {"text": out.text, "sources": out.sources, "model": out.model, "where": out.where,
            "blocked": out.blocked}


class ChangeIn(WeekIn):
    change: str


@router.post("/api/journal/weekly/accept")
def journal_weekly_accept(body: ChangeIn) -> dict[str, Any]:
    """Accept: the one change becomes the Rule Card's next version, dated."""
    change = body.change.strip()
    if not change:
        raise HTTPException(400, "Type one change for next week first.")
    r, _, _, _ = _weekly(_mkt(body.market), body.week_of, body.account)
    week = r.start if r else date.today().isoformat()
    rows = store().all("rule_cards", limit=1)
    card = {k: v for k, v in (rows[0] if rows else {}).items() if k not in ("id", "created", "tag")}
    key = next((k for k in ("rules", "lines", "written_rules") if isinstance(card.get(k), list)),
               "lines")
    lines = list(card.get(key, []))
    lines.append(change if all(isinstance(x, str) for x in lines)
                 else {"text": change, "date": date.today().isoformat()})
    card[key] = lines
    v = card.get("version")
    card["version"] = v + 1 if isinstance(v, int) else (len(store().all("rule_cards")) + 1)
    card.update({"changed_on": date.today().isoformat(), "change_source": f"Weekly Review {week}"})
    store().add("rule_cards", card)
    return {"version": card["version"], "change": change, "changed_on": card["changed_on"]}


class SaveReviewIn(WeekIn):
    narration: str = ""
    decision: str = ""


@router.post("/api/journal/weekly/save")
def journal_weekly_save(body: SaveReviewIn) -> dict[str, Any]:
    """Save review: tiles, narration and decision stored together."""
    r, _, _, _ = _weekly(_mkt(body.market), body.week_of, body.account)
    if r is None:
        raise HTTPException(400, "No journal rows yet. Import a tradebook or load the sample.")
    return {"id": rv.save(r, body.narration, body.decision.strip()), "start": r.start}


# ------------------------------------------------------------------ Ask My Journal
def _answer(i: int, a: journal.Answer) -> dict[str, Any]:
    return _clean({"i": i, "question": a.question, "label": a.spec.label, "via": a.via,
                   "text": a.text, "table": _rows(a.table), "rows": a.rows,
                   "sql": a.sql + ";\n\n-- rows\n" + a.spec.rows_sql() + ";"
                   if a.via != "none" else "",
                   "facts": a.facts() if a.via != "none" else []})


@router.get("/api/journal/ask")
def journal_ask_history(market: str = "IN") -> dict[str, Any]:
    m = _mkt(market)
    return {"history": [_answer(i, a) for i, a in enumerate(_history.get(m, []))]}


class AskIn(BaseModel):
    market: str = "IN"
    question: str


@router.post("/api/journal/ask")
def journal_ask(body: AskIn) -> dict[str, Any]:
    """A question → the query the lab ran → the answer and its rows (follow-ups chain)."""
    m = _mkt(body.market)
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "Type a question about your journal.")
    t, _, _ = _frame(m)
    if t.is_empty():
        raise HTTPException(400, "No journal rows yet. Import a tradebook in Journal › Trades, "
                                 "or load the lesson sample.")
    hist = _history.setdefault(m, [])
    prev = hist[-1].spec if hist and hist[-1].via != "none" else None
    hist.append(journal.ask(q, t, previous=prev, card=_card()))
    return journal_ask_history(m)


class PinIn(BaseModel):
    market: str = "IN"
    index: int


@router.post("/api/journal/ask/pin")
def journal_ask_pin(body: PinIn) -> dict[str, Any]:
    """Accept: pin this question so it runs every week in the Weekly Review."""
    hist = _history.get(_mkt(body.market), [])
    if not 0 <= body.index < len(hist) or hist[body.index].via == "none":
        raise HTTPException(400, "Pick an answered question to pin.")
    return {"id": rv.pin(hist[body.index])}


@router.post("/api/journal/ask/clear")
def journal_ask_clear(market: str = "IN") -> dict[str, Any]:
    _history.pop(_mkt(market), None)
    return {"history": []}


# ================================================================== Tax Export
def _tx(m: str) -> dict[str, Any]:
    return _tax.setdefault(m, {"rows": None})


def _tax_rows(m: str) -> pl.DataFrame:
    rows = _tx(m)["rows"]
    return rows if rows is not None else empty_trades()


def _tax_append(m: str, new: pl.DataFrame) -> None:
    """Add rows (renumbered after the existing ones); cached results are cleared."""
    st = _tx(m)
    old = st.get("rows")
    for k in ("classified", "wash", "itr", "8949", "rec", "tds_rec"):
        st.pop(k, None)
    if old is None or old.is_empty():
        st["rows"] = new
    elif new.height:
        st["rows"] = pl.concat([old, new.with_columns(
            trade_id=pl.col("trade_id") + old["trade_id"].max())])


def _rec(rec) -> dict[str, Any]:
    return _clean({"matched": rec.matched.height, "mismatches": _rows(rec.mismatches),
                   "matched_rows": _rows(rec.matched), "facts": rec.facts(),
                   "left": rec.left_name, "right": rec.right_name})


@router.get("/api/tax/state")
def tax_state(market: str = "IN") -> dict[str, Any]:
    m = _mkt(market)
    t = _tax_rows(m)
    st = _tx(m)
    brokers = journal.INDIA_BROKERS if m == "IN" else journal.US_BROKERS
    c = st.get("classified")
    return _clean({
        "market": m, "rows": t.height, "draft": tax.DRAFT, "as_of": rates.as_of(),
        "reference_as_of": reference.as_of(), "brokers": [*brokers, "Generic CSV"],
        "samples": [s.title() for s in TAX_SAMPLES[m]],
        "account_default": "Main" if m == "IN" else "Taxable",
        "preview": _rows(t.head(200), ("trade_id", "date", "symbol", "instrument", "side", "qty",
                                       "gross", "charges", "net", "account", "tags")),
        "classified": c is not None,
        "fys": sorted(set(c.rows["fy"].drop_nulls().to_list())) if c is not None and c.rows.height
        else [],
        "accounts": us.account_types(), "account_types": list(us.ACCOUNT_TYPES),
        "crypto_default": bool(rates.us().get("wash_sale_covers_crypto", False)),
        "loss_buckets": list(india.LOSS_BUCKETS),
        "account_names": sorted(set(t["account"].drop_nulls().to_list())) if t.height else [],
    })


class TaxImportIn(BaseModel):
    market: str = "IN"
    broker: str
    account: str = "Main"
    file_b64: str
    mapping: dict[str, str] | None = None


@router.post("/api/tax/import")
def tax_import(body: TaxImportIn) -> dict[str, Any]:
    m = _mkt(body.market)
    try:
        res = journal.import_tradebook(_decode(body.file_b64), body.broker, body.account,
                                       body.mapping if body.broker == "Generic CSV" else None,
                                       market=m)
    except importers.ImportError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, f"This file does not look like a {body.broker} export ({exc}). "
                                 "Pick the right broker or exchange, or Generic CSV.") from exc
    _tax_append(m, res.trades)
    return {"added": res.trades.height, "broker": res.broker, "state": tax_state(m)}


@router.post("/api/tax/use-journal")
def tax_use_journal(market: str = "IN") -> dict[str, Any]:
    """Use Journal › Trades rows (real rows only)."""
    m = _mkt(market)
    _tx(m)["rows"] = None
    _tax_append(m, journal.trades(market=m, include_simulated=False))
    return tax_state(m)


class TaxSampleIn(BaseModel):
    market: str = "IN"
    name: str


@router.post("/api/tax/sample")
def tax_sample(body: TaxSampleIn) -> dict[str, Any]:
    m = _mkt(body.market)
    name = body.name.lower()
    if name not in TAX_SAMPLES[m]:
        raise HTTPException(400, f"No lesson sample called {body.name} for this market.")
    _tax_append(m, journal.sample(name))
    return tax_state(m)


@router.post("/api/tax/clear")
def tax_clear(market: str = "IN") -> dict[str, Any]:
    _tax.pop(_mkt(market), None)
    return tax_state(market)


# ------------------------------------------------------------------ India
BUCKETS = (india.SPECULATIVE, india.NON_SPECULATIVE, india.STCG, india.LTCG, india.VDA,
           india.ASK_CA)


def _classified(m: str) -> india.Classified:
    c = _tx(m).get("classified")
    if c is None:
        raise HTTPException(400, "Click Classify first.")
    return c


def _classify_payload(m: str, c: india.Classified) -> dict[str, Any]:
    counts = c.counts()
    v = india.vda_ledger(c)
    return _clean({
        "counts": [{"bucket": b, "name": india.BUCKET_NAMES[b].split(" (")[0],
                    "full": india.BUCKET_NAMES[b], "n": counts.get(b, 0)} for b in BUCKETS],
        "rows": _rows(c.rows, ("trade_id", "fy", "symbol", "side", "gross", "bucket", "rule",
                               "section_old", "section_new", "ask_ca")),
        "excluded_simulated": c.excluded_simulated, "facts": c.facts(),
        "section_map": _rows(india.section_map()),
        "vda": None if v.rows.is_empty() else {
            "gains": v.gains, "losses": v.losses, "tds": v.tds, "rows": _rows(v.rows),
            "facts": v.facts()},
        "tds_rec": _rec(_tx(m)["tds_rec"]) if _tx(m).get("tds_rec") is not None else None,
        "fys": sorted(set(c.rows["fy"].drop_nulls().to_list())) if c.rows.height else [],
    })


@router.post("/api/tax/in/classify")
def tax_classify(market: str = "IN") -> dict[str, Any]:
    """Classify: each round trip gets a bucket and the rule that put it there."""
    m = _mkt(market)
    _tx(m)["classified"] = india.classify(_tax_rows(m))
    return _classify_payload(m, _tx(m)["classified"])


@router.get("/api/tax/in/classify")
def tax_classified(market: str = "IN") -> dict[str, Any]:
    m = _mkt(market)
    c = _tx(m).get("classified")
    return {"classified": None if c is None else _classify_payload(m, c)}


@router.get("/api/tax/in/turnover")
def tax_turnover(market: str = "IN", months: int = 12, opted: str = "") -> dict[str, Any]:
    """Turnover calculator (ICAI), audit check, presumptive note, carry-forward ledger."""
    m = _mkt(market)
    if not 1 <= months <= 12:
        raise HTTPException(400, "Months must be between 1 and 12.")
    opted = opted.strip()
    if opted and not (len(opted) >= 4 and opted[:4].isdigit()):
        raise HTTPException(400, "Type the year you opted in like 2024-25, or leave it empty.")
    c = _classified(m)
    t = india.turnover(c)
    annual = t.fo["turnover"] * 12 / months + t.speculative["turnover"] * 12 / months
    audit = india.audit_check(annual, presumptive_opted_fy=opted or None,
                              declared_profit=t.fo["net"], deemed_profit=t.deemed_profit)
    ledger = india.CarryForwardLedger.load()
    return _clean({
        "fo": t.fo, "speculative": t.speculative, "per_contract_fo": t.per_contract_fo,
        "old_method_fo": t.old_method_fo, "notional_fo": t.notional_fo,
        "deemed_profit": t.deemed_profit, "presumptive_rate": t.presumptive_rate,
        "annualised": annual,
        "audit": {"status": audit.status, "detail": audit.detail, "lock_in": audit.lock_in,
                  "lock_short": audit.lock_in.split(":")[0], "facts": audit.facts()},
        "carry_forward": round(sum(e.left for e in ledger.entries), 2),
        "presumptive_note": india.presumptive_note(t),
        "threshold_source": rates.source("india.tax.audit_threshold_inr"),
        "as_of": rates.as_of(),
        "per_trade": _rows(t.per_trade), "facts": t.facts() + audit.facts(),
        "ledger": {"rows": _rows(ledger.rows()), "facts": ledger.facts()},
        "suggested_losses": [{"fy": fy, "bucket": b, "amount": a}
                             for fy, b, a in india.losses_from(c)],
    })


class LossIn(BaseModel):
    fy: str
    bucket: str
    amount: float
    on_time: bool = True


@router.post("/api/tax/in/ledger/add")
def tax_ledger_add(body: LossIn) -> dict[str, Any]:
    """Add loss: one line per year per bucket."""
    if body.amount <= 0:
        raise HTTPException(400, "Type the loss as a positive amount in ₹.")
    ledger = india.CarryForwardLedger.load()
    try:
        ledger.add(body.fy.strip(), body.bucket, body.amount, body.on_time)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    ledger.save()
    return _clean({"rows": _rows(ledger.rows()), "facts": ledger.facts()})


@router.post("/api/tax/in/ledger/from-classified")
def tax_ledger_from(market: str = "IN") -> dict[str, Any]:
    """Add this year's losses from the classified rows."""
    c = _classified(_mkt(market))
    ledger = india.CarryForwardLedger.load()
    added = india.losses_from(c)
    for fy, b, amt in added:
        ledger.add(fy, b, amt)
    ledger.save()
    return _clean({"added": len(added), "rows": _rows(ledger.rows()), "facts": ledger.facts()})


@router.get("/api/tax/in/advance")
def tax_advance(estimated: float = 60000.0, fy: str = "2026-27", paid: float = 0.0
                ) -> dict[str, Any]:
    """Advance-tax planner: instalments from the dated schedule."""
    if estimated < 0 or paid < 0:
        raise HTTPException(400, "Amounts cannot be negative.")
    if not (len(fy) >= 4 and fy[:4].isdigit()):
        raise HTTPException(400, "Type the tax year like 2026-27.")
    plan = india.advance_tax(estimated, fy, paid)
    return _clean({"rows": _rows(plan.rows), "due": plan.due, "facts": plan.facts()})


class TdsIn(BaseModel):
    market: str = "IN"
    file_b64: str


@router.post("/api/tax/in/reconcile-tds")
def tax_reconcile_tds(body: TdsIn) -> dict[str, Any]:
    """Reconcile TDS: VDA ledger vs Form 26AS / AIS TDS rows."""
    m = _mkt(body.market)
    v = india.vda_ledger(_classified(m))
    if v.rows.is_empty():
        raise HTTPException(400, "No VDA rows to reconcile. Import an exchange trade history.")
    try:
        rec = india.reconcile_tds(v, _decode(body.file_b64, "Form 26AS / AIS file"))
    except (KeyError, ValueError, pl.exceptions.PolarsError) as exc:
        raise HTTPException(400, f"Could not read that 26AS / AIS file ({exc}).") from exc
    _tx(m)["tds_rec"] = rec
    return _rec(rec)


class AisIn(BaseModel):
    market: str = "IN"
    ais_b64: str
    broker_b64: str | None = None


@router.post("/api/tax/in/reconcile-ais")
def tax_reconcile_ais(body: AisIn) -> dict[str, Any]:
    """Reconcile AIS: broker tax P&L (or the classified rows) vs the AIS / 26AS export."""
    m = _mkt(body.market)
    if body.broker_b64:
        left: Any = _decode(body.broker_b64, "broker tax P&L")
    else:
        left = india.broker_rows(_classified(m))
    try:
        rec = india.reconcile_ais(left, _decode(body.ais_b64, "AIS file"))
    except (KeyError, ValueError, pl.exceptions.PolarsError) as exc:
        raise HTTPException(400, f"Could not read that AIS / 26AS file ({exc}).") from exc
    _tx(m)["rec"] = rec
    return _rec(rec)


class ExportIn(BaseModel):
    market: str = "IN"
    fy: str = "all"


@router.post("/api/tax/in/export")
def tax_export_in(body: ExportIn) -> dict[str, Any]:
    """Export: ITR-shaped CSV, stamped Draft for your CA / CPA."""
    m = _mkt(body.market)
    c = _classified(m)
    data = india.export_itr_csv(c, None if body.fy == "all" else body.fy)
    _tx(m)["itr"] = data
    return {"csv": data, "filename": "plugai_itr_draft.csv", "format": "ITR-shaped CSV"}


# ------------------------------------------------------------------ US
class AccountIn(BaseModel):
    name: str
    kind: str


@router.post("/api/tax/us/account")
def tax_add_account(body: AccountIn) -> dict[str, Any]:
    """Add account: tag an imported account as Taxable, IRA or Spouse."""
    if not body.name.strip():
        raise HTTPException(400, "Type the account name as it appears in the import.")
    try:
        us.add_account(body.name.strip(), body.kind)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    for st in _tax.values():
        st.pop("wash", None)
    return {"accounts": us.account_types()}


@router.get("/api/tax/us/1256")
def tax_1256(market: str = "US") -> dict[str, Any]:
    """1256 tagging: each instrument with its tag and the reason."""
    t = _tax_rows(_mkt(market))
    if t.is_empty():
        return {"rows": []}
    out = [{"instrument": u, "type": i, **dict(zip(("sec_1256", "reason", "ask_ca"),
                                                    us.tag_1256(u, i)))}
           for u, i in sorted(set(zip(t["underlying"].to_list(), t["instrument"].to_list())),
                              key=lambda x: (str(x[0]), str(x[1])))]
    return _clean({"rows": out})


class WashIn(BaseModel):
    market: str = "US"
    crypto: bool | None = None
    pairs: str = ""


def _pairs(text: str) -> list[tuple[str, ...]]:
    return [tuple(p.strip().upper() for p in x.split("/")) for x in text.split(",") if "/" in x]


def _form(m: str) -> us.Form8949 | None:
    st = _tx(m)
    t = _tax_rows(m)
    w = st.get("wash") or (us.wash_sales(t) if t.height else None)
    return us.form_8949(w) if w is not None else None


def _form_payload(f: us.Form8949 | None) -> dict[str, Any] | None:
    if f is None:
        return None
    part = (lambda p: round(float(f.rows.filter(pl.col("part") == p)["gain"].sum() or 0), 2)
            if f.rows.height else 0.0)
    return _clean({"rows": _rows(f.rows), "form_6781": _rows(f.form_6781), "flags": f.flags,
                   "excluded_ira": f.excluded_ira, "facts": f.facts(),
                   "short_total": part("I"), "long_total": part("II"),
                   "net_1256": round(float(f.form_6781["gain"].sum() or 0), 2)
                   if f.form_6781.height else 0.0})


@router.post("/api/tax/us/wash")
def tax_wash(body: WashIn) -> dict[str, Any]:
    """Wash-sale check (and Substantially identical warnings) across all tagged accounts."""
    m = _mkt(body.market)
    t = _tax_rows(m)
    if t.is_empty():
        raise HTTPException(400, "Load rows first: Import tradebook, or a lesson sample.")
    w = us.wash_sales(t, crypto=body.crypto, identical_pairs=_pairs(body.pairs))
    _tx(m)["wash"] = w
    return _clean({"hits": _rows(w.hits), "warnings": _rows(w.warnings),
                   "disallowed": round(float(w.hits["disallowed"].sum() or 0), 2)
                   if w.hits.height else 0.0,
                   "crypto_checked": w.crypto_checked, "facts": w.facts(),
                   "form": _form_payload(_form(m))})


@router.get("/api/tax/us/8949")
def tax_8949(market: str = "US") -> dict[str, Any]:
    return {"form": _form_payload(_form(_mkt(market)))}


@router.post("/api/tax/us/compare-1099b")
def tax_compare_1099b(body: TdsIn) -> dict[str, Any]:
    """Compare with 1099-B: lab 8949 rows vs the broker's form."""
    m = _mkt(body.market)
    f = _form(m)
    if f is None:
        raise HTTPException(400, "Load rows first: Import tradebook, or a lesson sample.")
    try:
        rec = us.compare_1099b(f, _decode(body.file_b64, "1099-B / 1099-DA file"))
    except (KeyError, ValueError, pl.exceptions.PolarsError) as exc:
        raise HTTPException(400, f"Could not read that 1099-B file ({exc}).") from exc
    _tx(m)["rec"] = rec
    return _rec(rec)


@router.post("/api/tax/us/export")
def tax_export_us(market: str = "US") -> dict[str, Any]:
    """Export: 8949-shaped CSV (box letters A–L, code W), stamped Draft for your CA / CPA."""
    m = _mkt(market)
    f = _form(m)
    if f is None:
        raise HTTPException(400, "Load rows first: Import tradebook, or a lesson sample.")
    data = us.export_8949_csv(f)
    _tx(m)["8949"] = data
    return {"csv": data, "filename": "plugai_8949_draft.csv", "format": "8949-shaped CSV"}
