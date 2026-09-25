"""Settings › Security (Chapter 33): checklist, registration check, pitch check, audit log.

* **Security checklist** — automatic checks on the lab itself (keys in the OS
  keychain only, no trade/withdraw keys, MCP tools READ + PAPER, cloud calls strip
  PAN/SSN, reference tables fresh) plus manual items only you can tick.
* **Registration check** — links to the *official* registers. The lab never
  judges a registration itself.
* **Check a pitch** — the chapter's scam-check prompt on your model, with a
  deterministic red-flag scan that always runs (and is the whole answer offline).
* **Audit log** — every key use, data fetch, AI call and MCP call; filter Cloud;
  Export log as CSV.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from . import ai, config, keys, privacy, prompts, reference
from .store import default as store

STALE_DAYS = 45  # reference tables older than this → "update available"


@dataclass(frozen=True)
class Item:
    """One checklist line: automatic (the lab checks) or manual (you tick)."""

    key: str
    text: str
    ok: bool
    detail: str = ""
    manual: bool = False


# ---------------------------------------------------------------- checklist
def _keys_in_keychain() -> Item:
    settings_text = config.path("settings.json").read_text() if config.path(
        "settings.json").exists() else ""
    leaked = [n for n in keys.listed() if (v := keys.get_key(n)) and len(v) > 6
              and v in settings_text]
    return Item("keychain", "Keys in OS keychain only", keys.keychain_ok() and not leaked,
                "stored only in the keychain" if not leaked else
                f"a key value appears in settings.json: {', '.join(leaked)}")


def _no_trade_keys() -> Item:
    risky = [r for r in store().all("audit_log", tag="key_refused")]
    return Item("no_trade_keys", "No trade / withdraw keys", True,
                "the Keys page refuses keys with trade, withdraw or transfer permission"
                + (f" ({len(risky)} refused so far)" if risky else ""))


def _mcp_tags() -> Item:
    try:
        from . import mcp_server
        tools = getattr(mcp_server, "TOOLS", None)
    except Exception:
        tools = None
    tags: set[str] = set()
    if isinstance(tools, dict):
        tags = {str(v.get("tag", v) if isinstance(v, dict) else v).upper() for v in tools.values()}
    elif isinstance(tools, (list, tuple)):
        tags = {str(getattr(t, "tag", t.get("tag", "") if isinstance(t, dict) else "")).upper()
                for t in tools}
    ok = not tags or tags <= {"READ", "PAPER"}
    return Item("mcp", "MCP tools: READ + PAPER", ok,
                "every tool is tagged READ or PAPER" if ok else f"unexpected tags: {sorted(tags)}")


def _strip_on() -> Item:
    on = privacy.settings().strip_identifiers
    return Item("strip", "Cloud calls strip PAN / SSN", on,
                "Settings › Privacy removes account numbers, PAN and SSN" if on else
                "switch it on in Settings › Privacy")


def _up_to_date(today: date | None = None) -> Item:
    try:
        as_of = date.fromisoformat(reference.as_of())
    except ValueError:
        return Item("update", "App and tables up to date", False, "reference tables have no date")
    age = ((today or date.today()) - as_of).days
    ok = age <= STALE_DAYS
    return Item("update", "App and tables up to date" if ok else "Update available", ok,
                f"reference tables as of {as_of:%d %b %Y}" + ("" if ok else
                                                              " — run `plugai-trade update`"))


MANUAL: tuple[tuple[str, str], ...] = (
    ("2fa", "Authenticator-app 2FA (or a passkey) on every broker and exchange account"),
    ("backup_codes", "Backup codes stored on paper"),
    ("otp", "OTP / TPIN never shared with anyone, on any call"),
    ("contacts", "Broker contact numbers saved from the official website"),
)


def manual_ticks() -> dict[str, bool]:
    return dict(config.get("security.manual", {}) or {})


def tick(key: str, on: bool) -> None:
    if key not in dict(MANUAL):
        raise KeyError(key)
    config.set_value(f"security.manual.{key}", bool(on))


def checklist(today: date | None = None) -> list[Item]:
    """Automatic items first, then the manual ones with your ticks."""
    auto = [_keys_in_keychain(), _no_trade_keys(), _mcp_tags(), _strip_on(), _up_to_date(today)]
    ticks = manual_ticks()
    manual = [Item(k, f"{t} (you)", bool(ticks.get(k)), "ticked by you" if ticks.get(k) else
                   "the lab cannot see this; tick it when done", manual=True) for k, t in MANUAL]
    return auto + manual


def score(items: list[Item]) -> str:
    return f"{sum(i.ok for i in items)} of {len(items)}"


# ---------------------------------------------------------------- registers
@dataclass(frozen=True)
class Register:
    name: str
    url: str
    covers: str


REGISTERS: dict[str, dict[str, list[Register]]] = {
    "IN": {
        "Adviser": [Register("SEBI intermediaries — Investment Advisers (INA…)",
                             "https://www.sebi.gov.in/intermediaries.html",
                             "SEBI-registered investment advisers")],
        "Analyst": [Register("SEBI intermediaries — Research Analysts (INH…)",
                             "https://www.sebi.gov.in/intermediaries.html",
                             "SEBI-registered research analysts")],
        "Broker": [Register("SEBI intermediaries — Stock brokers (INZ…)",
                            "https://www.sebi.gov.in/intermediaries.html",
                            "SEBI-registered stock brokers")],
        "Futures / forex": [Register("RBI Alert List (unauthorised forex platforms)",
                                     "https://www.rbi.org.in/",
                                     "forex platforms RBI has warned about (search the site for Alert List)")],
    },
    "US": {
        "Adviser": [Register("SEC adviser search (IAPD)", "https://adviserinfo.sec.gov/",
                             "registered investment advisers"),
                    Register("FINRA BrokerCheck", "https://brokercheck.finra.org/",
                             "brokers, representatives and many advisers")],
        "Analyst": [Register("FINRA BrokerCheck", "https://brokercheck.finra.org/",
                             "research staff at FINRA member firms")],
        "Broker": [Register("FINRA BrokerCheck", "https://brokercheck.finra.org/",
                            "brokers and their representatives, with disciplinary history")],
        "Futures / forex": [Register("NFA BASIC", "https://www.nfa.futures.org/BasicNet/",
                                     "futures, forex and commodity firms and people")],
    },
}
REG_TYPES = ("Adviser", "Analyst", "Broker", "Futures / forex")
REGISTRATION_NOTE = ("The lab opens the official register; it never judges a registration. "
                     "Match the name, number and contact details on the regulator's own page.")


def registers(market: str, kind: str) -> list[Register]:
    return REGISTERS[market][kind]


# ---------------------------------------------------------------- pitch check
@dataclass(frozen=True)
class Flag:
    kind: str  # returns | technology | regulation | custody | urgency
    flag: str
    quote: str


_RED_FLAGS: tuple[tuple[str, str, str], ...] = (
    ("returns", "Fixed or assured return",
     (r"(\d+(?:\.\d+)?\s*%\s*(?:a|per|every|/)\s*(?:day|daily|week|month)|assured|guarantee\w*|"
      r"fixed return|no[- ]loss|capital[- ]protected|risk[- ]free|double your)")),
    ("returns", "Profit screenshots you cannot tie to a contract note",
     r"(screenshot|proof of profit|bank credit|withdrawal proof|testimonial)"),
    ("technology", "'AI' used to explain away impossible returns or secrecy",
     (r"(ai (?:bot|robot|trading bot)|reads? the market before|proprietary (?:ai|algo|model)|"
      r"black[- ]box|sure[- ]?shot|100% accura\w*|never loses?)")),
    ("regulation", "Registration claim to verify on the regulator's own site",
     (r"(sebi[- ]registered|sebi approved|registered with|licen[cs]ed by|regulated by|"
      r"\bIN[AHZ]\d{6,}\b|\bCRD\s*#?\s*\d+)")),
    ("custody", "Money leaves your own broker",
     (r"(deposit|transfer|send (?:money|funds)|upi|wallet|usdt|crypto address|bank account|"
      r"wire|processing fee|unlock (?:fee|charge)|tax clearance|withdrawal fee)")),
    ("urgency", "Urgency or pressure",
     (r"(seats? (?:closing|left|filling)|limited (?:seats|time|slots)|only \d+ (?:seats|spots)|"
      r"today only|act now|last chance|vip (?:group|room)|join (?:now|fast)|hurry)")),
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def red_flags(text: str) -> list[Flag]:
    """Deterministic scan: each claim sentence quoted with the flag it matches."""
    out: list[Flag] = []
    for sentence in (s.strip() for s in _SENTENCE.findall(text)):
        if not sentence:
            continue
        for kind, flag, rx in _RED_FLAGS:
            if re.search(rx, sentence, re.IGNORECASE):
                out.append(Flag(kind, flag, sentence[:240]))
    return out


def daily_compound(pct_per_day: float, days: int = 250) -> float:
    """The calculator test: 3% a day for 250 days multiplies the stake by ≈ 1,619."""
    return (1 + pct_per_day / 100) ** days


@dataclass
class PitchCheck:
    """Claims table (deterministic) plus the model's reading of the scam-check prompt."""

    flags: list[Flag]
    names: list[str]
    compound: list[tuple[float, float]]
    ai_text: str = ""
    where: str = "Fallback"
    model: str = "fallback"
    prompt: str = ""

    def facts(self) -> list[str]:
        out = [f"{f.kind}: {f.flag} — “{f.quote}”" for f in self.flags] or [
            "No red-flag phrases matched the scan"]
        out += [f"Mentioned: {n}" for n in self.names]
        out += [f"{p:g}% a day for 250 trading days multiplies the stake by {m:,.0f}"
                for p, m in self.compound]
        return out


_NAMES = re.compile(r"(\bIN[AHZ]\d{6,}\b|\bCRD\s*#?\s*\d+|https?://\S+|www\.\S+|"
                    r"\b[\w.-]+\.(?:com|in|io|net|org|app)\b|@\w{3,})")
_PCT_DAY = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:a|per|every|/)\s*(?:day|daily)", re.IGNORECASE)


def check_pitch(pitch: str, section: str = "Research") -> PitchCheck:
    """Run the chapter's scam-check prompt; the red-flag scan works with no model."""
    clean = privacy.strip_identifiers(pitch)
    flags = red_flags(clean)
    names = list(dict.fromkeys(m.strip(".,)") for m in _NAMES.findall(clean)))
    compound = [(float(p), daily_compound(float(p))) for p in
                dict.fromkeys(_PCT_DAY.findall(clean))]
    template = prompts.get("scam-check-a-trading-pitch", include_mine=False)
    text = prompts.fill(template.text, {"PASTE THE PITCH, WEBSITE TEXT OR TERMS": clean})
    out = PitchCheck(flags, names, compound, prompt=text)
    reply = ai.complete(text, section=section, sensitive=False)
    if reply.text:
        out.ai_text, out.where, out.model = reply.text, reply.where, reply.model
    store().audit("pitch_check", {"where": out.where, "model": out.model, "flags": len(flags)})
    return out


# ---------------------------------------------------------------- audit log
FILTERS = ("All", "Cloud", "Keys", "MCP", "AI", "Data")


def _category(row: dict[str, Any]) -> str:
    kind = str(row.get("kind", row.get("tag", "")))
    if kind.startswith("ai") or kind == "pitch_check":
        return "Cloud" if row.get("where") == "Cloud" else "AI"
    if "key" in kind:
        return "Keys"
    if "mcp" in kind or "tool" in kind:
        return "MCP"
    if "fetch" in kind or "data" in kind:
        return "Data"
    return "Other"


def audit_rows(filter_: str = "All", limit: int = 500) -> list[dict[str, Any]]:
    """Newest first. ``Cloud`` shows exactly what left your computer."""
    rows = store().all("audit_log", limit=limit)
    out = []
    for r in rows:
        cat = _category(r)
        if filter_ == "All" or cat == filter_ or (filter_ == "AI" and cat == "Cloud"):
            detail = {k: v for k, v in r.items() if k not in ("id", "created", "tag", "kind")}
            out.append({"time": r["created"], "kind": r.get("kind", r["tag"]), "category": cat,
                        "detail": json.dumps(detail, default=str)[:300]})
    return out


def export_log(filter_: str = "All") -> str:
    """CSV text for Export log (keep it with your journal once a month)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["time", "kind", "category", "detail"])
    w.writeheader()
    w.writerows(audit_rows(filter_, limit=100_000))
    store().audit("audit_export", {"filter": filter_,
                                   "at": datetime.now(timezone.utc).isoformat()})
    return buf.getvalue()


@dataclass
class Summary:
    """One-line state for the Security page and the Lesson 33 check."""

    checklist: list[Item] = field(default_factory=checklist)

    def facts(self) -> list[str]:
        return [f"{'✓' if i.ok else '!'} {i.text}: {i.detail}" for i in self.checklist]
