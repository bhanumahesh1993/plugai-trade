"""API routes: Research A — Daily Briefing, Document Desk, Screener, Score-Tester.

Thin: every figure comes from the engine modules the classic pages call
(``plugai_trade.briefing``, ``docdesk``, ``screener``, ``scoretest``).
"""

from __future__ import annotations

import base64
from datetime import date, time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...store import default as store
from .. import clean as _clean

router = APIRouter()

MARKETS = ("IN", "US")


def _mkt(market: str) -> str:
    if market not in MARKETS:
        raise HTTPException(400, "Market must be IN or US.")
    return market


# ================================================================== Daily Briefing
SAMPLE_WATCHLIST = "Sample watchlist"
CHANNELS = ["Dashboard", "Desktop", "Email", "Telegram"]


@router.get("/api/research/briefing/setup")
def briefing_setup(market: str = "IN") -> dict[str, Any]:
    from ... import briefing, config, screener
    _mkt(market)
    saved = [{"name": w["name"], "symbols": w["symbols"], "review_by": w.get("review_by")}
             for w in screener.watchlists(market)]
    return _clean({
        "sample_name": SAMPLE_WATCHLIST,
        "sample": list((config.get("watchlists", {}) or {}).get(market, [])),
        "saved": saved,
        "defaults": briefing.DEFAULTS[market],
        "tz": briefing.TZ_LABEL[market],
        "channels": CHANNELS,
    })


class BriefingIn(BaseModel):
    symbols: list[str]
    market: str = "IN"
    cutoff: str | None = None
    online: bool = False


def _line(ln: Any) -> dict[str, Any]:
    return {"panel": ln.panel, "text": ln.text, "sourced": ln.sourced, "source": ln.source,
            "published": ln.published, "reason": ln.reason}


@router.post("/api/research/briefing/generate")
def briefing_generate(body: BriefingIn) -> dict[str, Any]:
    from ... import briefing
    _mkt(body.market)
    symbols = [s.strip().upper() for s in body.symbols if s.strip()]
    if not symbols:
        raise HTTPException(400, "Add at least one name to the watchlist, then generate again.")
    if body.cutoff:
        try:
            time.fromisoformat(body.cutoff)
        except ValueError as exc:
            raise HTTPException(400, "News cutoff must be a time such as 08:45.") from exc
    b = briefing.generate(symbols, body.market, body.cutoff, online=body.online)
    ok, bad = b.counts()
    panels = ("Watchlist", "Overnight news", "Events today")
    return _clean({
        "market": b.market, "day": b.day, "cutoff": b.cutoff, "edition": b.edition,
        "tz": briefing.TZ_LABEL[b.market], "sources": b.sources, "header": b.header(),
        "panels": {p: [_line(ln) for ln in b.panel(p)] for p in panels},
        "questions": b.questions, "yesterday": b.yesterday,
        "sourced": ok, "unsourced": bad, "dropped": b.dropped, "facts": b.facts(),
    })


class BriefingScheduleIn(BaseModel):
    market: str = "IN"
    run_time: str | None = None
    cutoff: str | None = None
    delivery: list[str] = Field(default_factory=lambda: ["Dashboard"])
    refresh_time: str | None = None


@router.post("/api/research/briefing/schedule")
def briefing_schedule(body: BriefingScheduleIn) -> dict[str, Any]:
    from ... import briefing
    _mkt(body.market)
    bad = [c for c in body.delivery if c not in CHANNELS]
    if bad:
        raise HTTPException(400, f"Unknown delivery channel: {', '.join(bad)}.")
    job = briefing.schedule(body.market, body.run_time, body.cutoff, body.delivery or None,
                            body.refresh_time or None)
    return {"id": job}


@router.get("/api/research/briefing/runs")
def briefing_runs(market: str = "IN") -> dict[str, Any]:
    from ... import briefing
    _mkt(market)
    eds = briefing.editions(market, date.today())  # noqa: DTZ011 (same day key as the engine)
    jobs = store().all("jobs", tag="briefing")
    return _clean({
        "editions": [{"edition": e.get("edition"), "cutoff": e.get("cutoff"),
                      "created": e.get("created")} for e in eds],
        "jobs": [{"market": j.get("market"), "days": j.get("days"), "run_time": j.get("run_time"),
                  "news_cutoff": j.get("news_cutoff"), "refresh_time": j.get("refresh_time"),
                  "delivery": j.get("delivery", []), "tz": j.get("tz")} for j in jobs],
    })


# ================================================================== Document Desk
_docs: dict[str, Any] = {}   # name -> docdesk.Document, the desk's open documents (like the classic session)


def _doc_row(d: Any) -> dict[str, Any]:
    return {"name": d.name, "check": d.text_check(), "market": d.market, "kind": d.kind,
            "pages": d.n_pages, "untrusted": d.kind in ("text", "link"), "source": d.source}


def _desk() -> dict[str, Any]:
    from ... import docdesk
    return {"documents": [_doc_row(d) for d in _docs.values()],
            "samples": list(docdesk.SAMPLES), "templates": list(docdesk.TEMPLATES)}


def _get_doc(name: str) -> Any:
    if name not in _docs:
        raise HTTPException(400, f"“{name}” is not on the desk. Load it first.")
    return _docs[name]


def _add_doc(doc: Any) -> dict[str, Any]:
    _docs.pop(doc.name, None)
    _docs[doc.name] = doc
    return {**_desk(), "added": doc.name}


@router.get("/api/research/documents")
def documents() -> dict[str, Any]:
    return _desk()


class UploadIn(BaseModel):
    name: str
    data_b64: str
    market: str = "IN"


def _load_bytes(raw: bytes, name: str, market: str) -> Any:
    from ... import docdesk
    try:
        if name.lower().endswith(".pdf"):
            return docdesk.load_pdf(raw, name=name[:-4], market=market)
        if name.lower().endswith((".txt", ".md")):
            return docdesk.load_text(raw.decode(errors="replace"), name, market)
    except docdesk.DocError as exc:
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(400, "Drop a PDF, .txt or .md file. Other formats cannot be read.")


@router.post("/api/research/documents/upload")
def documents_upload(body: UploadIn) -> dict[str, Any]:
    """A dropped file, sent as base64 JSON (works without python-multipart)."""
    _mkt(body.market)
    try:
        raw = base64.b64decode(body.data_b64.split(",")[-1], validate=False)
    except ValueError as exc:
        raise HTTPException(400, "The file could not be decoded. Drop it again.") from exc
    return _add_doc(_load_bytes(raw, body.name, body.market))


try:  # multipart upload for API users, when python-multipart is installed
    import python_multipart  # noqa: F401
    from fastapi import File, Form, UploadFile

    @router.post("/api/research/documents/upload-file")
    async def documents_upload_file(file: UploadFile = File(...),  # noqa: B008
                                    market: str = Form("IN")) -> dict[str, Any]:
        _mkt(market)
        return _add_doc(_load_bytes(await file.read(), file.filename or "document.pdf", market))
except ImportError:  # pragma: no cover
    pass


class LinkIn(BaseModel):
    url: str
    market: str = "IN"


@router.post("/api/research/documents/link")
def documents_link(body: LinkIn) -> dict[str, Any]:
    from ... import docdesk
    _mkt(body.market)
    try:
        return _add_doc(docdesk.load_link(body.url.strip(), market=body.market))
    except docdesk.DocError as exc:
        raise HTTPException(400, str(exc)) from exc


class TextIn(BaseModel):
    text: str
    name: str = "Pasted text"
    market: str = "IN"


@router.post("/api/research/documents/text")
def documents_text(body: TextIn) -> dict[str, Any]:
    from ... import docdesk
    _mkt(body.market)
    if not body.text.strip():
        raise HTTPException(400, "Paste some text first.")
    return _add_doc(docdesk.load_text(body.text, body.name.strip() or "Pasted text", body.market))


class SampleIn(BaseModel):
    name: str


@router.post("/api/research/documents/sample")
def documents_sample(body: SampleIn) -> dict[str, Any]:
    from ... import docdesk
    if body.name not in docdesk.SAMPLES:
        raise HTTPException(400, f"No sample called “{body.name}”.")
    return _add_doc(docdesk.sample(body.name))


@router.post("/api/research/documents/remove")
def documents_remove(body: SampleIn) -> dict[str, Any]:
    _docs.pop(body.name, None)
    return _desk()


class AskIn(BaseModel):
    question: str
    scope: str = "This document"   # or "Ask my documents"
    document: str | None = None


@router.post("/api/research/documents/ask")
def documents_ask(body: AskIn) -> dict[str, Any]:
    from ... import docdesk
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "Type a question first.")
    if body.scope == "Ask my documents":
        ans = docdesk.Library().ask(q)
    else:
        if not body.document:
            raise HTTPException(400, "Load a document first, or switch the scope to Ask my documents.")
        ans = docdesk.ask(q, _get_doc(body.document))
    return _clean({
        "question": ans.question, "found": ans.found,
        "quotes": [{"text": x.text, "cite": x.cite, "closeness": x.closeness} for x in ans.quotes],
        "searched": ans.searched(), "narration": ans.narration, "where": ans.where,
        "unverified": ans.unverified,
        "hits": [{"cite": h.chunk.cite, "closeness": round(h.closeness, 3), "method": h.method,
                  "passage": h.chunk.text[:220]} for h in ans.hits],
        "facts": ans.facts(),
    })


@router.get("/api/research/documents/fields")
def documents_fields(template: str) -> dict[str, Any]:
    from ... import docdesk
    if template not in docdesk.TEMPLATES:
        raise HTTPException(400, f"No template called “{template}”.")
    return {"template": template, "fields": docdesk.fields_text(template)}


class ExtractIn(BaseModel):
    document: str
    template: str
    fields: str | None = None


def _extraction(body: ExtractIn) -> Any:
    from ... import docdesk
    doc = _get_doc(body.document)
    if body.template not in docdesk.TEMPLATES:
        raise HTTPException(400, f"No template called “{body.template}”.")
    fields = docdesk.parse_fields(body.fields) if body.fields is not None else None
    if fields is not None and not fields:
        raise HTTPException(400, "Write at least one field, as Name: search words.")
    return docdesk.extract(doc, body.template, fields)


@router.post("/api/research/documents/extract")
def documents_extract(body: ExtractIn) -> dict[str, Any]:
    ext = _extraction(body)
    return _clean({
        "template": ext.template, "document": ext.document, "found": ext.found(),
        "rows": [{"field": r.field, "quote": r.quote, "cite": r.cite, "status": r.status,
                  "searched": r.searched} for r in ext.rows],
        "csv": ext.to_csv(), "filename": f"{ext.document}_{ext.template}.csv", "facts": ext.facts(),
    })


class CompareIn(BaseModel):
    a: str
    b: str


def _comparison(body: CompareIn) -> Any:
    from ... import docdesk
    return docdesk.compare(_get_doc(body.a), _get_doc(body.b))


@router.post("/api/research/documents/compare")
def documents_compare(body: CompareIn) -> dict[str, Any]:
    cmp = _comparison(body)
    tone = lambda t: {"words": t.words, "hedging": t.hedging_per_1000,
                      "confident": t.confident_per_1000}
    return _clean({
        "doc_a": cmp.doc_a, "doc_b": cmp.doc_b, "rows": [r.__dict__ for r in cmp.rows],
        "tone_a": tone(cmp.tone_a), "tone_b": tone(cmp.tone_b), "facts": cmp.facts(),
    })


class AcceptIn(BaseModel):
    kind: str                       # extraction | comparison
    market: str = "IN"
    extract: ExtractIn | None = None
    compare: CompareIn | None = None


@router.post("/api/research/documents/accept")
def documents_accept(body: AcceptIn) -> dict[str, Any]:
    """Accept: save to Portfolio › Thesis tracker (the same engine call as the classic page)."""
    from ... import docdesk
    _mkt(body.market)
    if body.kind == "extraction" and body.extract:
        ext = _extraction(body.extract)
        rid = docdesk.accept_to_thesis(ext.document, extraction=ext, market=body.market)
    elif body.kind == "comparison" and body.compare:
        cmp = _comparison(body.compare)
        rid = docdesk.accept_to_thesis(cmp.doc_b, comparison=cmp, market=body.market)
    else:
        raise HTTPException(400, "Nothing to accept: run Extract to table or Compare first.")
    return {"id": rid}


def _library() -> dict[str, Any]:
    from ... import docdesk
    lib = docdesk.Library()
    return _clean({"counts": lib.counts(),
                   "docs": [{"name": d["name"], "market": d["market"], "pages": d["pages"],
                             "chunks": d["chunks"], "scanned": d["scanned"]}
                            for d in lib.docs.values()]})


@router.get("/api/research/documents/library")
def library() -> dict[str, Any]:
    return _library()


class FolderIn(BaseModel):
    folder: str
    market: str = "IN"
    embed: bool = False


@router.post("/api/research/documents/library/folder")
def library_folder(body: FolderIn) -> dict[str, Any]:
    from ... import docdesk
    _mkt(body.market)
    if not body.folder.strip():
        raise HTTPException(400, "Type the folder path first, for example ~/Documents/trading-notes.")
    try:
        rep = docdesk.Library().add_folder(body.folder.strip(), market=body.market,
                                          use_embeddings=body.embed)
    except docdesk.DocError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**_library(), "line": rep.line(), "errors": rep.errors}


@router.post("/api/research/documents/library/samples")
def library_samples() -> dict[str, Any]:
    from ... import docdesk
    lib = docdesk.Library()
    for name in docdesk.SAMPLES:
        lib.add_document(docdesk.sample(name), key=f"sample:{name}")
    lib.save()
    return {**_library(), "line": f"{lib.counts()['chunks']:,} chunks indexed"}


# ================================================================== Screener
SCHEDULE_TIME = {"IN": "09:08", "US": "09:15"}
DEFAULT_UNIVERSE = {"IN": "NIFTY 500", "US": "S&P 500"}


@router.get("/api/research/screener/setup")
def screener_setup(market: str = "IN") -> dict[str, Any]:
    from ... import screener
    from ...screener import universe as uni
    _mkt(market)
    return _clean({
        "universes": list(uni.UNIVERSES[market]), "universe": DEFAULT_UNIVERSE[market],
        "asof": screener.latest_asof(market), "presets": list(screener.PRESETS),
        "triage": list(screener.TRIAGE), "schedule_time": SCHEDULE_TIME[market],
        "watchlists": [{"name": w["name"], "symbols": w["symbols"], "review_by": w.get("review_by")}
                       for w in screener.watchlists(market)],
    })


@router.get("/api/research/screener/preset")
def screener_preset(name: str, market: str = "IN") -> dict[str, str]:
    from ... import screener
    _mkt(market)
    if name not in screener.PRESETS:
        raise HTTPException(400, f"No preset called “{name}”.")
    return {"text": screener.preset(name, market)}


class ScreenIn(BaseModel):
    text: str
    market: str = "IN"
    edits: dict[int, float] = Field(default_factory=dict)   # rule index -> edited value
    exclude_events: int | None = None                        # None = what the text says; 0 = off


def _parsed(body: ScreenIn) -> Any:
    """Parse, then apply the rule-card edits exactly as the classic page does."""
    from ... import screener
    _mkt(body.market)
    parsed = screener.parse(body.text or "", body.market)
    rules = []
    for i, r in enumerate(parsed.rules):
        val = r.value
        if r.metric != "has_item" and i in body.edits:
            val = float(body.edits[i])
        rules.append(screener.Rule(r.metric, r.op, val,
                                   r.text if val == r.value else f"{r.text} (edited to {val:g})",
                                   r.interpreted))
    excl = parsed.exclude_events if body.exclude_events is None else (body.exclude_events or None)
    return screener.Parsed(rules, excl, parsed.unparsed), parsed


@router.post("/api/research/screener/parse")
def screener_parse(body: ScreenIn) -> dict[str, Any]:
    preview, original = _parsed(body)
    return _clean({
        "rules": [{"metric": r.metric, "op": r.op, "value": r.value, "original": o.value,
                   "text": r.text, "interpreted": r.interpreted, "editable": r.metric != "has_item"}
                  for r, o in zip(preview.rules, original.rules)],
        "exclude_events": original.exclude_events or 0, "unparsed": preview.unparsed,
        "read_back": preview.read_back(), "facts": preview.facts(),
    })


class RunIn(ScreenIn):
    universe: str
    asof: date | None = None


def _result(res: Any) -> dict[str, Any]:
    from ... import screener
    table = res.table()
    cols = list(table.columns)
    recs = table.to_dicts() if table.height else []
    by = {r.symbol: r for r in res.passed}
    rows = [{**rec, "_sessions": by[rec["Symbol"]].event_sessions,
             "_near": by[rec["Symbol"]].near_misses} for rec in recs]
    return _clean({
        "market": res.market, "universe": res.universe, "asof": res.asof, "source": res.source,
        "tested": len(res.rows), "passed": len(res.passed), "columns": cols, "rows": rows,
        "excluded": [{"symbol": r.symbol, "reason": r.excluded} for r in res.excluded],
        "triage": list(screener.TRIAGE), "facts": res.facts(),
        "rules": [r.text for r in res.rules],
    })


@router.post("/api/research/screener/run")
def screener_run(body: RunIn) -> dict[str, Any]:
    from ... import screener
    from ...screener import universe as uni
    preview, _ = _parsed(body)
    if not preview.rules:
        raise HTTPException(400, "No rules to run. Describe your screen, then check the Rules preview.")
    if body.universe not in uni.UNIVERSES[body.market]:
        raise HTTPException(400, f"Universe {body.universe} is not in the {body.market} list.")
    res = screener.run(preview.rules, body.universe, body.market, body.asof,
                       preview.exclude_events)
    return _result(res)


class WatchlistIn(BaseModel):
    name: str
    market: str = "IN"
    symbols: list[str]
    reasons: dict[str, str]
    review_by: date
    rules_text: str = ""
    triage: dict[str, str] = Field(default_factory=dict)


@router.post("/api/research/screener/watchlist")
def screener_watchlist(body: WatchlistIn) -> dict[str, Any]:
    from ... import screener
    _mkt(body.market)
    try:
        rid = screener.save_watchlist(body.name, body.market, body.symbols, body.reasons,
                                      body.review_by, body.rules_text, triage=body.triage)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": rid, "saved": len(body.symbols)}


class ScreenScheduleIn(BaseModel):
    name: str
    market: str = "IN"
    run_time: str
    text: str
    universe: str


@router.post("/api/research/screener/schedule")
def screener_schedule(body: ScreenScheduleIn) -> dict[str, Any]:
    from ... import screener
    _mkt(body.market)
    if not body.name.strip():
        raise HTTPException(400, "Give the scheduled screen a name.")
    return {"id": screener.schedule(body.name.strip(), body.market, body.run_time, body.text,
                                    body.universe)}


# ================================================================== Score-Tester
HORIZONS = {"1 month": 30, "3 months": 91, "6 months": 182, "12 months": 365}


@router.get("/api/research/score-tester/setup")
def scoretest_setup(market: str = "IN") -> dict[str, Any]:
    from ... import costs, scoretest
    _mkt(market)
    return {"fields": list(scoretest.FIELDS), "horizons": HORIZONS, "horizon": "3 months",
            "presets": list(costs.PROFILES), "preset": scoretest.COST_PRESET[market]}


@router.get("/api/research/score-tester/sample")
def scoretest_sample(market: str = "IN") -> dict[str, Any]:
    from ... import scoretest
    _mkt(market)
    return {"name": f"synthetic-scores-{market}.csv", "csv": scoretest.sample_csv(market)}


class CsvIn(BaseModel):
    csv: str


def _read(csv: str) -> Any:
    from ... import scoretest
    if not csv.strip():
        raise HTTPException(400, "The CSV is empty. Export past scores from the vendor and import again.")
    try:
        return scoretest.read_csv(csv if "\n" in csv else csv + "\n")
    except Exception as exc:  # a malformed CSV is shown, not raised
        raise HTTPException(400, f"Could not read the CSV: {exc}") from exc


@router.post("/api/research/score-tester/columns")
def scoretest_columns(body: CsvIn) -> dict[str, Any]:
    from ... import scoretest
    df = _read(body.csv)
    return _clean({"columns": df.columns, "guess": scoretest.guess_mapping(df.columns),
                   "rows": df.height, "preview": df.head(5).to_dicts()})


class ScoreRunIn(CsvIn):
    mapping: dict[str, str | None]
    market: str = "IN"
    horizon: str = "3 months"
    include_delisted: bool = True
    cost_preset: str | None = None


@router.post("/api/research/score-tester/run")
def scoretest_run(body: ScoreRunIn) -> dict[str, Any]:
    from ... import costs, scoretest
    _mkt(body.market)
    if body.horizon not in HORIZONS:
        raise HTTPException(400, f"Horizon must be one of: {', '.join(HORIZONS)}.")
    if body.cost_preset and body.cost_preset not in costs.PROFILES:
        raise HTTPException(400, f"Unknown cost preset {body.cost_preset}.")
    df = _read(body.csv)
    missing = [v for v in body.mapping.values() if v and v not in df.columns]
    if missing:
        raise HTTPException(400, f"Column not in the CSV: {', '.join(missing)}.")
    try:
        scores = scoretest.map_columns(df, body.mapping)
        rep = scoretest.run(scores, body.market, HORIZONS[body.horizon], body.include_delisted,
                            body.cost_preset)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _clean({
        "market": rep.market, "horizon_days": rep.horizon_days, "buckets": rep.buckets,
        "universe_return": rep.universe_return, "spread": rep.spread, "hit_share": rep.hit_share,
        "hit_dates": rep.hit_dates, "n_dates": rep.n_dates, "coverage": rep.coverage,
        "cost_preset": rep.cost_preset, "cost_pct": rep.cost_pct,
        "include_delisted": rep.include_delisted, "warnings": rep.warnings, "facts": rep.facts(),
        "assumed_next_day": not body.mapping.get("Published at"),
    })

