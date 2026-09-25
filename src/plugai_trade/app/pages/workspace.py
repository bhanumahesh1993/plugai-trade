"""Settings › Workspace (Chapter 34): Apply template, Preview changes, Accept per group,
Export workspace (settings, schedules and pins — never keys, never the journal)."""

from __future__ import annotations

import streamlit as st

from plugai_trade import workspace
from plugai_trade.app import ui


def _template() -> None:
    c1, c2 = st.columns(2)
    style = c1.selectbox("Template", workspace.STYLES, key="ws_style")
    default_mkt = "IN" if ui.market() == "IN" else "US"
    mkt = c2.radio("Market", list(workspace.MARKETS), horizontal=True,
                   index=list(workspace.MARKETS).index(default_mkt), key="ws_mkt")
    times = {}
    cols = st.columns(len(workspace.MARKETS[mkt]))
    for col, m in zip(cols, workspace.MARKETS[mkt]):
        zone = "IST, NSE trading days" if m == "IN" else "ET, NYSE trading days"
        times[m] = col.text_input(f"Daily Briefing time ({zone})", workspace.BRIEFING_AT[m],
                                  key=f"ws_time_{m}")
    if st.button("Apply template", key="ws_apply"):
        st.session_state["ws_preview"] = workspace.preview(style, mkt, times)
        st.session_state["ws_show"] = False
    if st.session_state.get("ws_preview") and st.button("Preview changes", key="ws_preview_btn"):
        st.session_state["ws_show"] = True


def _preview() -> None:
    pv: workspace.Preview | None = st.session_state.get("ws_preview")
    if pv is None:
        st.caption("Choose a template and click Apply template. Nothing changes until you Accept "
                   "each group.")
        return
    st.info(f"{pv.style} template for {' + '.join(pv.markets)} ready. "
            + ("" if st.session_state.get("ws_show") else "Click Preview changes to see it."))
    if not st.session_state.get("ws_show"):
        return
    for g in workspace.GROUPS:
        with st.container(border=True):
            st.markdown(f"**{g}**" + ("  ✓ accepted" if g in pv.accepted else ""))
            for line in pv.group(g):
                st.markdown(f"- {line}")
            if g == "Rule Card lines":
                st.caption("They arrive as suggestions on Plan & Risk › Rule Card; none is active "
                           "until you accept it there.")
            if st.button("Accept", key=f"ws_accept_{g}", disabled=g in pv.accepted):
                st.success(workspace.accept(pv, g))


def _export() -> None:
    if st.button("Export workspace", key="ws_export"):
        st.session_state["ws_json"] = workspace.export()
    if st.session_state.get("ws_json"):
        st.download_button("Download workspace.json", st.session_state["ws_json"],
                           file_name="plugai-trade-workspace.json", mime="application/json")
        st.caption("Holds settings, schedules and pins — not keys and not your journal.")


def render() -> None:
    ui.page_header("Workspace", "Settings", caption="One reviewed pass from a style template.")
    _template()
    _preview()
    pins = workspace.pinned()
    if pins:
        st.caption("Pinned on Home: " + " · ".join(pins))
    _export()
