"""Settings › MCP Server (Chapter 6): READ and PAPER tools only — no real-order tool exists."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from plugai_trade import mcp_server
from plugai_trade.app import ui

SECTION = "Settings"


def _tools() -> None:
    on = mcp_server.paper_order_enabled()
    rows = [{"Tool": name, "Tag": t["tag"], "What it does": t["does"],
             "Offered": "yes" if name != "paper_order" or on else "switched off"}
            for name, t in mcp_server.TOOLS.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption("READ tools look at your data. PAPER creates a pending paper order that waits in "
               "Paper Trading › Paper Desk for your Accept or Reject. There is no third kind: the "
               "app has no order code, so a real order has nowhere to go.")
    new = st.toggle("paper_order", value=on, key="mcp_paper_toggle",
                    help="Switch off for a strictly read-only session. Restart Claude Desktop "
                         "after changing it so the tool list refreshes.")
    if new != on:
        mcp_server.set_paper_order_enabled(new)
        st.rerun()


def _config() -> None:
    if st.button("Copy config for Claude Desktop", key="mcp_copy", type="primary"):
        st.session_state["mcp_show_cfg"] = True
    if st.session_state.get("mcp_show_cfg"):
        st.code(mcp_server.claude_desktop_config_json(), language="json")
        st.caption("Use the copy icon on the block. In Claude Desktop open Settings → Developer → "
                   "Edit Config, paste it beside any broker entry already there, save, and "
                   "restart Claude Desktop. It starts the server with `plugai-trade mcp` — the "
                   "same command you can run in a terminal.")
    st.info("ChatGPT's developer-mode connectors need a public HTTPS address. That suits "
            "broker-hosted servers, not a program on your laptop — use Claude Desktop for this "
            "lab.")


def _log() -> None:
    with st.expander("Tool-call log", expanded=False):
        rows = mcp_server.tool_log()
        if not rows:
            st.caption("Every button the assistant presses appears here with time, tool and "
                       "arguments.")
            return
        st.dataframe(pd.DataFrame([{"Time": r["created"][:19].replace("T", " "),
                                    "Tool": r.get("tool"), "Tag": r.get("tool_tag"),
                                    "Arguments": json.dumps(r.get("args", {}), ensure_ascii=False),
                                    "Result": r.get("result")} for r in rows]),
                     hide_index=True, use_container_width=True)


def render() -> None:
    ui.page_header("MCP Server", SECTION, "Use Claude Desktop as a front end to your journal, "
                                          "backtests and paper desk.")
    ui.paper_only_note()
    _tools()
    st.divider()
    _config()
    _log()
