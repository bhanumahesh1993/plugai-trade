"""Settings › Workspace (Chapter 34): a style template applied in one reviewed pass.

Apply template (Investor / Swing / Intraday / Options / Mixed; market IN, US or
both) → Preview changes lists three groups — screens to pin, Scheduler jobs
(Daily Briefing, Weekly Review, nightly backup, monthly update check) and
starter Rule Card lines — plus the rhythm reminders that appear under the Daily
Briefing's Questions for you. Each group is applied only when you click Accept
on it; Rule Card lines arrive as *suggestions* that you accept on the Rule Card.
Export workspace writes settings, schedules and pins — never keys or the journal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import __version__, config
from .store import default as store

STYLES = ("Investor", "Swing", "Intraday", "Options", "Mixed")
MARKETS = {"IN": ("IN",), "US": ("US",), "Both": ("IN", "US")}
GROUPS = ("Pinned screens", "Scheduler jobs", "Rule Card lines", "Rhythm reminders")

_SCREENS: dict[str, list[str]] = {
    "Investor": ["Portfolio Reviewer", "Document Desk", "Daily Briefing", "Weekly Review"],
    "Swing": ["Screener", "Position Sizer", "Alerts", "Trade Plan", "Weekly Review"],
    "Intraday": ["Screener", "Chart Helper", "Paper Desk", "Rule Card", "Trades"],
    "Options": ["Options Strategy Builder", "Earnings Desk", "Paper Desk", "Weekly Review"],
}
_RULES: dict[str, list[str]] = {
    "Investor": ["Keep the target allocation within its band (for example ±5 points).",
                 "No change to a holding without a written thesis note."],
    "Swing": ["Exclude names with results inside the holding window.",
              "Stop at an ATR multiple written in the plan before entry.",
              "Total open risk stays within the Rule Card cap."],
    "Intraday": ["Max trades a day as written on this card.",
                 "Cooldown after a losing trade before the next entry.",
                 "Trade only inside the written trading window."],
    "Options": ["Max premium or margin per trade as written on this card.",
                "Exit rule decided before expiry day.",
                "Scenario check (gap and IV) before every entry."],
}
_RHYTHM: dict[str, list[str]] = {
    "Investor": ["Monthly: SIP and allocation check", ("Quarterly: thesis review per holding and "
                  "rebalance check"), "Quarterly: tax records"],
    "Swing": ["Weekend: screen, plan, size and alerts", "Monthly: results calendar for the month",
              "Quarterly: tax records"],
    "Intraday": ["Daily: 10-minute journal after the close", "Monthly: cost share of gross",
                 "Quarterly: tax records and turnover (India)"],
    "Options": ["Weekly: plan around expiry days and events",
                "Monthly: scenario test of each open structure",
                "Quarterly: tax records (US: 1256 tags)"],
}
_COMMON_RHYTHM = ["Weekly Review due", "Monthly audit due (first weekend)", "Tax quarter closing"]
#: Default Daily Briefing times: Kavita 08:40 IST on NSE days, Marcus 08:50 ET on NYSE days.
BRIEFING_AT = {"IN": "08:40", "US": "08:50"}


@dataclass
class Job:
    job: str
    market: str
    schedule: dict[str, Any]

    def describe(self) -> str:
        from .scheduler import Schedule
        return Schedule(**self.schedule).describe(self.market)


@dataclass
class Preview:
    """Everything the template would change, grouped for per-group Accept."""

    style: str
    markets: tuple[str, ...]
    pinned: list[str] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    rhythm: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)

    def group(self, name: str) -> list[str]:
        if name == "Pinned screens":
            return list(self.pinned)
        if name == "Scheduler jobs":
            return [f"{j.job} · {j.market} · {j.describe()}" for j in self.jobs]
        if name == "Rule Card lines":
            return list(self.rules)
        if name == "Rhythm reminders":
            return list(self.rhythm)
        raise KeyError(name)

    def facts(self) -> list[str]:
        return [f"Template: {self.style} · {' + '.join(self.markets)}"] + [
            f"{g}: {len(self.group(g))}" for g in GROUPS]


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _styles(style: str) -> list[str]:
    if style not in STYLES:
        raise ValueError(f"unknown template {style!r}; choose one of {', '.join(STYLES)}")
    return ["Swing", "Options", "Investor"] if style == "Mixed" else [style]


def preview(style: str, market: str = "IN", briefing_at: dict[str, str] | None = None) -> Preview:
    """Preview changes for a template. ``market`` is IN, US or Both."""
    markets = MARKETS[market]
    parts = _styles(style)
    times = {**BRIEFING_AT, **(briefing_at or {})}
    jobs: list[Job] = []
    for m in markets:
        jobs += [Job("Daily Briefing", m, {"kind": "trading days", "at": times[m]}),
                 Job("Weekly Review", m, {"kind": "weekly", "day": "Sat", "at": "09:00"})]
    jobs += [Job("Backup", markets[0], {"kind": "daily", "at": "23:30"}),
             Job("Monthly update check", markets[0], {"kind": "monthly", "day": "1", "at": "10:00"})]
    return Preview(style, markets,
                   pinned=_dedupe([s for p in parts for s in _SCREENS[p]]),
                   jobs=jobs,
                   rules=_dedupe([r for p in parts for r in _RULES[p]]),
                   rhythm=_dedupe(_COMMON_RHYTHM + [r for p in parts for r in _RHYTHM[p]]))


def accept(pv: Preview, group: str) -> str:
    """Apply one group. Returns a one-line confirmation."""
    if group == "Pinned screens":
        config.set_value("workspace.pinned", pv.pinned)
        msg = f"Pinned {len(pv.pinned)} screens."
    elif group == "Scheduler jobs":
        from . import scheduler
        existing = {(j.get("job"), j.get("mkt")) for j in scheduler.jobs()}
        added = [scheduler.add_job(j.job, j.market, j.schedule) for j in pv.jobs
                 if (j.job, j.market) not in existing]
        msg = f"Added {len(added)} Scheduler jobs ({len(pv.jobs) - len(added)} already there)."
    elif group == "Rule Card lines":
        from . import rulecard
        card = rulecard.suggest_rules(rulecard.current(), pv.rules, group="Workspace template")
        rulecard.new_version(card, note=f"{pv.style} template: starter lines (suggested)")
        msg = f"{len(pv.rules)} starter lines sent to the Rule Card as suggestions."
    elif group == "Rhythm reminders":
        config.set_value("workspace.rhythm", pv.rhythm)
        msg = f"{len(pv.rhythm)} rhythm reminders will appear under Questions for you."
    else:
        raise KeyError(group)
    pv.accepted.append(group)
    config.set_value("workspace.template", pv.style)
    config.set_value("workspace.markets", list(pv.markets))
    store().add("workspaces", {"style": pv.style, "markets": list(pv.markets), "group": group},
                tag="accepted")
    return msg


def pinned() -> list[str]:
    return list(config.get("workspace.pinned", []) or [])


def rhythm() -> list[str]:
    return list(config.get("workspace.rhythm", []) or [])


_SAFE_SETTINGS = ("market", "education_lag_days", "watchlists", "ai", "privacy", "alerts",
                  "workspace", "scheduler")


def export() -> str:
    """Export workspace: settings, schedules and pins as JSON — no keys, no journal."""
    from . import rulecard, scheduler
    settings = config.load()
    body = {
        "plugai_trade": __version__,
        "exported": datetime.now(UTC).isoformat(timespec="seconds"),
        "settings": {k: settings[k] for k in _SAFE_SETTINGS if k in settings},
        "pinned": pinned(),
        "rhythm": rhythm(),
        "jobs": [{k: j.get(k) for k in ("job", "mkt", "schedule", "when", "model", "enabled")}
                 for j in scheduler.jobs()],
        "rule_card_lines": [r for r in asdict(rulecard.current())["rules"]
                            if r.get("group") == "Workspace template"],
        "note": "Keys and the journal are never included.",
    }
    return json.dumps(body, indent=2, default=str)
