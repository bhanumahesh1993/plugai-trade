"""API routes: Home's first-run wizard, Lessons, Prompt Library and the Settings screens.

Thin: every value comes from the engine modules the classic pages call
(``wizard``, ``lessons``, ``prompts``, ``data``/``data.catalog``, ``keys``,
``mcp_server``, ``privacy``, ``security``, ``workspace``).
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from ... import ai, config, keys, lessons, mcp_server, privacy, prompts, security, wizard, workspace
from ...app.registry import SCREENS
from .. import clean

router = APIRouter()

TITLE_OF = {slug: title for _s, title, _m, _i, slug in SCREENS}
SLUG_OF = {title: slug for slug, title in TITLE_OF.items()}
SECTION_OF = {slug: sec for sec, _t, _m, _i, slug in SCREENS}
QUICK = ("briefing", "lessons", "prompts", "paper-desk", "trades", "ai-models", "security")
_TAG = re.compile(r"^[\w.:/@-]{1,120}$")


def _market(m: str | None) -> str:
    m = (m or config.get("market", "IN") or "IN").upper()
    if m not in ("IN", "US"):
        raise HTTPException(400, "Market must be IN or US.")
    return m


def _link(slug: str) -> dict[str, str]:
    return {"slug": slug, "title": TITLE_OF.get(slug, slug), "section": SECTION_OF.get(slug, "")}


def _frame(df: Any) -> dict[str, Any] | None:
    if df is None:
        return None
    return clean({"columns": list(df.columns), "rows": df.to_dicts()})


# ================================================================== wizard (Home)
def _machine(m: wizard.Machine) -> dict[str, Any]:
    return {"ram_gb": m.ram_gb, "free_ram_gb": m.free_ram_gb, "disk_free_gb": m.disk_free_gb,
            "ollama": m.ollama, "lines": m.lines(), "suggestion": m.suggestion.tag}


def _model(x: wizard.ModelSize) -> dict[str, Any]:
    return {"size": x.size, "label": x.label, "tag": x.tag, "params_b": x.params_b,
            "download_gb": x.download_gb, "good_for": x.good_for}


def _fit(f: wizard.Fit) -> dict[str, Any]:
    return {"model_gb": f.model_gb, "context_gb": f.context_gb, "used_gb": f.used_gb,
            "ram_gb": f.ram_gb, "total_gb": f.total_gb, "share": f.share, "colour": f.colour,
            "facts": f.facts(), "line": f.facts()[-1]}


def _model_by_tag(tag: str) -> wizard.ModelSize:
    for x in (*wizard.MODELS, wizard.EMBEDDING):
        if x.tag == tag:
            return x
    raise HTTPException(400, f"No model size called {tag}. Choose one from the table.")


_last_test: dict[str, wizard.SelfTest] = {}


def _self_test(res: wizard.SelfTest) -> dict[str, Any]:
    return {"passed": res.passed, "seconds": res.seconds, "facts": res.facts(),
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                       for c in res.checks],
            "score": f"{sum(c.passed for c in res.checks)} of {len(res.checks)}"}


@router.get("/api/wizard/state")
def wizard_state() -> dict[str, Any]:
    m = wizard.check_machine()
    ctx = int(config.get("ai.context_length", 8192))
    return clean({
        "done": wizard.is_done(), "step": wizard.step(), "steps": list(wizard.STEPS),
        "machine": _machine(m), "models": [_model(x) for x in wizard.MODELS],
        "ram_rows": ["8 GB or less", "16 GB", "32 GB or more"],
        "context_length": ctx,
        "fits": {x.tag: _fit(wizard.fit_check(x, ctx, ram=m.ram_gb)) for x in wizard.MODELS},
        "ollama_host": wizard.ollama_host(), "ollama_download": wizard.OLLAMA_DOWNLOAD,
        "cloud_providers": list(wizard.CLOUD_PROVIDERS), "market": _market(None),
        "local_model": config.get("ai.local_model"),
        "sample_loaded": list(config.get("wizard.sample_loaded", []) or []),
        "self_test": config.get("wizard.self_test") or None,
    })


@router.get("/api/wizard/machine")
def wizard_machine() -> dict[str, Any]:
    """Check again."""
    return clean(_machine(wizard.check_machine()))


class StepIn(BaseModel):
    step: int


@router.post("/api/wizard/step")
def wizard_step(body: StepIn) -> dict[str, int]:
    return {"step": wizard.set_step(body.step)}


@router.get("/api/wizard/pull")
def wizard_pull(tag: str, set_default: bool = True) -> StreamingResponse:
    """Pull model: Ollama's /api/pull progress as server-sent events (message / done / fail)."""
    if not _TAG.match(tag):
        raise HTTPException(400, "That model name has characters Ollama does not use.")

    def events():
        try:
            for p in wizard.pull_model(tag):
                yield "data: " + json.dumps({"status": p.status, "completed": p.completed,
                                             "total": p.total, "fraction": p.fraction}) + "\n\n"
            if set_default:
                wizard.set_local_model(tag)
            msg = (f"{tag} is ready and set as the Default local model." if set_default
                   else f"{tag} is ready.")
            yield "event: done\ndata: " + json.dumps({"message": msg}) + "\n\n"
        except Exception as exc:  # network, Ollama missing, disk full: say it plainly
            yield "event: fail\ndata: " + json.dumps({"message": (
                f"Pull model did not finish: {exc} Start Ollama, then click Pull model again; "
                "it resumes. On a slow link choose the smaller model first.")}) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class CloudKeyIn(BaseModel):
    provider: str
    key: str


@router.post("/api/wizard/cloud-key")
def wizard_cloud_key(body: CloudKeyIn) -> dict[str, str]:
    if body.provider not in wizard.CLOUD_PROVIDERS:
        raise HTTPException(400, f"Choose one of: {', '.join(wizard.CLOUD_PROVIDERS)}.")
    if not body.key.strip():
        raise HTTPException(400, "Paste the key first.")
    name = f"{body.provider.lower()}_api_key"
    try:
        keys.set_key(name, body.key.strip())
    except Exception as exc:
        raise HTTPException(400, f"The keychain refused the key: {exc}") from exc
    return {"name": name, "masked": keys.masked(name),
            "message": f"Saved {body.provider} key {keys.masked(name)} to the keychain."}


class MarketIn(BaseModel):
    market: str = "IN"


@router.post("/api/wizard/sample")
def wizard_sample(body: MarketIn) -> dict[str, Any]:
    """Load sample data (also sets the market)."""
    out = wizard.load_sample_data(_market(body.market))
    return clean({"market": out.market, "facts": out.facts(),
                  "rows": [{"symbol": s, "bars": n, "last_close": out.last_close[s]}
                           for s, n in out.rows.items()]})


@router.post("/api/wizard/self-test")
def wizard_self_test(body: MarketIn) -> dict[str, Any]:
    res = wizard.self_test(_market(body.market))
    _last_test["last"] = res
    return clean(_self_test(res))


@router.post("/api/wizard/diagnostic")
def wizard_diagnostic() -> dict[str, str]:
    """Copy diagnostic: never contains keys or journal rows."""
    return {"text": wizard.diagnostic(_last_test.get("last"))}


class DoneIn(BaseModel):
    done: bool = True


@router.post("/api/wizard/done")
def wizard_done(body: DoneIn) -> dict[str, Any]:
    """Open dashboard (done) or Run the first-run wizard again (not done, back to screen 1)."""
    wizard.mark_done(body.done)
    if not body.done:
        wizard.set_step(0)
    return {"done": wizard.is_done(), "step": wizard.step()}


@router.get("/api/wizard/start")
def wizard_start() -> dict[str, Any]:
    """Where ``plugai-trade lesson N`` / ``start --page`` asked to open (redirect once per session)."""
    lesson = lessons.from_env()
    target = None
    if os.environ.get("PLUGAI_TRADE_LESSON", "").strip():
        target = "lessons"
    else:
        slug = os.environ.get("PLUGAI_TRADE_START_PAGE", "").strip().strip("/")
        target = slug if slug in TITLE_OF else None
    return {"target": target, "lesson": lesson}


@router.get("/api/wizard/home")
def wizard_home() -> dict[str, Any]:
    """Dashboard extras: pinned screens (Settings › Workspace), quick links, self-test line."""
    pins = [_link(SLUG_OF[t]) for t in workspace.pinned() if t in SLUG_OF]
    return {"pinned": pins, "quick": [_link(s) for s in QUICK],
            "self_test": config.get("wizard.self_test") or None}


# ================================================================== lessons
def _lesson_row(les: lessons.Lesson) -> dict[str, Any]:
    return {"n": les.n, "title": les.title, "levels": list(les.levels), "badge": lessons.badge(les.n),
            "command": f"plugai-trade lesson {les.n}"}


@router.get("/api/lessons")
def lessons_list() -> dict[str, Any]:
    return {"lessons": [_lesson_row(x) for x in lessons.all_lessons()],
            "from_env": lessons.from_env()}


def _lesson(n: int) -> lessons.Lesson:
    try:
        return lessons.get(n)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'\"")) from exc


@router.get("/api/lessons/{n}")
def lesson_detail(n: int, market: str | None = None) -> dict[str, Any]:
    les, mkt = _lesson(n), _market(market)
    exercise: dict[str, Any] | None = None
    error = None
    if les.exercise is not None:
        try:
            ex = les.exercise(mkt)
            exercise = {"title": ex.title, "facts": ex.facts(), "table": _frame(ex.table)}
        except Exception as exc:  # an optional module missing: say so, keep the lesson usable
            error = f"The exercise needs a part of the lab that is not available here: {exc}"
    return clean({
        **_lesson_row(les), "goal": les.goal, "market": mkt,
        "steps": [{"text": s.text, **({"screen": _link(s.slug)} if s.slug else {})}
                  for s in les.steps],
        "checks": [{"key": c.key, "text": c.text, "kind": c.kind, "unit": c.unit}
                   for c in les.checks],
        "progress": lessons.progress(n), "samples": list(les.samples),
        "exercise": exercise, "exercise_error": error,
    })


@router.post("/api/lessons/{n}/load-sample")
def lesson_load_sample(n: int, body: MarketIn) -> dict[str, Any]:
    _lesson(n)
    return {"lines": lessons.load_sample(n, _market(body.market))}


class AnswersIn(BaseModel):
    market: str = "IN"
    answers: dict[str, Any] = {}


@router.post("/api/lessons/{n}/check")
def lesson_check(n: int, body: AnswersIn) -> dict[str, Any]:
    les = _lesson(n)
    res = lessons.check(n, body.answers, _market(body.market))
    text = {c.key: c.text for c in les.checks}
    return {"results": [{"key": r.key, "text": text[r.key], "passed": r.passed, "detail": r.detail}
                        for r in res],
            "badge": lessons.badge(n), "progress": lessons.progress(n)}


@router.post("/api/lessons/{n}/reset")
def lesson_reset(n: int) -> dict[str, Any]:
    _lesson(n)
    removed = lessons.reset(n)
    return {"removed": removed, "badge": lessons.badge(n)}


# ================================================================== prompt library
def _prompt(p: prompts.Prompt) -> dict[str, Any]:
    return {"kid": f"{p.id}_{p.note_id}" if p.mine else p.id, "id": p.id, "title": p.title,
            "chapter": p.chapter, "chapter_title": p.chapter_title, "use": p.use,
            "works_with": p.works_with, "group": p.group, "chips": list(p.chips), "text": p.text,
            "mine": p.mine, "note_id": p.note_id, "facts": p.facts(),
            "placeholders": [{"name": n, "paste": prompts.is_paste_slot(n)}
                             for n in p.placeholders]}


@router.get("/api/prompts")
def prompts_search(q: str = "", chips: str = "") -> dict[str, Any]:
    wanted = [c for c in chips.split(",") if c]
    bad = [c for c in wanted if c not in prompts.CHIPS]
    if bad:
        raise HTTPException(400, f"Unknown filter: {', '.join(bad)}.")
    found = prompts.search(q, wanted)
    return {"chips": list(prompts.CHIPS), "count": len(found), "total": len(prompts.BOOK),
            "prompts": [_prompt(p) for p in found]}


class FillIn(BaseModel):
    text: str
    values: dict[str, str] = {}


@router.post("/api/prompts/fill")
def prompts_fill(body: FillIn) -> dict[str, Any]:
    filled = prompts.fill(body.text, body.values)
    return {"filled": filled, "left": prompts.placeholders(filled),
            "placeholders": [{"name": n, "paste": prompts.is_paste_slot(n)}
                             for n in prompts.placeholders(body.text)],
            "untrusted": "UNTRUSTED" in filled}


class MyVersionIn(BaseModel):
    text: str


@router.post("/api/prompts/{prompt_id}/my-version")
def prompts_save(prompt_id: str, body: MyVersionIn) -> dict[str, Any]:
    if not body.text.strip():
        raise HTTPException(400, "The prompt is empty. Type or keep some text first.")
    try:
        note = prompts.save_my_version(prompt_id, body.text)
    except KeyError as exc:
        raise HTTPException(404, f"No prompt called {prompt_id}.") from exc
    return {"note_id": note, "tag": prompts.MY_VERSION}


@router.post("/api/prompts/my-version/{note_id}/delete")
def prompts_delete(note_id: int) -> dict[str, bool]:
    prompts.delete_my_version(note_id)
    return {"deleted": True}


# ================================================================== data sources
STRIPS = {"IN": [("IN-eod", "India end of day"), ("IN-intraday", "India intraday")],
          "US": [("US-eod", "US end of day"), ("US-intraday", "US intraday")]}
OTHER_STRIPS = [("FX", "FX"), ("crypto", "Crypto")]
COMPARE_DEFAULTS = {"IN": ("NIFTY", "nse_bhavcopy", "yfinance"), "US": ("SPY", "alpaca", "yfinance")}
LICENCE_NOTE = [
    "Every stored bar carries a tag: its source, when it was fetched, and a licence class: public "
    "(SEC EDGAR, FRED, synthetic), personal-use (NSE/BSE files, yfinance, keyed vendors) or "
    "broker (your broker's API). When the router falls back, the tag names the source that "
    "answered.",
    "Downloading for your own analysis is what free sources are for; passing the data itself to "
    "other people is where licences bite. NSE owns its end-of-day data, so this app ships no NSE "
    "prices: plugai-trade fetch downloads them on your machine. Never re-serve personal-use or "
    "broker data on a website or app. SEC EDGAR data is public information and may be shared.",
]


def _catalog():
    from ...data import catalog
    return catalog


def _upstox_expiry() -> dict[str, Any] | None:
    catalog = _catalog()
    if not catalog.is_set_up("upstox"):
        return None
    from ...data import upstox
    exp = upstox.token_expiry()
    if not exp:
        return None
    left = (exp - date.today()).days
    return {"expires": exp.isoformat(), "days_left": left, "expired": left < 0}


def _source(info: Any, market: str) -> dict[str, Any]:
    from ...data import brokers
    catalog, name = _catalog(), info.name
    live = config.get(f"data.live.{name}", {}) or {}
    stored = set(keys.listed())
    return {
        "name": name, "label": catalog.label(name), "tier": info.tier,
        "description": info.description, "needs": info.needs, "license_class": info.license_class,
        "markets": [m for m in info.markets if m != "ANY"],
        "set_up": catalog.is_set_up(name), "working": catalog.is_working(name),
        "last_test": catalog.last_test(name),
        "key_fields": [{"key": k, "label": lbl, "saved": k in stored}
                       for k, lbl in catalog.KEY_FIELDS.get(name, [])],
        "connect_url": catalog.CONNECT_URLS.get(name),
        "testable": name != "synthetic",
        "live_capable": name in catalog.LIVE_CAPABLE,
        "live": {"on": bool(live.get("on")), "symbols": list(live.get("symbols") or [])},
        "remind": ({"at": config.get(f"data.remind_at.{name}", "08:55")}
                   if brokers.reminder_needed(name) else None),
        "expiry": _upstox_expiry() if name == "upstox" else None,
        "for_market": market in info.markets or "ANY" in info.markets,
    }


def _strip(key: str, head: str) -> dict[str, Any]:
    catalog = _catalog()
    names = catalog.STRIP_LABELS if key.startswith("IN") else catalog.LABELS
    chain = list(config.get(f"data.fallback.{key}", []) or [])
    items = [{"name": n, "label": names.get(n, n),
              "active": n in ("cache", "eod_replay") or catalog.is_set_up(n)} for n in chain]
    shown = [i["label"] for i in items if i["active"]]
    return {"key": key, "head": head, "chain": items,
            "text": " → ".join(shown) or "(nothing set up)",
            "is_default": chain == list(config.DEFAULTS["data"]["fallback"].get(key, []))}


@router.get("/api/settings/data-sources")
def data_sources(market: str | None = None) -> dict[str, Any]:
    from ... import data
    catalog, mkt = _catalog(), _market(market)
    order = list(catalog.LABELS)
    tiers: dict[str, list[dict[str, Any]]] = {t: [] for t in catalog.TIERS}
    for info in data.sources():
        tiers.setdefault(info.tier, []).append(_source(info, mkt))
    for rows in tiers.values():
        rows.sort(key=lambda s: order.index(s["name"]) if s["name"] in order else 99)
    from ...data.alpaca import FREE_STREAM_SYMBOLS
    all_sources = [s for rows in tiers.values() for s in rows]
    watch = config.get("watchlists", {}) or {}
    return clean({
        "market": mkt, "tiers": [{"tier": t, "sources": tiers[t]} for t in catalog.TIERS],
        "paid_brokers": catalog.PAID_BROKERS.replace(" · ", ", "),
        "strips": [_strip(k, h) for k, h in STRIPS[mkt] + OTHER_STRIPS],
        "known_keys": list(keys.KNOWN), "edgar_contact": config.get("data.edgar_contact", "") or "",
        "licence_note": LICENCE_NOTE, "alpaca_free_symbols": FREE_STREAM_SYMBOLS,
        "watchlists": {m: list(watch.get(m, []) or []) for m in ("IN", "US")},
        "working": sum(s["working"] for s in all_sources), "total": len(all_sources),
        "compare": {"symbol": COMPARE_DEFAULTS[mkt][0], "a": COMPARE_DEFAULTS[mkt][1],
                    "b": COMPARE_DEFAULTS[mkt][2], "start": "2026-05-01", "end": "2026-05-29",
                    "sources": [{"name": s.name, "label": catalog.label(s.name)}
                                for s in data.sources()
                                if mkt in s.markets or s.name == "synthetic"]},
    })


class KeysIn(BaseModel):
    values: dict[str, str]


@router.post("/api/settings/data-sources/{name}/keys")
def data_source_keys(name: str, body: KeysIn) -> dict[str, Any]:
    """Save to keychain (the source's fields only)."""
    catalog = _catalog()
    allowed = {k for k, _ in catalog.KEY_FIELDS.get(name, [])}
    if not allowed:
        raise HTTPException(400, f"{catalog.label(name)} does not need a key.")
    extra = set(body.values) - allowed
    if extra:
        raise HTTPException(400, f"{catalog.label(name)} has no field called {', '.join(extra)}.")
    try:
        saved = catalog.save_keys(name, body.values)
    except keys.KeyRefused as exc:
        raise HTTPException(400, str(exc)) from exc
    if not saved:
        raise HTTPException(400, "Nothing to save. Paste a value first.")
    return {"saved": [{"key": k, "masked": keys.masked(k)} for k in saved],
            "message": "Saved " + ", ".join(f"{k} {keys.masked(k)}" for k in saved)}


@router.post("/api/settings/data-sources/{name}/test")
def data_source_test(name: str, body: MarketIn) -> dict[str, Any]:
    """Test connection: a tiny sample straight from one source; the outcome is remembered."""
    from ... import data
    catalog = _catalog()
    if name == "synthetic":
        raise HTTPException(400, "Synthetic always works offline; there is nothing to test.")
    info = next((s for s in data.sources() if s.name == name), None)
    if info is None:
        raise HTTPException(404, f"No data source called {name}.")
    res = catalog.probe(name, _market(body.market))
    tag = catalog.label(name) + (" · IEX" if name == "alpaca" else "")
    frames = [{"what": what, "tag": tag, "license_class": info.license_class,
               **(_frame(df.tail(3)) or {})} for what, df in res.frames.items() if df.height]
    return clean({"ok": res.ok, "message": f"{catalog.label(name)}: {res.message}",
                  "frames": frames, "facts": res.facts(), "last_test": catalog.last_test(name)})


class ContactIn(BaseModel):
    contact: str


@router.post("/api/settings/data-sources/edgar-contact")
def edgar_contact(body: ContactIn) -> dict[str, str]:
    config.set_value("data.edgar_contact", body.contact.strip())
    return {"contact": body.contact.strip()}


class LiveIn(BaseModel):
    on: bool
    symbols: list[str] | None = None


@router.post("/api/settings/data-sources/{name}/live")
def data_source_live(name: str, body: LiveIn) -> dict[str, Any]:
    catalog = _catalog()
    if name not in catalog.LIVE_CAPABLE:
        raise HTTPException(400, f"{catalog.label(name)} has no live stream.")
    live = dict(config.get(f"data.live.{name}", {}) or {})
    live["on"] = body.on
    if body.symbols is not None:
        live["symbols"] = list(dict.fromkeys(s.strip().upper() for s in body.symbols if s.strip()))
    elif body.on and not live.get("symbols"):
        mkt = "US" if name == "alpaca" else "IN"
        live["symbols"] = list((config.get("watchlists", {}) or {}).get(mkt, []))
    config.set_value(f"data.live.{name}", live)
    any_on = any((config.get(f"data.live.{n}", {}) or {}).get("on") for n in catalog.LIVE_CAPABLE)
    config.set_value("data.live_stream", bool(any_on))
    return {"live": live, "live_stream": bool(any_on)}


class RemindIn(BaseModel):
    at: str


@router.post("/api/settings/data-sources/{name}/remind")
def data_source_remind(name: str, body: RemindIn) -> dict[str, str]:
    from ...data import brokers
    if not brokers.reminder_needed(name):
        raise HTTPException(400, "This source's login does not expire daily; no reminder needed.")
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", body.at):
        raise HTTPException(400, "Type the time as HH:MM, for example 08:55.")
    config.set_value(f"data.remind_at.{name}", body.at)
    return {"at": body.at}


class AddKeyIn(BaseModel):
    name: str
    value: str


@router.post("/api/settings/data-sources/add-key")
def data_source_add_key(body: AddKeyIn) -> dict[str, str]:
    """+ Add key: any known key, stored in the keychain with today's date."""
    if body.name not in keys.KNOWN:
        raise HTTPException(400, "Choose a key from the list.")
    if not body.value.strip():
        raise HTTPException(400, "Paste a value first.")
    try:
        keys.set_key(body.name, body.value.strip())
    except keys.KeyRefused as exc:
        raise HTTPException(400, str(exc)) from exc
    config.set_value(f"data.saved_on.{body.name}", date.today().isoformat())
    return {"name": body.name, "masked": keys.masked(body.name),
            "message": f"Saved {body.name} {keys.masked(body.name)}"}


class StripIn(BaseModel):
    key: str
    chain: list[str] | None = None
    reset: bool = False


@router.post("/api/settings/data-sources/fallback")
def data_source_fallback(body: StripIn) -> dict[str, Any]:
    """Reorder (drag and drop) or Reset one fallback strip. Same sources, new order."""
    defaults = config.DEFAULTS["data"]["fallback"]
    if body.key not in defaults:
        raise HTTPException(400, f"No fallback strip called {body.key}.")
    cur = list(config.get(f"data.fallback.{body.key}", []) or [])
    if body.reset:
        new = list(defaults[body.key])
    else:
        if body.chain is None or sorted(body.chain) != sorted(cur):
            raise HTTPException(400, "Reorder the sources already on the strip; add a source by "
                                     "connecting it first.")
        new = list(body.chain)
    config.set_value(f"data.fallback.{body.key}", new)
    head = dict(STRIPS["IN"] + STRIPS["US"] + OTHER_STRIPS)[body.key]
    return clean(_strip(body.key, head))


class CompareIn(BaseModel):
    symbol: str
    market: str = "IN"
    start: date
    end: date
    source_a: str
    source_b: str


_last_cmp: dict[str, Any] = {}


@router.post("/api/settings/data-sources/compare")
def data_source_compare(body: CompareIn) -> dict[str, Any]:
    catalog, mkt = _catalog(), _market(body.market)
    if body.start > body.end:
        raise HTTPException(400, "From is after To. Swap the dates.")
    sym = body.symbol.strip().upper()
    if not sym:
        raise HTTPException(400, "Type a symbol, for example NIFTY or SPY.")
    try:
        res = catalog.compare_sources(sym, mkt, body.start, body.end, body.source_a, body.source_b)
    except Exception as exc:  # one source failed: say which, keep the screen alive
        raise HTTPException(400, f"Could not load both sources: {exc}") from exc
    _last_cmp["last"] = res
    prov = {str(d): res.provenance(d) for d in res.table["date"].to_list()}
    return clean({"summary": res.summary(), "symbol": res.symbol, "market": res.market,
                  "source_a": catalog.label(res.source_a), "source_b": catalog.label(res.source_b),
                  "rows_compared": res.table.height, "missing": res.count("missing"),
                  "disagree": res.count("disagree"), "table": res.table.to_dicts(),
                  "provenance": prov, "facts": res.facts()})


@router.post("/api/settings/data-sources/compare/save")
def data_source_compare_save() -> dict[str, Any]:
    from ...store import default as store
    catalog = _catalog()
    res = _last_cmp.get("last")
    if res is None:
        raise HTTPException(400, "Run a comparison first.")
    rid = store().add("journal", {
        "kind": "data-check", "date": date.today().isoformat(),
        "title": f"Compare sources: {res.symbol} {catalog.label(res.source_a)} vs "
                 f"{catalog.label(res.source_b)}",
        "text": res.summary(), "facts": res.facts()}, tag="data-check")
    return {"id": rid}


# ================================================================== AI models
POLICIES = ("Local only", "Cloud allowed")
_SECTIONS = list(dict.fromkeys(s for s, *_ in SCREENS))
ROUTED = tuple(s for s in _SECTIONS if s not in ("Lessons", "Settings")) + ("Documents",)
CONTEXTS = (2048, 4096, 8192, 16384, 32768)
PROVIDERS = {"Gemini": "gemini", "Groq": "groq", "OpenRouter": "openrouter", "OpenAI": "openai",
             "Anthropic": "anthropic", "DeepSeek": "deepseek"}
LM_STUDIO = "http://localhost:1234/v1"


@router.get("/api/settings/ai-models")
def ai_models() -> dict[str, Any]:
    ram, free = wizard.ram_gb(), wizard.free_ram_gb()
    ctx = int(config.get("ai.context_length", 8192))
    default = config.get("ai.local_model")
    installed = wizard.installed_models()
    locals_ = list(dict.fromkeys([default, *installed]))
    clouds = list(config.get("ai.cloud_models", []) or [])
    use = dict(config.get("ai.use_for", {}) or {})
    forced = set(privacy.local_only_sections())
    s = ai.status()
    return clean({
        "ram_gb": ram, "free_ram_gb": free, "ollama": wizard.ollama_reachable(),
        "ollama_host": wizard.ollama_host(),
        "default": default, "local_models": locals_, "installed": installed,
        "local_servers": list(config.get("ai.local_servers", []) or []), "lm_studio": LM_STUDIO,
        "contexts": list(CONTEXTS), "context_length": ctx,
        "models": [{**_model(m), "fit": _fit(wizard.fit_check(m, ctx, ram=ram))}
                   for m in wizard.MODELS],
        "suggestion": wizard.suggest(ram).tag,
        "cloud_models": clouds,
        "providers": [{"provider": p, "key": f"{k}_api_key", "masked": keys.masked(f"{k}_api_key")}
                      for p, k in PROVIDERS.items()],
        "drafting": config.get("ai.drafting_model") or default,
        "journal": config.get("ai.journal_model") or default,
        "drafting_options": locals_ + clouds, "journal_options": locals_,
        "use_for": [{"section": sec, "policy": "Local only" if sec in forced
                     else use.get(sec, "Local only"), "forced": sec in forced} for sec in ROUTED],
        "budget": float(config.get("ai.monthly_budget", 5.0)),
        "spend": s["spend_this_month"],
        "embedding": config.get("ai.embedding_model", wizard.EMBEDDING.tag),
        "embedding_default": _model(wizard.EMBEDDING),
    })


class TagIn(BaseModel):
    tag: str


@router.post("/api/settings/ai-models/default")
def ai_default(body: TagIn) -> dict[str, str]:
    if not body.tag.strip():
        raise HTTPException(400, "Choose a model first.")
    wizard.set_local_model(body.tag.strip())
    return {"default": body.tag.strip()}


class TestModelIn(BaseModel):
    tag: str | None = None


@router.post("/api/settings/ai-models/test")
def ai_test(body: TestModelIn) -> dict[str, Any]:
    """Test model: speed, prompt reading time, and whether it invented numbers."""
    r = wizard.test_model(body.tag or None)
    return clean({"model": r.model, "ok": r.ok, "tokens_per_s": r.tokens_per_s,
                  "prompt_s": r.prompt_s, "detail": r.detail, "facts": r.facts()})


class ContextIn(BaseModel):
    tokens: int


@router.post("/api/settings/ai-models/context")
def ai_context(body: ContextIn) -> dict[str, Any]:
    if body.tokens not in CONTEXTS:
        raise HTTPException(400, f"Context length must be one of {', '.join(map(str, CONTEXTS))}.")
    config.set_value("ai.context_length", int(body.tokens))
    return ai_models()


@router.get("/api/settings/ai-models/fit")
def ai_fit(tag: str, context: int | None = None) -> dict[str, Any]:
    ctx = int(context or config.get("ai.context_length", 8192))
    return clean(_fit(wizard.fit_check(_model_by_tag(tag), ctx, ram=wizard.ram_gb())))


class ServerIn(BaseModel):
    url: str


@router.post("/api/settings/ai-models/local-server")
def ai_local_server(body: ServerIn) -> dict[str, Any]:
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Type the full address, for example http://localhost:1234/v1.")
    servers = list(dict.fromkeys([*(config.get("ai.local_servers", []) or []), url]))
    config.set_value("ai.local_servers", servers)
    return {"local_servers": servers}


@router.post("/api/settings/ai-models/local-server/remove")
def ai_local_server_remove(body: ServerIn) -> dict[str, Any]:
    servers = [s for s in (config.get("ai.local_servers", []) or []) if s != body.url.strip()]
    config.set_value("ai.local_servers", servers)
    return {"local_servers": servers}


class CloudModelIn(BaseModel):
    provider: str
    name: str


@router.post("/api/settings/ai-models/cloud")
def ai_cloud_add(body: CloudModelIn) -> dict[str, Any]:
    if body.provider not in PROVIDERS:
        raise HTTPException(400, f"Choose one of: {', '.join(PROVIDERS)}.")
    if not body.name.strip():
        raise HTTPException(400, "Type the model name as the provider lists it.")
    key_name = f"{PROVIDERS[body.provider]}_api_key"
    if not keys.get_key(key_name):
        raise HTTPException(400, f"No {body.provider} key in the keychain yet; add it in "
                                 "Settings › Keys first.")
    full = f"{PROVIDERS[body.provider]}/{body.name.strip()}"
    clouds = list(dict.fromkeys([*(config.get("ai.cloud_models", []) or []), full]))
    config.set_value("ai.cloud_models", clouds)
    return {"added": full, "cloud_models": clouds}


class NameIn(BaseModel):
    name: str


@router.post("/api/settings/ai-models/cloud/remove")
def ai_cloud_remove(body: NameIn) -> dict[str, Any]:
    clouds = [x for x in (config.get("ai.cloud_models", []) or []) if x != body.name]
    config.set_value("ai.cloud_models", clouds)
    return {"cloud_models": clouds}


class RolesIn(BaseModel):
    drafting: str
    journal: str


@router.post("/api/settings/ai-models/roles")
def ai_roles(body: RolesIn) -> dict[str, str]:
    local = config.get("ai.local_model")
    locals_ = list(dict.fromkeys([local, *wizard.installed_models()]))
    if body.journal not in locals_:
        raise HTTPException(400, "Journal and portfolio must use a local model.")
    config.set_value("ai.drafting_model", "" if body.drafting == local else body.drafting)
    config.set_value("ai.journal_model", "" if body.journal == local else body.journal)
    return {"drafting": body.drafting, "journal": body.journal}


class UseForIn(BaseModel):
    section: str
    policy: str


@router.post("/api/settings/ai-models/use-for")
def ai_use_for(body: UseForIn) -> dict[str, Any]:
    if body.section not in ROUTED or body.policy not in POLICIES:
        raise HTTPException(400, "Choose a section from the table and Local only or Cloud allowed.")
    if body.section in privacy.local_only_sections() and body.policy != "Local only":
        raise HTTPException(400, f"{body.section} is kept Local only by Settings › Privacy. "
                                 "Change it there first.")
    use = dict(config.get("ai.use_for", {}) or {})
    use[body.section] = body.policy
    config.set_value("ai.use_for", use)
    return {"use_for": use}


class BudgetIn(BaseModel):
    usd: float


@router.post("/api/settings/ai-models/budget")
def ai_budget(body: BudgetIn) -> dict[str, float]:
    if body.usd < 0:
        raise HTTPException(400, "The budget cannot be negative.")
    config.set_value("ai.monthly_budget", float(body.usd))
    return {"budget": float(body.usd)}


class EmbeddingIn(BaseModel):
    model: str


@router.post("/api/settings/ai-models/embedding")
def ai_embedding(body: EmbeddingIn) -> dict[str, str]:
    if not _TAG.match(body.model.strip()):
        raise HTTPException(400, "Type an Ollama model name, for example nomic-embed-text.")
    config.set_value("ai.embedding_model", body.model.strip())
    return {"embedding": body.model.strip()}


# ================================================================== keys
PERMISSIONS = ["read", "trade", "withdraw", "transfer"]


@router.get("/api/settings/keys")
def keys_list() -> dict[str, Any]:
    return {"keychain_ok": keys.keychain_ok(),
            "keys": [{"name": n, "masked": keys.masked(n)} for n in keys.listed()],
            "known": list(keys.KNOWN), "permissions": PERMISSIONS}


class KeyIn(BaseModel):
    name: str
    value: str
    permissions: list[str] = ["read"]


@router.post("/api/settings/keys")
def keys_save(body: KeyIn) -> dict[str, str]:
    name = body.name.strip().lower().replace(" ", "_")
    if not name or not body.value.strip():
        raise HTTPException(400, "Choose a key name and paste a value.")
    if not re.match(r"^[a-z0-9_.-]{2,64}$", name):
        raise HTTPException(400, "Use letters, numbers and underscores for the key name.")
    try:
        keys.set_key(name, body.value.strip(), permissions=body.permissions)
    except keys.KeyRefused as exc:
        raise HTTPException(400, str(exc) + " Create a read-only key on the provider's site "
                                              "instead.") from exc
    return {"name": name, "masked": keys.masked(name)}


@router.post("/api/settings/keys/{name}/remove")
def keys_remove(name: str) -> dict[str, str]:
    keys.remove_key(name)
    return {"removed": name}


# ================================================================== MCP server
@router.get("/api/settings/mcp")
def mcp() -> dict[str, Any]:
    on = mcp_server.paper_order_enabled()
    rows = [{"tool": n, "tag": t["tag"], "does": t["does"],
             "offered": n != "paper_order" or on} for n, t in mcp_server.TOOLS.items()]
    log = [{"time": r["created"][:19].replace("T", " "), "tool": r.get("tool"),
            "tag": r.get("tool_tag"), "args": json.dumps(r.get("args", {}), ensure_ascii=False),
            "result": r.get("result")} for r in mcp_server.tool_log()]
    return clean({"tools": rows, "paper_order": on, "server": mcp_server.SERVER_NAME,
                  "config": mcp_server.claude_desktop_config_json(), "log": log,
                  "offered": sum(r["offered"] for r in rows)})


class OnIn(BaseModel):
    on: bool


@router.post("/api/settings/mcp/paper-order")
def mcp_paper_order(body: OnIn) -> dict[str, Any]:
    mcp_server.set_paper_order_enabled(body.on)
    return mcp()


# ================================================================== privacy
TOGGLES = (
    ("journal_local_only", "Journal and tradebook use the local model only"),
    ("holdings_local_only", "Holdings use the local model only"),
    ("ask_before_cloud", "Ask before sending to cloud"),
    ("strip_identifiers", "Remove account numbers and PAN/SSN before cloud calls"),
    ("crash_reports", "Share anonymous crash reports"),
)


@router.get("/api/settings/privacy")
def privacy_state() -> dict[str, Any]:
    s = privacy.settings()
    default = privacy.Settings()
    return {"toggles": [{"name": n, "label": lbl, "on": getattr(s, n), "default": getattr(default, n)}
                        for n, lbl in TOGGLES],
            "defaults_on": privacy.defaults_on(), "lag": privacy.education_lag(),
            "min_lag": privacy.MIN_LAG, "default_lag": privacy.DEFAULT_LAG,
            "local_only_sections": privacy.local_only_sections()}


class ToggleIn(BaseModel):
    name: str
    on: bool


@router.post("/api/settings/privacy/toggle")
def privacy_toggle(body: ToggleIn) -> dict[str, Any]:
    try:
        privacy.set_toggle(body.name, body.on)
    except KeyError as exc:
        raise HTTPException(400, f"No privacy setting called {body.name}.") from exc
    return privacy_state()


class TextIn(BaseModel):
    text: str


@router.post("/api/settings/privacy/preview")
def privacy_preview(body: TextIn) -> dict[str, Any]:
    """See what a cloud call would send."""
    return {"found": privacy.found_identifiers(body.text), "payload": privacy.cloud_payload(body.text),
            "stripping": privacy.settings().strip_identifiers}


class LagIn(BaseModel):
    days: int


@router.post("/api/settings/privacy/lag")
def privacy_lag(body: LagIn) -> dict[str, Any]:
    if body.days > 3650:
        raise HTTPException(400, "Use at most 3,650 days.")
    stored = privacy.set_education_lag(body.days)
    return {**privacy_state(), "raised": stored != body.days}


# ================================================================== security
def _item(i: security.Item) -> dict[str, Any]:
    return {"key": i.key, "text": i.text, "ok": i.ok, "detail": i.detail, "manual": i.manual}


@router.get("/api/settings/security")
def security_state() -> dict[str, Any]:
    items = security.checklist()
    return {"items": [_item(i) for i in items], "score": security.score(items),
            "passed": sum(i.ok for i in items), "total": len(items),
            "facts": security.Summary(items).facts(),
            "reg_types": list(security.REG_TYPES), "note": security.REGISTRATION_NOTE,
            "filters": list(security.FILTERS)}


class TickIn(BaseModel):
    key: str
    on: bool


@router.post("/api/settings/security/tick")
def security_tick(body: TickIn) -> dict[str, Any]:
    try:
        security.tick(body.key, body.on)
    except KeyError as exc:
        raise HTTPException(400, f"No manual checklist item called {body.key}.") from exc
    return security_state()


@router.get("/api/settings/security/registers")
def security_registers(market: str = "IN", kind: str = "Adviser") -> dict[str, Any]:
    if kind not in security.REG_TYPES:
        raise HTTPException(400, f"Type must be one of {', '.join(security.REG_TYPES)}.")
    return {"registers": [{"name": r.name, "url": r.url, "covers": r.covers}
                          for r in security.registers(_market(market), kind)]}


@router.post("/api/settings/security/pitch")
def security_pitch(body: TextIn) -> dict[str, Any]:
    if not body.text.strip():
        raise HTTPException(400, "Paste the pitch, website text or terms first.")
    pc = security.check_pitch(body.text)
    return clean({"flags": [{"kind": f.kind, "flag": f.flag, "quote": f.quote} for f in pc.flags],
                  "names": pc.names, "compound": [{"pct": p, "multiple": m} for p, m in pc.compound],
                  "ai_text": pc.ai_text, "where": pc.where, "model": pc.model, "facts": pc.facts()})


@router.get("/api/settings/security/audit")
def security_audit(filter: str = "All") -> dict[str, Any]:  # noqa: A002 - the screen's word
    if filter not in security.FILTERS:
        raise HTTPException(400, f"Filter must be one of {', '.join(security.FILTERS)}.")
    return clean({"rows": security.audit_rows(filter)})


@router.get("/api/settings/security/export")
def security_export(filter: str = "All") -> PlainTextResponse:  # noqa: A002
    if filter not in security.FILTERS:
        raise HTTPException(400, f"Filter must be one of {', '.join(security.FILTERS)}.")
    return PlainTextResponse(security.export_log(filter), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="plugai-trade-audit-log.csv"'})


# ================================================================== workspace
_preview: dict[str, workspace.Preview] = {}


def _pv(pv: workspace.Preview) -> dict[str, Any]:
    return {"style": pv.style, "markets": list(pv.markets), "accepted": list(pv.accepted),
            "groups": [{"name": g, "lines": pv.group(g)} for g in workspace.GROUPS],
            "facts": pv.facts()}


@router.get("/api/settings/workspace")
def workspace_state() -> dict[str, Any]:
    pv = _preview.get("current")
    return {"styles": list(workspace.STYLES), "markets": list(workspace.MARKETS),
            "market_parts": {k: list(v) for k, v in workspace.MARKETS.items()},
            "groups": list(workspace.GROUPS), "briefing_at": workspace.BRIEFING_AT,
            "pinned": workspace.pinned(), "template": config.get("workspace.template"),
            "preview": _pv(pv) if pv else None}


class TemplateIn(BaseModel):
    style: str
    market: str = "IN"
    times: dict[str, str] = {}


@router.post("/api/settings/workspace/preview")
def workspace_preview(body: TemplateIn) -> dict[str, Any]:
    """Apply template: builds the preview only. Nothing changes until Accept per group."""
    if body.market not in workspace.MARKETS:
        raise HTTPException(400, "Market must be IN, US or Both.")
    for m, t in body.times.items():
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t.strip()):
            raise HTTPException(400, f"Type the {m} briefing time as HH:MM, for example 08:40.")
    try:
        pv = workspace.preview(body.style, body.market, {k: v.strip() for k, v in body.times.items()})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _preview["current"] = pv
    return _pv(pv)


class GroupIn(BaseModel):
    group: str


@router.post("/api/settings/workspace/accept")
def workspace_accept(body: GroupIn) -> dict[str, Any]:
    pv = _preview.get("current")
    if pv is None:
        raise HTTPException(400, "Click Apply template first.")
    if body.group not in workspace.GROUPS:
        raise HTTPException(400, f"No group called {body.group}.")
    if body.group in pv.accepted:
        raise HTTPException(400, f"{body.group} is already accepted.")
    msg = workspace.accept(pv, body.group)
    return {**_pv(pv), "message": msg, "pinned": workspace.pinned()}


@router.get("/api/settings/workspace/export")
def workspace_export() -> PlainTextResponse:
    return PlainTextResponse(workspace.export(), media_type="application/json", headers={
        "Content-Disposition": 'attachment; filename="plugai-trade-workspace.json"'})
