"""My library: index your own folders once, then Ask my documents.

Indexing runs on your computer: files are split into page-labelled chunks,
embedded by the local embedding model when one is reachable, and saved to
``<lab>/library/index.json``. Re-indexing only reads new or changed files.
Scanned PDFs (no selectable text) are skipped and counted.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config
from ..store import default as store
from .ask import Answer, ask_chunks
from .loader import DocError, Document, load_file
from .retrieve import Chunk, chunk, embed

SUFFIXES = (".pdf", ".txt", ".md")


@dataclass
class IndexReport:
    """What one Add folder / re-index run did."""

    files: int
    chunks: int
    scanned_skipped: int
    unchanged: int
    errors: list[str]

    def line(self) -> str:
        s = f"{self.chunks:,} chunks · {self.scanned_skipped} scanned PDFs skipped"
        if self.unchanged:
            s += f" · {self.unchanged} unchanged"
        return s


class Library:
    """A local, file-backed index of chunks with their labels."""

    def __init__(self, root: Path | None = None):
        self.root = root or config.path("library")
        self.root.mkdir(parents=True, exist_ok=True)
        self.file = self.root / "index.json"
        data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {}
        self.docs: dict[str, dict] = data.get("docs", {})
        self.chunks: list[Chunk] = [Chunk(**c) for c in data.get("chunks", [])]

    def save(self) -> None:
        self.file.write_text(
            json.dumps({"docs": self.docs, "chunks": [asdict(c) for c in self.chunks]}), encoding="utf-8")

    def counts(self) -> dict[str, int]:
        """Documents, chunks and scanned files in the index."""
        return {
            "documents": sum(not d.get("scanned") for d in self.docs.values()),
            "chunks": len(self.chunks),
            "scanned": sum(bool(d.get("scanned")) for d in self.docs.values()),
        }

    def add_document(
        self,
        doc: Document,
        key: str | None = None,
        mtime: float = 0.0,
        use_embeddings: bool = False,
    ) -> int:
        """Index one document (replacing an older copy). Returns chunks added."""
        key = key or f"{doc.kind}:{doc.name}"
        self.chunks = [c for c in self.chunks if c.doc != key]
        if doc.is_scanned:
            self.docs[key] = {
                "name": doc.name,
                "market": doc.market,
                "pages": doc.n_pages,
                "chunks": 0,
                "scanned": True,
                "mtime": mtime,
            }
            return 0
        new = chunk(doc, with_name=True)
        for c in new:
            c.doc = key
        if use_embeddings and new:
            vecs = embed([c.text for c in new])
            for c, v in zip(new, vecs or []):
                c.embedding = v
        self.chunks += new
        self.docs[key] = {
            "name": doc.name,
            "market": doc.market,
            "pages": doc.n_pages,
            "chunks": len(new),
            "scanned": False,
            "mtime": mtime,
        }
        store().add(
            "documents",
            {
                "name": doc.name,
                "source": doc.source,
                "market": doc.market,
                "pages": doc.n_pages,
                "chunks": len(new),
            },
            tag="library",
        )
        return len(new)

    def add_folder(
        self, folder: str | Path, market: str = "IN", use_embeddings: bool = False
    ) -> IndexReport:
        """Index every PDF, text and Markdown file under ``folder`` (new or changed only)."""
        root = Path(folder).expanduser()
        if not root.is_dir():
            raise DocError(f"Folder not found: {root}")
        rep = IndexReport(0, 0, 0, 0, [])
        for f in sorted(p for p in root.rglob("*") if p.suffix.lower() in SUFFIXES):
            key, mtime = str(f.resolve()), f.stat().st_mtime
            if self.docs.get(key, {}).get("mtime") == mtime:
                rep.unchanged += 1
                continue
            try:
                doc = load_file(f, market=market)
            except DocError as exc:
                rep.errors.append(f"{f.name}: {exc}")
                continue
            rep.files += 1
            added = self.add_document(doc, key=key, mtime=mtime, use_embeddings=use_embeddings)
            rep.chunks += added
            rep.scanned_skipped += int(doc.is_scanned)
        self.save()
        return rep

    def ask(
        self, question: str, k: int = 5, market: str | None = None, use_model: bool = True
    ) -> Answer:
        """Ask my documents: quotes first, each with ``[file · p. N]``."""
        pool = [c for c in self.chunks if market is None or c.market == market]
        use_emb = bool(pool) and all(c.embedding for c in pool)
        return ask_chunks(
            question, pool, k=k, use_model=use_model, use_embeddings=use_emb, section="Documents"
        )
