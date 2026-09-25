"""Lessons › Prompt Library (Chapter 3, Appendix B).

Search box, filter chips (Research / Plan / Journal / Review, plus the book's
other groups), and one card per prompt with Fill in, Send to Document Desk and
Save my version (tagged MY VERSION). Pasted text is fenced as UNTRUSTED.
"""

from __future__ import annotations

import streamlit as st

from plugai_trade import prompts
from plugai_trade.app import nav, ui


def _kid(p: prompts.Prompt) -> str:
    return f"{p.id}_{p.note_id}" if p.mine else p.id


def _values(p: prompts.Prompt, text: str) -> dict[str, str]:
    vals = {}
    for i, name in enumerate(prompts.placeholders(text)):
        key = f"pl_v_{_kid(p)}_{i}"
        if prompts.is_paste_slot(name):
            vals[name] = st.text_area(name, key=key, height=110,
                                      help="Pasted text is fenced as UNTRUSTED automatically.")
        else:
            vals[name] = st.text_input(name, key=key)
    return vals


def _send_to_desk(p: prompts.Prompt, filled: str, vals: dict[str, str]) -> None:
    """Hand the prompt (and any pasted source) to Research › Document Desk."""
    pasted = "\n\n".join(v for k, v in vals.items() if prompts.is_paste_slot(k) and v.strip())
    if pasted:
        from plugai_trade import docdesk
        doc = docdesk.load_text(pasted, f"{p.title} · pasted", ui.market())
        st.session_state.setdefault("dd_docs", {})[doc.name] = doc
        st.session_state["dd_current"] = doc.name
    st.session_state["dd_prompt"] = filled
    nav.go("documents")


def _fill_panel(p: prompts.Prompt) -> None:
    kid = _kid(p)
    text = st.text_area("Prompt (edit it to make it yours)", p.text, key=f"pl_edit_{kid}",
                        height=220)
    vals = _values(p, text)
    filled = prompts.fill(text, vals)
    left = prompts.placeholders(filled)
    st.markdown("**Ready to paste**" + (f" · {len(left)} placeholder(s) still to fill"
                                        if left else ""))
    st.code(filled, language=None)
    if "UNTRUSTED" in filled:
        st.caption("UNTRUSTED · pasted text is fenced so instructions inside it are not followed.")
    c1, c2 = st.columns(2)
    if c1.button("Send to Document Desk", key=f"pl_send_{kid}", type="primary"):
        _send_to_desk(p, filled, vals)
    if c2.button("Save my version", key=f"pl_save_{kid}"):
        prompts.save_my_version(p.id, text)
        st.success("Saved. Your copy (MY VERSION) now sits above the book's version.")


def _card(p: prompts.Prompt) -> None:
    kid = _kid(p)
    with st.container(border=True):
        tag = "  `MY VERSION`" if p.mine else ""
        st.markdown(f"**{p.title}**{tag}")
        st.caption(f"From Chapter {p.chapter} · {p.chapter_title} · Use it for {p.use} · "
                   f"{p.works_with} · {' · '.join(p.chips)}")
        open_ = st.session_state.get("pl_open") == kid
        if not open_:
            st.code(p.text, language=None)
        c1, c2, c3 = st.columns([1, 1.6, 1.4])
        if c1.button("Fill in", key=f"pl_fill_{kid}"):
            st.session_state["pl_open"] = None if open_ else kid
            st.rerun()
        if not open_:
            if c2.button("Send to Document Desk", key=f"pl_send0_{kid}"):
                _send_to_desk(p, p.text, {})
            if c3.button("Save my version", key=f"pl_save0_{kid}"):
                st.session_state["pl_open"] = kid
                st.rerun()
        if p.mine and c3.button("Delete my version", key=f"pl_del_{kid}"):
            prompts.delete_my_version(p.note_id)
            st.rerun()
        if open_:
            _fill_panel(p)


def render() -> None:
    ui.page_header("Prompt Library", "Lessons",
                   caption="The book's 40 prompts (Appendix B). Text in [CAPITALS] is yours to "
                           "replace. Keep the “Do NOT recommend” and “Do NOT do arithmetic” lines.")
    q = st.text_input("Search", placeholder="concall, 10-K, plan, wash sale…", key="pl_q")
    chips = st.pills("Filter", list(prompts.CHIPS), selection_mode="multi", key="pl_chips") or []
    found = prompts.search(q, chips)
    st.caption(f"{len(found)} prompt(s)")
    for p in found:
        _card(p)
