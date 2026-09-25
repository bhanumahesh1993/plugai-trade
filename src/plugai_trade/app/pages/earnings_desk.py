"""Research › Earnings Desk: Results calendar · Results digest · Implied vs historical move."""

from __future__ import annotations

from datetime import date, timedelta

import altair as alt
import polars as pl
import streamlit as st

from plugai_trade import docdesk, earnings, screener
from plugai_trade.app import ui
from plugai_trade.earnings import calendar

SAMPLE_WATCH = {
    "IN": ["SYN-IN-004", "SYN-IN-010", "SYN-IN-027"],
    "US": ["SYN-US-006", "SYN-US-012"],
}
INDEX = {"IN": "NIFTY", "US": "SPY"}
MOVE_DEFAULT = {"IN": "NIFTY", "US": "SYN-US-006"}


def _positions(mkt: str) -> list[str]:
    rows = ui.lab_store().all("paper_positions")
    return sorted(
        {str(r.get("symbol")) for r in rows if r.get("symbol") and r.get("market", mkt) == mkt}
    )


def _calendar_tab(mkt: str) -> None:
    saved = {w["name"]: w["symbols"] for w in screener.watchlists(mkt)}
    picks = st.multiselect("Watchlists", list(saved))
    if st.button("Import watchlist"):
        names = [s for p in picks for s in saved[p]] + _positions(mkt)
        st.session_state[f"ed_syms_{mkt}"] = ", ".join(dict.fromkeys(names or SAMPLE_WATCH[mkt]))
    text = st.text_input(
        "Names",
        st.session_state.get(f"ed_syms_{mkt}", ", ".join(SAMPLE_WATCH[mkt])),
        key=f"ed_names_{mkt}",
    )
    symbols = [s.strip().upper() for s in text.split(",") if s.strip()]
    c1, c2, c3 = st.columns(3)
    macro = c1.toggle("Macro events", value=False)
    start = c2.date_input("From", date.today())
    days = c3.slider("Days", 5, 60, 7)
    rows = earnings.results_calendar(symbols, mkt, start, days, macro, _positions(mkt))
    if not rows:
        st.caption("No events in this window.")
        return
    df = pl.DataFrame(rows)
    st.dataframe(
        df.to_pandas().style.apply(
            lambda r: ["background-color: #FEF3C7" if r["Overlap"] else "" for _ in r], axis=1
        ),
        hide_index=True,
    )
    st.caption("Estimated rows are not confirmed by the company. Sample calendar rules offline.")
    ui.ai_block(
        {
            "rows": len(rows),
            **{
                f"{r['Date']} {r['Time']}": f"{r['Event']} ({r['Status']}; "
                f"{r['Source']}){' · OVERLAP: ' + r['Overlap'] if r['Overlap'] else ''}"
                for r in rows
            },
        },
        "ed_cal",
        section="Research",
        question="Summarise the week in plain English. Cite each row; add no dates.",
    )
    if st.button("Send to Alerts"):
        ids = earnings.send_to_alerts(rows, mkt)
        st.success(
            f"{len(ids)} SIMULATED alerts proposed in Paper Trading › Alerts. Nothing is "
            "active until you click Accept there."
        )


def _digest_tab(mkt: str) -> None:
    samples = {"Kaveri Pumps (fictional) · Q2 FY27": "Kaveri_Q2-FY27_results"}
    company = st.text_input("Company", "Kaveri Pumps (fictional)")
    up = st.file_uploader("Drop the results PDF", type=["pdf"], key="ed_pdf")
    use_sample = st.selectbox("Or use a sample filing", list(samples))
    if st.button("Generate digest", type="primary"):
        doc = (
            docdesk.load_pdf(up.getvalue(), name=up.name, market=mkt)
            if up
            else docdesk.sample(samples[use_sample])
        )
        prior = earnings.last_guidance(company) or (
            {
                "quote": "For the full year we continue to guide for mid-teens revenue growth.",
                "cite": "[Q1 p. 4]",
            }
            if "Kaveri" in company
            else None
        )
        st.session_state["ed_digest"] = earnings.digest(doc, company, prior)
    d: earnings.Digest | None = st.session_state.get("ed_digest")
    if d is None:
        st.caption("The desk runs the quote-first template, then computes Change in code.")
        return
    st.dataframe(pl.DataFrame(d.rows), hide_index=True)
    with st.container(border=True):
        st.markdown("**Guidance · word for word**")
        if d.guidance_before:
            st.markdown(f"Before: “{d.guidance_before}” {d.guidance_before_cite}")
        st.markdown(f"Now: “{d.guidance_now}” {d.guidance_cite}")
        colour = {"wording softer": "red", "wording firmer": "green"}.get(d.chip, "gray")
        st.markdown(f":{colour}-background[{d.chip.upper()}]")
    with st.expander("Consensus (you fill it in)"):
        c1, c2, c3, c4 = st.columns(4)
        item = c1.selectbox("Item", [r["Item"] for r in d.rows])
        val = c2.number_input("Consensus figure", value=0.0)
        src = c3.text_input("Source", "")
        asof = c4.date_input("Date", date.today())
        if st.button("Add consensus") and src:
            earnings.add_consensus(d, item, val, src, asof.isoformat())
        if d.consensus:
            st.dataframe(pl.DataFrame(d.consensus), hide_index=True)
        st.caption("The desk only subtracts; it never fetches or guesses consensus.")
    with st.expander("History"):
        for h in earnings.history(d.company):
            st.markdown(
                f"- {h['created'][:10]} · guidance: “{h['guidance']['quote']}” · {h['chip']}"
            )
    ui.ai_block(d, "ed_dig", section="Research", on_accept=lambda _t: earnings.save_digest(d, mkt))


def _move_tab(mkt: str) -> None:
    sym = st.text_input("Symbol", MOVE_DEFAULT[mkt], key=f"ed_im_{mkt}").upper().strip()
    today = date.today()
    evs = calendar.results_dates(sym, mkt, today, today + timedelta(days=120))
    if sym in (INDEX[mkt], "NIFTY", "BANKNIFTY", "SPY"):
        evs = calendar.macro_events(mkt, today, today + timedelta(days=90))
    if not evs:
        st.caption("No scheduled event for this symbol in the next months.")
        return
    labels = [e.label() for e in evs]
    ev = evs[labels.index(st.selectbox("Calendar row", labels))]
    im = earnings.implied_move(sym, mkt, ev, today)
    if im is None:
        st.info(
            "Implied move: n/a (not in the F&O list). The history of results-day moves is below."
        )
        moves = earnings.historical_moves(sym, mkt, today)
        if moves:
            st.dataframe(pl.DataFrame(moves), hide_index=True)
        return
    st.caption(
        f"Expiry {im.expiry} · ATM {im.strike:,.2f} · call {im.call:,.2f} · put {im.put:,.2f} · "
        f"{im.chain_source}"
    )
    tiles = im.tiles()
    for col, (k, v) in zip(st.columns(len(tiles)), tiles.items()):
        col.metric(k, v)
    if im.moves:
        chart = (
            alt.Chart(pl.DataFrame(im.moves).to_pandas())
            .mark_bar(color="#1D4ED8")
            .encode(
                x=alt.X("event:N", title="Announcement"),
                y=alt.Y("move_pct:Q", title="Move, %"),
                tooltip=["event", "time", "close_before", "close_after", "from", "to"],
            )
            .properties(height=200)
        )
        st.altair_chart(ui.hypothetical_chart(chart), use_container_width=True)
    if st.toggle("Event split"):
        quiet = st.number_input(
            "Normal-day move from a quiet week, % (0 = use realised vol)", 0.0, 10.0, 0.0, 0.05
        )
        split = im.event_split(quiet / 100 if quiet else None)
        st.write({k: v for k, v in split.items()})
        st.caption("approximate: total implied variance minus the normal days' share")
    with st.expander("Scenarios"):
        st.dataframe(im.scenarios(), hide_index=True)
        st.caption(
            "Straddle value one day later after an IV crush to the normal level. HYPOTHETICAL."
        )
    c1, c2 = st.columns(2)
    if c1.button("Open in Options Strategy Builder"):
        earnings.open_in_options_builder(im)
        st.session_state["options_prefill"] = {
            "symbol": im.symbol,
            "strike": im.strike,
            "expiry": im.expiry.isoformat(),
        }
        st.success(
            "Draft straddle sent to Derivatives › Options Strategy Builder (test it with "
            "the Days left slider)."
        )
    if c2.button("Save to journal"):
        earnings.save_move_to_journal(im)
        st.success("Logged before the event; the actual move is added after it.")
    ui.ai_block(
        im,
        "ed_im",
        section="Research",
        question="Narrate the tiles and cite each one. Do not suggest a strike, a direction "
        "or a trade.",
    )


def render() -> None:
    ui.page_header(
        "Earnings Desk",
        "Research",
        "Dates with sources, digests with page chips, moves computed in code.",
    )
    mkt = ui.market()
    earnings.fill_actual_moves()
    t1, t2, t3 = st.tabs(["Results calendar", "Results digest", "Implied vs historical move"])
    with t1:
        _calendar_tab(mkt)
    with t2:
        _digest_tab(mkt)
    with t3:
        _move_tab(mkt)
