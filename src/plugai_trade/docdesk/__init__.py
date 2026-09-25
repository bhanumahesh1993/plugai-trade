"""Research › Document Desk: read filings and transcripts with page citations.

    from plugai_trade import docdesk
    doc = docdesk.load_pdf("Kaveri_Q1-FY27_concall.pdf")
    print(doc.text_check())                       # "11 pages · text OK"
    ans = docdesk.ask("What did management say about receivables?", doc)
    print(ans.markdown())                         # quotes first, each with [p. 6]
    table = docdesk.extract(doc, "Red-flag checklist")
    print(table.to_csv())

Retrieval, quoting, extraction, comparison and the tone count all run in code.
A model, when connected, only writes around the quotes the code selected.
"""

from __future__ import annotations

from ..store import default as store
from .ask import Answer, Quote, ask, ask_chunks, verify_quotes
from .extract import (
    COMPARE_TOPICS,
    NOT_FOUND,
    TEMPLATES,
    Comparison,
    Extraction,
    Field,
    Row,
    Tone,
    compare,
    extract,
    fields_text,
    parse_fields,
    tone_count,
    word_change,
)
from .library import IndexReport, Library
from .loader import DocError, Document, load_file, load_link, load_pdf, load_text
from .retrieve import BM25, Chunk, Hit, Retriever, chunk, tfidf_cosine, tokens
from .samples import SAMPLES, make_pdf, sample

__all__ = [
    "BM25",
    "COMPARE_TOPICS",
    "NOT_FOUND",
    "SAMPLES",
    "TEMPLATES",
    "Answer",
    "Chunk",
    "Comparison",
    "DocError",
    "Document",
    "Extraction",
    "Field",
    "Hit",
    "IndexReport",
    "Library",
    "Quote",
    "Retriever",
    "Row",
    "Tone",
    "accept_to_thesis",
    "ask",
    "ask_chunks",
    "chunk",
    "compare",
    "extract",
    "fields_text",
    "load_file",
    "load_link",
    "load_pdf",
    "load_text",
    "make_pdf",
    "parse_fields",
    "sample",
    "tfidf_cosine",
    "tokens",
    "tone_count",
    "verify_quotes",
    "word_change",
]


def accept_to_thesis(
    name: str,
    extraction: Extraction | None = None,
    comparison: Comparison | None = None,
    market: str = "IN",
    note: str = "",
) -> int:
    """Accept: save an extraction or comparison to Portfolio › Thesis tracker (store "theses").

    The row carries the Thesis tracker's fields (holding, why, conditions,
    figures) plus the quoted table, so next quarter's comparison starts from it.
    """
    body: dict = {
        "holding": name,
        "why": note or "Saved from the Document Desk",
        "conditions": [],
        "figures": [],
        "name": name,
        "market": market,
        "source": "Document Desk",
    }
    if extraction is not None:
        body.update(
            kind="extraction",
            template=extraction.template,
            document=extraction.document,
            rows=extraction.as_records(),
        )
    if comparison is not None:
        body.update(
            kind="comparison",
            documents=[comparison.doc_a, comparison.doc_b],
            rows=[r.__dict__ for r in comparison.rows],
            tone={"A": comparison.tone_a.__dict__, "B": comparison.tone_b.__dict__},
        )
    return store().add("theses", body, tag="document_desk")
