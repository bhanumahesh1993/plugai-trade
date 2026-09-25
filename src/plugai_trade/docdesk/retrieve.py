"""Find the passages that answer a question, in code, before any model reads them.

Two lexical scorers are implemented here with no extra packages: BM25 ranks
chunks, TF-IDF cosine gives each one a 0–1 *closeness* score for Show sources.
When a local Ollama embedding model is reachable, its cosine similarity is
blended in, so the desk also finds passages worded differently from the question.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

import httpx

from .. import config
from .loader import Document

_WORD = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[\"“A-Z0-9(₹$])")
STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
        "about",
        "than",
        "also",
        "very",
        "can",
        "said",
        "say",
        "says",
        "management",
    ]
)

NOT_FOUND = 0.08  # closeness below this is reported as "not found"


def stem(w: str) -> str:
    """A light suffix stem: receivables -> receivable, orders -> order, rising -> ris."""
    for suf, rep in (
        ("ies", "y"),
        ("sses", "ss"),
        ("ches", "ch"),
        ("xes", "x"),
        ("ings", ""),
        ("ing", ""),
        ("ed", ""),
        ("s", ""),
    ):
        if w.endswith(suf) and len(w) > len(suf) + 2 and not w.endswith("ss"):
            return w[: -len(suf)] + rep
    return w


def tokens(text: str) -> list[str]:
    """Lower-case word tokens with stop words removed and a light suffix stem."""
    out = []
    for w in _WORD.findall(text.lower()):
        if w in STOP or len(w) < 2:
            continue
        out.append(stem(w))
    return out


def sentences(text: str) -> list[str]:
    """Split a passage into sentences, keeping the exact wording."""
    flat = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in _SENT.split(flat) if s.strip()]


@dataclass
class Chunk:
    """A passage from one page of one document."""

    doc: str
    page: int
    text: str
    cite: str
    market: str = "IN"
    embedding: list[float] | None = None


def chunk(
    doc: Document, words: int = 120, overlap: int = 1, with_name: bool = False
) -> list[Chunk]:
    """Split each page into ~``words``-word chunks that share ``overlap`` sentences.

    Chunks never cross a page boundary, so every chunk has exactly one page chip.
    """
    out: list[Chunk] = []
    for page_no, text in enumerate(doc.pages, 1):
        if page_no in doc.scanned_pages:
            continue
        sents = sentences(text)
        cur: list[str] = []
        for s in sents:
            cur.append(s)
            if sum(len(x.split()) for x in cur) >= words:
                out.append(
                    Chunk(
                        doc.name, page_no, " ".join(cur), doc.cite(page_no, with_name), doc.market
                    )
                )
                cur = cur[-overlap:] if overlap else []
        if cur and (not out or out[-1].page != page_no or " ".join(cur) not in out[-1].text):
            out.append(
                Chunk(doc.name, page_no, " ".join(cur), doc.cite(page_no, with_name), doc.market)
            )
    return out


class BM25:
    """Okapi BM25 over a list of token lists."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, d in zip(self.tf, self.docs):
            s, dl = 0.0, len(d) or 1
            for q in query:
                f = tf.get(q, 0)
                if f:
                    s += (
                        self.idf.get(q, 0.0)
                        * f
                        * (self.k1 + 1)
                        / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
                    )
            out.append(s)
        return out


def tfidf_cosine(query: list[str], docs: list[list[str]]) -> list[float]:
    """Cosine similarity between the query and each document in TF-IDF space (0–1)."""
    n = len(docs)
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    idf = {t: math.log((1 + n) / (1 + f)) + 1 for t, f in df.items()}

    def vec(toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        return {t: c * idf.get(t, math.log(1 + n) + 1) for t, c in tf.items()}

    qv = vec(query)
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
    out = []
    for d in docs:
        dv = vec(d)
        dn = math.sqrt(sum(v * v for v in dv.values())) or 1.0
        out.append(sum(qv[t] * dv.get(t, 0.0) for t in qv) / (qn * dn))
    return out


def _cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


def embed(texts: list[str], timeout: float = 30.0) -> list[list[float]] | None:
    """Embeddings from the local Ollama embedding model, or None when it is not reachable."""
    host = config.get("ai.ollama_host", "http://localhost:11434")
    model = config.get("ai.embedding_model", "nomic-embed-text")
    try:
        r = httpx.post(f"{host}/api/embed", json={"model": model, "input": texts}, timeout=timeout)
        r.raise_for_status()
        vecs = r.json().get("embeddings")
        return vecs if vecs and len(vecs) == len(texts) else None
    except Exception:
        return None


@dataclass
class Hit:
    """A retrieved chunk with its ranking score and closeness (0–1)."""

    chunk: Chunk
    score: float
    closeness: float
    method: str = "tf-idf"


@dataclass
class Retriever:
    """Index a set of chunks once; search them for every question."""

    chunks: list[Chunk]
    use_embeddings: bool = False
    _toks: list[list[str]] = field(default_factory=list, init=False)
    _bm25: BM25 | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._toks = [tokens(c.text) for c in self.chunks]
        self._bm25 = BM25(self._toks)
        if self.use_embeddings and any(c.embedding is None for c in self.chunks):
            vecs = embed([c.text for c in self.chunks])
            if vecs is None:
                self.use_embeddings = False
            else:
                for c, v in zip(self.chunks, vecs):
                    c.embedding = v

    def search(self, question: str, k: int = 5) -> list[Hit]:
        """Top ``k`` chunks. BM25 ranks; closeness is TF-IDF cosine (or embedding cosine)."""
        if not self.chunks:
            return []
        q = tokens(question)
        bm = self._bm25.scores(q) if self._bm25 else [0.0] * len(self.chunks)
        close = tfidf_cosine(q, self._toks)
        method = "tf-idf"
        if self.use_embeddings:
            qv = embed([question])
            if qv:
                emb = [_cos(qv[0], c.embedding or []) for c in self.chunks]
                close = [0.5 * a + 0.5 * b for a, b in zip(close, emb)]
                method = "tf-idf + embeddings"
        top = max(bm) or 1.0
        combined = [0.6 * (b / top) + 0.4 * c for b, c in zip(bm, close)]
        order = sorted(range(len(self.chunks)), key=lambda i: -combined[i])[:k]
        return [
            Hit(self.chunks[i], round(combined[i], 4), round(close[i], 3), method) for i in order
        ]


def best_sentences(question: str, text: str, n: int = 2) -> list[str]:
    """The sentences of a passage that share the most question words, in reading order."""
    q = set(tokens(question))
    sents = sentences(text)
    scored = [(len(q & set(tokens(s))), i, s) for i, s in enumerate(sents)]
    keep = sorted([x for x in scored if x[0] > 0], key=lambda x: (-x[0], x[1]))[:n]
    return [s for _, _, s in sorted(keep, key=lambda x: x[1])]
