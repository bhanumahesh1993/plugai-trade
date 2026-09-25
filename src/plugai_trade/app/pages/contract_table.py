"""Derivatives › Contract Table — dated lot sizes, expiry days, settlement, sessions and fees."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from plugai_trade import futures, reference
from plugai_trade.app import ui


def _asset(row: dict) -> str:
    if row["Symbol"] == "USDINR":
        return "Currency"
    if row["Exchange"] in ("MCX", "NYMEX", "COMEX"):
        return "Commodity"
    return "Index / ETF"


def _sessions() -> pd.DataFrame:
    rows = []
    for mkt, root in (("IN", "india"), ("US", "us")):
        for name, s in (reference.lookup(f"{root}.sessions", {}) or {}).items():
            hours = f"{s['open']}–{s['close']}" if "open" in s else s.get("note", "")
            rows.append({"Market": mkt, "Session": name, "Hours": hours, "Time zone": s.get("tz", ""),
                         "Settlement": s.get("settlement", "")})
    return pd.DataFrame(rows)


def _fees() -> pd.DataFrame:
    stt = reference.lookup("india.charges.stt", {}) or {}
    rows = [{"Market": "IN", "Fee": "Brokerage per order (typical)",
             "Value": f"₹{reference.lookup('india.charges.brokerage_per_order')}"},
            {"Market": "IN", "Fee": "STT futures (sell)", "Value": f"{stt.get('futures', {}).get('sell', 0) * 100:.3f}%"},
            {"Market": "IN", "Fee": "STT options premium (sell)",
             "Value": f"{stt.get('options_premium', {}).get('sell', 0) * 100:.3f}%"},
            {"Market": "IN", "Fee": "STT options exercised", "Value": f"{stt.get('options_exercised', 0) * 100:.3f}%"},
            {"Market": "US", "Fee": "Options contract fee (typical)",
             "Value": f"${reference.lookup('us.charges.options_contract_fee')}"},
            {"Market": "US", "Fee": "Regulatory per $ sold",
             "Value": f"{reference.lookup('us.charges.regulatory_per_dollar_sold')}"}]
    return pd.DataFrame(rows)


def render() -> None:
    ui.page_header("Contract Table", "Derivatives")
    st.caption(f"As of **{reference.as_of()}** · dated rows from the reference tables. "
               "Run `plugai-trade update` to fetch the latest published table.")
    rows = futures.contract_rows()
    for r in rows:
        r["Asset"] = _asset(r)
        r["Exposure required"] = "Exposure required" if r["Exposure required"] else ""
    df = pd.DataFrame(rows)
    c1, c2, c3 = st.columns(3)
    mkt = c1.selectbox("Market", ["All", "IN", "US"],
                       index=["All", "IN", "US"].index(ui.market()), key="ct_market")
    cur = c2.selectbox("Currency", ["All", "INR", "USD"], key="ct_currency")
    asset = c3.selectbox("Asset", ["All", "Index / ETF", "Commodity", "Currency"], key="ct_asset")
    if mkt != "All":
        df = df[df["Market"] == mkt]
    if cur != "All":
        df = df[df["Currency"] == cur]
    if asset != "All":
        df = df[df["Asset"] == asset]
    cols = ["Symbol", "Market", "Exchange", "Asset", "Currency", "Lot / multiplier", "Expiry",
            "Settlement", "Exposure required", "Effective from", "Source", "As of"]
    st.dataframe(df[cols].astype(str), hide_index=True, width="stretch")
    if (df["Exposure required"] != "").any():
        st.warning("Exposure required: USDINR positions beyond small limits need genuine "
                   "underlying currency exposure (Chapter 26).")
    if df["Source"].str.startswith("†").any():
        st.caption("† pending reference row: the book's printed value, not yet in the dated "
                   "reference tables — confirm with the exchange before relying on it.")
    st.markdown("**Sessions**")
    st.dataframe(_sessions(), hide_index=True, width="stretch")
    st.markdown("**Fees and taxes on the trade**")
    st.dataframe(_fees(), hide_index=True, width="stretch")
    ui.dated_note()
