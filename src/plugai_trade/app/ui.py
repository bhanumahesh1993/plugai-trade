"""Shared Streamlit pieces: top bar, AI buttons, charts with the HYPOTHETICAL mark.

Every page calls ``page_header(title, section)`` first. Anything an AI produces
is shown through ``ai_block`` so it always has Explain / Show sources /
Second opinion, and nothing it proposes is applied until the user clicks Accept.
"""

from __future__ import annotations

from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

from .. import ai, config, reference
from ..store import default as store


def market() -> str:
    if "market" not in st.session_state:
        st.session_state["market"] = config.get("market", "IN")
    return st.session_state["market"]


def page_header(title: str, section: str, caption: str | None = None) -> None:
    """Title plus the top bar: IN | US switch, data status, AI status, cost meter."""
    c1, c2, c3, c4 = st.columns([3, 1.2, 1.6, 1.2])
    with c1:
        st.markdown(f"### {title}")
        if caption:
            st.caption(caption)
    with c2:
        m = st.segmented_control("Market", ["IN", "US"], default=market(), key=f"mkt_{title}",
                                 label_visibility="collapsed")
        if m and m != st.session_state.get("market"):
            st.session_state["market"] = m
            config.set_value("market", m)
            st.rerun()
    with c3:
        last = st.session_state.get("data_status", "Synthetic · offline")
        st.caption(f"● Data: {last}")
    with c4:
        s = ai.status()
        badge = "Local" if s["reachable"] else "No model"
        st.caption(f"AI: {badge} · {s['model']}")
        st.caption(f"Cost: ${s['spend_this_month']:.2f} / ${s['budget']:.0f}")
    st.divider()


def set_data_status(df) -> None:
    try:
        src = df["source"][-1]
        when = df["fetched_at"][-1]
        st.session_state["data_status"] = f"{src} · {when[11:16]} UTC"
    except Exception:
        pass


def hypothetical_chart(chart: alt.Chart) -> alt.LayerChart:
    """Every backtest/paper chart carries the HYPOTHETICAL watermark."""
    mark = alt.Chart(pd.DataFrame({"t": ["HYPOTHETICAL"]})).mark_text(
        fontSize=28, opacity=0.12, fontWeight="bold", color="#475569"
    ).encode(text="t:N")
    return alt.layer(chart, mark)


def line_chart(df: pd.DataFrame, x: str, y: list[str] | str, title: str = "",
               hypothetical: bool = False, height: int = 260) -> None:
    ys = [y] if isinstance(y, str) else y
    long = df[[x, *ys]].melt(x, var_name="series", value_name="value")
    ch = alt.Chart(long).mark_line().encode(
        x=alt.X(f"{x}:T" if "date" in x else x, title=None),
        y=alt.Y("value:Q", title=None, scale=alt.Scale(zero=False)),
        color=alt.Color("series:N", legend=alt.Legend(orient="bottom")),
    ).properties(height=height, title=title)
    st.altair_chart(hypothetical_chart(ch) if hypothetical else ch, use_container_width=True)


def candles(df: pd.DataFrame, height: int = 300, levels: list[tuple[float, str]] | None = None) -> None:
    base = alt.Chart(df).encode(x=alt.X("date:T", title=None))
    color = alt.condition("datum.open <= datum.close", alt.value("#15803D"), alt.value("#DC2626"))
    rule = base.mark_rule().encode(y=alt.Y("low:Q", scale=alt.Scale(zero=False), title=None),
                                   y2="high:Q", color=color)
    bar = base.mark_bar().encode(y="open:Q", y2="close:Q", color=color)
    layers = [rule, bar]
    for price, label in levels or []:
        lv = pd.DataFrame({"y": [price], "label": [label]})
        layers.append(alt.Chart(lv).mark_rule(strokeDash=[4, 3], color="#7C3AED").encode(y="y:Q"))
        layers.append(alt.Chart(lv).mark_text(align="left", dx=4, dy=-6, color="#7C3AED")
                      .encode(y="y:Q", text="label:N", x=alt.value(0)))
    st.altair_chart(alt.layer(*layers).properties(height=height), use_container_width=True)


def ai_block(obj: Any, key: str, section: str = "Research", question: str | None = None,
             sensitive: bool = False, on_accept: Callable[[str], None] | None = None) -> None:
    """Explain / Show sources / Second opinion / Accept, for any lab result."""
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Explain", key=f"{key}_explain"):
        st.session_state[f"{key}_exp"] = ai.explain(obj, question, section=section,
                                                    sensitive=sensitive)
    exp = st.session_state.get(f"{key}_exp")
    if exp:
        box = st.warning if exp.blocked else st.info
        box(exp.text)
        st.caption(f"{exp.where} · {exp.model}")
    if c2.button("Show sources", key=f"{key}_src"):
        st.session_state[f"{key}_showsrc"] = not st.session_state.get(f"{key}_showsrc", False)
    if st.session_state.get(f"{key}_showsrc"):
        facts = ai.facts_from(obj)
        st.code("\n".join(f"[{i}] {f}" for i, f in enumerate(facts, 1)), language=None)
    if c3.button("Second opinion", key=f"{key}_2nd", disabled=not exp):
        st.session_state[f"{key}_second"] = ai.second_opinion(exp.text if exp else "", obj, section)
    sec = st.session_state.get(f"{key}_second")
    if sec:
        st.warning(sec.text)
    if on_accept and c4.button("Accept", key=f"{key}_accept", disabled=not exp, type="primary"):
        on_accept(exp.text if exp else "")
        st.success("Saved.")


def dated_note(text: str = "") -> None:
    st.caption(f"As of {reference.as_of()} · live values in Derivatives › Contract Table. {text}")


def paper_only_note() -> None:
    st.caption("PAPER ONLY — PlugAI-Trade never places real orders.")


def todo(features: list[str]) -> None:
    st.info("This screen is part of PlugAI-Trade v1.0.")
    for f in features:
        st.markdown(f"- {f}")


def lab_store():
    return store()
