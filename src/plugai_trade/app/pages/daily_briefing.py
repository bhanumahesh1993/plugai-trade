"""Today › Daily Briefing: four panels, a Yesterday strip, ✓/? on every line, no buy/sell field."""

from __future__ import annotations

from datetime import date, time

import streamlit as st

from plugai_trade import briefing, config, screener
from plugai_trade.app import ui

SAMPLE = "Sample watchlist"
CHANNELS = ["Dashboard", "Desktop", "Email", "Telegram"]


def _watchlist(mkt: str) -> list[str]:
    saved = {w["name"]: w["symbols"] for w in screener.watchlists(mkt)}
    choice = st.selectbox(
        "Watchlist",
        [SAMPLE, *saved],
        key="br_wl",
        help="Saved watchlists come from Research › Screener › Save as watchlist.",
    )
    base = saved.get(choice) or list(config.get("watchlists", {}).get(mkt, []))
    text = st.text_input("Names (comma-separated)", ", ".join(base), key=f"br_names_{mkt}_{choice}")
    return [s.strip().upper() for s in text.split(",") if s.strip()]


@st.dialog("Schedule")
def _schedule(mkt: str) -> None:
    d = briefing.DEFAULTS[mkt]
    st.caption(
        f"Runs on {d['days']}; exchange holidays are skipped. Times in {briefing.TZ_LABEL[mkt]}."
    )
    run = st.time_input("Run time", time.fromisoformat(d["run_time"]))
    cut = st.time_input("News cutoff", time.fromisoformat(d["cutoff"]))
    refresh = st.time_input("Second edition (optional refresh)", value=None)
    where = st.multiselect(
        "Delivery",
        CHANNELS,
        default=["Dashboard"],
        help="Desktop, Email and Telegram go through Paper Trading › Alerts.",
    )
    st.caption("Model: the local default (₹0 / $0). Each run is saved with its cutoff time.")
    if st.button("Accept", type="primary"):
        briefing.schedule(
            mkt,
            run.strftime("%H:%M"),
            cut.strftime("%H:%M"),
            where,
            refresh.strftime("%H:%M") if refresh else None,
        )
        st.success("Scheduled. It appears in Automate › Scheduler.")


def _panel(title: str, lines: list[briefing.Line]) -> None:
    with st.container(border=True):
        st.markdown(f"**{title.upper()}**")
        if not lines:
            st.caption("Nothing on your list for this panel.")
        for ln in lines:
            st.markdown(f"{'✅' if ln.sourced else '❔'} {ln.text}")
            st.caption(f"{ln.source} · {ln.published}" if ln.sourced else f"unsourced: {ln.reason}")


def render() -> None:
    ui.page_header(
        "Daily Briefing",
        "Today",
        "Scheduled facts and your questions. Nothing here is a trade suggestion.",
    )
    mkt = ui.market()
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        symbols = _watchlist(mkt)
    with c2:
        cutoff = st.time_input(
            "News cutoff", time.fromisoformat(briefing.DEFAULTS[mkt]["cutoff"]), key=f"br_cut_{mkt}"
        )
    with c3:
        online = st.toggle(
            "Read RSS feeds",
            value=False,
            help="Off: offline sample items. On: NSE/BSE announcements or SEC EDGAR.",
        )
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("Generate briefing", type="primary"):
        with st.spinner("Gathering closes, headlines and the calendar…"):
            st.session_state["briefing"] = briefing.generate(
                symbols, mkt, cutoff.strftime("%H:%M"), online=online
            )
    if b2.button("Schedule"):
        _schedule(mkt)
    b: briefing.Briefing | None = st.session_state.get("briefing")
    if b is None or b.market != mkt:
        st.info(
            "Click **Generate briefing**. The filter runs in code first: nothing after the "
            "cutoff, nothing older than the previous close, nothing off your list."
        )
        _saved_runs(mkt)
        return
    st.markdown(f"#### {b.header()}")
    left, right = st.columns(2)
    with left:
        _panel("Watchlist", b.panel("Watchlist"))
        _panel("Events today", b.panel("Events today"))
    with right:
        _panel("Overnight news", b.panel("Overnight news"))
        with st.container(border=True):
            st.markdown("**QUESTIONS FOR YOU**")
            for i, q in enumerate(b.questions, 1):
                st.markdown(f"{i}. {q}")
    st.info(f"YESTERDAY · {b.yesterday}")
    ok, bad = b.counts()
    st.caption(f"{ok} sourced · {bad} unsourced · flags are set by code, not by the model")
    if b.dropped:
        with st.expander(f"Filtered out ({len(b.dropped)})"):
            for d in b.dropped:
                st.markdown(f"- {d}")
    ui.ai_block(
        b,
        "brief",
        section="Today",
        question="Write the morning briefing from these facts. Keep every flag; no advice.",
    )
    _saved_runs(mkt)


def _saved_runs(mkt: str) -> None:
    eds = briefing.editions(mkt, date.today())
    jobs = ui.lab_store().all("jobs", tag="briefing")
    with st.expander(f"Editions today ({len(eds)}) · saved runs ({len(jobs)})"):
        for e in eds:
            st.markdown(
                f"- Edition {e['edition']} · cutoff {e['cutoff']} · saved {e['created'][11:16]} UTC"
            )
        for j in jobs:
            st.markdown(
                f"- {j['market']} · {j['days']} · run {j['run_time']} · cutoff "
                f"{j['news_cutoff']} → {', '.join(j['delivery'])}"
            )
