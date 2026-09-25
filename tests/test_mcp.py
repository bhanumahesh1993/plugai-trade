"""Settings › MCP Server: READ + PAPER tools only, audit log, paper_order toggle."""

import asyncio
import json

from plugai_trade import mcp_server
from plugai_trade.store import default as store

ORDER_WORDS = ("place", "modify", "cancel", "gtt", "real", "live", "broker", "submit", "execute")


def _names(srv) -> list[str]:
    return [t.name for t in asyncio.run(srv.list_tools())]


def test_only_read_and_paper_tools_exist():
    names = _names(mcp_server.build_server(include_paper=True))
    assert names == ["get_watchlist", "get_journal", "get_backtest", "run_backtest",
                     "get_paper_positions", "paper_order"]
    assert {t["tag"] for t in mcp_server.TOOLS.values()} == {"READ", "PAPER"}
    for n in names:
        assert not any(w in n for w in ORDER_WORDS), n
    public = [a for a in dir(mcp_server) if not a.startswith("_")]
    assert not any(w in a.lower() for a in public for w in ("place_order", "modify_order",
                                                             "cancel_order", "real_order"))


def test_paper_order_toggle_removes_the_tool_and_refuses():
    mcp_server.set_paper_order_enabled(False)
    assert "paper_order" not in _names(mcp_server.build_server())
    out = mcp_server.paper_order(symbol="NIFTY", side="buy", qty=65)
    assert out["status"] == "refused"
    assert store().count("paper_orders", tag="pending") == 0
    mcp_server.set_paper_order_enabled(True)
    assert "paper_order" in _names(mcp_server.build_server())


def test_paper_order_creates_pending_row_waiting_for_accept():
    mcp_server.set_paper_order_enabled(True)
    out = mcp_server.paper_order(symbol="nifty", side="BUY", qty=65, market="IN",
                                 note="from Claude")
    assert out["status"] == "ok" and out["label"] == "PAPER"
    row = store().get("paper_orders", out["pending_order_id"])
    assert row["tag"] == "pending" and row["status"] == "PENDING"
    assert row["symbol"] == "NIFTY" and row["side"] == "buy" and row["qty"] == 65
    bad = mcp_server.paper_order(symbol="NIFTY", side="short-sell-live", qty=1)
    assert bad["status"] == "refused"


def test_every_call_is_in_the_tool_call_log():
    mcp_server.get_paper_positions()
    mcp_server.get_backtest()
    mcp_server.get_journal(market="IN", symbol="NIFTY")
    log = mcp_server.tool_log()
    assert [r["tool"] for r in log[:3]] == ["get_journal", "get_backtest", "get_paper_positions"]
    assert log[0]["args"] == {"market": "IN", "symbol": "NIFTY"} and log[0]["tool_tag"] == "READ"
    assert all(r["kind"] == "mcp" for r in log)


def test_read_tools_return_data_offline():
    wl = mcp_server.get_watchlist(market="IN")
    assert wl["status"] == "ok"
    assert {r["symbol"] for r in wl["watchlists"]["IN"]} >= {"NIFTY", "BANKNIFTY", "SENSEX"}
    j = mcp_server.get_journal()
    assert j["query"].startswith("SELECT") and j["count"] == 0
    bt = mcp_server.get_backtest()
    assert bt["label"] == "HYPOTHETICAL" and bt["report"] is None
    store().add("paper_positions", {"symbol": "SPY", "qty": 1}, tag="open")
    assert mcp_server.get_paper_positions()["positions"][0]["symbol"] == "SPY"


def test_run_backtest_counts_a_trial_and_degrades_without_module(monkeypatch):
    out = mcp_server.run_backtest(rules="Buy at the next open on the first close above the "
                                        "50-day average; sell at the next open when the close "
                                        "is below the 20-day average")
    assert out["status"] == "ok" and out["label"] == "HYPOTHETICAL"
    assert any("Trials in this family" in f for f in out["facts"])
    monkeypatch.setattr(mcp_server, "_module", lambda name: None)
    missing = mcp_server.run_backtest(rules="anything")
    assert missing["status"] == "not available"


def test_errors_are_returned_not_raised():
    out = mcp_server.run_backtest(rules="this is not a rule at all")
    assert out["status"] in ("error", "ok")
    assert mcp_server.tool_log()[0]["tool"] == "run_backtest"


def test_claude_desktop_config_uses_plugai_trade_mcp():
    cfg = json.loads(mcp_server.claude_desktop_config_json())
    assert cfg == {"mcpServers": {"plugai-trade": {"command": "plugai-trade", "args": ["mcp"]}}}
