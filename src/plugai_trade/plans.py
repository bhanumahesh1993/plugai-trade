"""Plan & Risk › Trade Plan — the plan on one page, written before the open.

Templates list their fields and who fills each one: YOU (the trader), CODE (the
Position Sizer or the Alerts screen) or CALENDAR (the lab's event calendar).
Plans are versioned: every save keeps the previous version. The AI sceptic
critiques the text; it never grades the idea, predicts prices or computes size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import ai, reference
from .store import default as store
from .store import now

YOU, CODE, CALENDAR = "YOU", "CODE", "CALENDAR"

TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "Seven-field plan": [("Setup", YOU), ("Entry", YOU), ("Stop", YOU), ("Exit logic", YOU),
                         ("Size", CODE), ("Invalidation", YOU), ("Events", CALENDAR)],
    "Weekend swing plan": [("Setup", YOU), ("Trigger", YOU), ("Stop", CODE), ("Size", CODE),
                           ("Exit logic", YOU), ("Events", CALENDAR), ("Invalidation", YOU),
                           ("Alerts", CODE)],
    "Intraday plan": [("Setup", YOU), ("Entry", YOU), ("Stop", YOU), ("Exit logic", YOU),
                      ("Size", CODE), ("Invalidation", YOU), ("Events", CALENDAR),
                      ("Guardrails", CODE)],
}

VAGUE = ("somewhere", "strong", "maybe", "around", "about", "roughly", "if it looks",
         "probably", "should", "might", "kind of", "a bit", "approximately", "near")

CRITIQUE_PROMPT = (
    "You are a sceptical risk reviewer. Below is my written trade plan.\n\n{plan}\n\n"
    "Rules: do NOT say whether the trade is good or bad, do NOT predict prices, do NOT "
    "recommend a size, and do NOT do any arithmetic.\n"
    "1. List every field that is missing, vague or untestable.\n"
    "2. List any contradictions (e.g. a stop on the wrong side of entry, an exit that happens "
    "after a known event, invalidation looser than the stop).\n"
    "3. Name three ways this plan could fail that it does not mention.\n"
    "4. List the numbers I should recompute myself with a calculator or tool.\n"
    "5. End with five yes/no questions I must answer before the open."
)


@dataclass
class Plan:
    """A trade plan. ``fields`` holds the template's text fields in order."""

    name: str
    template: str = "Seven-field plan"
    market: str = "IN"
    symbol: str = ""
    side: str = "long"
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    qty: int | None = None
    risk_money: float | None = None
    trigger_expiry: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    id: int | None = None
    version: int = 0
    versions: list[dict[str, Any]] = field(default_factory=list)

    def owners(self) -> dict[str, str]:
        return dict(TEMPLATES.get(self.template, TEMPLATES["Seven-field plan"]))

    def body(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("name", "template", "market", "symbol", "side",
                                              "entry", "stop", "target", "qty", "risk_money",
                                              "trigger_expiry", "fields", "version", "versions")}

    def text(self) -> str:
        head = f"{self.name} · {self.symbol or '(symbol)'} · {self.market} · {self.side}"
        return head + "\n" + "\n".join(f"{k}: {self.fields.get(k) or 'MISSING'}"
                                       for k in self.owners())

    def facts(self) -> list[str]:
        """Only the plan's own fields — what Show sources lists for a critique."""
        return [f"{k}: {self.fields.get(k) or 'MISSING'}" for k in self.owners()]


def new_plan(template: str = "Seven-field plan", market: str = "IN", symbol: str = "",
             name: str | None = None) -> Plan:
    """A blank plan from a template, with Events pre-filled from the lab calendar."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template {template!r}. Choose one of {list(TEMPLATES)}.")
    p = Plan(name or f"{symbol or 'New'} plan", template, market, symbol,
             fields={k: "" for k, _ in TEMPLATES[template]})
    ev = calendar_events(symbol, market)
    if ev:
        p.fields["Events"] = "; ".join(ev)
    return p


def from_row(row: dict[str, Any]) -> Plan:
    keys = Plan.__dataclass_fields__
    p = Plan(**{k: v for k, v in row.items() if k in keys and k != "id"})
    p.id = row["id"]
    return p


def save(plan: Plan, note: str = "") -> Plan:
    """Save a new version; the previous version is kept in ``versions`` (plan history)."""
    st = store()
    if plan.id is not None:
        old = st.get("plans", plan.id)
        if old:
            snap = {k: old.get(k) for k in ("fields", "entry", "stop", "qty", "target", "side",
                                            "version")}
            snap["saved"] = old.get("saved", old["created"])
            plan.versions = [*(old.get("versions") or []), snap]
    plan.version += 1
    body = {**plan.body(), "saved": now(), "note": note}
    if plan.id is None:
        plan.id = st.add("plans", body, tag="plan")
    else:
        st.update("plans", plan.id, body)
    return plan


def load(plan_id: int) -> Plan | None:
    row = store().get("plans", plan_id)
    return from_row(row) if row else None


def all_plans(market: str | None = None) -> list[Plan]:
    rows = store().all("plans", tag="plan")
    return [from_row(r) for r in rows if market is None or r.get("market") == market]


# ---------------------------------------------------------------- calendar
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def calendar_events(symbol: str, market: str, start: date | None = None,
                    sessions: int = 10) -> list[str]:
    """Expiry days for index contracts from the dated table, within the next ``sessions``."""
    from .sizing import base_symbol
    start = start or date.today()
    row = reference.lookup(f"india.contracts.{base_symbol(symbol)}") if market == "IN" else None
    if not row or not row.get("expiry"):
        return []
    text = str(row["expiry"]).lower()
    days = [i for i, d in enumerate(_WEEKDAYS) if d in text]
    out, d, n = [], start, 0
    while n < sessions:
        d += timedelta(days=1)
        if d.weekday() >= 5:
            continue
        n += 1
        if d.weekday() in days and "weekly" in text:
            out.append(f"{base_symbol(symbol)} expiry {d:%a %d %b}")
    return out


# ---------------------------------------------------------------- critique
@dataclass
class Critique:
    text: str
    plan: Plan
    where: str = "Fallback"
    model: str = "checklist"
    missing: list[str] = field(default_factory=list)
    vague: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)

    def facts(self) -> list[str]:
        return self.plan.facts()


def _num(text: str) -> float | None:
    m = re.search(r"(\d[\d,]*\.?\d*)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def checklist(plan: Plan) -> Critique:
    """The critique computed in code: missing fields, vague words, contradictions, questions."""
    owners = plan.owners()
    missing = [k for k in owners if not (plan.fields.get(k) or "").strip()
               and not (k == "Size" and plan.qty)]
    vague = sorted({f"'{w}' in {k}" for k, v in plan.fields.items() for w in VAGUE
                    if re.search(rf"\b{re.escape(w)}\b", v or "", re.IGNORECASE)})
    contra = []
    entry = plan.entry if plan.entry is not None else _num(plan.fields.get("Entry") or
                                                           plan.fields.get("Trigger", ""))
    stop = plan.stop if plan.stop is not None else _num(plan.fields.get("Stop", ""))
    if entry and stop:
        if plan.side == "long" and stop >= entry:
            contra.append(f"Stop {stop:,.2f} is not below the entry {entry:,.2f} for a long plan")
        if plan.side == "short" and stop <= entry:
            contra.append(f"Stop {stop:,.2f} is not above the entry {entry:,.2f} for a short plan")
    inv = _num(plan.fields.get("Invalidation", ""))
    if inv and stop and entry and plan.side == "long" and inv > entry:
        contra.append("Invalidation level sits above the entry")
    if plan.template == "Weekend swing plan" and "valid" not in (plan.fields.get("Trigger") or "").lower():
        missing.append("Trigger expiry (e.g. 'valid Monday to Wednesday only')")
    lines = ["*Missing / vague:* " + ("; ".join(missing + vague) or "none found by the checklist"),
             "*Contradictions:* " + ("; ".join(contra) or "none found on price"),
             "*Unmentioned failure modes to consider:* a gap through the stop at the open; "
             "an event inside the holding period; entering late after a fast move, when the "
             "stop is further away than planned.",
             "*Recompute yourself:* risk per unit including costs; whether the total fits your "
             "daily limit and open-risk cap (Position Sizer).",
             "*Yes/no:* Is the entry void after a set time or day? Will you hold through the "
             "next expiry or results date? Is the stop written as a price, not a feeling? Is the "
             "size from the sizer, rounded down? Would you take this trade after two losses today?"]
    return Critique("\n".join(lines), plan, missing=missing, vague=vague, contradictions=contra)


def critique(plan: Plan, section: str = "Plan & Risk") -> Critique:
    """AI sceptic via ``ai.complete``; with no model reachable, the code checklist."""
    base = checklist(plan)
    out = ai.complete(CRITIQUE_PROMPT.format(plan=plan.text()), section=section)
    if out.text:
        base.text, base.where, base.model = out.text, out.where, out.model
    return base


# ---------------------------------------------------------------- hand-offs
def save_to_journal(plan: Plan) -> int:
    """Timestamp the plan *before* the trade (Chapter 14 compares plan with action)."""
    if plan.id is None:
        save(plan)
    return store().add("journal", {"kind": "plan", "plan_id": plan.id, "name": plan.name,
                                   "symbol": plan.symbol, "market": plan.market,
                                   "version": plan.version, "fields": plan.fields,
                                   "entry": plan.entry, "stop": plan.stop, "qty": plan.qty,
                                   "saved_at": now()}, tag="PLAN")


def ticket_from(plan: Plan) -> dict[str, Any]:
    """The Paper Desk ticket a plan describes: contract, side, size, stop-entry, stop."""
    if not plan.symbol or not plan.qty:
        raise ValueError("Send to Paper Desk needs a symbol and a size (click Size it first).")
    return {"symbol": plan.symbol, "market": plan.market,
            "side": "buy" if plan.side == "long" else "sell", "qty": int(plan.qty),
            "kind": "stop" if plan.entry else "market", "price": plan.entry, "stop": plan.stop,
            "target": plan.target, "plan_id": plan.id, "risk_money": plan.risk_money}


def send_to_paper_desk(plan: Plan) -> int:
    """Prefill the Paper Desk ticket from the plan. You still click Place paper order."""
    from .paper import hand_ticket
    if plan.id is None:
        save(plan)
    return hand_ticket(ticket_from(plan), source=f"Trade Plan #{plan.id}")


def use_size(plan: Plan, size: Any) -> Plan:
    """Position Sizer › Use in plan: write size (and an ATR stop) into the plan, new version."""
    plan.qty = int(size.quantity)
    plan.risk_money = float(size.actual_risk)
    if size.stop is not None:
        plan.stop = float(size.stop)
        if plan.owners().get("Stop") == CODE or not plan.fields.get("Stop"):
            plan.fields["Stop"] = f"{size.stop:,.2f}" + (
                f" = {size.entry:,.2f} − {size.extra['atr_multiple']:g} × ATR "
                f"({size.extra['atr']:,.2f})" if "atr" in size.extra else "")
    plan.entry = plan.entry or float(size.entry)
    plan.fields["Size"] = size.size_text()
    return save(plan, note=f"Size from Position Sizer ({size.method})")
