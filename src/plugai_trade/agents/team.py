"""The built-in research team: analysts → bull → bear → risk manager → rule proposer.

Each turn is one ``ai.complete`` call that may only quote the facts the tools
returned (numbers are computed in code, never by the model). With no model
reachable, every turn falls back to a deterministic text built from the same
facts, and the rule proposer drafts a rule from simple features. The output is
always a *rule proposal*: a research note plus a rule spec for the backtester.
Never an order, never a paper order.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .. import ai
from .tools import TOOLS, Tools, as_date

SYSTEM = (
    "You are one member of a research team inside PlugAI-Trade, an education lab. Rules: "
    "1) Use ONLY the facts provided; quote them, never invent or calculate a number. "
    "2) Never recommend buying, selling or holding anything; no price targets; no orders. "
    "3) The subject's name and dates may be hidden; do not guess them. "
    "4) Write at most five short bullet points."
)

ROLES = ("Technical", "News", "Fundamentals", "Bull", "Bear", "Risk manager", "Rule proposer")
RULE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "entry": {"type": "array"},
                   "exit": {"type": "array"}},
    "required": ["text", "entry", "exit"],
}


class BudgetExceeded(RuntimeError):
    """Raised inside a run when the next step would pass the step or cost cap."""


@dataclass
class Budget:
    """Step and cost caps. A run stops before a step that could overrun either."""

    max_steps: int = 40
    max_cost: float = 0.50
    steps: int = 0
    cost: float = 0.0
    worst_step: float = 0.0

    def take(self, what: str) -> None:
        if self.steps + 1 > self.max_steps:
            raise BudgetExceeded(f"step limit reached ({self.max_steps}) before {what}")
        if self.cost + self.worst_step > self.max_cost:
            raise BudgetExceeded(f"cost cap ${self.max_cost:.2f} would be passed by {what}")
        self.steps += 1

    def spend(self, usd: float) -> None:
        self.cost += usd
        self.worst_step = max(self.worst_step, usd)


@dataclass
class Proposal:
    """What a team run produced: a note and rules. ``kind`` is always ``rule_proposal``."""

    symbol: str
    market: str
    as_of: date
    team: str
    note: str
    rules: dict[str, Any] | None
    cost: float
    steps: int
    transcript: list[dict[str, Any]]
    mask_names: bool = True
    stopped: str = ""
    warnings: list[str] = field(default_factory=list)
    sections: dict[str, list[str]] = field(default_factory=dict)
    kind: str = "rule_proposal"

    @property
    def trials_added(self) -> int:
        return sum(1 for t in self.transcript if t.get("tool") == "run_backtest" and t.get("ok"))

    def facts(self) -> list[str]:
        out = [(f"Research proposal (not an order) on {self.symbol} ({self.market}), "
                f"data up to {self.as_of}, team {self.team}"),
               f"Steps used: {self.steps}; cost: ${self.cost:.2f}",
               f"Agent's own backtests (added to the Trials counter): {self.trials_added}"]
        if self.rules:
            out.append(f"Proposed rule: {self.rules.get('text', '')}")
        if self.stopped:
            out.append(f"Run stopped: {self.stopped}")
        out += [ln for ln in self.note.splitlines() if ln.startswith("- ")][:12]
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "market": self.market, "as_of": str(self.as_of),
                "team": self.team, "note": self.note, "rules": self.rules, "cost": self.cost,
                "steps": self.steps, "kind": self.kind, "stopped": self.stopped,
                "mask_names": self.mask_names, "trials_added": self.trials_added}


# ---------------------------------------------------------------- deterministic fallbacks
def _num(facts: list[str], prefix: str) -> float | None:
    for f in facts:
        if f.startswith(prefix):
            try:
                return float(f.split(":", 1)[1].strip().rstrip("%×").replace("+", ""))
            except ValueError:
                return None
    return None


def _fallback_turn(role: str, facts: list[str], news: list[str], filings: list[str]) -> list[str]:
    ma50 = _num(facts, "Close vs 50-day")
    ma200 = _num(facts, "Close vs 200-day")
    volr = _num(facts, "20-day volatility vs")
    r252 = _num(facts, "Return over 252")
    dd = _num(facts, "Worst fall")
    if role == "Technical":
        return [f for f in facts[1:7]]
    if role == "News":
        return ([f"Headline: {h}" for h in news[:5]] or
                ["No headlines were available before the as-of date; the note has no news view."])
    if role == "Fundamentals":
        return ([f"Filing on file: {f}" for f in filings[:5]] or
                ["No filings on file before the as-of date; the note has no fundamentals view."])
    if role == "Bull":
        pts = []
        if ma200 is not None and ma200 > 0:
            pts.append(f"The close is {ma200:+.1f}% vs its 200-day average (tool: get_bars).")
        if ma50 is not None and ma50 > 0:
            pts.append(f"The close is {ma50:+.1f}% vs its 50-day average (tool: get_bars).")
        if r252 is not None and r252 > 0:
            pts.append(f"The 252-session return was {r252:+.1f}% (tool: get_bars).")
        if volr is not None and volr < 1:
            pts.append(f"Volatility is {volr:.2f}× its past-year median: a calmer stretch.")
        return pts or ["The facts give the bull side little to work with."]
    if role == "Bear":
        pts = []
        if ma200 is not None and ma200 <= 0:
            pts.append(f"The close is {ma200:+.1f}% vs its 200-day average (tool: get_bars).")
        if ma50 is not None and ma50 <= 0:
            pts.append(f"The close is {ma50:+.1f}% vs its 50-day average (tool: get_bars).")
        if volr is not None and volr >= 1:
            pts.append(f"Volatility is {volr:.2f}× its past-year median: a stormier stretch.")
        if dd is not None:
            pts.append(f"The worst fall from a high in the last 252 sessions was {dd:.1f}%.")
        return pts or ["The facts give the bear side little to work with."]
    if role == "Risk manager":
        return [("Costs: any rule must be judged after charges and slippage for the market's "
                 "cost profile."),
                "Sample: one instrument and one period; a single strong year can carry a result.",
                ("Trials: every variant the team or you test is counted; judge the grade, "
                 "not the headline.")]
    return []


def fallback_rule(facts: list[str], market: str, as_of: date) -> dict[str, Any]:
    """A simple, testable rule drafted in code from the trend and volatility facts."""
    ma200 = _num(facts, "Close vs 200-day") or 0.0
    if ma200 >= 0:
        text = ("Buy at the next open on the first close above the 50-day average; sell at the "
                "next open when the close is below the 20-day average")
        entry = [{"op": "cross_above", "left": {"kind": "close"}, "right": {"kind": "sma", "n": 50}}]
        exit_ = [{"op": "below", "left": {"kind": "close"}, "right": {"kind": "sma", "n": 20}}]
    else:
        text = ("Buy at the next open when RSI(14) is below 30; sell at the next open when the "
                "close is above the 20-day average")
        entry = [{"op": "below", "left": {"kind": "rsi", "n": 14}, "right": {"kind": "value",
                                                                          "value": 30}}]
        exit_ = [{"op": "above", "left": {"kind": "close"}, "right": {"kind": "sma", "n": 20}}]
    return _spec(text, entry, exit_, market, as_of)


def _spec(text: str, entry: list, exit_: list, market: str, as_of: date) -> dict[str, Any]:
    return {"text": text, "mode": "entry_exit", "entry": entry, "exit": exit_, "origin": "agent",
            "market": market, "notes": [(f"PROPOSED by an agent team, data up to {as_of}; "
                                         "not an order. Test it before you trust it.")]}


def _validate(spec: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from ..backtest import Spec
        Spec.from_dict(spec).validate()
        return spec
    except ImportError:
        return spec
    except (ValueError, TypeError, KeyError, AttributeError):  # SpecError is a ValueError
        return None


# ---------------------------------------------------------------- the team
class Team:
    """An agent team. ``propose`` returns a :class:`Proposal`; nothing can place an order."""

    tools = TOOLS

    def __init__(self, name: str = "builtin", model: str = "local", as_of: Any = None,
                 mask_names: bool = True, budget: dict[str, float] | None = None,
                 requested: str | None = None, warning: str = ""):
        self.name, self.model = name, model
        self.as_of = as_date(as_of)
        self.mask_names = mask_names
        self.budget_caps = {"max_steps": 40, "max_cost": 0.50, **(budget or {})}
        self.requested = requested or name
        self.warning = warning
        self._stop = False
        self._result: Proposal | None = None

    @property
    def title(self) -> str:
        return {"builtin": "Built-in research team"}.get(self.name, self.name)

    @property
    def result(self) -> Proposal | None:
        """The proposal from the last completed ``steps`` run (None while running)."""
        return self._result

    def stop(self) -> None:
        """Ask a running ``propose`` to stop before its next step."""
        self._stop = True

    def _turn(self, role: str, context: str, budget: Budget, tools: Tools,
              fallback: list[str]) -> list[str]:
        if self._stop:
            raise BudgetExceeded("stopped by you")
        budget.take(f"the {role} turn")
        prompt = (f"ROLE: {role}.\nSUBJECT: {tools.alias}. DATA UP TO: "
                  f"{'t-0' if tools.mask else tools.as_of}.\n{ai.fence_untrusted(context)}\n"
                  "Write your part now.")
        out = ai.complete(prompt, section="Research", system=SYSTEM)
        budget.spend(out.cost_usd)
        if out.text.strip():
            return [ln.strip().lstrip("-•* ").strip() for ln in tools.mask_text(out.text).splitlines()
                    if ln.strip()][:6]
        return fallback

    def _rule(self, context: str, budget: Budget, tools: Tools, facts: list[str],
              market: str) -> dict[str, Any]:
        if self._stop:
            raise BudgetExceeded("stopped by you")
        budget.take("the rule proposal")
        prompt = ("ROLE: Rule proposer. Draft ONE testable rule as JSON with keys text, entry, exit. "
                  "Conditions: {\"op\": above|below|cross_above|cross_below, \"left\": {\"kind\": "
                  "close|sma|ema|rsi, \"n\": int}, \"right\": {...} or {\"kind\": \"value\", "
                  "\"value\": number}}. Fill at the next open.\n" + ai.fence_untrusted(context))
        out = ai.complete(prompt, section="Research", system=SYSTEM, schema=RULE_SCHEMA)
        budget.spend(out.cost_usd)
        if out.text.strip():
            try:
                d = ai.extract_json(out.text)
                spec = _validate(_spec(str(d["text"]), d["entry"], d["exit"], market, tools.as_of))
                if spec:
                    return spec
            except (ValueError, TypeError, KeyError):
                tools.log({"kind": "turn", "agent": "Rule proposer",
                           "lines": ["The model's rule could not be read; drafted in code instead."]})
        return fallback_rule(facts, market, tools.as_of)

    def steps(self, symbol: str, market: str = "IN",
              on_event: Callable[[dict[str, Any]], None] | None = None) -> Iterator[dict[str, Any]]:
        """Run the team one step at a time (the Agents screen draws each event)."""
        transcript: list[dict[str, Any]] = []

        def log(ev: dict[str, Any]) -> None:
            transcript.append(ev)
            if on_event:
                on_event(ev)

        budget = Budget(int(self.budget_caps["max_steps"]), float(self.budget_caps["max_cost"]))
        tools = Tools(symbol, market, self.as_of, self.mask_names, log)
        sections: dict[str, list[str]] = {}
        rules: dict[str, Any] | None = None
        stopped = ""
        try:
            budget.take("get_bars")
            facts = tools.get_bars("Technical")
            yield transcript[-1]
            budget.take("get_news")
            news = tools.get_news("News")
            yield transcript[-1]
            budget.take("get_filings")
            filings = tools.get_filings("Fundamentals")
            yield transcript[-1]
            context = "FACTS:\n" + "\n".join(facts + news + filings)
            for role in ROLES[:-1]:
                sections[role] = self._turn(role, context, budget, tools,
                                            _fallback_turn(role, facts, news, filings))
                context += f"\n{role.upper()}:\n" + "\n".join(sections[role])
                log({"kind": "turn", "agent": role, "lines": sections[role]})
                yield transcript[-1]
            rules = self._rule(context, budget, tools, facts, market)
            log({"kind": "turn", "agent": "Rule proposer", "lines": [rules["text"]]})
            yield transcript[-1]
            budget.take("run_backtest")
            test = tools.run_backtest(rules, "Rule proposer")
            own = (f"Grade {test['grade']} on data up to the as-of date (counted as a trial)"
                   if test.get("ok") else f"Backtest not run: {test.get('error', '')}")
            sections["Agent's own test"] = [own]
            yield transcript[-1]
        except BudgetExceeded as exc:
            stopped = str(exc)
            log({"kind": "stop", "agent": "Budget", "lines": [stopped]})
            yield transcript[-1]
        self._result = Proposal(
            symbol=symbol, market=market, as_of=self.as_of, team=self.title,
            note=_note(tools.alias, self.as_of, self.mask_names, sections, rules, stopped),
            rules=rules, cost=round(budget.cost, 4), steps=budget.steps, transcript=transcript,
            mask_names=self.mask_names, stopped=stopped,
            warnings=[self.warning] if self.warning else [], sections=sections)

    def propose(self, symbol: str, market: str = "IN") -> Proposal:
        """Run the team on ``symbol`` and return a note and rules — never an order."""
        self._stop = False
        for _ in self.steps(symbol, market):
            pass
        assert self._result is not None
        return self._result


def _note(alias: str, as_of: date, mask: bool, sections: dict[str, list[str]],
          rules: dict[str, Any] | None, stopped: str) -> str:
    head = f"RESEARCH NOTE · {alias} · data up to {'t-0 (dates hidden)' if mask else as_of}"
    lines = [head, "PROPOSAL · NOT AN ORDER", ""]
    groups = [("Analysts", ("Technical", "News", "Fundamentals")), ("Bull case", ("Bull",)),
              ("Bear case", ("Bear",)), ("Risk", ("Risk manager",)),
              ("Agent's own test", ("Agent's own test",))]
    for title, roles in groups:
        body = [ln for r in roles for ln in sections.get(r, [])]
        if body:
            lines += [title.upper()] + [f"- {ln}" for ln in body] + [""]
    if rules:
        lines += ["PROPOSED RULE (untested by you)", f"- {rules['text']}", ""]
    if stopped:
        lines.append(f"Run stopped: {stopped}.")
    lines.append("Send it to the Strategy Builder and backtest it with costs before you trust it.")
    return "\n".join(lines)


def warn(msg: str) -> None:
    warnings.warn(msg, stacklevel=3)
