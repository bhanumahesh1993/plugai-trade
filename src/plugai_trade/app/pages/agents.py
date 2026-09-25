"""Automate › Agents — a research team that proposes rules, never orders (Chapter 30).

Team picker (Built-in research team / TradingAgents / ai-hedge-fund), market and
subject, As-of date, Mask names, Budget (max steps, max cost), Run / Stop, the
Transcript with tool-call chips, and the Proposal card "PROPOSAL · NOT AN ORDER"
with Send to Strategy Builder or Reject.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from plugai_trade import agents
from plugai_trade.app import ui

SECTION = "Automate"
TEAM_KEYS = {"Built-in research team": "builtin", "TradingAgents": "tradingagents",
             "ai-hedge-fund": "ai-hedge-fund"}
DEFAULT_SYMBOL = {"IN": "NIFTY", "US": "SPY"}


def _chip(ev: dict) -> None:
    """One transcript line: an agent turn, or a tool call as a clickable chip."""
    if ev["kind"] == "tool":
        mark = "✓" if ev.get("ok") else "✗"
        with st.expander(f"`{ev['tool']} {mark}` · {ev['agent']} — {ev['summary']}"):
            st.caption(f"Arguments: {ev['args']}")
            st.code("\n".join(ev.get("data") or ["(nothing returned)"]), language=None)
    elif ev["kind"] == "stop":
        st.error(f"⏹ {ev['lines'][0]}")
    else:
        st.markdown(f"**{ev['agent']}**")
        for ln in ev.get("lines", []):
            st.markdown(f"- {ln}")


def _controls(mkt: str) -> dict:
    c1, c2 = st.columns([1.3, 1])
    team = c1.radio("Team", list(TEAM_KEYS), key="ag_team", horizontal=True)
    key = TEAM_KEYS[team]
    if key != "builtin" and not agents.is_installed(key):
        c1.caption(f"{team} is not installed: Automate › Plugins › Install fetches the official "
                   f"GitHub repository at a pinned tag. Until then the Built-in research team runs.")
    symbol = c2.text_input("Subject", DEFAULT_SYMBOL.get(mkt, "NIFTY"), key=f"ag_sym_{mkt}")
    c3, c4, c5, c6 = st.columns(4)
    as_of = c3.date_input("As-of date", date(2026, 5, 29), key="ag_asof",
                          help="Tools return data only up to this date.")
    mask = c4.toggle("Mask names", value=True, key="ag_mask",
                     help="The team sees 'Index A' and relative dates instead of the name.")
    steps = c5.number_input("Budget: max steps", 1, 200, 40, key="ag_steps")
    cost = c6.number_input("Budget: max cost (USD)", 0.0, 50.0, 0.50, step=0.10, key="ag_cost")
    st.caption("With a local model the cost line shows ₹0 / $0 and the step limit does the work.")
    return {"key": key, "symbol": symbol.strip().upper(), "as_of": as_of, "mask": mask,
            "steps": int(steps), "cost": float(cost), "market": mkt}


def _run(cfg: dict, box) -> None:
    agents.write_config(cfg["key"], model="local", as_of=cfg["as_of"], mask_names=cfg["mask"],
                        max_steps=cfg["steps"], max_cost=cfg["cost"])
    team = agents.load(cfg["key"], model="local", as_of=cfg["as_of"], mask_names=cfg["mask"],
                       budget={"max_steps": cfg["steps"], "max_cost": cfg["cost"]})
    if team.warning:
        st.warning(team.warning)
    events: list[dict] = []
    st.session_state["ag_events"] = events
    with box:
        for ev in team.steps(cfg["symbol"], cfg["market"]):
            events.append(ev)
            _chip(ev)
    st.session_state["ag_prop"] = team.result
    st.session_state.pop("ag_sent", None)


def _proposal(prop: agents.Proposal) -> None:
    with st.container(border=True):
        st.markdown("**PROPOSAL · NOT AN ORDER**")
        if prop.rules:
            st.markdown(f"**Rule:** {prop.rules['text']}")
        bulls, bears = len(prop.sections.get("Bull", [])), len(prop.sections.get("Bear", []))
        risks = len(prop.sections.get("Risk manager", []))
        st.caption(f"Bull {bulls} points · Bear {bears} points · Risk: {risks} objections · "
                   f"Steps {prop.steps} · Cost ${prop.cost:.2f} · Trials +{prop.trials_added} (agent's own tests)")
        with st.expander("Research note"):
            st.text(prop.note)
        st.caption("Untested by you. Send to the backtester to grade.")
    ui.ai_block(prop, "ag_prop_ai", section="Research")
    c1, c2 = st.columns([1.2, 2])
    if c1.button("Send to Strategy Builder", type="primary", key="ag_send",
                 disabled=not prop.rules or bool(st.session_state.get("ag_sent"))):
        rid = agents.propose_to_builder(prop)
        st.session_state["ag_sent"] = rid
        st.session_state["strategy_builder_spec"] = prop.rules
    if st.session_state.get("ag_sent"):
        st.success(f"Sent as proposal #{st.session_state['ag_sent']}, tagged PROPOSED. Open "
                   "Strategy › Strategy Builder: Read back in English, Chart check, Backtest.")
    reason = c2.text_input("Reason (one line, for the journal)", key="ag_reason")
    if c2.button("Reject", key="ag_reject", disabled=not reason.strip()):
        agents.reject(prop, reason.strip())
        st.session_state.pop("ag_prop", None)
        st.info("Rejected; the reason went to your journal.")


def render() -> None:
    ui.page_header("Agents", SECTION, "A research team writes notes and proposes rules. "
                   "It has no order tool, no keys and no Accept button.")
    cfg = _controls(ui.market())
    b1, b2, _ = st.columns([1, 1, 4])
    run = b1.button("Run", type="primary", key="ag_run")
    if b2.button("Stop", key="ag_stop"):
        st.session_state["ag_stopped"] = True
        st.warning("Stopped. The run ends at once; nothing after this step was called.")
    left, right = st.columns([1.3, 1])
    with left:
        st.markdown("**Transcript**")
        box = st.container()
        if run:
            st.session_state["ag_stopped"] = False
            _run(cfg, box)
        else:
            with box:
                for ev in st.session_state.get("ag_events", []):
                    _chip(ev)
        if not st.session_state.get("ag_events"):
            st.caption("Click Run. Each agent's turn appears here, and every tool call as a chip "
                       "you can open to see exactly what data came back.")
    with right:
        prop = st.session_state.get("ag_prop")
        if prop:
            _proposal(prop)
        else:
            st.caption("The Proposal card appears here after a run.")
    st.caption("Tools: get_bars · get_news · get_filings · run_backtest. Agent backtests count "
               "as trials. Paper only — nothing here can place an order.")
