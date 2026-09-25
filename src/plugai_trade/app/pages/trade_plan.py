"""Plan & Risk › Trade Plan — New plan, Critique (AI sceptic), Save to journal, Send to Paper Desk.

Owner chips show who fills each field: YOU, CODE (Position Sizer / Alerts) or
CALENDAR. The critique reads only the plan's fields (Show sources proves it).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from plugai_trade import ai, plans
from plugai_trade.app import ui

SECTION = "Plan & Risk"
CHIP = {plans.YOU: "🟧 YOU", plans.CODE: "🟩 CODE", plans.CALENDAR: "🟦 CALENDAR"}


def _current(mkt: str) -> plans.Plan | None:
    pid = st.session_state.get("tp_plan_id")
    return plans.load(pid) if pid else None


def _picker(mkt: str) -> None:
    c1, c2, c3 = st.columns([2, 2, 1])
    template = c1.selectbox("Plan template", list(plans.TEMPLATES), key="tp_template")
    symbol = c2.text_input("Symbol", "NIFTY FUT" if mkt == "IN" else "SPY", key=f"tp_sym_{mkt}")
    if c3.button("New plan", type="primary", key="tp_new"):
        p = plans.save(plans.new_plan(template, mkt, symbol.strip().upper()), note="created")
        st.session_state["tp_plan_id"] = p.id
        st.session_state.pop("tp_critique", None)
    saved = plans.all_plans(mkt)
    if saved:
        labels = {f"#{p.id} {p.name} · v{p.version}": p.id for p in saved}
        cur = st.session_state.get("tp_plan_id")
        idx = next((i for i, v in enumerate(labels.values()) if v == cur), 0)
        pick = st.selectbox("Saved plans", list(labels), index=idx, key="tp_pick")
        if labels[pick] != cur:
            st.session_state["tp_plan_id"] = labels[pick]
            st.session_state.pop("tp_critique", None)


def _editor(p: plans.Plan) -> plans.Plan:
    c1, c2, c3, c4 = st.columns(4)
    p.name = c1.text_input("Plan name", p.name, key=f"tp_name_{p.id}")
    p.side = c2.segmented_control("Side", ["long", "short"], default=p.side,
                                  key=f"tp_side_{p.id}") or p.side
    entry = c3.number_input("Entry / trigger price", value=float(p.entry or 0.0),
                            key=f"tp_entry_{p.id}", format="%.2f")
    stop = c4.number_input("Stop price", value=float(p.stop or 0.0), key=f"tp_stop_{p.id}",
                           format="%.2f")
    p.entry, p.stop = (entry or None), (stop or None)
    if p.template == "Weekend swing plan":
        p.trigger_expiry = st.text_input("Trigger valid until (date)", p.trigger_expiry,
                                         key=f"tp_exp_{p.id}", placeholder="2026-06-03")
    owners = p.owners()
    for fname, owner in owners.items():
        a, b = st.columns([6, 1])
        help_ = {plans.CODE: "Filled by code (Position Sizer / Alerts); you may edit",
                 plans.CALENDAR: "Filled from the lab calendar; add any it missed"}.get(owner)
        p.fields[fname] = a.text_area(fname, p.fields.get(fname, ""), height=68,
                                      key=f"tp_f_{p.id}_{fname}", help=help_,
                                      placeholder="MISSING" if owner == plans.YOU else "")
        b.markdown(f"<br>{CHIP[owner]}", unsafe_allow_html=True)
    return p


def _critique(p: plans.Plan) -> None:
    if st.button("Critique", key="tp_crit", help="AI sceptic: gaps, contradictions, questions"):
        st.session_state["tp_critique"] = plans.critique(p, SECTION)
    crit = st.session_state.get("tp_critique")
    if not crit:
        return
    st.info(crit.text)
    st.caption(f"{crit.where} · {crit.model} — reads only this plan's fields.")
    c1, c2 = st.columns(2)
    if c1.button("Show sources", key="tp_crit_src"):
        st.session_state["tp_crit_showsrc"] = not st.session_state.get("tp_crit_showsrc", False)
    if st.session_state.get("tp_crit_showsrc"):
        st.code("\n".join(f"[{i}] {f}" for i, f in enumerate(crit.facts(), 1)), language=None)
    if c2.button("Second opinion", key="tp_crit_2nd"):
        st.session_state["tp_crit_second"] = ai.second_opinion(crit.text, p, SECTION)
    sec = st.session_state.get("tp_crit_second")
    if sec:
        st.warning(sec.text)


def render() -> None:
    ui.page_header("Trade Plan", SECTION, "A plan is decisions made while the market is closed.")
    mkt = ui.market()
    _picker(mkt)
    p = _current(mkt)
    if p is None:
        st.info("Click **New plan** to open the plan template. Fill the YOU fields in your own "
                "words; leave Size empty — the Position Sizer fills it.")
        return
    st.caption(f"Plan #{p.id} · {p.template} · {p.symbol} · version {p.version}")
    p = _editor(p)
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Save", key="tp_save"):
        plans.save(p, note="edited")
        st.success(f"Saved version {p.version}.")
    if c2.button("Size it", key="tp_size"):
        plans.save(p, note="sent to sizer")
        st.session_state["sizer_plan_id"] = p.id
        st.success("Open Plan & Risk › Position Sizer: this plan is selected there. "
                   "Use in plan writes the size back.")
    if c3.button("Save to journal", key="tp_journal"):
        plans.save(p, note="saved to journal")
        rid = plans.save_to_journal(p)
        st.success(f"Plan timestamped in the journal (row {rid}) before the trade.")
    if c4.button("Send to Paper Desk", key="tp_paper"):
        try:
            plans.save(p, note="sent to Paper Desk")
            plans.send_to_paper_desk(p)
            st.success("The Paper Desk ticket is filled in from this plan. Click Place paper "
                       "order there; nothing is placed until you do.")
        except ValueError as exc:
            st.warning(str(exc))
    _critique(p)
    if p.versions:
        with st.expander(f"Plan version history ({len(p.versions)} earlier)"):
            st.dataframe(pd.DataFrame([{"version": v.get("version"), "saved": v.get("saved"),
                                        "entry": v.get("entry"), "stop": v.get("stop"),
                                        "qty": v.get("qty"),
                                        **{k: (t or "")[:40] for k, t in (v.get("fields") or {}).items()}}
                                       for v in reversed(p.versions)]),
                         hide_index=True, width="stretch")
