"""Lessons: one per chapter, "Check my work" and "Reset lesson" (Chapter 4, Appendix G).

    from plugai_trade import lessons
    les = lessons.get(22)
    lessons.check(22, {"be": "25,089"}, market="IN")   # → [Result(key, passed, detail), …]
    lessons.progress(22)                              # {"be": True, …}
    lessons.reset(22)

Progress lives in the store table ``lessons`` (tag ``ch22``). Every expected
value is computed in code at check time; nothing is stored as an answer key.
"""

from __future__ import annotations

import os
from typing import Any

from ..store import default as store
from .content import LESSONS
from .model import Check, Exercise, Lesson, Result, Step, evaluate, fmt, parse_number

__all__ = ["LESSONS", "Check", "Exercise", "Lesson", "Result", "Step", "all_lessons", "badge",
           "check", "evaluate", "fmt", "from_env", "get", "load_sample", "parse_number",
           "progress", "reset"]

_BY_N = {les.n: les for les in LESSONS}
BADGES = ("Not started", "In progress", "Done")


def all_lessons() -> list[Lesson]:
    return list(LESSONS)


def get(n: int) -> Lesson:
    if n not in _BY_N:
        raise KeyError(f"There is no lesson {n}; lessons run from 1 to {len(LESSONS)}.")
    return _BY_N[n]


def _tag(n: int) -> str:
    return f"ch{n}"


def check(n: int, answers: dict[str, Any], market: str = "IN", save: bool = True) -> list[Result]:
    """Check my work: compare each answer (or the lab's state) with the lab's own value."""
    les = get(n)
    results = [evaluate(c, answers.get(c.key), market) for c in les.checks]
    if save:
        for c, r in zip(les.checks, results):
            store().add("lessons", {"lesson": n, "check": c.key, "passed": r.passed,
                                    "answer": str(answers.get(c.key, "")), "market": market,
                                    "detail": r.detail}, tag=_tag(n))
    return results


def progress(n: int) -> dict[str, bool]:
    """Latest result per check (only checks you have run)."""
    out: dict[str, bool] = {}
    for row in store().all("lessons", tag=_tag(n)):  # newest first
        out.setdefault(row.get("check", ""), bool(row.get("passed")))
    return out


def badge(n: int) -> str:
    done = progress(n)
    keys = [c.key for c in get(n).checks]
    if not done:
        return BADGES[0]
    return BADGES[2] if all(done.get(k) for k in keys) else BADGES[1]


def reset(n: int) -> int:
    """Reset lesson: forget every result for this lesson. Returns rows removed."""
    rows = store().all("lessons", tag=_tag(n))
    for row in rows:
        store().delete("lessons", int(row["id"]))
    return len(rows)


def load_sample(n: int, market: str = "IN") -> list[str]:
    """Load the lesson's sample data; optional modules degrade to a plain message."""
    from .. import wizard
    lines = []
    try:
        wizard.load_sample_data(market)
        lines.append(f"Sample watchlist loaded for {market} (synthetic)")
    except Exception as exc:
        lines.append(f"Sample bars unavailable: {exc}")
    for name in get(n).samples:
        lines.append(_load_one(name))
    return lines


def _load_one(name: str) -> str:
    try:
        if name in ("kavita", "marcus", "meera"):
            from .. import journal
            return f"Journal sample {name}: {journal.sample(name).height} round trips (synthetic)"
        if name == "pairs":
            from .. import pairs
            f = pairs.fit_symbols("SYN-A", "SYN-B")
            return f"Pair SYN-A / SYN-B loaded: half-life {f.half_life:.1f} sessions"
        if name == "options":
            from .. import options
            leg = options.leg("NIFTY", kind="call", strike=25000, expiry="weekly", side="buy")
            return f"Options defaults loaded: {getattr(leg, 'symbol', 'NIFTY')} 25000 call"
        if name == "paper":
            return "Paper Desk ready (paper only; Replay works offline)"
    except Exception as exc:  # another module missing must not break the lesson
        return f"{name}: sample unavailable here ({exc}); the lesson's own numbers still work"
    return f"{name}: nothing to load"


def from_env() -> int | None:
    """The lesson requested by ``plugai-trade lesson N`` (env PLUGAI_TRADE_LESSON)."""
    raw = os.environ.get("PLUGAI_TRADE_LESSON", "").strip()
    return int(raw) if raw.isdigit() and int(raw) in _BY_N else None
