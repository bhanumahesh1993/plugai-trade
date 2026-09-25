"""Extract to table, Compare and the Tone count — all computed in code.

A template is a list of fields; each field has search words. For every field
the desk quotes the best matching sentence with its page chip, or writes
"not found in source" and lists the pages it searched. Figures are quoted,
never calculated here; growth rates belong in your spreadsheet (Export CSV).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass, field

from .loader import Document
from .retrieve import sentences

NOT_FOUND = "not found in source"


@dataclass(frozen=True)
class Field:
    """One row of a template: a name and the words that locate it."""

    name: str
    keywords: tuple[str, ...]


def _f(name: str, *words: str) -> Field:
    return Field(name, tuple(words))


TEMPLATES: dict[str, list[Field]] = {
    "Red-flag checklist": [
        _f("Promoter pledge", "pledge", "pledged", "encumbered", "encumbrance", "collateral"),
        _f(
            "Related parties",
            "related party",
            "related-party",
            "promoter-owned",
            "promoter group",
            "related persons",
        ),
        _f(
            "Auditor",
            "auditor",
            "emphasis of matter",
            "qualified opinion",
            "resignation",
            "unmodified opinion",
        ),
        _f(
            "Receivables vs revenue",
            "trade receivables",
            "receivable days",
            "receivable",
            "debtor",
            "credit terms",
        ),
        _f(
            "One-off gains",
            "exceptional",
            "one-off",
            "one-time",
            "land sale",
            "write-back",
            "settlement",
        ),
        _f("Guidance language", "guide", "guidance", "outlook", "confident of"),
    ],
    "Results set": [
        _f("Revenue", "revenue", "sales", "turnover"),
        _f("EBITDA margin", "ebitda margin", "operating margin", "margin"),
        _f("Net profit", "net profit", "profit after tax", "pat", "net income"),
        _f("Receivable days", "receivable days", "receivable", "debtor days"),
        _f("One-off items", "exceptional", "one-off", "one-time"),
        _f("Guidance", "guide", "guidance", "outlook"),
    ],
    "RHP digest": [
        _f(
            "Fresh issue and offer for sale",
            "fresh issue",
            "offer for sale",
            "ofs",
            "selling shareholder",
        ),
        _f(
            "Objects of the issue",
            "objects of the issue",
            "debt repayment",
            "capital expenditure",
            "general corporate purposes",
        ),
        _f(
            "Financials (revenue, EBITDA, PAT, debt, CFO)",
            "revenue from operations",
            "profit after tax",
            "ebitda",
            "total borrowings",
            "cash from operations",
        ),
        _f(
            "Share count and promoter holding",
            "pre-issue",
            "post-issue",
            "promoter holding",
            "shares outstanding",
        ),
        _f("Peers and P/E", "basis for offer price", "peer", "p/e", "price to earnings"),
        _f(
            "Specific risk factors",
            "top five customers",
            "customer",
            "supplier",
            "litigation",
            "lawsuit",
            "tax demand",
        ),
        _f("Related parties and contingent liabilities", "related party", "contingent liabilit"),
        _f("Lock-in periods", "lock-in", "locked in", "anchor investor"),
    ],
}


@dataclass
class Row:
    """One extracted field."""

    field: str
    quote: str
    cite: str
    status: str  # found | not found in source
    searched: list[str] = field(default_factory=list)


@dataclass
class Extraction:
    """The table from Extract to table."""

    template: str
    document: str
    rows: list[Row]

    def facts(self) -> list[str]:
        out = [f"Template: {self.template}", f"Document: {self.document}"]
        for r in self.rows:
            out.append(
                f"{r.field}: “{r.quote}” {r.cite}"
                if r.status == "found"
                else f"{r.field}: {NOT_FOUND} (searched {len(r.searched)} pages)"
            )
        return out

    def found(self) -> int:
        return sum(r.status == "found" for r in self.rows)

    def to_csv(self) -> str:
        """CSV for your spreadsheet: field, quote, citation, status."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["field", "quote", "citation", "status", "document"])
        for r in self.rows:
            w.writerow([r.field, r.quote, r.cite, r.status, self.document])
        return buf.getvalue()

    def as_records(self) -> list[dict]:
        return [{k: v for k, v in asdict(r).items() if k != "searched"} for r in self.rows]


def _match_score(sentence: str, words: tuple[str, ...]) -> int:
    low = sentence.lower()
    return sum(2 if " " in w else 1 for w in words if w in low)


def find(doc: Document, fld: Field) -> Row:
    """Quote the sentence that best matches a field, or report not found."""
    best: tuple[int, int, str] | None = None
    for page_no, text in enumerate(doc.pages, 1):
        for s in sentences(text):
            sc = _match_score(s, fld.keywords)
            if sc and (best is None or sc > best[0]):
                best = (sc, page_no, s)
    searched = [doc.cite(p) for p in range(1, doc.n_pages + 1) if p not in doc.scanned_pages]
    if best is None:
        return Row(fld.name, "", "", NOT_FOUND, searched)
    return Row(fld.name, best[2], doc.cite(best[1]), "found", searched)


def parse_fields(text: str) -> list[Field]:
    """Edit fields: one field per line, ``Name: word, word``."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        name, _, words = line.partition(":")
        kws = tuple(w.strip().lower() for w in (words or name).split(",") if w.strip())
        out.append(Field(name.strip(), kws))
    return out


def fields_text(template: str) -> str:
    """A template as editable text for the Edit fields box."""
    return "\n".join(f"{f.name}: {', '.join(f.keywords)}" for f in TEMPLATES[template])


def extract(
    doc: Document, template: str = "Red-flag checklist", fields: list[Field] | None = None
) -> Extraction:
    """Run a template (or your edited fields) over a document."""
    flds = fields if fields is not None else TEMPLATES[template]
    return Extraction(template, doc.name, [find(doc, f) for f in flds])


# ---------------------------------------------------------------- tone count
HEDGING = (
    "may",
    "might",
    "could",
    "uncertain",
    "uncertainty",
    "subject to",
    "expect",
    "expects",
    "challenging",
    "would like to see",
    "hope",
    "possibly",
    "cautious",
    "depends",
    "depend on",
    "volatile",
    "volatility",
    "pressure",
    "difficult",
    "headwind",
    "headwinds",
)
CONFIDENT = (
    "strong",
    "record",
    "robust",
    "confident",
    "confidence",
    "healthy",
    "excellent",
    "momentum",
    "well positioned",
    "outperform",
    "accelerate",
    "best",
    "significant",
)


def _count(text: str, words: tuple[str, ...]) -> int:
    low = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()) + " "
    low = re.sub(r"\s+", " ", low)
    return sum(low.count(f" {w} ") for w in words)


@dataclass
class Tone:
    """Hedging and confident words per 1,000 words of a text."""

    words: int
    hedging: int
    confident: int

    @property
    def hedging_per_1000(self) -> float:
        return round(1000 * self.hedging / self.words, 1) if self.words else 0.0

    @property
    def confident_per_1000(self) -> float:
        return round(1000 * self.confident / self.words, 1) if self.words else 0.0


def tone_count(text: str) -> Tone:
    """Count hedging and confident words (word lists above) in code."""
    n = len(re.findall(r"[A-Za-z]+", text))
    return Tone(n, _count(text, HEDGING), _count(text, CONFIDENT))


# ---------------------------------------------------------------- compare
COMPARE_TOPICS: dict[str, tuple[str, ...]] = {
    "Guidance": ("guide", "guidance", "outlook", "confident of", "growth in fy"),
    "Demand": ("demand", "order book", "orders"),
    "Receivables": ("receivable days", "receivable", "credit terms"),
    "Revenue": ("revenue", "sales"),
    "Margin": ("ebitda margin", "margin"),
}


@dataclass
class CompareRow:
    topic: str
    quote_a: str
    cite_a: str
    quote_b: str
    cite_b: str
    change: str


@dataclass
class Comparison:
    """Two documents, topic by topic, word for word, plus the Tone count."""

    doc_a: str
    doc_b: str
    rows: list[CompareRow]
    tone_a: Tone
    tone_b: Tone

    def facts(self) -> list[str]:
        out = [f"Compare {self.doc_a} (A) with {self.doc_b} (B)"]
        for r in self.rows:
            out.append(
                f"{r.topic}: A “{r.quote_a}” {r.cite_a}; "
                f"B “{r.quote_b}” {r.cite_b}; change: {r.change}"
            )
        out.append(
            f"Tone A: hedging {self.tone_a.hedging_per_1000}/1,000 words, "
            f"confident {self.tone_a.confident_per_1000}/1,000"
        )
        out.append(
            f"Tone B: hedging {self.tone_b.hedging_per_1000}/1,000 words, "
            f"confident {self.tone_b.confident_per_1000}/1,000"
        )
        return out


def word_change(a: str, b: str) -> str:
    """Which content words were dropped from A and added in B (a fact about wording)."""
    ta, tb = (
        [w for w in re.findall(r"[a-z-]+", a.lower()) if len(w) > 3],
        [w for w in re.findall(r"[a-z-]+", b.lower()) if len(w) > 3],
    )
    dropped = [w for w in dict.fromkeys(ta) if w not in tb]
    added = [w for w in dict.fromkeys(tb) if w not in ta]
    if not dropped and not added:
        return "unchanged"
    parts = []
    if dropped:
        parts.append("dropped: " + ", ".join(f'"{w}"' for w in dropped[:4]))
    if added:
        parts.append("added: " + ", ".join(f'"{w}"' for w in added[:4]))
    return "; ".join(parts)


def compare(
    a: Document, b: Document, topics: dict[str, tuple[str, ...]] | None = None
) -> Comparison:
    """Word-for-word table by topic, and the Tone count for each document."""
    rows = []
    for topic, words in (topics or COMPARE_TOPICS).items():
        ra, rb = find(a, Field(topic, words)), find(b, Field(topic, words))
        if ra.status != "found" and rb.status != "found":
            change = "not found in either"
        elif ra.status != "found" or rb.status != "found":
            change = "only in " + ("B" if ra.status != "found" else "A")
        else:
            change = word_change(ra.quote, rb.quote)
        rows.append(
            CompareRow(
                topic, ra.quote or NOT_FOUND, ra.cite, rb.quote or NOT_FOUND, rb.cite, change
            )
        )
    return Comparison(a.name, b.name, rows, tone_count(a.full_text()), tone_count(b.full_text()))
