"""The shapes of a lesson: steps, a hands-on exercise and "Check my work" checks."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import polars as pl


@dataclass(frozen=True)
class Step:
    """One numbered step; ``slug`` is the registry url slug of the screen it uses."""

    text: str
    slug: str | None = None


@dataclass
class Exercise:
    """What the lesson computes in code, shown before you check your work."""

    title: str
    facts_list: list[str]
    table: pl.DataFrame | None = None

    def facts(self) -> list[str]:
        return list(self.facts_list)


@dataclass(frozen=True)
class Check:
    """One "Check my work" line.

    * ``number`` — your answer is compared with ``expected(market)`` within ``tol``.
    * ``state``  — the lab looks at its own settings or store (``state()`` → ok, detail).
    * ``tick``   — something only you can see; your tick is the answer.
    """

    key: str
    text: str
    kind: str = "number"
    expected: Callable[[str], float] | None = None
    tol: float = 0.01
    unit: str = ""
    state: Callable[[], tuple[bool, str]] | None = None


@dataclass(frozen=True)
class Result:
    key: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Lesson:
    n: int
    title: str
    goal: str
    levels: tuple[str, ...]
    steps: tuple[Step, ...]
    checks: tuple[Check, ...]
    exercise: Callable[[str], Exercise] | None = None
    samples: tuple[str, ...] = field(default=())

    @property
    def screens(self) -> list[str]:
        return list(dict.fromkeys(s.slug for s in self.steps if s.slug))


_NUM = re.compile(r"[-−]?\d[\d,]*(?:\.\d+)?|[-−]?\.\d+")


def parse_number(text: Any) -> float | None:
    """'₹9,028.50', '12.9%', '−14,300', '$0.42' → a float; None when there is no number."""
    if isinstance(text, (int, float)):
        return float(text)
    m = _NUM.search(str(text or ""))
    if not m:
        return None
    return float(m.group(0).replace(",", "").replace("−", "-"))


def fmt(x: float, unit: str = "") -> str:
    body = f"{x:,.2f}".rstrip("0").rstrip(".") if abs(x) < 1e6 else f"{x:,.0f}"
    if unit in ("₹", "$"):
        return f"{'-' if x < 0 else ''}{unit}{body.lstrip('-')}"
    return f"{body}{unit}"


def evaluate(check: Check, answer: Any, market: str) -> Result:
    """Compare one answer (or the lab's state) with the lab's own value."""
    if check.kind == "state":
        assert check.state is not None
        try:
            ok, detail = check.state()
        except Exception as exc:  # a missing optional module must not break the lesson
            ok, detail = False, f"could not check: {exc}"
        return Result(check.key, ok, detail)
    if check.kind == "tick":
        ok = bool(answer)
        return Result(check.key, ok, "ticked by you" if ok else "not ticked yet")
    assert check.expected is not None
    try:
        want = float(check.expected(market))
    except Exception as exc:
        return Result(check.key, False, f"the lab could not compute this: {exc}")
    got = parse_number(answer)
    if got is None:
        return Result(check.key, False, "type a number first")
    if abs(got - want) <= check.tol:
        return Result(check.key, True, f"matches the lab: {fmt(want, check.unit)}")
    return Result(check.key, False,
                  f"the lab computes {fmt(want, check.unit)}; you typed {fmt(got, check.unit)}")
