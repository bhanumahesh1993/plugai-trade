"""Automate › Scheduler (Chapters 28, 31, 34): one list of jobs, each run by the lab."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from plugai_trade import scheduler
from plugai_trade.app import ui

SECTION = "Automate"
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


def _job_form(mkt: str) -> None:
    job = st.selectbox("Job", scheduler.JOB_TYPES, key="sch_type")
    p = PRESETS[job]
    c1, c2, c3 = st.columns(3)
    market = c1.selectbox("Market", ["IN", "US"], index=0 if mkt == "IN" else 1, key="sch_mkt",
                          help="IN runs on NSE trading days; US on NYSE trading days. Holidays "
                               "come from the dated reference tables.")
    kind = c2.selectbox("When", scheduler.KINDS, index=scheduler.KINDS.index(p["kind"]),
                        key=f"sch_kind_{job}")
    model = c3.selectbox("Model", MODELS, index=MODELS.index(scheduler.DEFAULT_MODEL[job]),
                         key=f"sch_model_{job}")
    c4, c5, c6 = st.columns(3)
    at = c4.text_input("Run time (HH:MM, market time)", p["at"], key=f"sch_at_{job}")
    day = p.get("day", "Sat")
    if kind == "weekly":
        day = c5.selectbox("Day", scheduler.WEEKDAYS, index=scheduler.WEEKDAYS.index("Sat"),
                           key=f"sch_day_{job}")
    elif kind == "monthly":
        day = str(c5.number_input("Day of month", 1, 28, 1, key=f"sch_dom_{job}"))
    minutes, until = p.get("minutes", 15), p.get("until", "23:00")
    if kind == "every N minutes":
        minutes = int(c5.number_input("Every (minutes)", 5, 240, minutes, key=f"sch_min_{job}"))
        until = c6.text_input("Last run (HH:MM)", until, key=f"sch_until_{job}")
    sch = scheduler.Schedule(kind=kind, at=at, day=day, minutes=minutes, until=until)
    st.caption(f"Preview: {job} · {market} · {sch.describe(market)} · model {model}")
    if st.button("Accept", key="sch_accept", type="primary"):
        try:
            scheduler.add_job(job, market, sch, model)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state["sch_adding"] = False
        st.rerun()


def _table() -> list[dict]:
    rows = scheduler.jobs()
    if not rows:
        st.info("No jobs yet. Click Add job. Jobs you schedule elsewhere (Daily Briefing › "
                "Schedule, Workspace templates) appear here too.")
        return rows
    df = pd.DataFrame([{"#": r["id"], "Job": r["job"], "Mkt": r["mkt"], "When": r["when"],
                        "Model": r["model"], "On": "✓" if r.get("enabled", True) else "off",
                        "Last run": (f"{r['last_result']} · {r['last_run'][:16].replace('T', ' ')}"
                                     if r.get("last_run") else "not yet")} for r in rows])
    st.dataframe(df, hide_index=True, use_container_width=True)
    cost = "₹0 / $0" if all(r["model"] in ("local", "none", "embed") for r in rows) else "metered"
    st.caption(f"Every job on a local model or none → {cost}.")
    return rows


def _log_view(job_id: int | None) -> None:
    rows = scheduler.log(job_id)
    if not rows:
        st.caption("No runs yet. Click Run now to test a job.")
        return
    st.dataframe(pd.DataFrame([{"Start": r["start"][:19].replace("T", " "), "Job": r["job"],
                                "Mkt": r["mkt"], "Status": r["status"], "Rows": r["rows"],
                                "Duration (s)": r["duration_s"], "Model": r["model"],
                                "Trigger": r["trigger"], "Output": r["output"]} for r in rows]),
                 hide_index=True, use_container_width=True)


def render() -> None:
    ui.page_header("Scheduler", SECTION, "Jobs run on NSE / NYSE trading days, on your own "
                                         "computer. The lab has no order code.")
    mkt = ui.market()
    scheduler.ensure_started()
    rows = _table()
    labels = {r["id"]: f"#{r['id']} {r['job']} ({r['mkt']})" for r in rows}
    pick = st.selectbox("Job", list(labels), format_func=labels.get, key="sch_pick",
                        disabled=not rows) if rows else None
    b1, b2, b3, b4, b5 = st.columns(5)
    add = b1.button("Add job", key="sch_add", type="primary")
    new = b5.button("New job", key="sch_new", help="Same as Add job")
    if add or new:
        st.session_state["sch_adding"] = True
    if b2.button("Run now", key="sch_run", disabled=pick is None):
        with st.spinner("Running…"):
            entry = scheduler.run_now(int(pick))
        (st.success if entry["status"] == "ok" else st.warning)(
            f"{entry['job']}: {entry['status']} · {entry['output']}")
    if b3.button("View log", key="sch_log"):
        st.session_state["sch_show_log"] = not st.session_state.get("sch_show_log", False)
    paused = scheduler.paused()
    if b4.button("Resume all" if paused else "Pause all", key="sch_pause"):
        scheduler.pause_all(not paused)
        st.rerun()
    if paused:
        st.warning("Paused: no job runs on schedule until you click Resume all.")
    if pick is not None:
        c1, c2 = st.columns(2)
        on = next(r for r in rows if r["id"] == pick).get("enabled", True)
        if c1.toggle("Job switched on", value=on, key=f"sch_on_{pick}") != on:
            scheduler.set_enabled(int(pick), not on)
            st.rerun()
        if c2.button("Delete job", key="sch_del"):
            scheduler.delete_job(int(pick))
            st.rerun()
    if st.session_state.get("sch_adding"):
        with st.container(border=True):
            st.markdown("**New job**")
            _job_form(mkt)
    cu = st.checkbox("Catch up missed runs when the computer wakes",
                     value=scheduler.catch_up_enabled(), key="sch_catchup")
    if cu != scheduler.catch_up_enabled():
        scheduler.set_catch_up(cu)
    ha = st.toggle("Health alert", value=scheduler.health_alert_enabled(), key="sch_health",
                   help="If a news feed returns nothing for two hours of market time, you get a "
                        "SIMULATED alert in Alerts — a silent feed looks like a quiet news day.")
    if ha != scheduler.health_alert_enabled():
        scheduler.set_health_alert(ha)
    st.caption("Background checks every minute while the app is open"
               f" · {'running' if scheduler.running() else 'stopped'}. A job needs the computer "
               "on and awake; catch-up runs a missed job at the next wake-up.")
    if st.session_state.get("sch_show_log"):
        st.markdown("**Run log**")
        _log_view(int(pick) if pick is not None else None)
