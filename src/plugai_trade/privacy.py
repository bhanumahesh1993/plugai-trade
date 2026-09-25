"""Settings › Privacy: what may leave your computer (Chapters 2 and 4).

The defaults are strict and are what the book assumes: journal, holdings and
tradebook use the local model only; the lab asks before any cloud request;
account numbers, PAN, Aadhaar and SSN are removed from anything sent to a cloud
model; anonymous crash reports are off. The Education lag (default 90 days,
minimum 30) is a house rule for *named* Indian securities in lessons.

``strip_identifiers`` is what ``ai`` should call before every cloud request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config

MIN_LAG = 30
DEFAULT_LAG = 90

#: (label, pattern) — order matters: specific formats before the generic digit run.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PAN", re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b")),
    ("SSN", re.compile(r"\b(?!000|666|9\d\d)\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}\b")),
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}[ -]\d{4}[ -]\d{4}\b")),
    ("DEMAT", re.compile(r"\bIN\d{6}[ -]?\d{8}\b|\b120\d{13}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"(?<![\w.])(?:\+91[ -]?|\+1[ -]?)?(?:[6-9]\d{9}|\(?\d{3}\)?[ -]\d{3}-\d{4})\b")),
    ("ACCOUNT", re.compile(r"(?<![\d.,])\d{9,18}(?![\d.,])")),
)
_LABELLED = re.compile(
    r"(?i)(?<!\[)\b(account|a/c|acct|client\s*id|client\s*code|ucc|folio|dp\s*id|bo\s*id|demat)"
    r"(\s*(?:no\.?|number|#)?\s*[:=#-]?\s*)(?!REMOVED)(?=[A-Z/-]*\d)([A-Z0-9][A-Z0-9/-]{3,})")


@dataclass(frozen=True)
class Settings:
    """The Privacy page toggles."""

    journal_local_only: bool = True
    holdings_local_only: bool = True
    ask_before_cloud: bool = True
    strip_identifiers: bool = True
    crash_reports: bool = False


def settings() -> Settings:
    raw = config.get("privacy", {}) or {}
    return Settings(**{k: bool(raw.get(k, v)) for k, v in Settings().__dict__.items()})


def set_toggle(name: str, on: bool) -> None:
    if name not in Settings.__dataclass_fields__:
        raise KeyError(name)
    config.set_value(f"privacy.{name}", bool(on))


def defaults_on() -> bool:
    """True when every toggle is at the book's strict default."""
    return settings() == Settings()


def education_lag() -> int:
    return max(MIN_LAG, int(config.get("education_lag_days", DEFAULT_LAG)))


def set_education_lag(days: int) -> int:
    """Store the lag; values under 30 are raised to 30. Returns the stored value."""
    days = max(MIN_LAG, int(days))
    config.set_value("education_lag_days", days)
    return days


def strip_identifiers(text: str) -> str:
    """Remove account numbers, PAN, Aadhaar, SSN, demat IDs, emails and phone numbers.

    Prices and quantities (with commas or decimals, or under nine digits) survive.
    """
    out = text
    for label, rx in _PATTERNS:
        out = rx.sub(f"[{label} REMOVED]", out)
    return _LABELLED.sub(lambda m: f"{m.group(1)}{m.group(2)}[ACCOUNT REMOVED]", out)


def found_identifiers(text: str) -> list[str]:
    """Labels of the identifier kinds present in ``text`` (for the preview dialog)."""
    kinds = [label for label, rx in _PATTERNS if rx.search(text)]
    if _LABELLED.search(text) and "ACCOUNT" not in kinds:
        kinds.append("ACCOUNT")
    return kinds


def local_only_sections() -> list[str]:
    """Sidebar sections the privacy toggles force onto the local model."""
    s = settings()
    out = []
    if s.journal_local_only:
        out.append("Journal")
    if s.holdings_local_only:
        out.append("Portfolio")
    return out


def cloud_payload(prompt: str) -> str:
    """What a cloud call would send: stripped when the toggle is on."""
    return strip_identifiers(prompt) if settings().strip_identifiers else prompt
