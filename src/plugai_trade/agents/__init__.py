"""Agents (Chapter 30): a research team that proposes rules, never orders.

    from plugai_trade import agents, data, backtest, ai
    team = agents.load("tradingagents", model="local",
                       as_of="2026-05-29", mask_names=True,
                       budget={"max_steps": 40, "max_cost": 0.50})
    prop = team.propose("NIFTY", market="IN")   # a note + rules, never an order
    print(prop.note)                            # bull, bear and risk sections
    res = backtest.run(prop.rules, bars, costs="IN-equity-delivery")

Teams: ``"builtin"`` (the Built-in research team, always available), and the
separate-process plugins ``"tradingagents"`` and ``"ai-hedge-fund"``, used only
when installed from their pinned GitHub tag. If a plugin is not installed,
``load`` explains how to install it and falls back to the built-in team with a
warning. Tools: get_bars, get_news, get_filings, run_backtest — behind an
as-of wall, with names masked, inside a step and cost budget.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import config
from ..store import default as store
from .adapters import ADAPTERS, InstallPlan, install, install_plan, is_installed, pin, run_adapter
from .team import Budget, BudgetExceeded, Proposal, Team, fallback_rule, warn
from .tools import TOOLS, Tools, as_date

TEAMS = {"builtin": "Built-in research team", "tradingagents": "TradingAgents",
         "ai-hedge-fund": "ai-hedge-fund"}

__all__ = ["ADAPTERS", "TEAMS", "TOOLS", "Budget", "BudgetExceeded", "InstallPlan", "PluginTeam",
           "Proposal", "Team", "Tools", "config_path", "fallback_rule", "install", "install_plan",
           "is_installed", "load", "propose_to_builder", "reject", "write_config"]


class PluginTeam(Team):
    """A separate-process agent plugin; the lab still owns tools, rules and the budget."""

    def _turn(self, role, context, budget, tools, fallback):  # type: ignore[override]
        if role != "Technical":
            return super()._turn(role, context, budget, tools, fallback)
        if self._stop:
            raise BudgetExceeded("stopped by you")
        budget.take(f"the {self.title} process")
        facts = [ln for ln in context.splitlines() if ln and not ln.startswith(("FACTS", "<<"))]
        out = run_adapter(self.name, {"facts": facts, "as_of": "t-0" if self.mask_names
                                      else str(self.as_of)}, timeout=600)
        if not out.get("ok"):
            return fallback + [f"{self.title} process: {out.get('error', 'no output')}"]
        return [tools.mask_text(str(x)) for x in out["sections"].get("Analysts", [])][:6] or fallback


def config_path(plugin: str) -> Path:
    """``~/.plugai-trade/agents/<plugin>.toml`` (inside the lab folder)."""
    return config.path("agents", f"{plugin}.toml")


def _col(left: str, comment: str, col: int = 34) -> str:
    return f"{left}{' ' * max(1, col - len(left))}{comment}"


def write_config(plugin: str, model: str = "local", as_of: Any = None, mask_names: bool = True,
                 max_steps: int = 40, max_cost: float = 0.50) -> Path:
    """Write the agent settings file in the book's format (Chapter 30)."""
    process = "in-lab" if plugin == "builtin" else "separate"
    why = "# the Built-in research team" if plugin == "builtin" else "# pinned GitHub tag, not PyPI"
    text = f"""# ~/.plugai-trade/agents/{plugin}.toml  (written by the Agents screen)
[agent]
{_col(f'plugin   = "{plugin}"', why)}
process  = "{process}"
{_col(f'model    = "{model}"', "# routed through Settings › AI Models")}
tools    = [{", ".join(f'"{t}"' for t in TOOLS)}]
as_of    = "{as_date(as_of)}"           # data after this date is invisible
mask_names = {"true" if mask_names else "false"}                 # hide tickers and dates from the model
[budget]
max_steps = {int(max_steps)}
max_cost  = {float(max_cost):.2f}                # USD; the run stops, it does not overrun
[output]
kind = "rule_proposal"            # never an order, never a paper order
"""
    p = config_path(plugin)
    p.write_text(text, encoding="utf-8")
    return p


def load(name: str = "builtin", model: str = "local", as_of: Any = None, mask_names: bool = True,
         budget: dict[str, float] | None = None) -> Team:
    """An agent team. Unknown or uninstalled plugins fall back to the built-in team."""
    key = name.lower().replace("_", "-").replace(" ", "-")
    if key in ("builtin", "built-in", "built-in-research-team"):
        return Team("builtin", model, as_of, mask_names, budget)
    if key not in ADAPTERS:
        raise ValueError(f"unknown team {name!r}; choose one of {', '.join(TEAMS)}")
    if is_installed(key):
        return PluginTeam(key, model, as_of, mask_names, budget)
    a = ADAPTERS[key]
    msg = (f"{a['title']} is not installed. Install it from Automate › Plugins › Install, which "
           f"fetches {a['repo']} at the pinned tag {pin(key)} (never the PyPI package). "
           "Using the Built-in research team instead.")
    warn(msg)
    return Team("builtin", model, as_of, mask_names, budget, requested=key, warning=msg)


def propose_to_builder(prop: Proposal) -> int:
    """Send a proposal's rules to the Strategy Builder: a ``proposals`` row tagged PROPOSED."""
    if not prop.rules:
        raise ValueError("this proposal has no rule to send (the run stopped before drafting one)")
    row = {**prop.to_dict(), "status": "PROPOSED", "spec": prop.rules}
    rid = store().add("proposals", row, tag="PROPOSED")
    store().audit("agent_proposal", {"id": rid, "team": prop.team, "symbol": prop.symbol})
    return rid


def reject(prop: Proposal, reason: str) -> int:
    """Reject a proposal with a one-line reason, kept for the journal."""
    row = {**prop.to_dict(), "status": "REJECTED", "reason": reason,
           "rejected": datetime.now(UTC).date().isoformat()}
    rid = store().add("proposals", row, tag="REJECTED")
    store().add("notes", {"kind": "agent_rejected", "text": f"Rejected agent proposal on "
                          f"{prop.symbol}: {reason}", "proposal_id": rid}, tag="journal")
    return rid
