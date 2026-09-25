"""Settings › Privacy (Chapters 2 and 4): what may leave your computer, and the Education lag.

Strict defaults: journal and holdings local-only, ask before sending to cloud,
strip account numbers / PAN / SSN before cloud calls, crash reports off.
Education lag: named Indian securities in lessons use data at least N days old
(default 90, minimum 30).
"""

from __future__ import annotations

import streamlit as st

from plugai_trade import privacy
from plugai_trade.app import ui

TOGGLES = (
    ("journal_local_only", "Journal and tradebook use the local model only"),
    ("holdings_local_only", "Holdings use the local model only"),
    ("ask_before_cloud", "Ask before sending to cloud"),
    ("strip_identifiers", "Remove account numbers and PAN/SSN before cloud calls"),
    ("crash_reports", "Share anonymous crash reports"),
)


def _toggles() -> None:
    s = privacy.settings()
    for name, label in TOGGLES:
        val = st.toggle(label, value=getattr(s, name), key=f"pv_{name}")
        if val != getattr(s, name):
            privacy.set_toggle(name, val)
    if privacy.defaults_on():
        st.caption("✓ The book's defaults are on.")
    else:
        st.caption("You changed a default. The book assumes the strict defaults.")


def _preview() -> None:
    with st.expander("See what a cloud call would send"):
        text = st.text_area("Paste text", key="pv_sample",
                            placeholder="Contract note line, client code, PAN, SSN…")
        if text.strip():
            kinds = privacy.found_identifiers(text)
            st.caption("Found: " + (", ".join(kinds) if kinds else "no identifiers"))
            st.code(privacy.cloud_payload(text), language=None)


def _lag() -> None:
    st.markdown("#### Education lag")
    days = st.number_input("Days of lag for named Indian securities in lessons and AI "
                           "explanations", min_value=privacy.MIN_LAG, max_value=3650,
                           value=privacy.education_lag(), step=1, key="pv_lag")
    if int(days) != privacy.education_lag():
        privacy.set_education_lag(int(days))
    st.caption(f"Default {privacy.DEFAULT_LAG} days (minimum {privacy.MIN_LAG}). Indices "
               "(NIFTY, BANKNIFTY, SENSEX), synthetic data and your own tradebook are not affected.")


def render() -> None:
    ui.page_header("Privacy", "Settings", caption="What may leave your computer.")
    _toggles()
    _preview()
    _lag()
