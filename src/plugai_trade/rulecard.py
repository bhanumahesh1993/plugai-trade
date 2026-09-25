"""Plan & Risk › Rule Card — your written rules, versioned, and what code can check.

Tabs: Written rules / Checklist / Go / no-go / Monthly audit. Numbers on the card
(1R, caps, loss limits in R, intraday guardrails) are synced to the Position
Sizer and the Paper Desk with ``sync_limits``. The go/no-go check and the
adherence score are computed from the journal — process, never profit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from . import config
from .store import default as store
from .store import now

TEMPLATE_RULES = {
    "Size & risk": ["1R = 1% of account", "Largest position 25% of account",
                    "Open risk ≤ 3R; one group ≤ 2R", "Size from the sizer, rounded down"],
    "Limits": ["Daily loss 2R → stop for the day", "Weekly loss 4R → stop until Monday review",
               "Max 3 new trades a day", "No trade in the first 15 min"],
    "Behaviour": ["Stop is never moved away from entry", "No re-entry after invalidation this week",
                  "No averaging down", "Plan saved before every trade",
                  "AI and broker: read-only → paper → your own click"],
}

CHECKLIST = ["Events today: expiry, results, policy?", "Yesterday's limits reset, no carry-over tilt?",
             "Every planned trade has 7 fields and a size?", "Open risk + planned risk ≤ 3R?",
             "Data timestamp is today's?", "Slept, calm, time to watch the trade?"]

EVENT_TYPES = {"IN": ["RBI policy", "NIFTY expiry", "Results"],
               "US": ["CPI", "FOMC", "Jobs report", "Results"]}

PASS_MARKS = {"min_signals": 30, "min_weeks": 4, "adherence": 0.90, "stops_moved": 0,
              "off_plan": 0, "cost_gap_r": 0.05, "cost_share": 0.25, "limit_breaches": 0}


@dataclass
class RuleCard:
    """One version of the card. Money figures derive from ``account`` and ``risk_pct``."""

    version: int = 1
    account: dict[str, float] = field(default_factory=lambda: {"IN": 1_500_000.0, "US": 40_000.0})
    risk_pct: float = 0.01
    position_cap_pct: float = 0.25
    open_risk_cap_r: float = 3.0
    group_cap_r: float = 2.0
    daily_limit_r: float = 2.0
    weekly_limit_r: float = 4.0
    max_trades_day: int = 3
    cooldown_min: int = 30
    window: dict[str, str] = field(default_factory=lambda: {"IN": "09:30-15:00", "US": "09:45-15:30"})
    event_lockout_min: int = 30
    event_types: list[str] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)   # {"when": iso, "name": ...}
    rules: list[dict[str, str]] = field(default_factory=list)    # {"group","text","status"}
    checklist: list[dict[str, Any]] = field(default_factory=list)  # {"text","ticked"}
    pass_marks: dict[str, float] = field(default_factory=lambda: dict(PASS_MARKS))
    note: str = ""
    written: str = ""

    def one_r(self, market: str) -> float:
        return round(self.account.get(market, 0.0) * self.risk_pct, 2)

    def money_limits(self, market: str) -> dict[str, float]:
        """1R, daily and weekly limits in money: ₹15,000 / ₹30,000 / ₹60,000 for ₹15 lakh at 1%."""
        r = self.one_r(market)
        return {"one_r": r, "daily": round(r * self.daily_limit_r, 2),
                "weekly": round(r * self.weekly_limit_r, 2),
                "position_cap": round(self.account.get(market, 0.0) * self.position_cap_pct, 2)}

    def accepted_rules(self) -> list[dict[str, str]]:
        return [r for r in self.rules if r.get("status") == "accepted"]

    def facts(self) -> list[str]:
        out = [f"Version {self.version}", f"1R = {self.risk_pct:.2%} of account",
               f"Position cap {self.position_cap_pct:.0%}",
               f"Open risk cap {self.open_risk_cap_r:g}R; group cap {self.group_cap_r:g}R",
               f"Daily limit {self.daily_limit_r:g}R; weekly limit {self.weekly_limit_r:g}R",
               f"Max trades a day {self.max_trades_day}; cooldown {self.cooldown_min} min"]
        for m in ("IN", "US"):
            lim = self.money_limits(m)
            c = "₹" if m == "IN" else "$"
            out.append(f"{m}: 1R {c}{lim['one_r']:,.0f}, daily {c}{lim['daily']:,.0f}, "
                       f"weekly {c}{lim['weekly']:,.0f}")
        out += [f"Rule: {r['text']}" for r in self.accepted_rules()]
        return out


def template_card() -> RuleCard:
    rules = [{"group": g, "text": t, "status": "accepted"} for g, ts in TEMPLATE_RULES.items()
             for t in ts]
    return RuleCard(rules=rules, checklist=[{"text": t, "ticked": True} for t in CHECKLIST])


def current() -> RuleCard:
    """The latest saved version, or the chapter-12 template if none is saved."""
    rows = store().all("rule_cards", limit=1)
    if not rows:
        return template_card()
    body = {k: v for k, v in rows[0].items() if k in RuleCard.__dataclass_fields__}
    return RuleCard(**body)


def history() -> list[dict[str, Any]]:
    return store().all("rule_cards")


def new_version(card: RuleCard, note: str = "") -> RuleCard:
    """Save the card as a new, dated version (the previous one stays in history)."""
    rows = store().all("rule_cards", limit=1)
    card.version = (int(rows[0].get("version", 0)) + 1) if rows else 1
    card.note, card.written = note, now()
    store().add("rule_cards", asdict(card), tag=f"v{card.version}")
    return card


def suggest_rules(card: RuleCard, lines: list[str], group: str = "Behaviour") -> RuleCard:
    """Pasted or AI-drafted lines arrive as suggestions until you click Accept."""
    card.rules += [{"group": group, "text": ln.strip(), "status": "suggested"}
                   for ln in lines if ln.strip()]
    return card


def checklist_questions() -> list[str]:
    """Ticked pre-market checklist items (Daily Briefing › Questions for you)."""
    return [c["text"] for c in current().checklist if c.get("ticked")]


def sync_limits(card: RuleCard) -> dict[str, Any]:
    """Rule Card → Position Sizer caps and the Paper Desk's daily loss limit and guardrails."""
    mkt = config.get("market", "IN")
    lim = card.money_limits(mkt)
    values = {
        "paper.daily_loss_limit": lim["daily"],
        "paper.one_r": {m: card.one_r(m) for m in ("IN", "US")},
        "paper.daily_loss_limit_by_market": {m: card.money_limits(m)["daily"] for m in ("IN", "US")},
        "paper.max_trades_per_day": int(card.max_trades_day),
        "paper.cooldown_minutes": int(card.cooldown_min),
        "paper.trading_window": dict(card.window),
        "paper.event_lockout_minutes": int(card.event_lockout_min),
        "paper.events": list(card.events),
        "sizing.account": dict(card.account),
        "sizing.risk_pct": card.risk_pct,
        "sizing.cap_pct": card.position_cap_pct,
        "sizing.total_cap_r": card.open_risk_cap_r,
        "sizing.group_cap_r": card.group_cap_r,
        "rulecard.synced_version": card.version,
    }
    for k, v in values.items():
        config.set_value(k, v)
    store().audit("sync_limits", {"version": card.version, "market": mkt})
    return values


# ---------------------------------------------------------------- measures from the journal
def _trades(rows: list[dict[str, Any]], account: str) -> list[dict[str, Any]]:
    tags = {"Paper": ("PAPER", "REPLAY"), "Pilot": ("PILOT",)}[account]
    return [r for r in rows if r.get("tag") in tags and r.get("kind", "paper_trade") != "plan"
            and r.get("kind") != "blocked_paper_order"]


def _week(d: str) -> date:
    x = date.fromisoformat(str(d)[:10])
    return x - timedelta(days=x.weekday())


def _breaks(t: dict[str, Any]) -> list[str]:
    b = list(t.get("rule_breaks") or [])
    if t.get("unplanned") and "off-plan" not in b:
        b.append("off-plan")
    if any(m.get("away_from_entry") for m in t.get("stop_moves") or []) and "stop moved away" not in b:
        b.append("stop moved away")
    return b


def adherence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Share of decisions handled as the rules say, with the row ids of the breaks."""
    decisions = [r for r in rows if r.get("kind") in ("paper_trade", "skipped_signal", None, "trade")]
    broken = [r for r in decisions if _breaks(r) or r.get("kind") == "skipped_signal"]
    n = len(decisions)
    return {"decisions": n, "followed": n - len(broken),
            "score": (n - len(broken)) / n if n else None,
            "broken_rows": [r.get("id") for r in broken]}


@dataclass
class Measure:
    name: str
    pass_mark: str
    value: str
    passed: bool
    rows: list[Any] = field(default_factory=list)


@dataclass
class GoNoGo:
    account: str
    measures: list[Measure]

    @property
    def verdict(self) -> str:
        if all(m.passed for m in self.measures):
            return "GO to pilot" if self.account == "Paper" else "GO to next size step"
        return "NOT YET"

    def facts(self) -> list[str]:
        return [f"{m.name}: {m.value} (pass mark {m.pass_mark}) → "
                f"{'PASS' if m.passed else 'NOT YET'}" for m in self.measures] + \
               [f"Verdict: {self.verdict}", "Profit is deliberately not a measure."]


def go_no_go(rows: list[dict[str, Any]] | None = None, account: str = "Paper",
             marks: dict[str, float] | None = None, start: str | None = None,
             end: str | None = None) -> GoNoGo:
    """Run check: process measures from Journal › Trades → PASS / NOT YET chips (Chapter 34)."""
    marks = {**PASS_MARKS, **(marks or current().pass_marks)}
    rows = rows if rows is not None else store().all("journal")
    trades = [t for t in _trades(rows, account)
              if (not start or str(t.get("date", t.get("created", "")))[:10] >= start)
              and (not end or str(t.get("date", t.get("created", "")))[:10] <= end)]
    trades = [t for t in trades if t.get("kind") in ("paper_trade", "skipped_signal", "trade", None)]
    dates = sorted(str(t.get("date") or t.get("created"))[:10] for t in trades)
    weeks = sorted({_week(d) for d in dates})
    n_weeks = ((weeks[-1] - weeks[0]).days // 7 + 1) if weeks else 0
    m: list[Measure] = []
    m.append(Measure("Paper length" if account == "Paper" else "Pilot length",
                     f"≥ {marks['min_signals']:g} · ≥ {marks['min_weeks']:g} wks",
                     f"{len(trades)} · {n_weeks} wks",
                     len(trades) >= marks["min_signals"] and n_weeks >= marks["min_weeks"]))
    for label, wk in (("Adherence, week before last", -2), ("Adherence, last week", -1)):
        if len(weeks) >= -wk:
            wrows = [t for t in trades if _week(str(t.get("date") or t.get("created"))[:10]) == weeks[wk]]
            a = adherence(wrows)
            val = f"{a['score']:.1%}" if a["score"] is not None else "no trades"
            ok = a["score"] is not None and a["score"] >= marks["adherence"]
            m.append(Measure(label, f"≥ {marks['adherence']:.0%}", val, ok, a["broken_rows"]))
        else:
            m.append(Measure(label, f"≥ {marks['adherence']:.0%}", "no data", False))
    moved = [t.get("id") for t in trades if "stop moved away" in _breaks(t)]
    m.append(Measure("Stops moved away", f"{marks['stops_moved']:g}", str(len(moved)),
                     len(moved) <= marks["stops_moved"], moved))
    off = [t.get("id") for t in trades if "off-plan" in _breaks(t)]
    m.append(Measure("Off-plan trades", f"{marks['off_plan']:g}", str(len(off)),
                     len(off) <= marks["off_plan"], off))
    with_r = [t for t in trades if t.get("cost_r") is not None]
    gap = sum(float(t["cost_r"]) for t in with_r) / len(with_r) if with_r else 0.0
    m.append(Measure("Cost gap per trade", f"≤ {marks['cost_gap_r']:.2f}R", f"{gap:.2f}R",
                     gap <= marks["cost_gap_r"]))
    gross = sum(abs(float(t.get("chart_move") or t.get("gross") or 0)) for t in trades)
    paid = sum(float(t.get("costs_total") or 0) + float(t.get("slippage") or 0) for t in trades)
    share = paid / gross if gross else 0.0
    m.append(Measure("Costs share of gross", f"≤ {marks['cost_share']:.0%}", f"{share:.1%}",
                     share <= marks["cost_share"]))
    breaches = _limit_breaches(trades)
    m.append(Measure("Drawdown behaviour: trades after a daily limit", f"{marks['limit_breaches']:g}",
                     str(len(breaches)), len(breaches) <= marks["limit_breaches"], breaches))
    practised = store().count("audit_log", tag="kill_switch") > 0
    m.append(Measure("Kill switch practised", "yes", "yes" if practised else "no", practised))
    return GoNoGo(account, m)


def _limit_breaches(trades: list[dict[str, Any]]) -> list[Any]:
    """Trades taken on a day after that day's losses already reached the daily limit."""
    card = current()
    out = []
    by_day: dict[str, list[dict[str, Any]]] = {}
    for t in sorted(trades, key=lambda t: str(t.get("exit_time") or t.get("date") or "")):
        by_day.setdefault(str(t.get("date") or "")[:10], []).append(t)
    for ts in by_day.values():
        running = 0.0
        for t in ts:
            r = t.get("r")
            if running <= -card.daily_limit_r:
                out.append(t.get("id"))
            running += float(r) if r is not None else 0.0
    return out


def save_pilot_plan(market: str, budget: float, trades_per_day: int, review_date: str,
                    stop_conditions: list[str], size_text: str = "",
                    review_after_trades: int = 20) -> int:
    """Save pilot plan: small, capped and dated (Chapter 34)."""
    if budget <= 0 or trades_per_day <= 0:
        raise ValueError("A pilot needs a positive budget and a trades-a-day limit.")
    return store().add("pilot_plans", {
        "market": market, "budget": budget, "trades_per_day": trades_per_day,
        "review_date": review_date, "review_after_trades": review_after_trades,
        "stop_conditions": stop_conditions, "size": size_text, "card_version": current().version,
        "saved_at": now()}, tag="pilot")


# ---------------------------------------------------------------- Monthly audit
AUDIT_ITEMS = ("Rules", "Costs", "Tools", "AI", "Data", "Security", "Backup")


def start_audit(today: date | None = None) -> dict[str, Any]:
    """The monthly audit checklist, with the numbers code can fill in (Chapter 34)."""
    today = today or date.today()
    this_m = today.strftime("%Y-%m")
    last_m = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    rows = store().all("journal")

    def month(r: dict[str, Any]) -> str:
        return str(r.get("date") or r.get("created"))[:7]

    def share(m: str) -> float | None:
        ts = [r for r in rows if month(r) == m and r.get("kind") == "paper_trade"]
        g = sum(abs(float(r.get("chart_move") or 0)) for r in ts)
        return (sum(float(r.get("costs_total") or 0) + float(r.get("slippage") or 0)
                    for r in ts) / g) if g else None

    broken: dict[str, int] = {}
    for r in rows:
        if month(r) == this_m:
            for b in _breaks(r):
                broken[b] = broken.get(b, 0) + 1
    from . import keys
    hints = {
        "Rules": ("Broken this month: " + ", ".join(f"{k} ×{v}" for k, v in broken.items())
                  if broken else "No rule breaks recorded this month"),
        "Costs": f"Charges share of gross: this month {_pct(share(this_m))}, last month {_pct(share(last_m))}",
        "Tools": "List screens and paid tools you used; cancel what you did not",
        "AI": "Re-run two saved prompts with known answers; check the cost meter",
        "Data": "Token expiry dates, sources that disagreed, provenance gaps",
        "Security": f"{len(keys.listed())} keys stored; "
                    f"{store().count('audit_log')} audit-log rows to read; confirm 2FA",
        "Backup": "Restore one file from last month's backup",
    }
    return {"month": this_m, "items": [{"item": k, "hint": hints[k], "done": False}
                                       for k in AUDIT_ITEMS]}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def save_audit(audit: dict[str, Any]) -> int:
    return store().add("reviews", {**audit, "saved_at": now(),
                                   "at": datetime.now().isoformat(timespec="minutes")},
                       tag="monthly-audit")
