"""Research › Screener: Describe your screen → rule cards → Run → triage → Save as watchlist."""

from __future__ import annotations

from datetime import date, time, timedelta

import polars as pl
import streamlit as st

from plugai_trade import screener
from plugai_trade.app import ui
from plugai_trade.screener import universe as uni

SCHEDULE_TIME = {"IN": "09:08", "US": "09:15"}


def _presets(mkt: str) -> None:
    with st.popover("Presets"):
        for name in screener.PRESETS:
            if st.button(name, key=f"pre_{name}"):
                st.session_state["scr_text"] = screener.preset(name, mkt)
                st.session_state["scr_accepted"] = False
                st.rerun()


def _rule_cards(parsed: screener.Parsed) -> list[screener.Rule]:
    """Show each rule as a card; amber ? on interpreted words; the number is editable."""
    st.markdown("**Rules preview**")
    rules = []
    for i, r in enumerate(parsed.rules):
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            flag = " :orange[**?**]" if r.interpreted else ""
            c1.markdown(f"{i + 1}. {r.text}{flag}", help=r.interpreted or None)
            if r.metric == "has_item":
                val = r.value
            else:
                val = c2.number_input(
                    "Value",
                    value=float(r.value),
                    key=f"rule_{i}_{r.metric}",
                    label_visibility="collapsed",
                )
            rules.append(
                screener.Rule(
                    r.metric,
                    r.op,
                    val,
                    r.text if val == r.value else f"{r.text} (edited to {val:g})",
                    r.interpreted,
                )
            )
    for u in parsed.unparsed:
        st.warning(f"Not understood: “{u}” — reword it or remove it.")
    return rules


@st.dialog("Schedule")
def _schedule(mkt: str, text: str, universe: str) -> None:
    run = st.time_input(
        "Run time",
        time.fromisoformat(SCHEDULE_TIME[mkt]),
        help="A gap scan runs on the indicated / pre-market price, not last night's close.",
    )
    name = st.text_input("Name", "Gap scan" if "gap" in text.lower() else "My screen")
    if st.button("Accept", type="primary"):
        screener.schedule(name, mkt, run.strftime("%H:%M"), text, universe)
        st.success("Scheduled on market days. It appears in Automate › Scheduler.")


def _results(res: screener.Result) -> None:
    st.markdown(
        f"**{len(res.passed)} passed · {len(res.excluded)} excluded** · {res.universe} · "
        f"as of {res.asof} · source {res.source}"
    )
    if st.button("Next event", help="Sort by the next event, nearest first"):
        st.session_state["scr_sort_event"] = True
    rows = (
        sorted(res.passed, key=lambda r: r.event_sessions if r.event_sessions is not None else 999)
        if st.session_state.get("scr_sort_event")
        else res.passed
    )
    tags = st.session_state.setdefault("scr_tags", {})
    table = res.table()
    if table.height:
        order = {r.symbol: i for i, r in enumerate(rows)}
        table = (
            table.with_columns(pl.col("Symbol").replace_strict(order, default=0).alias("_o"))
            .sort("_o")
            .drop("_o")
        )
        table = table.with_columns(
            pl.Series("Triage", [tags.get(s, t) for s, t in zip(table["Symbol"], table["Triage"])])
        )
        edited = st.data_editor(
            table.to_pandas(),
            hide_index=True,
            key="scr_editor",
            column_config={
                "Triage": st.column_config.SelectboxColumn(
                    "Triage", options=list(screener.TRIAGE), required=True
                )
            },
            disabled=[c for c in table.columns if c != "Triage"],
        )
        for s, t in zip(edited["Symbol"], edited["Triage"]):
            tags[s] = t
    if res.excluded:
        st.caption("Removed by the event rule:")
        for r in res.excluded:
            st.caption(f":gray[{r.symbol} · excluded · {r.excluded}]")
    ui.ai_block(
        res,
        "scr_res",
        section="Research",
        question="Group these names into the four triage bins (Watch closely, Wait for the "
        "setup, Research first, Drop), quoting the columns. No recommendations.",
    )


def _save(res: screener.Result, mkt: str, text: str) -> None:
    tags = st.session_state.get("scr_tags", {})
    with st.expander("Save as watchlist", expanded=False):
        keep = st.multiselect("Filter: Triage =", list(screener.TRIAGE), default=["Watch closely"])
        names = [r.symbol for r in res.passed if tags.get(r.symbol, r.triage) in keep]
        name = st.text_input("Watchlist name", f"Screen · week {date.today().isocalendar().week}")
        reason_df = st.data_editor(
            pl.DataFrame({"Symbol": names, "Reason": [""] * len(names)}).to_pandas(),
            hide_index=True,
            key="scr_reasons",
            disabled=["Symbol"],
        )
        review = st.date_input("Review by", date.today() + timedelta(days=7))
        if st.button("Save as watchlist", type="primary"):
            try:
                screener.save_watchlist(
                    name,
                    mkt,
                    names,
                    dict(zip(reason_df["Symbol"], reason_df["Reason"])),
                    review,
                    text,
                    triage={s: tags.get(s, "") for s in names},
                )
                st.success(f"Saved {len(names)} names. The Daily Briefing picks it up tomorrow.")
            except ValueError as exc:
                st.error(str(exc))


def render() -> None:
    ui.page_header(
        "Screener",
        "Research",
        "The AI drafts rules; the lab computes. No stock is picked by a model.",
    )
    mkt = ui.market()
    with st.sidebar:
        st.caption("WATCHLISTS")
        for w in screener.watchlists(mkt)[:8]:
            st.caption(f"{w['name']} · {len(w['symbols'])} · review by {w['review_by']}")
    c1, c2, c3 = st.columns([1.3, 1, 1])
    universe = c1.selectbox("Universe", list(uni.UNIVERSES[mkt]), index=1)
    asof = c2.date_input("As of", screener.latest_asof(mkt))
    with c3:
        _presets(mkt)
    st.caption(f"Offline universe: synthetic SYN-{mkt}-### names (no real market information).")
    text = st.text_area(
        "Describe your screen",
        key="scr_text",
        placeholder="Stocks near their 52-week high with volume picking up, liquid",
    )
    parsed = screener.parse(text or "", mkt)
    rules = _rule_cards(parsed) if text else []
    excl = st.number_input(
        "Exclude events within N sessions (0 = off)", 0, 60, int(parsed.exclude_events or 0)
    )
    if rules:
        preview = screener.Parsed(rules, excl or None, parsed.unparsed)
        ui.ai_block(
            preview,
            "scr_rules",
            section="Research",
            question="Read every rule back in plain English, one line each. Do not add rules.",
            on_accept=lambda _t: st.session_state.update(scr_accepted=True),
        )
        if not st.session_state.get("scr_accepted"):
            st.caption("Rules not accepted yet: Explain, compare with your sentence, then Accept.")
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("Run", type="primary", disabled=not rules):
        with st.spinner("Computing every rule on every name…"):
            st.session_state["scr_res"] = screener.run(rules, universe, mkt, asof, excl or None)
            st.session_state["scr_tags"] = {}
    if b2.button("Schedule", disabled=not rules):
        _schedule(mkt, text, universe)
    res: screener.Result | None = st.session_state.get("scr_res")
    if res is not None and res.market == mkt:
        _results(res)
        _save(res, mkt, text)
