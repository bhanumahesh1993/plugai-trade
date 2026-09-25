"""Lessons › Prompt Library: the book's 40 prompts (Appendix B) as data (Chapter 3).

    from plugai_trade import prompts
    p = prompts.get("concall-first-read-six-parts")
    prompts.placeholders(p.text)            # ['paste the full concall transcript here', 'COMPANY']
    prompts.fill(p.text, {"COMPANY": "Kaveri Pumps", ...})

Placeholders are the book's AMBER CAPITALS written as ``[NAME]``. Anything a
reader pastes into a "paste …" slot (or any multi-line value) is fenced with
``ai.fence_untrusted`` so instructions hidden in it are treated as data.
"Save my version" keeps an edited copy in the store table ``notes`` with the
tag ``MY VERSION``; it is listed above the book's version from then on.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .. import ai
from ..store import default as store
from .library import PROMPTS as _RAW

#: Filter chips on the screen. The first four are the book's (Chapter 3); the
#: rest mirror Appendix B's other groups.
CHIPS: tuple[str, ...] = ("Research", "Plan", "Journal", "Review",
                          "Options", "Investing", "Tax", "Safety")
MY_VERSION = "MY VERSION"
_PH = re.compile(r"\[([^\[\]]+)\]")
_PASTE_WORDS = ("paste", "source", "attach", "transcript", "statement", "article", "message")


@dataclass(frozen=True)
class Prompt:
    """One prompt card: printed exactly as in its chapter."""

    id: str
    title: str
    chapter: int
    chapter_title: str
    use: str
    works_with: str
    group: str
    chips: tuple[str, ...]
    text: str
    mine: bool = False
    note_id: int | None = None
    tags: tuple[str, ...] = field(default=())

    @property
    def placeholders(self) -> list[str]:
        return placeholders(self.text)

    def facts(self) -> list[str]:
        return [f"Prompt: {self.title}", f"From Chapter {self.chapter}: {self.chapter_title}",
                f"Use it for {self.use}", f"Placeholders: {len(self.placeholders)}"]


def _build(raw: dict) -> Prompt:
    return Prompt(id=raw["id"], title=raw["title"], chapter=int(raw["chapter"]),
                  chapter_title=raw["chapter_title"], use=raw["use"],
                  works_with=raw["works_with"], group=raw["group"], chips=tuple(raw["chips"]),
                  text=raw["text"])


BOOK: tuple[Prompt, ...] = tuple(_build(r) for r in _RAW)
GROUPS: tuple[str, ...] = tuple(dict.fromkeys(p.group for p in BOOK))


def placeholders(text: str) -> list[str]:
    """Unique placeholder names in order of first appearance."""
    return list(dict.fromkeys(m.strip() for m in _PH.findall(text)))


def is_paste_slot(name: str) -> bool:
    """True for placeholders that take pasted documents, rows or messages."""
    low = name.lower()
    return any(w in low for w in _PASTE_WORDS)


def fence_if_pasted(name: str, value: str) -> str:
    """Fence pasted text as UNTRUSTED (Chapter 3); short typed values pass through."""
    if not value.strip():
        return value
    if is_paste_slot(name) or "\n" in value.strip() or len(value) > 200:
        return ai.fence_untrusted(value.strip())
    return value


def fill(text: str, values: dict[str, str]) -> str:
    """Replace ``[NAME]`` with ``values[NAME]``; empty values keep the placeholder."""
    def sub(m: re.Match) -> str:
        name = m.group(1).strip()
        val = values.get(name, "")
        return fence_if_pasted(name, val) if val and val.strip() else m.group(0)
    return _PH.sub(sub, text)


def mine() -> list[Prompt]:
    """Saved edited copies (``MY VERSION``), newest first."""
    out = []
    for row in store().all("notes", tag=MY_VERSION):
        base = get(row.get("prompt_id", ""), include_mine=False)
        if base is None:
            continue
        out.append(Prompt(**{**base.__dict__, "text": row.get("text", base.text), "mine": True,
                             "note_id": int(row["id"]), "tags": (MY_VERSION,)}))
    return out


def all_prompts(include_mine: bool = True) -> list[Prompt]:
    """My versions first (each above the book's version), then the book's 40 in book order."""
    if not include_mine:
        return list(BOOK)
    saved = {p.id: p for p in reversed(mine())}  # newest saved copy per prompt
    out: list[Prompt] = []
    for p in BOOK:
        if p.id in saved:
            out.append(saved[p.id])
        out.append(p)
    return out


def get(prompt_id: str, include_mine: bool = True) -> Prompt | None:
    """A prompt by id; with ``include_mine`` your saved version wins."""
    if include_mine:
        for p in mine():
            if p.id == prompt_id:
                return p
    return next((p for p in BOOK if p.id == prompt_id), None)


def search(query: str = "", chips: Iterable[str] = (), include_mine: bool = True) -> list[Prompt]:
    """Search titles, uses and text (all words must match); chips narrow by task."""
    words = [w for w in query.lower().split() if w]
    wanted = set(chips)
    out = []
    for p in all_prompts(include_mine):
        hay = f"{p.title} {p.use} {p.chapter_title} {p.group} {p.text}".lower()
        if words and not all(w in hay for w in words):
            continue
        if wanted and not wanted.intersection(p.chips):
            continue
        out.append(p)
    return out


def save_my_version(prompt_id: str, text: str) -> int:
    """Keep an edited copy; it is tagged MY VERSION and listed above the book's version."""
    if get(prompt_id, include_mine=False) is None:
        raise KeyError(prompt_id)
    return store().add("notes", {"kind": "prompt", "prompt_id": prompt_id, "text": text},
                       tag=MY_VERSION)


def delete_my_version(note_id: int) -> None:
    store().delete("notes", note_id)
