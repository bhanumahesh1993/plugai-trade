"""Automate › Scheduler: jobs on NSE / NYSE calendars, run by the lab itself (Chapters 28, 31, 34).

Jobs live in the store table ``jobs`` (Job, Mkt, When, Model, Last run); every
run writes a row to ``job_log``. :func:`run_due` runs whatever is due now;
:func:`run_now` runs one job on demand; :func:`ensure_started` starts one
background thread per process (idempotent). Missed runs (a sleeping laptop)
are caught up at the next check when *Catch up missed runs* is on.

Each job type calls into its module only if that module is importable; a
missing module is logged as "not available", never raised. No job can place an
order: the lab has no order code.
"""

from __future__ import annotations

import importlib
import os
import threading
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from . import config
from .news import clock
from .store import default as store

JOB_TYPES = (
    "Daily Briefing", "Fetch end-of-day data", "Index new documents", "Weekly Review", "Backup",
    "News Pipeline: fetch", "News Pipeline: score", "Monthly update check",
)
KINDS = ("trading days", "daily", "weekly", "monthly", "every N minutes")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DEFAULT_MODEL = {"Daily Briefing": "local", "Fetch end-of-day data": "none",
                 "Index new documents": "embed", "Weekly Review": "local", "Backup": "none",
                 "News Pipeline: fetch": "none", "News Pipeline: score": "local",
                 "Monthly update check": "none"}
GRACE = timedelta(minutes=30)  # a run later than this counts as "missed"
HEALTH_SILENCE = timedelta(hours=2)
CHECK_EVERY = 60.0


# ---------------------------------------------------------------- settings
def paused() -> bool:
    """True when Pause all is on: nothing runs on schedule (Run now still works)."""
    return bool(config.get("scheduler.paused", False))


def pause_all(on: bool = True) -> None:
    """Switch Pause all on or off."""
    config.set_value("scheduler.paused", bool(on))


def catch_up_enabled() -> bool:
    """Catch up missed runs when the computer wakes (default on)."""
    return bool(config.get("scheduler.catch_up", True))


def set_catch_up(on: bool) -> None:
    config.set_value("scheduler.catch_up", bool(on))


def health_alert_enabled() -> bool:
    """Health alert: a SIMULATED alert when a news feed is silent for two market hours."""
    return bool(config.get("scheduler.health_alert", False))


def set_health_alert(on: bool) -> None:
    config.set_value("scheduler.health_alert", bool(on))


# ---------------------------------------------------------------- schedule maths
@dataclass
class Schedule:
    """When a job runs, in the market's own time zone."""

    kind: str = "trading days"  # one of KINDS
    at: str = "07:30"  # HH:MM (first run of the day for "every N minutes")
    day: str = "Sat"  # weekly: weekday name; monthly: day of month as text
    minutes: int = 15  # every N minutes
    until: str = "23:00"  # every N minutes: last run of the day

    def validate(self) -> Schedule:
        """Raise ValueError unless times look like HH:MM and the kind is known."""
        if self.kind not in KINDS:
            raise ValueError(f"When must be one of {', '.join(KINDS)}")
        for t in (self.at, self.until):
            try:
                _hm(t)
            except (ValueError, AttributeError):
                raise ValueError(f"Times must look like 07:30 (got {t!r}).") from None
        return self

    def describe(self, market: str) -> str:
        z = clock.zone_label(market) if market in ("IN", "US") else ""
        if self.kind == "trading days":
            return f"Mon–Fri {self.at} {z}".strip()
        if self.kind == "daily":
            return f"Daily {self.at} {z}".strip()
        if self.kind == "weekly":
            return f"{self.day} {self.at} {z}".strip()
        if self.kind == "monthly":
            return f"Monthly day {self.day} {self.at} {z}".strip()
        return f"Every {self.minutes} min {self.at}–{self.until} {z}".strip()


def _tz(market: str):
    return clock.zone(market if market in ("IN", "US") else "IN")


def _hm(s: str) -> time:
    h, m = str(s).strip().split(":")
    return time(int(h), int(m))


def _runs_on(d: date, sch: Schedule, market: str) -> bool:
    if sch.kind in ("trading days", "every N minutes"):
        return clock.is_session_day(d, market if market in ("IN", "US") else "IN")
    if sch.kind == "weekly":
        return WEEKDAYS[d.weekday()] == sch.day[:3]
    if sch.kind == "monthly":
        return d.day == max(1, min(28, int(sch.day) if str(sch.day).isdigit() else 1))
    return True


def last_occurrence(sch: Schedule, market: str, now: datetime) -> datetime | None:
    """The latest scheduled run time at or before ``now`` (UTC), looking back 40 days."""
    tz = _tz(market)
    local = now.astimezone(tz)
    for back in range(40):
        d = local.date() - timedelta(days=back)
        if not _runs_on(d, sch, market):
            continue
        if sch.kind == "every N minutes":
            first, last = datetime.combine(d, _hm(sch.at), tz), datetime.combine(d, _hm(sch.until), tz)
            if local < first:
                continue
            step = timedelta(minutes=max(1, int(sch.minutes)))
            n = int((min(local, last) - first) / step)
            return (first + n * step).astimezone(UTC)
        t = datetime.combine(d, _hm(sch.at), tz)
        if t <= local:
            return t.astimezone(UTC)
    return None


def next_occurrence(sch: Schedule, market: str, now: datetime) -> datetime | None:
    """The next scheduled run after ``now`` (UTC), or ``None`` if none is near."""
    probe = now + timedelta(days=32 if sch.kind == "monthly" else 8)
    best = None
    t = last_occurrence(sch, market, probe)
    while t is not None and t > now:
        best = t
        t = last_occurrence(sch, market, t - timedelta(seconds=1))
    return best


# ---------------------------------------------------------------- job store
def _body(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("id", "created", "tag")}


def add_job(job: str, market: str = "IN", schedule: Schedule | dict | None = None,
            model: str | None = None, params: dict[str, Any] | None = None) -> int:
    """Add a job (nothing runs until its first scheduled time). Returns the job id."""
    if job not in JOB_TYPES:
        raise ValueError(f"unknown job type {job!r}; choose one of {', '.join(JOB_TYPES)}")
    sch = schedule if isinstance(schedule, Schedule) else Schedule(**(schedule or {}))
    sch.validate()
    body = {"job": job, "mkt": market, "schedule": sch.__dict__, "when": sch.describe(market),
            "model": model or DEFAULT_MODEL[job], "enabled": True, "params": params or {},
            "last_run": "", "last_result": "", "since": _now().isoformat()}
    return store().add("jobs", body, tag="job")


def jobs() -> list[dict[str, Any]]:
    """Every scheduled job, oldest first."""
    return sorted(store().all("jobs", tag="job"), key=lambda r: r["id"])


def get_job(job_id: int) -> dict[str, Any]:
    row = store().get("jobs", job_id)
    if row is None or row.get("tag") != "job":
        raise KeyError(f"No job {job_id}")
    return row


def delete_job(job_id: int) -> None:
    store().delete("jobs", job_id)


def set_enabled(job_id: int, on: bool) -> None:
    row = get_job(job_id)
    store().update("jobs", job_id, {**_body(row), "enabled": bool(on)})


def _save(job_id: int, **fields: Any) -> None:
    row = get_job(job_id)
    store().update("jobs", job_id, {**_body(row), **fields})


def log(job_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """The run log (newest first), for one job or all."""
    rows = store().all("job_log", limit=None if job_id else limit)
    if job_id is not None:
        rows = [r for r in rows if r.get("job_id") == job_id][:limit]
    return rows


# ---------------------------------------------------------------- runners
@dataclass
class Outcome:
    status: str  # ok | error | not available | skipped
    output: str
    rows: int = 0


def _module(name: str) -> Any | None:
    try:
        return importlib.import_module(f"plugai_trade.{name}")
    except Exception:
        return None


def _missing(name: str) -> Outcome:
    return Outcome("not available", f"The {name} module is not installed in this build yet.")


def _run_briefing(job: dict[str, Any]) -> Outcome:
    mod = _module("briefing")
    fn = next((getattr(mod, n) for n in ("scheduled_run", "generate", "run")
               if mod is not None and callable(getattr(mod, n, None))), None)
    if fn is None:
        return _missing("briefing")
    res = fn(market=job["mkt"])
    return Outcome("ok", f"Briefing generated: {str(res)[:160]}", 1)


def _run_eod(job: dict[str, Any]) -> Outcome:
    from . import data
    mkt = job["mkt"] if job["mkt"] in ("IN", "US") else "IN"
    syms = (config.get("watchlists", {}) or {}).get(mkt, [])
    rows, notes = 0, []
    for s in syms:
        try:
            df = data.get(s, market=mkt, fallback=False)
            rows += df.height
            notes.append(f"{s}: {df['source'][-1] if df.height else '-'}")
        except Exception as exc:
            notes.append(f"{s}: {str(exc)[:60]}")
    status = "ok" if rows else "error"
    return Outcome(status, f"{len(syms)} symbols · " + "; ".join(notes), rows)


def _run_index(job: dict[str, Any]) -> Outcome:
    mod = _module("docdesk.library")
    if mod is None:
        return _missing("Document Desk library")
    lib = mod.Library()
    folders = list(job.get("params", {}).get("folders") or config.get("library.folders", []) or [])
    if not folders:
        folders = sorted({str(Path(k).parent) for k in lib.docs if Path(k).is_absolute()})
    if not folders:
        return Outcome("skipped", "No library folders yet — use Add folder in Document Desk.")
    files = chunks = 0
    for f in folders:
        rep = lib.add_folder(f, market=job["mkt"] if job["mkt"] in ("IN", "US") else "IN")
        files, chunks = files + rep.files, chunks + rep.chunks
    return Outcome("ok", f"{files} new or changed files · {chunks} chunks", chunks)


def _run_review(job: dict[str, Any]) -> Outcome:
    jmod, rmod = _module("journal"), _module("journal.review")
    if jmod is None or rmod is None:
        return _missing("journal")
    trades = jmod.trades(job["mkt"] if job["mkt"] in ("IN", "US") else None)
    if not trades.height:
        return Outcome("skipped", "No journal trades yet — import a tradebook in Journal › Trades.")
    rev = rmod.build(trades)
    rid = rmod.save(rev)
    return Outcome("ok", f"Weekly Review saved (row {rid}); open Journal › Weekly Review.", 1)


def _run_backup(job: dict[str, Any]) -> Outcome:
    mod = _module("backup")
    if mod is None:
        return _missing("backup")
    from . import keys
    phrase = os.environ.get("PLUGAI_TRADE_BACKUP_PASSPHRASE") or keys.get_key("backup_passphrase")
    if not phrase:
        return Outcome("error", "Set a backup passphrase in Settings › Keys (name "
                                "'backup_passphrase') so the job can encrypt without asking.")
    folder = Path(job.get("params", {}).get("folder") or config.home().parent /
                  "plugai-trade-backups")
    return Outcome("ok", mod.create(folder, passphrase=phrase), 1)


def _news_sources(job: dict[str, Any]) -> list[str]:
    from . import news
    return list(job.get("params", {}).get("sources") or news.default_sources(job["mkt"]))


def _run_news_fetch(job: dict[str, Any]) -> Outcome:
    from . import news
    mkt = job["mkt"] if job["mkt"] in ("IN", "US") else "IN"
    today = date.today()
    heads = news.fetch(_news_sources(job), market=mkt, start=today - timedelta(days=1), end=today)
    status = news.last_status()
    live = heads.filter(~heads["source"].str.contains("synthetic")) if heads.height else heads
    detail = "; ".join(f"{k}: {v}" for k, v in status.items() if k in _news_sources(job))
    return Outcome("ok", f"{live.height} live headlines · {len(news.unstamped(mkt))} unstamped · "
                         f"{detail}", live.height)


def _run_news_score(job: dict[str, Any]) -> Outcome:
    from . import news
    mkt = job["mkt"] if job["mkt"] in ("IN", "US") else "IN"
    scorer = job.get("params", {}).get("scorer", "finbert")
    heads = news.stored(mkt, since=date.today() - timedelta(days=3))
    done = news.scored_ids(scorer)
    todo = heads.filter(~heads["id"].is_in(list(done))) if heads.height else heads
    if not todo.height:
        return Outcome("ok", "0 new headlines to score.", 0)
    out = news.score(todo, scorer=scorer)
    return Outcome("ok", f"{out.height} headlines scored · {out['scorer_used'][0]}", out.height)


def _run_update(job: dict[str, Any]) -> Outcome:
    from .data import httpkit
    if httpkit.offline():
        return Outcome("skipped", "Offline — the update check needs the network.")
    mod = _module("updater")
    if mod is None:
        return _missing("updater")
    lines: list[str] = []
    changed = mod.run(echo=lines.append)
    return Outcome("ok", f"{len(changed)} reference rows changed. " + " ".join(lines)[:300],
                   len(changed))


RUNNERS: dict[str, Callable[[dict[str, Any]], Outcome]] = {
    "Daily Briefing": _run_briefing, "Fetch end-of-day data": _run_eod,
    "Index new documents": _run_index, "Weekly Review": _run_review, "Backup": _run_backup,
    "News Pipeline: fetch": _run_news_fetch, "News Pipeline: score": _run_news_score,
    "Monthly update check": _run_update,
}


# ---------------------------------------------------------------- running
def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _execute(job: dict[str, Any], trigger: str, now: datetime) -> dict[str, Any]:
    t0 = _time.monotonic()
    try:
        out = RUNNERS[job["job"]](job)
    except Exception as exc:  # a failing job is logged, never raised into the app
        out = Outcome("error", f"{type(exc).__name__}: {str(exc)[:200]}")
    entry = {"job_id": job["id"], "job": job["job"], "mkt": job["mkt"], "model": job["model"],
             "start": now.isoformat(), "duration_s": round(_time.monotonic() - t0, 2),
             "status": out.status, "rows": out.rows, "output": out.output, "trigger": trigger}
    store().add("job_log", entry, tag=out.status)
    mark = {"ok": "✓", "skipped": "–", "not available": "?", "error": "✗"}[out.status]
    _save(job["id"], last_run=now.isoformat(), last_result=f"{mark} {out.status}")
    if job["job"] == "News Pipeline: fetch":
        _health_check(job, now)
    return entry


def run_now(job_id: int, now: datetime | None = None) -> dict[str, Any]:
    """Run one job immediately (works even while paused). Returns its log row."""
    return _execute(get_job(job_id), "run now", now or _now())


def _is_due(job: dict[str, Any], now: datetime, catch_up: bool) -> tuple[bool, str]:
    sch = Schedule(**job.get("schedule", {}))
    occ = last_occurrence(sch, job["mkt"], now)
    if occ is None:
        return False, ""
    since = datetime.fromisoformat(job.get("since") or job["created"])
    last = datetime.fromisoformat(job["last_run"]) if job.get("last_run") else since
    if occ <= last or occ < since:
        return False, ""
    if now - occ > GRACE:
        return (True, "catch-up") if catch_up else (False, "missed")
    return True, "schedule"


def run_due(now: datetime | None = None, catch_up: bool | None = None) -> list[dict[str, Any]]:
    """Run every enabled job that is due at ``now``. Missed runs follow the catch-up switch."""
    now = now or _now()
    if paused():
        return []
    cu = catch_up_enabled() if catch_up is None else catch_up
    out = []
    for job in jobs():
        if not job.get("enabled", True):
            continue
        due, why = _is_due(job, now, cu)
        if due:
            out.append(_execute(job, why, now))
        elif why == "missed":
            _save(job["id"], last_run=now.isoformat(), last_result="missed · asleep")
            store().add("job_log", {"job_id": job["id"], "job": job["job"], "mkt": job["mkt"],
                                    "model": job["model"], "start": now.isoformat(),
                                    "duration_s": 0.0, "status": "missed", "rows": 0,
                                    "output": "Missed while the computer was off or asleep; "
                                              "catch-up is off.", "trigger": "schedule"},
                        tag="missed")
    return out


# ---------------------------------------------------------------- health alert
def _market_hours_between(market: str, a: datetime, b: datetime) -> timedelta:
    """Session time elapsed between ``a`` and ``b`` (weekends and closed hours excluded)."""
    mk = market if market in ("IN", "US") else "IN"
    s = clock.session(mk)
    tz = clock.zone(mk)
    total, d = timedelta(0), a.astimezone(tz).date()
    while d <= b.astimezone(tz).date():
        if clock.is_session_day(d, mk):
            o = datetime.combine(d, _hm(s["open"]), tz)
            c = datetime.combine(d, _hm(s["close"]), tz)
            lo, hi = max(o, a), min(c, b)
            if hi > lo:
                total += hi - lo
        d += timedelta(days=1)
    return total


def _health_check(job: dict[str, Any], now: datetime) -> None:
    """If the feed job has returned nothing for two market hours, write a SIMULATED alert."""
    if not health_alert_enabled():
        return
    runs = [r for r in log(job["id"]) if r.get("status") in ("ok", "error")]
    if not runs or runs[0].get("rows", 0) > 0:
        return
    streak_start = runs[0]
    for r in runs:
        if r.get("rows", 0) > 0:
            break
        streak_start = r
    first = datetime.fromisoformat(streak_start["start"])
    if _market_hours_between(job["mkt"], first, now) < HEALTH_SILENCE:
        return
    already = [a for a in store().all("alert_log", tag="health")
               if a.get("job_id") == job["id"] and a.get("streak") == streak_start["start"]]
    if already:
        return
    store().add("alert_log", {
        "alert_id": None, "name": f"Health: {job['job']} ({job['mkt']})", "event": "health",
        "message": "SIMULATED alert — the news feed returned nothing for two market hours. "
                   "A silent feed looks exactly like a quiet news day; check the Scheduler log.",
        "at": now.isoformat(), "job_id": job["id"], "streak": streak_start["start"],
        "delivered": ["dashboard"]}, tag="health")


# ---------------------------------------------------------------- background thread
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def _loop(interval: float) -> None:
    """Check every ``interval`` seconds. After a sleep, missed runs look late (> GRACE)
    and follow the catch-up switch."""
    while True:
        _time.sleep(interval)
        try:
            run_due()
        except Exception:  # never let the scheduler thread die
            pass


def ensure_started(interval: float = CHECK_EVERY, force: bool = False) -> bool:
    """Start the background scheduler thread once per process. True if it is running.

    Under pytest the thread is not started unless ``force`` is set, so a page
    render in a test never runs real jobs in the background.
    """
    global _thread
    if "PYTEST_CURRENT_TEST" in os.environ and not force:
        return running()
    with _thread_lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, args=(interval,), daemon=True,
                                       name="plugai-scheduler")
            _thread.start()
    return _thread.is_alive()


def running() -> bool:
    """True when the background thread is alive in this process."""
    return _thread is not None and _thread.is_alive()
