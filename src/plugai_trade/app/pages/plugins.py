"""Automate › Plugins — New from template, Open folder, Run checks, Run, Enable, Install.

Plugins are folders under ``<lab>/plugins`` (Chapter 27). The Plugin check must
pass before a plugin can run or be enabled; plugins run in their own process and
never receive keys. Agent plugins (Chapter 30) are installed from their official
GitHub repository at a pinned tag, with the allowed tools listed first.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import agents, plugin
from plugai_trade.app import ui

SECTION = "Automate"
KIND_LABELS = {"Screen": "screen", "Strategy": "strategy", "Report": "report"}


def _open_folder(path) -> None:
    st.code(str(path), language=None)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        st.caption("Open this path in your editor (Cursor or VS Code) or start your coding agent there.")


def _new_panel() -> None:
    with st.container(border=True):
        c1, c2, c3 = st.columns([1, 1.4, 1])
        kind = c1.selectbox("Template", list(KIND_LABELS), index=2, key="pl_kind")
        name = c2.text_input("Name", "gap_report", key="pl_name")
        c3.write("")
        if c3.button("New from template", type="primary", key="pl_new"):
            try:
                st.success(plugin.new(name.strip(), KIND_LABELS[kind]))
            except ValueError as exc:
                st.error(str(exc))
        st.caption("Terminal: `plugai-trade plugin new gap_report --kind report`. The folder holds "
                   "plugin.toml, plugin.py, tests/ and AGENTS.md.")


def _plugin_row(name: str) -> None:
    try:
        m = plugin.manifest(name)
    except (OSError, ValueError) as exc:  # TOMLDecodeError is a ValueError
        st.error(f"{name}: cannot read plugin.toml ({exc})")
        return
    s = plugin.status(name)
    net = ", ".join(m.get("network", [])) or "none"
    c1, c2, c3 = st.columns([2.2, 1.3, 0.8])
    c1.markdown(f"**{name}**  \n{m.get('kind')} · {', '.join(m.get('markets', []))} · network: {net}")
    if s.get("checked"):
        if s.get("passed"):
            c2.success("✓ checks passed")
        else:
            n = s.get("red_flags", 0)
            c2.error(f"✗ {n} red flag{'s' if n != 1 else ''}")
    else:
        c2.caption("not checked yet")
    c3.markdown("**Enabled**" if s.get("enabled") else ("Blocked" if s.get("checked") and
                                                          not s.get("passed") else "Off"))


def _run_panel(name: str) -> None:
    mkt = ui.market()
    c1, c2, c3 = st.columns(3)
    symbol = c1.text_input("Symbol", {"IN": "NIFTY", "US": "SPY"}.get(mkt, "NIFTY"),
                           key=f"pl_sym_{mkt}")
    start = c2.date_input("From", date(2024, 6, 1), key="pl_start")
    end = c3.date_input("To", date(2026, 5, 29), key="pl_end")
    if st.button("Run", key="pl_run"):
        try:
            st.session_state["pl_result"] = plugin.run(name, symbol.strip().upper(), mkt,
                                                       start=start, end=end)
        except (PermissionError, ValueError, RuntimeError) as exc:
            st.error(str(exc))
    res = st.session_state.get("pl_result")
    if not res or res.name != name:
        return
    st.dataframe(res.table.to_pandas(), width="stretch", hide_index=True, height=260)
    if res.backtest is not None:
        eq = pd.DataFrame({"date": res.backtest.dates, "equity": res.backtest.equity})
        ch = alt.Chart(eq).mark_line().encode(x=alt.X("date:T", title=None),
                                              y=alt.Y("equity:Q", title=None,
                                                      scale=alt.Scale(zero=False)))
        st.altair_chart(ui.hypothetical_chart(ch.properties(height=220)), width="stretch")
        st.caption(f"Report Card grade: {res.backtest.card().grade} · HYPOTHETICAL · fills at the "
                   "next open, costs on")
    ui.ai_block(res, f"pl_ai_{name}", section=SECTION)


def _selected_panel(names: list[str]) -> None:
    name = st.selectbox("Plugin", names, key="pl_sel")
    if not name:
        return
    b = st.columns(4)
    if b[0].button("Open folder", key="pl_open"):
        _open_folder(plugin.folder(name))
    if b[1].button("Run checks", key="pl_check"):
        with st.spinner("Running tests and scans…"):
            st.session_state["pl_report"] = plugin.check(name)
    if b[2].button("Enable", type="primary", key="pl_enable",
                   disabled=not plugin.status(name).get("passed")):
        st.success(plugin.enable(name))
    if b[3].button("Disable", key="pl_disable", disabled=not plugin.status(name).get("enabled")):
        st.info(plugin.enable(name, on=False))
    rep = st.session_state.get("pl_report")
    if rep is not None and rep.name == name:
        st.markdown(f"**PLUGIN CHECK · {name}**")
        st.code(rep.text(), language=None)
    if plugin.status(name).get("passed"):
        _run_panel(name)
    else:
        st.caption("Run checks until every line is green; a plugin that fails is never run.")


def _install_panel() -> None:
    st.markdown("**Agent plugins** (Chapter 30)")
    for key, a in agents.ADAPTERS.items():
        with st.container(border=True):
            plan = agents.install_plan(key)
            done = agents.is_installed(key)
            st.markdown(f"**{a['title']}** · {a['licence']} · pinned tag `{plan.tag}` · "
                        f"{'installed' if done else 'not installed'}")
            st.caption("Allowed tools: " + ", ".join(plan.tools) +
                       ". There is no order or paper-order tool.")
            with st.expander("What Install will do"):
                st.code(plan.text(), language=None)
            if st.button("Install", key=f"pl_install_{key}", disabled=done):
                with st.spinner("Fetching the official repository at the pinned tag…"):
                    st.info(agents.install(key))


def render() -> None:
    ui.page_header("Plugins", SECTION, "Your code, under the lab's rules: checked, contained, "
                   "no keys, no order code.")
    _new_panel()
    names = plugin.installed()
    st.markdown("**YOUR PLUGINS**")
    if not names:
        st.caption("No plugins yet. Click New from template.")
    for n in names:
        _plugin_row(n)
    if names:
        st.divider()
        _selected_panel(names)
    st.divider()
    _install_panel()
    ui.paper_only_note()
