"""Journal › Ask My Journal: a question → the query the lab ran → the answer and its rows."""

from __future__ import annotations

import streamlit as st

from plugai_trade import journal
from plugai_trade.app import ui
from plugai_trade.app.pages.journal_common import journal_frame, load_sample_button, rule_card
from plugai_trade.journal import review as rv
from plugai_trade.journal.query import EXAMPLES

HISTORY = "aj_history"


def _show(i: int, a: journal.Answer) -> None:
    with st.chat_message("user"):
        st.write(a.question)
    with st.chat_message("assistant"):
        st.caption(f"The lab runs: {a.spec.label}  ·  via {a.via}")
        st.write(a.text)
        if a.table.height:
            st.dataframe(a.table.to_pandas(), hide_index=True, use_container_width=True)
        if a.rows:
            st.caption("Rows: " + ", ".join(map(str, a.rows)))
        c1, c2 = st.columns(2)
        if c1.button("Show query", key=f"aj_q_{i}"):
            st.session_state[f"aj_showq_{i}"] = not st.session_state.get(f"aj_showq_{i}", False)
        if st.session_state.get(f"aj_showq_{i}"):
            st.code(a.sql + ";\n\n-- rows\n" + a.spec.rows_sql() + ";", language="sql")
        if a.via != "none" and c2.button("Accept", key=f"aj_pin_{i}",
                                         help="Pin this question to the Weekly Review"):
            rv.pin(a)
            st.success("Pinned: it will run every week in the Weekly Review.")


def render() -> None:
    ui.page_header("Ask My Journal", "Journal")
    market = ui.market()
    t, label = journal_frame(market)
    if t.is_empty():
        st.info("No journal rows yet. Import a tradebook in Journal › Trades, or load the "
                "lesson sample.")
        load_sample_button(market, "aj_sample")
        return
    st.caption(f"Asking {label} · 🔒 local model · read the query line before the answer.")
    history: list[journal.Answer] = st.session_state.setdefault(HISTORY, [])
    with st.expander("Examples"):
        for ex in EXAMPLES:
            st.markdown(f"- {ex}")
    for i, a in enumerate(history):
        _show(i, a)
    q = st.chat_input("Ask a question about your journal")
    if q:
        prev = history[-1].spec if history and history[-1].via != "none" else None
        history.append(journal.ask(q, t, previous=prev, card=rule_card()))
        st.rerun()
    if history and history[-1].via != "none":
        ui.ai_block(history[-1], f"aj_ai_{len(history)}", section="Journal", sensitive=True)
    if history and st.button("Clear chat"):
        st.session_state[HISTORY] = []
        st.rerun()
