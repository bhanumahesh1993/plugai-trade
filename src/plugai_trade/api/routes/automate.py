"""API routes: Automate › Scheduler, News Pipeline, ML Lab, Agents, Plugins (Ch 27–31, 34).

Thin: every number comes from the engine modules (``plugai_trade.scheduler``,
``news``, ``ml``, ``agents``, ``plugin``). Per-market working state (fetched
headlines, the last model card, an agent run) is kept in this process, like the
classic pages' session state. Nothing here can place an order: the lab has no
order code.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import config
from ...store import default as store
from .. import clean as _clean

router = APIRouter()
DEFAULT_SYMBOL = {"IN": "NIFTY", "US": "SPY"}


def _mkt(market: str) -> str:
    if market not in ("IN", "US"):
        raise HTTPException(400, "Market must be IN or US.")
    return market


def _day(text: str | None, default: date, what: str) -> date:
    if not text:
        return default
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError as exc:
        raise HTTPException(400, f"{what} must be a date like 2026-05-29.") from exc


# ====================================================================== Scheduler
MODELS = ("local", "none", "embed")
PRESETS = {  # sensible first settings per job type (times from the book's walkthroughs)
    "Daily Briefing": {"kind": "trading days", "at": "07:30"},
    "Fetch end-of-day data": {"kind": "trading days", "at": "19:00"},
    "Index new documents": {"kind": "daily", "at": "20:30"},
    "Weekly Review": {"kind": "weekly", "at": "09:00", "day": "Sat"},
    "Backup": {"kind": "daily", "at": "23:30"},
    "News Pipeline: fetch": {"kind": "every N minutes", "at": "08:00", "until": "23:00",
                             "minutes": 15},
    "News Pipeline: score": {"kind": "daily", "at": "23:30"},
    "Monthly update check": {"kind": "monthly", "at": "10:00", "day": "1"},
}


class JobIn(BaseModel):
    job: str
    market: str = "IN"
    kind: str = "trading days"
    at: str = "07:30"
    day: str = "Sat"
    minutes: int = 15
    until: str = "23:00"
    model: str | None = None


def _schedule(body: JobIn):
    from ... import scheduler
    if body.job not in scheduler.JOB_TYPES:
        raise HTTPException(400, f"Job must be one of: {', '.join(scheduler.JOB_TYPES)}.")
    _mkt(body.market)
    if body.model is not None and body.model not in MODELS:
        raise HTTPException(400, f"Model must be one of: {', '.join(MODELS)}.")
    if body.kind == "every N minutes" and not 5 <= int(body.minutes) <= 240:
        raise HTTPException(400, "Every (minutes) must be between 5 and 240.")
    if body.kind == "monthly" and not (str(body.day).isdigit() and 1 <= int(body.day) <= 28):
        raise HTTPException(400, "Day of month must be between 1 and 28.")
    if body.kind == "weekly" and body.day[:3] not in scheduler.WEEKDAYS:
        raise HTTPException(400, f"Day must be one of {', '.join(scheduler.WEEKDAYS)}.")
    sch = scheduler.Schedule(kind=body.kind, at=body.at.strip(), day=str(body.day),
                             minutes=int(body.minutes), until=body.until.strip())
    try:
        sch.validate()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return sch


def _next_run(job: dict[str, Any]) -> str | None:
    from ... import scheduler
    from ...news import clock
    try:
        sch = scheduler.Schedule(**job.get("schedule", {}))
        nxt = scheduler.next_occurrence(sch, job["mkt"], datetime.now(UTC))
    except Exception:
        return None
    if nxt is None:
        return None
    mk = job["mkt"] if job["mkt"] in ("IN", "US") else "IN"
    return f"{nxt.astimezone(clock.zone(mk)).strftime('%a %d %b %H:%M')} {clock.zone_label(mk)}"


def _sched_state() -> dict[str, Any]:
    from ... import scheduler
    scheduler.ensure_started()
    rows = scheduler.jobs()
    jobs = [{"id": r["id"], "job": r["job"], "mkt": r["mkt"], "when": r["when"],
             "model": r["model"], "enabled": r.get("enabled", True),
             "last_run": r.get("last_run") or "", "last_result": r.get("last_result") or "",
             "next_run": _next_run(r) if r.get("enabled", True) else None,
             "schedule": r.get("schedule", {})} for r in rows]
    local = all(r["model"] in MODELS for r in rows)
    return _clean({
        "jobs": jobs, "paused": scheduler.paused(), "catch_up": scheduler.catch_up_enabled(),
        "health_alert": scheduler.health_alert_enabled(), "running": scheduler.running(),
        "cost": "₹0 / $0" if local else "metered", "all_local": local,
        "job_types": list(scheduler.JOB_TYPES), "kinds": list(scheduler.KINDS),
        "weekdays": list(scheduler.WEEKDAYS), "models": list(MODELS), "presets": PRESETS,
        "default_model": scheduler.DEFAULT_MODEL,
    })


@router.get("/api/automate/scheduler")
def scheduler_state() -> dict[str, Any]:
    return _sched_state()


@router.post("/api/automate/scheduler/preview")
def scheduler_preview(body: JobIn) -> dict[str, Any]:
    from ... import scheduler
    sch = _schedule(body)
    model = body.model or scheduler.DEFAULT_MODEL[body.job]
    nxt = _next_run({"schedule": sch.__dict__, "mkt": body.market})
    return {"when": sch.describe(body.market), "model": model, "next_run": nxt,
            "text": f"{body.job}, {body.market}, {sch.describe(body.market)}, model {model}"}


@router.post("/api/automate/scheduler/jobs")
def scheduler_add(body: JobIn) -> dict[str, Any]:
    from ... import scheduler
    sch = _schedule(body)
    try:
        jid = scheduler.add_job(body.job, body.market, sch, body.model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**_sched_state(), "added": jid}


def _job(job_id: int) -> dict[str, Any]:
    from ... import scheduler
    try:
        return scheduler.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(400, f"There is no job #{job_id}. Refresh the list.") from exc


@router.post("/api/automate/scheduler/jobs/{job_id}/run")
def scheduler_run(job_id: int) -> dict[str, Any]:
    from ... import scheduler
    _job(job_id)
    entry = scheduler.run_now(job_id)
    return {**_sched_state(), "entry": _clean(entry)}


class OnIn(BaseModel):
    on: bool


@router.post("/api/automate/scheduler/jobs/{job_id}/enabled")
def scheduler_enable(job_id: int, body: OnIn) -> dict[str, Any]:
    from ... import scheduler
    _job(job_id)
    scheduler.set_enabled(job_id, body.on)
    return _sched_state()


@router.post("/api/automate/scheduler/jobs/{job_id}/delete")
def scheduler_delete(job_id: int) -> dict[str, Any]:
    from ... import scheduler
    _job(job_id)
    scheduler.delete_job(job_id)
    return _sched_state()


@router.get("/api/automate/scheduler/log")
def scheduler_log(job_id: int | None = None) -> list[dict[str, Any]]:
    from ... import scheduler
    return _clean([{k: r.get(k) for k in ("id", "start", "job", "mkt", "status", "rows",
                                          "duration_s", "model", "trigger", "output")}
                   for r in scheduler.log(job_id)])


@router.post("/api/automate/scheduler/pause")
def scheduler_pause(body: OnIn) -> dict[str, Any]:
    from ... import scheduler
    scheduler.pause_all(body.on)
    return _sched_state()


class SchedSettingsIn(BaseModel):
    catch_up: bool | None = None
    health_alert: bool | None = None


@router.post("/api/automate/scheduler/settings")
def scheduler_settings(body: SchedSettingsIn) -> dict[str, Any]:
    from ... import scheduler
    if body.catch_up is not None:
        scheduler.set_catch_up(body.catch_up)
    if body.health_alert is not None:
        scheduler.set_health_alert(body.health_alert)
    return _sched_state()


# ====================================================================== News Pipeline
INDEXES = {"IN": ["NIFTY", "SENSEX", "BANKNIFTY"], "US": ["SPY", "QQQ", "DIA"]}
SCORER_NAMES = {"finbert": "FinBERT", "llm": "Local model"}
RULES = ("Leave disagreements out of tests", "Use FinBERT's label", "Use the Local model's label",
         "Mark as unclear and read by hand")
_news: dict[str, dict[str, Any]] = {}


def _nstate(market: str) -> dict[str, Any]:
    return _news.setdefault(_mkt(market), {})


def _heads_rows(df) -> list[dict[str, Any]]:
    cols = ["id", "source", "symbol", "headline", "original", "lang", "published", "seen",
            "tradable_from"]
    out = []
    for r in df.select([c for c in cols if c in df.columns]).iter_rows(named=True):
        r["original"] = r.get("original") if r.get("lang") != "en" else ""
        out.append(r)
    return out


def _cmp_json(cmp) -> dict[str, Any]:
    table = cmp.table()
    dis = cmp.disagreements()
    return {"n": cmp.n, "agreement": cmp.agreement, "opposite": cmp.opposite(),
            "disagreements_n": dis.height, "name_a": SCORER_NAMES.get(cmp.name_a, cmp.name_a),
            "name_b": SCORER_NAMES.get(cmp.name_b, cmp.name_b),
            "table_columns": table.columns, "table": table.to_dicts(),
            "disagreements": dis.to_dicts(), "facts": cmp.facts()}


def _es_json(es) -> dict[str, Any]:
    m, lo, hi = es.drift()
    ct = es.cost_table()
    return {"n": es.n, "day0": es.day0(), "trials": es.trials, "drift": m, "drift_lo": lo,
            "drift_hi": hi, "after_20": m - 20, "preset_bps": es.preset_bps(),
            "benchmark": es.benchmark, "costs": es.costs, "entry": es.entry,
            "window": list(es.window), "side": es.side,
            "path": es.path.to_dicts(),
            "cost_table": ct.drop("cost_bps").to_dicts(), "skipped": es.skipped[:5],
            "facts": es.facts()}


def _news_out(market: str) -> dict[str, Any]:
    from ... import costs, news
    from ...news import feeds, scoring
    s = _nstate(market)
    heads = s.get("heads")
    tray = news.unstamped(market)
    scored = s.get("scored") or {}
    view = None
    if scored:
        base = next(iter(scored.values()))
        view = {"rows": _heads_rows(base), "scorers": []}
        for key, df in scored.items():
            view["scorers"].append({"key": key, "name": SCORER_NAMES[key],
                                    "used": str(df["scorer_used"][0]) if df.height else "",
                                    "labels": df["label"].to_list(), "paths": df["path"].to_list()})
    watch = (config.get("watchlists", {}) or {}).get(market, [])
    contact = str(config.get("data.edgar_contact", "") or "")
    return _clean({
        "market": market,
        "sources": [{"key": k, "label": lab, "market": m} for k, (lab, m) in news.SOURCES.items()
                    if m in (market, "ANY")],
        "watchlist": watch, "edgar_contact_set": "@" in contact,
        "finbert_available": scoring.finbert_available(),
        "indexes": INDEXES[market],
        "cost_presets": [p for p in costs.PROFILES if p.startswith(market)],
        "rules": list(RULES), "gdelt_interval": feeds.GDELT_INTERVAL,
        "status": news.last_status() if heads is not None else {},
        "fetched": heads is not None, "range": s.get("range"),
        "heads": _heads_rows(heads) if heads is not None else [],
        "tray": tray.to_dicts() if heads is not None else [],
        "scored": view,
        "compare": _cmp_json(s["cmp"]) if s.get("cmp") is not None else None,
        "study": _es_json(s["es"]) if s.get("es") is not None else None,
        "rule_saved": s.get("rule_saved"),
    })


@router.get("/api/automate/news/state")
def news_state(market: str = "IN") -> dict[str, Any]:
    return _news_out(_mkt(market))


class ContactIn(BaseModel):
    contact: str


@router.post("/api/automate/news/contact")
def news_contact(body: ContactIn) -> dict[str, Any]:
    c = body.contact.strip()
    if "@" not in c or " " not in c:
        raise HTTPException(400, "Enter a name and an email, like: Asha Rao asha@example.com")
    config.set_value("data.edgar_contact", c)
    return {"saved": True}


class FetchIn(BaseModel):
    market: str = "IN"
    sources: list[str] = Field(default_factory=list)
    rss: str = ""
    watchlists: list[str] | None = None
    start: str | None = None
    end: str | None = None


@router.post("/api/automate/news/fetch")
def news_fetch(body: FetchIn) -> dict[str, Any]:
    from ... import news
    s = _nstate(body.market)
    allowed = {k for k, (_, m) in news.SOURCES.items() if m in (body.market, "ANY")}
    chosen = [x for x in body.sources if x in allowed]
    bad = [x for x in body.sources if x not in allowed]
    if bad:
        raise HTTPException(400, f"Unknown source for {body.market}: {', '.join(bad)}.")
    if body.rss.strip():
        if not body.rss.strip().startswith(("http://", "https://")):
            raise HTTPException(400, "The extra RSS feed must be a web address starting with https://.")
        chosen.append(f"rss:{body.rss.strip()}")
    if not chosen:
        raise HTTPException(400, "Tick at least one feed, then click Fetch now.")
    end = _day(body.end, date.today(), "To")
    start = _day(body.start, end - timedelta(days=30), "From")
    if start > end:
        raise HTTPException(400, "From must be on or before To.")
    query = None
    if body.watchlists:
        query = " OR ".join(f'"{x}"' for x in body.watchlists[:5])
    s["heads"] = news.fetch(chosen, market=body.market, start=start, end=end, query=query)
    s["range"] = [start.isoformat(), end.isoformat()]
    for k in ("scored", "cmp", "es", "rule_saved"):
        s.pop(k, None)
    return _news_out(body.market)


class ScoreIn(BaseModel):
    market: str = "IN"
    finbert: bool = True
    llm: bool = True


@router.post("/api/automate/news/score")
def news_score(body: ScoreIn) -> dict[str, Any]:
    from ... import news
    s = _nstate(body.market)
    heads = s.get("heads")
    if heads is None or not heads.height:
        raise HTTPException(400, "Fetch headlines in the Sources tab first.")
    if not (body.finbert or body.llm):
        raise HTTPException(400, "Tick FinBERT, Local model or both, then click Score.")
    scored = {}
    for key, on in (("finbert", body.finbert), ("llm", body.llm)):
        if on:
            scored[key] = news.score(heads, scorer=key)
    s["scored"] = scored
    for k in ("cmp", "es", "rule_saved"):
        s.pop(k, None)
    return _news_out(body.market)


class MarketIn(BaseModel):
    market: str = "IN"


@router.post("/api/automate/news/compare")
def news_compare(body: MarketIn) -> dict[str, Any]:
    from ... import news
    s = _nstate(body.market)
    scored = s.get("scored") or {}
    if len(scored) < 2:
        raise HTTPException(400, "Score with both FinBERT and Local model, then click Compare scorers.")
    s["cmp"] = news.compare(scored["finbert"], scored["llm"])
    s.pop("es", None)
    return _news_out(body.market)


class RuleIn(BaseModel):
    market: str = "IN"
    rule: str
    note: str = ""


@router.post("/api/automate/news/rule")
def news_rule(body: RuleIn) -> dict[str, Any]:
    s = _nstate(body.market)
    cmp = s.get("cmp")
    if cmp is None:
        raise HTTPException(400, "Click Compare scorers first; the rule is about their disagreements.")
    if body.rule not in RULES:
        raise HTTPException(400, f"Rule must be one of: {'; '.join(RULES)}.")
    rid = store().add("notes", {"kind": "news disagreement rule", "rule": body.rule,
                                "note": body.note.strip(), "market": body.market,
                                "agreement": round(cmp.agreement, 3)}, tag="news-rule")
    s["rule_saved"] = {"id": rid, "rule": body.rule}
    return _news_out(body.market)


class StudyIn(BaseModel):
    market: str = "IN"
    group: str = "Both agreed: positive"
    window: tuple[int, int] = (-5, 10)
    benchmark: str = "NIFTY"
    costs: str = "IN-equity-delivery"
    entry: str = "tradable_from"


@router.post("/api/automate/news/event-study")
def news_event_study(body: StudyIn) -> dict[str, Any]:
    from ... import news
    s = _nstate(body.market)
    cmp = s.get("cmp")
    if cmp is None:
        raise HTTPException(400, "Score with both scorers and click Compare scorers first: the "
                                 "event groups are the headlines both scorers agreed on.")
    if body.group not in ("Both agreed: positive", "Both agreed: negative"):
        raise HTTPException(400, "Event group must be Both agreed: positive or negative.")
    lo, hi = int(body.window[0]), int(body.window[1])
    if not (-10 <= lo <= 0 <= hi <= 20) or lo >= hi:
        raise HTTPException(400, "Window must run from between −10 and 0 to between 0 and +20 sessions.")
    if body.benchmark not in INDEXES[body.market]:
        raise HTTPException(400, f"Index must be one of {', '.join(INDEXES[body.market])}.")
    try:
        s["es"] = news.event_study(cmp.agreed(body.group.split()[-1]), window=(lo, hi),
                                   benchmark=body.benchmark, entry=body.entry, costs=body.costs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _news_out(body.market)


# ====================================================================== ML Lab
_ml: dict[str, dict[str, Any]] = {}


@router.get("/api/automate/ml/meta")
def ml_meta() -> dict[str, Any]:
    from ... import ml
    from ...ml import features, scenarios
    return {"features": [{"key": f, "known_at": ml.KNOWN_AT[f]} for f in ml.FEATURES],
            "noise": {"key": ml.NOISE, "known_at": ml.KNOWN_AT[ml.NOISE]},
            "labels": [{"key": k, "name": v, "question": ml.LABEL_QUESTION[k]}
                       for k, v in ml.LABELS.items()],
            "horizon": features.HORIZON, "scenario_engine": scenarios.ENGINE,
            "sklearn": ml.sklearn_available(), "default_symbol": DEFAULT_SYMBOL}


def _card_json(card, shuffle=None) -> dict[str, Any]:
    from ... import ml
    sp = card.split
    return {"label": sp.ds.label, "label_name": ml.LABELS[sp.ds.label],
            "question": ml.LABEL_QUESTION[sp.ds.label], "features": sp.ds.features,
            "symbol": getattr(sp.ds, "symbol", ""), "engine": card.model.engine,
            "scores": card.scores, "baselines": [{"name": k, "score": v}
                                                 for k, v in card.baselines.items()],
            "importance": [{"feature": k, "points": v, "control": k == ml.NOISE}
                           for k, v in card.importance.items()],
            "overfit": card.overfit, "trials": card.trials, "grade": card.grade, "why": card.why,
            "spans": {b: sp.span(b) for b in ("train", "valid", "test")},
            "rows": {"train": len(sp.train), "valid": len(sp.valid), "test": len(sp.test)},
            "purge": sp.purge, "embargo": sp.embargo, "text": card.text(),
            "facts": card.facts() + (shuffle.facts()[:1] if shuffle else []),
            "shuffle": None if shuffle is None else {"score": shuffle.score, "folds": shuffle.folds,
                                                     "label": shuffle.label,
                                                     "text": shuffle.text()}}


def _ml_out(market: str) -> dict[str, Any]:
    s = _ml.get(market, {})
    card = s.get("card")
    sc, hist = s.get("sc"), s.get("hist")
    out: dict[str, Any] = {"market": market, "card": _card_json(card, s.get("shuffle")) if card else None,
                           "accepted": s.get("accepted"), "sent": s.get("sent")}
    if sc is not None:
        from ... import ml
        out["scenarios"] = {**sc.to_dict(), "symbol": s.get("sc_symbol"), "facts": sc.facts()}
        out["history"] = {"rows": hist.to_dicts() if hist is not None else [],
                          "facts": ml.history_facts(hist) if hist is not None else []}
    else:
        out["scenarios"], out["history"] = None, None
    return _clean(out)


@router.get("/api/automate/ml/state")
def ml_state(market: str = "IN") -> dict[str, Any]:
    return _ml_out(_mkt(market))


class TrainIn(BaseModel):
    market: str = "IN"
    symbol: str = ""
    start: str = "2010-01-01"
    end: str = "2026-05-29"
    features: list[str] = Field(default_factory=list)
    noise: bool = True
    label: str = "high_vol_next_10"
    train_pct: int = 60
    valid_pct: int = 20
    purge: int = 10
    embargo: int = 0
    rule: str = "vol_20 > 1"


def _bars(symbol: str, market: str, start: str, end: str):
    from ... import data
    s = _day(start, date(2010, 1, 1), "From")
    e = _day(end, date(2026, 5, 29), "To")
    if s >= e:
        raise HTTPException(400, "From must be before To.")
    sym = symbol.strip().upper() or DEFAULT_SYMBOL[market]
    try:
        return sym, data.get(sym, market=market, start=s, end=e)
    except Exception as exc:
        raise HTTPException(400, f"No price history for {sym} ({market}): {str(exc)[:120]}") from exc


@router.post("/api/automate/ml/train")
def ml_train(body: TrainIn) -> dict[str, Any]:
    from ... import ml
    market = _mkt(body.market)
    if not body.features:
        raise HTTPException(400, "Tick at least one feature in Dataset.")
    if body.label not in ml.LABELS:
        raise HTTPException(400, f"Label must be one of: {', '.join(ml.LABELS.values())}.")
    tr, va = body.train_pct / 100, body.valid_pct / 100
    if tr <= 0 or va <= 0 or tr + va >= 1:
        raise HTTPException(400, "Train, validation and test must each be more than 0% of history.")
    sym, bars = _bars(body.symbol, market, body.start, body.end)
    try:
        ds = ml.dataset(bars, label=body.label, features=body.features, noise_column=body.noise)
        ds.symbol = sym
        split = ml.time_split(ds, train=tr, valid=va, test=round(1 - tr - va, 6),
                              purge=int(body.purge), embargo=int(body.embargo))
        model = ml.boosting(split)
        baselines = ["majority"] + ([body.rule.strip()] if body.rule.strip() else [])
        card = ml.report(model, split, baselines=baselines)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    s = _ml.setdefault(market, {})
    s.update(card=card, shuffle=None, accepted=None)
    return _ml_out(market)


@router.post("/api/automate/ml/shuffle")
def ml_shuffle(body: MarketIn) -> dict[str, Any]:
    from ... import ml
    s = _ml.get(_mkt(body.market), {})
    card = s.get("card")
    if card is None:
        raise HTTPException(400, "Click Train baseline first; the Shuffle test reuses its data.")
    s["shuffle"] = ml.shuffle_test(card.split, honest=card.scores["test"])
    return _ml_out(body.market)


class AcceptIn(BaseModel):
    market: str = "IN"
    text: str = ""


@router.post("/api/automate/ml/accept")
def ml_accept(body: AcceptIn) -> dict[str, Any]:
    s = _ml.get(_mkt(body.market), {})
    card = s.get("card")
    if card is None:
        raise HTTPException(400, "Train a model first; Accept saves its model card.")
    rid = store().add("notes", _clean({"kind": "model_card", **card.to_dict(),
                                       "explanation": body.text}), tag="journal")
    s["accepted"] = rid
    return _ml_out(body.market)


class ScenIn(BaseModel):
    market: str = "IN"
    symbol: str = ""
    start: str = "2010-01-01"
    end: str = "2026-05-29"
    horizon: int = 10


@router.post("/api/automate/ml/scenarios")
def ml_scenarios(body: ScenIn) -> dict[str, Any]:
    from ... import ml
    market = _mkt(body.market)
    if not 5 <= body.horizon <= 30:
        raise HTTPException(400, "Horizon must be between 5 and 30 sessions.")
    sym, bars = _bars(body.symbol, market, body.start, body.end)
    try:
        sc = ml.vol_scenarios(bars, horizon=int(body.horizon))
        hist = ml.scored_history(bars, horizon=int(body.horizon))
    except ValueError as exc:
        raise HTTPException(400, f"{exc}. Widen From / To.") from exc
    s = _ml.setdefault(market, {})
    s.update(sc=sc, hist=hist, sc_symbol=sym, sent=None)
    return _ml_out(market)


@router.post("/api/automate/ml/send-to-sizer")
def ml_send(body: MarketIn) -> dict[str, Any]:
    s = _ml.get(_mkt(body.market), {})
    sc = s.get("sc")
    if sc is None:
        raise HTTPException(400, "Click Volatility scenarios first.")
    rid = store().add("notes", _clean({"kind": "vol_scenarios", "symbol": s.get("sc_symbol"),
                                       "market": body.market, **sc.to_dict()}), tag="sizer")
    s["sent"] = rid
    return _ml_out(body.market)


# ====================================================================== Agents
TEAM_KEYS = {"builtin": "Built-in research team", "tradingagents": "TradingAgents",
             "ai-hedge-fund": "ai-hedge-fund"}
_runs: dict[str, dict[str, Any]] = {}
_runs_lock = threading.Lock()


@router.get("/api/automate/agents/meta")
def agents_meta() -> dict[str, Any]:
    from ... import agents
    return {"teams": [{"key": k, "title": t, "installed": k == "builtin" or agents.is_installed(k),
                       "tag": None if k == "builtin" else agents.pin(k)}
                      for k, t in TEAM_KEYS.items()],
            "tools": list(agents.TOOLS), "default_symbol": DEFAULT_SYMBOL,
            "default_as_of": "2026-05-29", "latest": _latest_run()}


def _latest_run() -> str | None:
    with _runs_lock:
        if not _runs:
            return None
        return max(_runs.values(), key=lambda r: r["started"])["id"]


class RunIn(BaseModel):
    market: str = "IN"
    team: str = "builtin"
    symbol: str = ""
    as_of: str = "2026-05-29"
    mask: bool = True
    max_steps: int = 40
    max_cost: float = 0.50


def _prop_json(p) -> dict[str, Any]:
    return {**p.to_dict(), "facts": p.facts(), "sections": p.sections,
            "warnings": p.warnings, "bull": len(p.sections.get("Bull", [])),
            "bear": len(p.sections.get("Bear", [])),
            "risk": len(p.sections.get("Risk manager", []))}


def _drive(run: dict[str, Any]) -> None:
    team = run["team"]
    try:
        for ev in team.steps(run["symbol"], run["market"]):
            run["events"].append(_clean(ev))
        run["proposal"] = team.result
        run["status"] = "stopped" if team.result and team.result.stopped else "done"
    except Exception as exc:  # a failing run is reported, never raised into the server
        run["status"], run["error"] = "error", f"{type(exc).__name__}: {str(exc)[:300]}"


def _run_out(run: dict[str, Any]) -> dict[str, Any]:
    p = run.get("proposal")
    return _clean({"id": run["id"], "status": run["status"], "error": run.get("error"),
                   "events": list(run["events"]), "warning": run.get("warning", ""),
                   "config_path": run.get("config_path"), "settings": run["settings"],
                   "proposal": _prop_json(p) if p is not None else None,
                   "sent": run.get("sent"), "rejected": run.get("rejected")})


@router.post("/api/automate/agents/run")
def agents_run(body: RunIn) -> dict[str, Any]:
    from ... import agents
    market = _mkt(body.market)
    if body.team not in TEAM_KEYS:
        raise HTTPException(400, f"Team must be one of: {', '.join(TEAM_KEYS.values())}.")
    if not 1 <= body.max_steps <= 200:
        raise HTTPException(400, "Budget: max steps must be between 1 and 200.")
    if not 0 <= body.max_cost <= 50:
        raise HTTPException(400, "Budget: max cost must be between $0 and $50.")
    as_of = _day(body.as_of, date(2026, 5, 29), "As-of date")
    symbol = body.symbol.strip().upper() or DEFAULT_SYMBOL[market]
    with _runs_lock:
        if any(r["status"] == "running" for r in _runs.values()):
            raise HTTPException(400, "A run is already going. Wait for it, or click Stop.")
    path = agents.write_config(body.team, model="local", as_of=as_of, mask_names=body.mask,
                               max_steps=body.max_steps, max_cost=body.max_cost)
    team = agents.load(body.team, model="local", as_of=as_of, mask_names=body.mask,
                       budget={"max_steps": body.max_steps, "max_cost": body.max_cost})
    rid = uuid.uuid4().hex[:10]
    run = {"id": rid, "status": "running", "events": [], "team": team, "symbol": symbol,
           "market": market, "warning": team.warning, "config_path": str(path),
           "started": datetime.now(UTC).isoformat(),
           "settings": {"team": TEAM_KEYS[body.team], "symbol": symbol, "market": market,
                        "as_of": as_of.isoformat(), "mask": body.mask,
                        "max_steps": body.max_steps, "max_cost": body.max_cost}}
    with _runs_lock:
        _runs[rid] = run
    threading.Thread(target=_drive, args=(run,), daemon=True, name=f"agents-{rid}").start()
    return _run_out(run)


def _run(run_id: str) -> dict[str, Any]:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(400, "That run is not in this session any more. Click Run again.")
    return run


@router.get("/api/automate/agents/runs/{run_id}")
def agents_get(run_id: str) -> dict[str, Any]:
    return _run_out(_run(run_id))


@router.post("/api/automate/agents/runs/{run_id}/stop")
def agents_stop(run_id: str) -> dict[str, Any]:
    run = _run(run_id)
    if run["status"] == "running":
        run["team"].stop()
    return _run_out(run)


@router.post("/api/automate/agents/runs/{run_id}/send")
def agents_send(run_id: str) -> dict[str, Any]:
    from ... import agents
    run = _run(run_id)
    p = run.get("proposal")
    if p is None:
        raise HTTPException(400, "Wait for the run to finish; the Proposal card appears then.")
    if run.get("sent"):
        return _run_out(run)
    try:
        run["sent"] = agents.propose_to_builder(p)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _run_out(run)


class RejectIn(BaseModel):
    reason: str


@router.post("/api/automate/agents/runs/{run_id}/reject")
def agents_reject(run_id: str, body: RejectIn) -> dict[str, Any]:
    from ... import agents
    run = _run(run_id)
    p = run.get("proposal")
    if p is None:
        raise HTTPException(400, "There is no proposal to reject yet.")
    if not body.reason.strip():
        raise HTTPException(400, "Write a one-line reason for the journal, then click Reject.")
    run["rejected"] = {"id": agents.reject(p, body.reason.strip()), "reason": body.reason.strip()}
    return _run_out(run)


# ====================================================================== Plugins
KIND_LABELS = {"Screen": "screen", "Strategy": "strategy", "Report": "report"}
_installs: dict[str, dict[str, Any]] = {}
_reports: dict[str, Any] = {}


def _plugin_name(name: str) -> str:
    from ... import plugin
    if name not in plugin.installed():
        raise HTTPException(400, f"There is no plugin called {name!r}. Click New from template.")
    return name


def _check_json(rep) -> dict[str, Any]:
    return {"name": rep.name, "passed": rep.passed, "red_flags": rep.red_flags,
            "items": [{"name": i.name, "ok": i.ok, "value": i.value,
                       "shown": i.always_shown or not i.ok, "hits": [str(h) for h in i.hits[:5]]}
                      for i in rep.items],
            "summary": rep.text(details=False).splitlines()[-1], "text": rep.text(),
            "facts": rep.facts()}


@router.get("/api/automate/plugins")
def plugins_state() -> dict[str, Any]:
    from ... import agents, plugin
    rows = []
    for n in plugin.installed():
        row: dict[str, Any] = {"name": n, "folder": str(plugin.folder(n))}
        try:
            m = plugin.manifest(n)
            row.update(kind=m.get("kind"), markets=m.get("markets", []),
                       network=m.get("network", []), licence=m.get("licence"), error=None)
        except (OSError, ValueError) as exc:
            row.update(kind=None, markets=[], network=[], error=f"cannot read plugin.toml ({exc})")
        s = plugin.status(n)
        row["status"] = {"checked": s.get("checked", ""), "passed": bool(s.get("passed")),
                         "red_flags": s.get("red_flags", 0), "enabled": bool(s.get("enabled"))}
        rows.append(row)
    adapters = []
    for key, a in agents.ADAPTERS.items():
        plan = agents.install_plan(key)
        adapters.append({"key": key, "title": a["title"], "licence": a["licence"], "repo": a["repo"],
                         "tag": plan.tag, "installed": agents.is_installed(key),
                         "tools": list(plan.tools), "plan": plan.text(),
                         "install": _installs.get(key)})
    return _clean({"plugins": rows, "adapters": adapters, "kinds": list(KIND_LABELS),
                   "plugins_dir": str(plugin.plugins_dir()),
                   "reports": {k: _check_json(v) for k, v in _reports.items()}})


class NewIn(BaseModel):
    name: str
    kind: str = "Report"


@router.post("/api/automate/plugins/new")
def plugins_new(body: NewIn) -> dict[str, Any]:
    from ... import plugin
    kind = KIND_LABELS.get(body.kind, body.kind.lower())
    try:
        msg = plugin.new(body.name.strip(), kind)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**plugins_state(), "message": msg, "name": body.name.strip()}


@router.get("/api/automate/plugins/{name}/folder")
def plugins_folder(name: str) -> dict[str, Any]:
    from ... import plugin
    root = plugin.folder(_plugin_name(name))
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts)
    return {"path": str(root), "files": files}


@router.post("/api/automate/plugins/{name}/check")
def plugins_check(name: str) -> dict[str, Any]:
    from ... import plugin
    rep = plugin.check(_plugin_name(name))
    _reports[name] = rep
    return {**plugins_state(), "report": _check_json(rep)}


@router.post("/api/automate/plugins/{name}/enable")
def plugins_enable(name: str, body: OnIn) -> dict[str, Any]:
    from ... import plugin
    n = _plugin_name(name)
    if body.on and not plugin.status(n).get("passed"):
        raise HTTPException(400, f"{n} cannot be enabled: run the Plugin check until it passes.")
    msg = plugin.enable(n, on=body.on)
    return {**plugins_state(), "message": msg}


class PluginRunIn(BaseModel):
    market: str = "IN"
    symbol: str = ""
    start: str = "2024-06-01"
    end: str = "2026-05-29"


@router.post("/api/automate/plugins/{name}/run")
def plugins_run(name: str, body: PluginRunIn) -> dict[str, Any]:
    from ... import plugin
    n = _plugin_name(name)
    market = _mkt(body.market)
    s = _day(body.start, date(2024, 6, 1), "From")
    e = _day(body.end, date(2026, 5, 29), "To")
    sym = body.symbol.strip().upper() or DEFAULT_SYMBOL[market]
    try:
        res = plugin.run(n, sym, market, start=s, end=e)
    except (PermissionError, ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    out: dict[str, Any] = {"name": n, "kind": res.kind, "symbol": sym, "market": market,
                           "columns": res.table.columns, "height": res.table.height,
                           "rows": res.table.head(500).to_dicts(), "facts": res.facts(),
                           "backtest": None}
    if res.backtest is not None:
        bt = res.backtest
        out["backtest"] = {"dates": list(bt.dates), "equity": list(bt.equity),
                           "grade": bt.card().grade, "facts": list(bt.facts())}
    return _clean(out)


def _do_install(key: str) -> None:
    from ... import agents
    try:
        msg = agents.install(key)
        ok = msg.startswith("Installed")
        _installs[key] = {"state": "done" if ok else "failed", "message": msg}
    except Exception as exc:
        _installs[key] = {"state": "failed", "message": f"{type(exc).__name__}: {str(exc)[:300]}"}


@router.post("/api/automate/plugins/install/{key}")
def plugins_install(key: str) -> dict[str, Any]:
    from ... import agents
    if key not in agents.ADAPTERS:
        raise HTTPException(400, f"Unknown agent plugin {key!r}; choose {', '.join(agents.ADAPTERS)}.")
    if agents.is_installed(key):
        raise HTTPException(400, f"{agents.ADAPTERS[key]['title']} is already installed.")
    if (_installs.get(key) or {}).get("state") == "running":
        return plugins_state()
    _installs[key] = {"state": "running",
                      "message": "Fetching the official repository at the pinned tag…"}
    threading.Thread(target=_do_install, args=(key,), daemon=True, name=f"install-{key}").start()
    return plugins_state()
