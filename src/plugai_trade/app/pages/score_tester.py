"""Research › Score-Tester: a vendor score, tested point-in-time with delisted names and costs."""

from __future__ import annotations

import altair as alt
import streamlit as st

from plugai_trade import costs, scoretest
from plugai_trade.app import ui

NONE = "— none (assume next-day use) —"
HORIZONS = {"1 month": 30, "3 months": 91, "6 months": 182, "12 months": 365}


def _mapper(cols: list[str]) -> dict[str, str | None]:
    guess = scoretest.guess_mapping(cols)
    st.markdown("**Column mapper**")
    out: dict[str, str | None] = {}
    cs = st.columns(4)
    for c, fld in zip(cs, scoretest.FIELDS):
        opts = ([NONE] if fld == "Published at" else []) + cols
        g = guess.get(fld)
        pick = c.selectbox(fld, opts, index=opts.index(g) if g in opts else 0, key=f"st_map_{fld}")
        out[fld] = None if pick == NONE else pick
    if out["Published at"] is None:
        st.caption("No publication time: the lab assumes next-day use and says so in Warnings.")
    return out


def _report(rep: scoretest.Report) -> None:
    with st.expander("Report", expanded=True):
        _report_body(rep)


def _report_body(rep: scoretest.Report) -> None:
    if rep.buckets:
        chart = (
            alt.Chart(rep.table().to_pandas())
            .mark_bar(color="#0F766E")
            .encode(
                x=alt.X("label:N", title="Score bucket", sort=None),
                y=alt.Y("return:Q", title="Average return after costs, %"),
                tooltip=["label", "return", "names"],
            )
            .properties(height=240)
        )
        st.altair_chart(ui.hypothetical_chart(chart), use_container_width=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Top − bottom spread", f"{rep.spread:+.2f} pts")
    c2.metric("Universe average", f"{rep.universe_return:+.2f}%")
    c3.metric(
        "Hit share (top beat universe)",
        f"{rep.hit_share:.0f}%",
        f"{rep.hit_dates} of {rep.n_dates} dates",
        delta_color="off",
    )
    c4.metric(
        "Coverage (names per date)",
        f"{rep.coverage['median']:.0f}",
        f"{rep.coverage['min']:.0f}–{rep.coverage['max']:.0f}",
        delta_color="off",
    )
    st.markdown("**Warnings**")
    if rep.warnings:
        for w in rep.warnings:
            st.warning(w)
    else:
        st.caption("No warnings.")
    st.caption(
        f"Costs: {rep.cost_preset}, {rep.cost_pct:.2f}% round trip from the dated table. "
        "HYPOTHETICAL."
    )
    ui.ai_block(rep, "st_rep", section="Research")


def render() -> None:
    ui.page_header(
        "Score-Tester",
        "Research",
        "Did higher scores do better after costs, on the dates they were published?",
    )
    mkt = ui.market()
    up = st.file_uploader("Import vendor score CSV", type=["csv"])
    if up is not None:
        st.session_state["st_raw"] = up.getvalue()
    if st.button("Use the synthetic sample CSV"):
        st.session_state["st_raw"] = scoretest.sample_csv(mkt)
    raw = st.session_state.get("st_raw")
    if raw is None:
        st.info(
            "Export past scores from the vendor as a CSV with date, symbol and score (and "
            "ideally a published-at column), then import it."
        )
        return
    try:
        df = scoretest.read_csv(raw)
    except Exception as exc:  # a malformed CSV is shown, not raised
        st.error(f"Could not read the CSV: {exc}")
        return
    mapping = _mapper(df.columns)
    c1, c2, c3 = st.columns(3)
    horizon = c1.selectbox("Horizon", list(HORIZONS), index=1)
    delisted = c2.toggle("Include delisted", value=True)
    presets = list(costs.PROFILES)
    preset = c3.selectbox("Cost preset", presets, index=presets.index(scoretest.COST_PRESET[mkt]))
    if st.button("Point-in-time test", type="primary"):
        try:
            scores = scoretest.map_columns(df, mapping)
            st.session_state["st_rep"] = scoretest.run(
                scores, mkt, HORIZONS[horizon], delisted, preset
            )
        except ValueError as exc:
            st.error(str(exc))
    rep = st.session_state.get("st_rep")
    if rep is not None:
        _report(rep)
