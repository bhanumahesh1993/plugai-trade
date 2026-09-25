"""Automate › Scheduler: due maths, run now, log, pause, catch-up, health alert."""

from datetime import datetime, timedelta, timezone

import pytest

from plugai_trade import scheduler
from plugai_trade.store import default as store

IST = timezone(timedelta(hours=5, minutes=30))


def _add(job="Monthly update check", market="IN", since=None, **sch):
    jid = scheduler.add_job(job, market, sch or {"kind": "trading days", "at": "19:00"})
    if since:
        scheduler._save(jid, since=since.isoformat())
    return jid


def test_add_job_lists_book_columns_and_rejects_bad_input():
    jid = _add(job="Fetch end-of-day data")
    row = scheduler.get_job(jid)
    assert row["job"] == "Fetch end-of-day data" and row["mkt"] == "IN"
    assert row["when"] == "Mon–Fri 19:00 IST" and row["model"] == "none"
    assert set(scheduler.JOB_TYPES) >= {"Daily Briefing", "Backup", "Weekly Review",
                                        "News Pipeline: fetch", "News Pipeline: score",
                                        "Monthly update check", "Index new documents"}
    with pytest.raises(ValueError):
        scheduler.add_job("Place order", "IN")
    with pytest.raises(ValueError):
        scheduler.add_job("Backup", "IN", {"kind": "daily", "at": "7pm"})


def test_last_and_next_occurrence_skip_weekends():
    sch = scheduler.Schedule(kind="trading days", at="07:30")
    sat = datetime(2026, 5, 16, 12, 0, tzinfo=IST)
    last = scheduler.last_occurrence(sch, "IN", sat)
    assert last.astimezone(IST) == datetime(2026, 5, 15, 7, 30, tzinfo=IST)
    nxt = scheduler.next_occurrence(sch, "IN", sat)
    assert nxt.astimezone(IST) == datetime(2026, 5, 18, 7, 30, tzinfo=IST)
    every = scheduler.Schedule(kind="every N minutes", at="08:00", until="23:00", minutes=15)
    t = scheduler.last_occurrence(every, "IN", datetime(2026, 5, 12, 8, 40, tzinfo=IST))
    assert t.astimezone(IST).strftime("%H:%M") == "08:30"


def test_run_due_runs_once_and_logs():
    jid = _add(since=datetime(2026, 5, 11, 12, 0, tzinfo=IST))
    now = datetime(2026, 5, 12, 19, 5, tzinfo=IST)
    out = scheduler.run_due(now)
    assert len(out) == 1 and out[0]["trigger"] == "schedule"
    assert out[0]["status"] == "skipped"  # offline: the update check needs the network
    assert scheduler.run_due(now + timedelta(minutes=1)) == []
    assert scheduler.log(jid)[0]["job"] == "Monthly update check"
    assert scheduler.get_job(jid)["last_result"] == "– skipped"


def test_pause_all_and_run_now():
    jid = _add(since=datetime(2026, 5, 11, 12, 0, tzinfo=IST))
    scheduler.pause_all(True)
    assert scheduler.run_due(datetime(2026, 5, 12, 19, 5, tzinfo=IST)) == []
    entry = scheduler.run_now(jid)  # Run now still works while paused
    assert entry["trigger"] == "run now"
    scheduler.pause_all(False)
    assert not scheduler.paused()


def test_catch_up_switch():
    since = datetime(2026, 5, 11, 12, 0, tzinfo=IST)
    woke = datetime(2026, 5, 13, 7, 0, tzinfo=IST)  # slept through Tue 19:00
    scheduler.set_catch_up(False)
    jid = _add(since=since)  # offline → skipped, fast
    assert scheduler.run_due(woke) == []
    assert scheduler.get_job(jid)["last_result"] == "missed · asleep"
    scheduler.set_catch_up(True)
    _add(since=since)
    out = scheduler.run_due(woke)
    assert [o["trigger"] for o in out] == ["catch-up"] and out[0]["status"] == "skipped"


def test_missing_module_is_logged_not_raised(monkeypatch):
    jid = _add(job="Daily Briefing")
    monkeypatch.setattr(scheduler, "_module", lambda name: None)
    entry = scheduler.run_now(jid)
    assert entry["status"] == "not available"


def test_eod_job_reports_offline_honestly():
    entry = scheduler.run_now(_add(job="Fetch end-of-day data"))
    assert entry["status"] == "error" and "NIFTY" in entry["output"]


def test_failing_job_is_logged_as_error(monkeypatch):
    jid = _add()
    monkeypatch.setitem(scheduler.RUNNERS, "Monthly update check",
                        lambda job: (_ for _ in ()).throw(RuntimeError("boom")))
    entry = scheduler.run_now(jid)
    assert entry["status"] == "error" and "boom" in entry["output"]


def test_news_jobs_and_health_alert(monkeypatch):
    fetch = scheduler.add_job("News Pipeline: fetch", "IN",
                              {"kind": "every N minutes", "at": "08:00", "until": "23:00",
                               "minutes": 15})
    score = scheduler.add_job("News Pipeline: score", "IN", {"kind": "daily", "at": "23:30"})
    scheduler.set_health_alert(True)
    t0 = datetime(2026, 5, 12, 10, 0, tzinfo=IST)
    e1 = scheduler.run_now(fetch, now=t0)
    assert e1["status"] == "ok" and e1["rows"] == 0  # offline: no live headlines
    assert store().count("alert_log", tag="health") == 0
    scheduler.run_now(fetch, now=t0 + timedelta(hours=2, minutes=15))
    alerts = store().all("alert_log", tag="health")
    assert len(alerts) == 1 and "SIMULATED" in alerts[0]["message"]
    scheduler.run_now(fetch, now=t0 + timedelta(hours=3))
    assert store().count("alert_log", tag="health") == 1  # once per silent streak
    assert scheduler.run_now(score)["output"].startswith("0 new headlines")


def test_ensure_started_is_idempotent():
    assert scheduler.ensure_started(interval=3600, force=True)
    first = scheduler._thread
    assert scheduler.ensure_started(interval=3600, force=True) and scheduler._thread is first
