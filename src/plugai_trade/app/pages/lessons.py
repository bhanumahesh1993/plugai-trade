"""Lessons › Lessons: one lesson per chapter, Check my work, Reset lesson (Appendix G).

``plugai-trade lesson 22`` opens here on Chapter 22. Each lesson has a goal,
its levels, steps that link to the real screens, an exercise computed in code on
synthetic data, and "Check my work", which compares your answers (or the lab's
own state) with values the lab computes at that moment.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from plugai_trade import lessons
from plugai_trade.app import nav, ui

BADGE_ICON = {"Not started": "○", "In progress": "◐", "Done": "●"}


def _label(les: lessons.Lesson) -> str:
    return f"Chapter {les.n} — {les.title}"


def _pick() -> lessons.Lesson:
    all_ = lessons.all_lessons()
    if "les_n" not in st.session_state:
        st.session_state["les_n"] = lessons.from_env() or 1
    n = st.selectbox("Lesson", [x.n for x in all_], key="les_n",
                     format_func=lambda k: _label(lessons.get(k)))
    return lessons.get(n)


def _steps(les: lessons.Lesson) -> None:
    st.markdown("##### Steps")
    for i, s in enumerate(les.steps, 1):
        c1, c2 = st.columns([3, 1.2])
        c1.markdown(f"**{i}.** {s.text}")
        if s.slug:
            with c2:
                nav.link(s.slug)


def _exercise(les: lessons.Lesson, mkt: str) -> None:
    st.markdown("##### Hands-on (synthetic data, computed in code)")
    if st.button("Load lesson sample", key=f"les_load_{les.n}"):
        st.session_state[f"les_loaded_{les.n}"] = lessons.load_sample(les.n, mkt)
    for line in st.session_state.get(f"les_loaded_{les.n}", []):
        st.caption(f"✓ {line}")
    if les.exercise is None:
        return
    try:
        ex = les.exercise(mkt)
    except Exception as exc:  # an optional module missing: say so, keep the lesson usable
        st.info(f"The exercise needs a part of the lab that is not available here: {exc}")
        return
    st.markdown(f"**{ex.title}**")
    for f in ex.facts():
        st.markdown(f"- {f}")
    if ex.table is not None:
        st.dataframe(ex.table.to_pandas(), hide_index=True, width="stretch")
    ui.ai_block(ex, key=f"les_ai_{les.n}", section="Research")


def _answer_widget(les: lessons.Lesson, c: lessons.Check) -> None:
    key = f"les_{les.n}_{c.key}"
    if c.kind == "number":
        st.text_input(c.text, key=key, placeholder="Type your number")
    elif c.kind == "tick":
        st.checkbox(c.text, key=key)
    else:
        st.markdown(f"☐ {c.text} — *the lab checks this itself*")


def _check_my_work(les: lessons.Lesson, mkt: str) -> None:
    st.markdown("##### Check my work")
    for c in les.checks:
        _answer_widget(les, c)
    c1, c2, _ = st.columns([1.2, 1.2, 3])
    if c1.button("Check my work", key=f"les_check_{les.n}", type="primary"):
        answers = {c.key: st.session_state.get(f"les_{les.n}_{c.key}") for c in les.checks}
        st.session_state[f"les_res_{les.n}"] = lessons.check(les.n, answers, mkt)
    if c2.button("Reset lesson", key=f"les_reset_{les.n}"):
        lessons.reset(les.n)
        for k in [k for k in st.session_state if str(k).startswith(
                (f"les_{les.n}_", f"les_res_{les.n}", f"les_loaded_{les.n}", f"les_ai_{les.n}"))]:
            del st.session_state[k]
        st.rerun()
    results = st.session_state.get(f"les_res_{les.n}")
    if results:
        text = {c.key: c.text for c in les.checks}
        for r in results:
            (st.success if r.passed else st.warning)(
                f"{'✓' if r.passed else '✗'} {text[r.key]} — {r.detail}")
        st.caption(f"Progress: {lessons.badge(les.n)}")


def _overview() -> None:
    with st.expander("All lessons and your progress"):
        st.dataframe(pd.DataFrame([{"Chapter": x.n, "Lesson": x.title,
                                    "Levels": " · ".join(x.levels),
                                    "Progress": lessons.badge(x.n),
                                    "Command": f"plugai-trade lesson {x.n}"}
                                   for x in lessons.all_lessons()]),
                     hide_index=True, width="stretch")


def render() -> None:
    ui.page_header("Lessons", "Lessons",
                   caption="One lesson per chapter · synthetic data, so your numbers match the book")
    mkt = ui.market()
    les = _pick()
    b = lessons.badge(les.n)
    st.markdown(f"### Chapter {les.n}: {les.title}  ·  {BADGE_ICON[b]} {b}")
    st.markdown(f"**Goal.** {les.goal}")
    st.caption(f"Levels: {' · '.join(les.levels)} · Market: {mkt} · Terminal: "
               f"`plugai-trade lesson {les.n}`")
    _steps(les)
    _exercise(les, mkt)
    _check_my_work(les, mkt)
    _overview()
    ui.paper_only_note()
