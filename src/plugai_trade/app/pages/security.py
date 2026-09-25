"""Settings › Security (Chapter 33): Security checklist, Registration check, Check a pitch,
Audit log (Cloud filter) and Export log. The lab never judges a registration."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from plugai_trade import security
from plugai_trade.app import ui


def _checklist() -> None:
    items = security.checklist()
    st.markdown(f"#### Security checklist · {security.score(items)}")
    for it in items:
        if it.manual:
            val = st.checkbox(it.text, value=it.ok, key=f"sec_tick_{it.key}")
            if val != it.ok:
                security.tick(it.key, val)
                st.rerun()
        else:
            (st.success if it.ok else st.warning)(f"{'✓' if it.ok else '!'} {it.text} — {it.detail}")


def _registration() -> None:
    st.markdown("#### Registration check")
    c1, c2 = st.columns(2)
    mkt = c1.radio("Market", ["IN", "US"], index=["IN", "US"].index(ui.market()),
                   horizontal=True, key="sec_reg_mkt")
    kind = c2.selectbox("Type", security.REG_TYPES, key="sec_reg_type")
    for r in security.registers(mkt, kind):
        st.link_button(f"Open {r.name}", r.url)
        st.caption(r.covers)
    st.caption(security.REGISTRATION_NOTE)


def _pitch() -> None:
    st.markdown("#### Check a pitch")
    text = st.text_area("Paste the pitch, website text or terms (remove your personal details)",
                        key="sec_pitch", height=120)
    if st.button("Check a pitch", key="sec_pitch_run", type="primary") and text.strip():
        st.session_state["sec_pc"] = security.check_pitch(text)
    pc: security.PitchCheck | None = st.session_state.get("sec_pc")
    if pc is None:
        return
    if pc.flags:
        st.dataframe(pd.DataFrame([{"Claim (quoted)": f.quote, "Type": f.kind,
                                    "Red flag": f.flag} for f in pc.flags]),
                     hide_index=True, width="stretch")
    else:
        st.info("No red-flag phrases matched the scan. That is not a clean bill of health: check "
                "the register yourself.")
    for p, mult in pc.compound:
        st.warning(f"Calculator test: {p:g}% a day for 250 trading days multiplies the stake by "
                   f"{mult:,.0f}.")
    if pc.names:
        st.caption("Names, numbers and sites mentioned: " + " · ".join(pc.names))
    if pc.ai_text:
        st.markdown(f"**Model reading** ({pc.where} · {pc.model})")
        st.info(pc.ai_text)
    else:
        st.caption("No model connected: the red-flag scan above is computed in code.")
    ui.ai_block(pc, key="sec_pc_ai", section="Research")


def _audit() -> None:
    st.markdown("#### Audit log")
    f = st.segmented_control("Filter", security.FILTERS, default="All", key="sec_filter") or "All"
    rows = security.audit_rows(f)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("Nothing logged for this filter yet.")
    if st.button("Export log", key="sec_export"):
        st.session_state["sec_csv"] = security.export_log(f)
    if st.session_state.get("sec_csv"):
        st.download_button("Download audit-log.csv", st.session_state["sec_csv"],
                           file_name="plugai-trade-audit-log.csv", mime="text/csv")


def render() -> None:
    ui.page_header("Security", "Settings",
                   caption="The lab holds no money and places no orders; this page protects your "
                           "keys, journal and accounts.")
    _checklist()
    _registration()
    _pitch()
    _audit()
