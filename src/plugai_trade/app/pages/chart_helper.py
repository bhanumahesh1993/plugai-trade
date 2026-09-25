"""Research › Chart Helper: Describe (numbers mode), Levels, Add timeframe, Screenshot mode."""

from __future__ import annotations

import polars as pl
import streamlit as st

from plugai_trade import charthelper as ch
from plugai_trade.app import ui

DEFAULT_SYMBOL = {"IN": "NIFTY", "US": "SPY"}
SOURCES = {"Synthetic": "synthetic", "Data Sources (Settings)": None}


def _chart(bars: pl.DataFrame, lv: ch.Levels | ch.IntradayLevels | None) -> None:
    lines: list[tuple[float, str]] = []
    if isinstance(lv, ch.Levels):
        lines = [
            ((z.low + z.high) / 2, z.kind)
            for z in lv.zones
            if z.touches >= 2 or z.kind.startswith(("Pivot P", "POC"))
        ]
    elif isinstance(lv, ch.IntradayLevels):
        lines = [(v, k) for k, v in lv.values.items()]
    view = bars.tail(60)
    if "time" in view.columns:
        view = view.with_columns(pl.col("time").str.to_datetime("%Y-%m-%dT%H:%M").alias("date"))
    ui.candles(view.select("date", "open", "high", "low", "close").to_pandas(), levels=lines)


def _describe(bars: pl.DataFrame, symbol: str, tf: str, shot: bool) -> None:
    d = ch.describe(bars, symbol, tf)
    if not shot:
        st.markdown("\n".join(f"- {ln}" for ln in d.lines))
        ui.ai_block(
            d,
            "chd",
            section="Research",
            question="Describe this chart from the numbers only. Cite each value.",
        )
        return
    left, right = st.columns(2)
    with left:
        st.markdown("**Numbers answer**")
        st.markdown("\n".join(f"- {ln}" for ln in d.lines))
    with right:
        st.markdown("**Screenshot answer (unreliable)**")
        st.caption(
            "Simulated vision reading: this build does not send images to a model. Each "
            "claim is checked against the table."
        )
        claims = ch.screenshot_claims(d, ch.levels(bars, symbol))
        st.dataframe(
            pl.DataFrame(
                [{"Claim": c.text, "Check": c.check, "Against the table": c.why} for c in claims]
            ),
            hide_index=True,
        )
        st.caption(f"✗ marks: {sum(c.check == '✗' for c in claims)} of {len(claims)}")
    ui.ai_block(d, "chd", section="Research")


def _levels(bars: pl.DataFrame, symbol: str, mkt: str, tf: str) -> ch.Levels | ch.IntradayLevels:
    kind = st.radio("Levels set", ["Zones", "Intraday"], horizontal=True, key="chl_set")
    if kind == "Intraday":
        orm = st.select_slider("Opening range (minutes)", [5, 15, 30], value=15)
        intra = bars if "time" in bars.columns else ch.load(symbol, mkt, "5-min")
        daily = ch.load(symbol, mkt, "Daily", end=intra["date"][-1], source="synthetic")
        prev = daily.filter(pl.col("date") < intra["date"][-1]).row(-1, named=True)
        lv: ch.Levels | ch.IntradayLevels = ch.intraday_levels(intra, prev, orm, symbol)
    else:
        lv = ch.levels(bars, symbol)
    st.dataframe(lv.table(), hide_index=True)
    c1, c2 = st.columns(2)
    if c1.button("Save levels to journal"):
        ch.save_levels_to_journal(symbol, mkt, tf, lv)
        st.success("Saved with today's date for the weekly review.")
    if c2.button("Send levels to Paper Desk"):
        ch.send_levels_to_paper_desk(symbol, mkt, lv)
        st.success('Sent. Alerts can reference them by name, e.g. "OR high", "VWAP".')
    return lv


def render() -> None:
    ui.page_header(
        "Chart Helper",
        "Research",
        "The model receives the table and the computed values, never the picture.",
    )
    mkt = ui.market()
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1.4])
    symbol = c1.text_input("Symbol", DEFAULT_SYMBOL[mkt], key=f"ch_sym_{mkt}").upper().strip()
    tf = c2.selectbox("Timeframe", list(ch.TIMEFRAMES))
    src = c3.selectbox(
        "Data",
        list(SOURCES),
        help="Data Sources uses the chain in Settings › Data Sources and "
        "falls back to the synthetic sample when a source "
        "returns too little history.",
    )
    shot = c4.toggle("Screenshot mode (unreliable)", value=False)
    try:
        bars = ch.load(symbol, mkt, tf, source=SOURCES[src])
    except Exception as exc:  # a source failure is shown, the screen keeps working
        st.error(f"Could not load {symbol}: {exc}")
        return
    ui.set_data_status(bars)
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("Describe", type="primary"):
        st.session_state["ch_view"] = "describe"
    if b2.button("Levels"):
        st.session_state["ch_view"] = "levels"
    view = st.session_state.get("ch_view")
    lv = None
    if view == "levels":
        lv = _levels(bars, symbol, mkt, tf)
    _chart(bars, lv)
    if view == "describe":
        _describe(bars, symbol, tf, shot)
    with st.expander("Add timeframe"):
        frames = st.multiselect(
            "Timeframes", list(ch.TIMEFRAMES), default=["Daily", "Weekly", "15-min"]
        )
        if st.button("Add timeframe"):
            st.session_state["ch_tf"] = ch.timeframes(symbol, mkt, frames, source=SOURCES[src])
        if "ch_tf" in st.session_state:
            st.dataframe(st.session_state["ch_tf"], hide_index=True)
            st.caption("A row that disagrees with the others is worth a note, not a decision.")
    st.caption(f"Source: {bars['source'][-1]} · HYPOTHETICAL study, not a signal.")
