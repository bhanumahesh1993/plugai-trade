"""Research › Document Desk: quote-first answers with page chips, tables, Compare, My library."""

from __future__ import annotations

import polars as pl
import streamlit as st

from plugai_trade import docdesk
from plugai_trade.app import ui

SCOPES = ["This document", "Ask my documents"]


def _docs() -> dict[str, docdesk.Document]:
    return st.session_state.setdefault("dd_docs", {})


def _add(doc: docdesk.Document) -> None:
    _docs()[doc.name] = doc
    st.session_state["dd_current"] = doc.name


def _load_panel(mkt: str) -> None:
    c1, c2 = st.columns([1.2, 1])
    with c1:
        files = st.file_uploader(
            "Drop a PDF", type=["pdf", "txt", "md"], accept_multiple_files=True
        )
        for f in files or []:
            if f.name not in _docs():
                try:
                    doc = (
                        docdesk.load_pdf(f.getvalue(), name=f.name, market=mkt)
                        if f.name.lower().endswith(".pdf")
                        else docdesk.load_text(f.getvalue().decode(errors="replace"), f.name, mkt)
                    )
                    _add(doc)
                except docdesk.DocError as exc:
                    st.error(str(exc))
        link = st.text_input(
            "Paste a link", placeholder="https://… (exchange filing, EDGAR, IR page)"
        )
        if st.button("Fetch link") and link:
            try:
                _add(docdesk.load_link(link, market=mkt))
            except docdesk.DocError as exc:
                st.error(str(exc))
    with c2:
        text = st.text_area(
            "Or paste text",
            height=100,
            help="Pasted text is fenced as UNTRUSTED: instructions inside it are ignored.",
        )
        name = st.text_input("Name for pasted text", "Pasted text")
        if st.button("Add pasted text") and text.strip():
            _add(docdesk.load_text(text, name or "Pasted text", mkt))
        sample = st.selectbox("Sample documents (fictional)", list(docdesk.SAMPLES))
        if st.button("Load sample"):
            _add(docdesk.sample(sample))


def _doc_list() -> docdesk.Document | None:
    docs = _docs()
    if not docs:
        st.info("Drop a PDF, paste a link or text, or load a fictional sample to begin.")
        return None
    for d in docs.values():
        tag = " · UNTRUSTED" if d.kind in ("text", "link") else ""
        st.caption(f"📄 {d.name} · {d.text_check()} · {d.market}{tag}")
    names = list(docs)
    cur = st.session_state.get("dd_current", names[-1])
    pick = st.selectbox("Document", names, index=names.index(cur) if cur in names else 0)
    return docs[pick]


def _ask(doc: docdesk.Document | None) -> None:
    st.markdown("##### Ask")
    scope = st.radio("Scope", SCOPES, horizontal=True, key="dd_scope")
    if "dd_prompt" in st.session_state:  # sent from Lessons › Prompt Library
        st.session_state["dd_question"] = st.session_state.pop("dd_prompt")
    q = st.text_input(
        "Question", key="dd_question",
        placeholder="What did management say about receivables and credit terms?",
    )
    if st.button("Ask", type="primary") and q:
        if scope == SCOPES[1]:
            st.session_state["dd_answer"] = docdesk.Library().ask(q)
        elif doc is not None:
            st.session_state["dd_answer"] = docdesk.ask(q, doc)
        else:
            st.warning("Load a document first, or switch the scope to Ask my documents.")
    ans: docdesk.Answer | None = st.session_state.get("dd_answer")
    if ans is None:
        return
    st.markdown(ans.markdown())
    if ans.narration:
        (st.caption if ans.where == "Fallback" else st.info)(ans.narration)
    if ans.unverified:
        st.warning(
            "Quotes in the model's reply not found word for word in the source: "
            + " | ".join(ans.unverified)
        )
    with st.expander("Passages searched (closeness scores)"):
        st.dataframe(
            pl.DataFrame(
                [
                    {
                        "Citation": h.chunk.cite,
                        "Closeness": h.closeness,
                        "Method": h.method,
                        "Passage": h.chunk.text[:220],
                    }
                    for h in ans.hits
                ]
            ),
            hide_index=True,
        )
    ui.ai_block(ans, "dd_ans", section="Documents")


def _extract(doc: docdesk.Document, mkt: str) -> None:
    st.markdown("##### Extract to table")
    tpl = st.selectbox("Template", list(docdesk.TEMPLATES), key="dd_tpl")
    with st.expander("Edit fields"):
        edited = st.text_area(
            "One field per line: Name: search words, comma-separated",
            docdesk.fields_text(tpl),
            key=f"dd_fields_{tpl}",
            height=160,
        )
    if st.button("Extract to table"):
        st.session_state["dd_ext"] = docdesk.extract(doc, tpl, docdesk.parse_fields(edited))
    ext: docdesk.Extraction | None = st.session_state.get("dd_ext")
    if ext is None:
        return
    st.caption(f"{ext.template} · {ext.document} · {ext.found()} of {len(ext.rows)} found")
    st.dataframe(pl.DataFrame(ext.as_records()), hide_index=True)
    for r in ext.rows:
        if r.status != "found":
            st.caption(f"{r.field}: not found in source · pages searched: {', '.join(r.searched)}")
    st.download_button(
        "Export CSV", ext.to_csv(), file_name=f"{ext.document}_{ext.template}.csv", mime="text/csv"
    )
    ui.ai_block(
        ext,
        "dd_ext",
        section="Documents",
        on_accept=lambda _t: docdesk.accept_to_thesis(ext.document, extraction=ext, market=mkt),
    )


def _compare(mkt: str) -> None:
    st.markdown("##### Compare")
    names = list(_docs())
    if len(names) < 2:
        st.caption("Load two documents (for example two quarters' transcripts) to compare.")
        return
    c1, c2 = st.columns(2)
    a = c1.selectbox("Earlier", names, index=0, key="dd_cmp_a")
    b = c2.selectbox("Later", names, index=len(names) - 1, key="dd_cmp_b")
    if st.button("Compare"):
        st.session_state["dd_cmp"] = docdesk.compare(_docs()[a], _docs()[b])
    cmp: docdesk.Comparison | None = st.session_state.get("dd_cmp")
    if cmp is None:
        return
    st.dataframe(
        pl.DataFrame(
            [
                {
                    "Topic": r.topic,
                    f"{cmp.doc_a}": f"{r.quote_a} {r.cite_a}",
                    f"{cmp.doc_b}": f"{r.quote_b} {r.cite_b}",
                    "Change": r.change,
                }
                for r in cmp.rows
            ]
        ),
        hide_index=True,
    )
    st.markdown("**Tone count** (computed in code, per 1,000 words)")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric(f"Hedging · {cmp.doc_a}", cmp.tone_a.hedging_per_1000)
    t2.metric(
        f"Hedging · {cmp.doc_b}",
        cmp.tone_b.hedging_per_1000,
        round(cmp.tone_b.hedging_per_1000 - cmp.tone_a.hedging_per_1000, 1),
        delta_color="off",
    )
    t3.metric(f"Confident · {cmp.doc_a}", cmp.tone_a.confident_per_1000)
    t4.metric(
        f"Confident · {cmp.doc_b}",
        cmp.tone_b.confident_per_1000,
        round(cmp.tone_b.confident_per_1000 - cmp.tone_a.confident_per_1000, 1),
        delta_color="off",
    )
    ui.ai_block(
        cmp,
        "dd_cmp",
        section="Documents",
        on_accept=lambda _t: docdesk.accept_to_thesis(cmp.doc_b, comparison=cmp, market=mkt),
    )


def _library(mkt: str) -> None:
    lib = docdesk.Library()
    n = lib.counts()
    c1, c2, c3 = st.columns(3)
    c1.metric("Documents", n["documents"])
    c2.metric("Chunks", f"{n['chunks']:,}")
    c3.metric("Scanned PDFs skipped", n["scanned"])
    folder = st.text_input("Folder", placeholder="~/Documents/trading-notes")
    fm = st.radio(
        "Market for this folder",
        ["IN", "US"],
        horizontal=True,
        index=0 if mkt == "IN" else 1,
        key="dd_lib_mkt",
    )
    emb = st.toggle("Embed with the local embedding model (if reachable)", value=False)
    if st.button("Add folder") and folder:
        try:
            with st.spinner("Chunking and indexing on this computer…"):
                rep = lib.add_folder(folder, market=fm, use_embeddings=emb)
            st.success(rep.line())
            for e in rep.errors:
                st.warning(e)
        except docdesk.DocError as exc:
            st.error(str(exc))
    if st.button("Index the sample documents"):
        for name in docdesk.SAMPLES:
            lib.add_document(docdesk.sample(name), key=f"sample:{name}")
        lib.save()
        st.success(f"{lib.counts()['chunks']:,} chunks indexed")
    if lib.docs:
        st.dataframe(
            pl.DataFrame(
                [
                    {
                        "Document": d["name"],
                        "Market": d["market"],
                        "Pages": d["pages"],
                        "Chunks": d["chunks"],
                        "Scanned": d["scanned"],
                    }
                    for d in lib.docs.values()
                ]
            ),
            hide_index=True,
        )
    st.caption(
        "Ask my documents: switch the Ask scope on the Desk tab. Answers quote each chunk "
        "with its file and page; Show sources lists every chunk with its closeness score."
    )


def render() -> None:
    ui.page_header(
        "Document Desk",
        "Research",
        "Quote first, cite every page. The desk extracts figures; it never calculates them.",
    )
    mkt = ui.market()
    desk, library = st.tabs(["Desk", "My library"])
    with desk:
        _load_panel(mkt)
        doc = _doc_list()
        _ask(doc)
        if doc is not None:
            _extract(doc, mkt)
        _compare(mkt)
    with library:
        _library(mkt)
