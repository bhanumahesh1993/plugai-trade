"""Load a document (PDF, link or pasted text) into page-labelled text.

Every page keeps its number, so every quote the desk returns can carry a page
chip such as ``[p. 6]``. US filings keep their item structure too:
``[Item 7 · p. 25]``. Anything that came from outside the lab is *untrusted*:
it is data to quote, never instructions to follow.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .. import ai

_ITEM = re.compile(r"^\s*item\s+(\d{1,2}[a-c]?)\b[.:]?", re.IGNORECASE | re.MULTILINE)
MIN_PAGE_CHARS = 25  # below this a PDF page is treated as a scanned image


class DocError(RuntimeError):
    """A document could not be loaded; the message is shown to the reader."""


@dataclass
class Document:
    """A loaded document: page texts plus labels for citations."""

    name: str
    pages: list[str]
    source: str = "pasted"
    market: str = "IN"
    kind: str = "text"  # pdf | text | link | sample
    untrusted: bool = True
    items: dict[int, str] = field(default_factory=dict)  # page number -> "Item 7"

    def __post_init__(self) -> None:
        if not self.items:
            self.items = detect_items(self.pages)

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    @property
    def scanned_pages(self) -> list[int]:
        """Page numbers with no selectable text."""
        return [i for i, p in enumerate(self.pages, 1) if len(p.strip()) < MIN_PAGE_CHARS]

    @property
    def is_scanned(self) -> bool:
        return self.n_pages > 0 and len(self.scanned_pages) == self.n_pages

    def text_check(self) -> str:
        """The line shown when a document loads: page count and whether text is selectable."""
        n = self.n_pages
        noun = "page" if n == 1 else "pages"
        if n == 0:
            return "0 pages · nothing to read"
        if self.is_scanned:
            return f"{n} {noun} · scanned image, no selectable text (run OCR first; no guessing)"
        if self.scanned_pages:
            return (
                f"{n} {noun} · text OK · {len(self.scanned_pages)} scanned "
                f"{'page' if len(self.scanned_pages) == 1 else 'pages'} skipped"
            )
        return f"{n} {noun} · text OK"

    def cite(self, page: int, with_name: bool = False) -> str:
        """Citation chip for a page: ``[p. 6]``, ``[Item 7 · p. 25]`` or ``[name · p. 1]``."""
        parts = [self.name] if with_name else []
        if page in self.items:
            parts.append(self.items[page])
        parts.append(f"p. {page}")
        return "[" + " · ".join(parts) + "]"

    def full_text(self) -> str:
        return "\n\n".join(self.pages)

    def fenced(self) -> str:
        """The document text wrapped as UNTRUSTED for any model prompt."""
        body = "\n\n".join(f"--- page {i} ---\n{p}" for i, p in enumerate(self.pages, 1))
        return ai.fence_untrusted(body)


def detect_items(pages: list[str]) -> dict[int, str]:
    """Label each page with the 10-K/10-Q item it belongs to, if the filing has items."""
    out: dict[int, str] = {}
    current = ""
    for i, text in enumerate(pages, 1):
        found = _ITEM.findall(text)
        if found:
            current = f"Item {found[0].upper()}"
        if current:
            out[i] = current
    return out


def load_pdf(data: bytes | str | Path, name: str | None = None, market: str = "IN") -> Document:
    """Extract text from each PDF page with pypdf."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if isinstance(data, (str, Path)):
        path = Path(data)
        name = name or path.stem
        raw = path.read_bytes()
        source = str(path)
    else:
        raw, source = data, name or "uploaded.pdf"
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
    except (PdfReadError, ValueError, OSError) as exc:
        raise DocError(f"Could not read this PDF: {exc}") from exc
    return Document(name=name or "document", pages=pages, source=source, market=market, kind="pdf")


def split_pasted(text: str) -> list[str]:
    """Pasted text becomes pages at form feeds or '--- page N ---' markers, else one page."""
    parts = re.split(
        r"\f|^-{3,}\s*page\s+\d+\s*-{3,}\s*$", text, flags=re.IGNORECASE | re.MULTILINE
    )
    pages = [p.strip() for p in parts if p.strip()]
    return pages or [text.strip()]


def load_text(text: str, name: str = "Pasted text", market: str = "IN") -> Document:
    """Pasted text. It is always UNTRUSTED: instructions inside it are never followed."""
    return Document(
        name=name, pages=split_pasted(text), source="pasted", market=market, kind="text"
    )


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"[ \t]+", " ", text)


def load_link(url: str, market: str = "IN", timeout: float = 20.0) -> Document:
    """Fetch a PDF or a web page. Fails with a clear message when offline."""
    if not url.lower().startswith(("http://", "https://")):
        raise DocError("Paste a full link starting with http:// or https://")
    try:
        r = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "PlugAI-Trade research lab"},
        )
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise DocError(
            f"Could not fetch the link ({exc.__class__.__name__}). "
            "Download the file and drop it on the desk instead."
        ) from exc
    name = url.rstrip("/").split("/")[-1] or url
    if "pdf" in r.headers.get("content-type", "") or url.lower().endswith(".pdf"):
        doc = load_pdf(r.content, name=name, market=market)
    else:
        doc = Document(
            name=name, pages=split_pasted(_html_to_text(r.text)), market=market, kind="link"
        )
    doc.source = url
    return doc


def load_file(path: str | Path, market: str = "IN") -> Document:
    """A PDF, text or Markdown file from disk (used by My library)."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return load_pdf(p, market=market)
    return Document(
        name=p.stem,
        pages=split_pasted(p.read_text(errors="replace")),
        source=str(p),
        market=market,
        kind="text",
    )
