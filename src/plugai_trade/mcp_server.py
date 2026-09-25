"""PlugAI-Trade's own MCP server (`plugai-trade mcp`, Chapter 6).

Six tools, each READ or PAPER — there is no third kind, because the app has no
order code at all:

    get_watchlist        READ   your watchlists, with the data source and age of each price
    get_journal          READ   journal rows (identifiers stripped), with the query used
    get_backtest         READ   a saved Backtest Report, marked HYPOTHETICAL
    run_backtest         READ   runs a rule on local data with the lab's costs; counts a trial
    get_paper_positions  READ   open paper positions from the Paper Desk
    paper_order          PAPER  a *pending* paper order that waits for Accept in Paper Desk
                                (switch it off in Settings › MCP Server for a read-only session)

Every call is written to the audit log (tag ``mcp``) — the Tool-call log.
The tool functions are plain Python so they can be tested and called directly;
:func:`build_server` registers them with the official ``mcp`` SDK.
"""

from __future__ import annotations

import functools
import importlib
import inspect
import json
import sys
import warnings
from collections.abc import Callable
from datetime import date
from typing import Any

from . import config
from .store import default as store

SERVER_NAME = "plugai-trade"
AUDIT_KIND = "mcp"
TOOLS: dict[str, dict[str, str]] = {
    "get_watchlist": {"tag": "READ",
                      "does": "Returns your watchlist with the data source and age of each price"},
    "get_journal": {"tag": "READ", "does": "Returns journal rows and tags, with the query used"},
    "get_backtest": {"tag": "READ", "does": "Returns a saved Backtest Report, marked HYPOTHETICAL"},
    "run_backtest": {"tag": "READ", "does": "Runs a rule on local data with the lab's costs; "
                                            "computes in code, writes nothing to your account; "
                                            "counts as a trial"},
    "get_paper_positions": {"tag": "READ", "does": "Returns open paper positions from the "
                                                   "Paper Desk"},
    "paper_order": {"tag": "PAPER", "does": "Creates a pending paper order that appears in Paper "
                                            "Desk until you click Accept or Reject"},
}
HIDDEN_JOURNAL_COLUMNS = ("account", "source", "notes_private")
PAPER_SIDES = ("buy", "sell")
PAPER_KINDS = ("market", "limit", "stop", "stop-limit")


def paper_order_enabled() -> bool:
    """The paper_order toggle in Settings › MCP Server (``mcp.paper_order_enabled``)."""
    return bool(config.get("mcp.paper_order_enabled", True))


def set_paper_order_enabled(on: bool) -> None:
    config.set_value("mcp.paper_order_enabled", bool(on))


def claude_desktop_config() -> dict[str, Any]:
    """The block to paste into Claude Desktop's config (Settings → Developer → Edit Config)."""
    return {"mcpServers": {SERVER_NAME: {"command": "plugai-trade", "args": ["mcp"]}}}


def claude_desktop_config_json() -> str:
    return json.dumps(claude_desktop_config(), indent=2)


def tool_log(limit: int = 200) -> list[dict[str, Any]]:
    """The Tool-call log: every MCP call, newest first."""
    return store().all("audit_log", tag=AUDIT_KIND, limit=limit)


def _short(v: Any) -> Any:
    s = json.dumps(v, default=str)
    return v if len(s) <= 300 else s[:300] + "…"


def _audited(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Log every call (time, tool, arguments, result) and never raise into the client."""
    name = fn.__name__
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            called = dict(sig.bind_partial(*args, **kwargs).arguments)
        except TypeError:
            called = dict(kwargs)
        try:
            out = fn(*args, **kwargs)
            result = out.get("status", "ok")
        except Exception as exc:  # report, do not crash the server
            out = {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            result = "error"
        store().audit(AUDIT_KIND, {"tool": name, "tool_tag": TOOLS[name]["tag"],
                                   "args": {k: _short(v) for k, v in called.items()},
                                   "result": result})
        return out
    return wrapper


def _module(name: str) -> Any | None:
    try:
        return importlib.import_module(f"plugai_trade.{name}")
    except Exception:
        return None


# ---------------------------------------------------------------- READ tools
@_audited
def get_watchlist(market: str = "") -> dict[str, Any]:
    """Your watchlists with the last close, its date, the data source and its age in days."""
    from . import data
    markets = [market.upper()] if market else ["IN", "US"]
    lists = config.get("watchlists", {}) or {}
    saved = {m: [s for r in store().all("watchlists", tag=m) for s in r.get("symbols", [])]
             for m in markets}
    out: dict[str, list[dict[str, Any]]] = {}
    for m in markets:
        rows = []
        for sym in dict.fromkeys(list(lists.get(m, [])) + saved.get(m, [])):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    df = data.get(sym, market=m)
                last = df.tail(1).to_dicts()[0]
                d = last["date"]
                rows.append({"symbol": sym, "last_close": round(float(last["close"]), 2),
                             "date": str(d), "source": last.get("source", ""),
                             "age_days": (date.today() - d).days})
            except Exception as exc:
                rows.append({"symbol": sym, "error": str(exc)[:120]})
        out[m] = rows
    return {"status": "ok", "watchlists": out}


@_audited
def get_journal(market: str = "", symbol: str = "", limit: int = 50) -> dict[str, Any]:
    """Journal rows and tags (account numbers and file names stripped), with the query used."""
    mod = _module("journal")
    if mod is None:
        return {"status": "not available", "error": "The journal module is not available."}
    t = mod.trades(market.upper() or None)
    query = ["SELECT * FROM journal"]
    conds = []
    if market:
        conds.append(f"market = '{market.upper()}'")
    if symbol and t.height:
        import polars as pl
        t = t.filter(pl.col("symbol").str.contains(symbol.upper(), literal=True)
                     | pl.col("underlying").str.contains(symbol.upper(), literal=True))
        conds.append(f"symbol LIKE '%{symbol.upper()}%'")
    if conds:
        query.append("WHERE " + " AND ".join(conds))
    limit = max(1, min(int(limit), 500))
    query.append(f"ORDER BY entry_time DESC LIMIT {limit}")
    keep = [c for c in t.columns if c not in HIDDEN_JOURNAL_COLUMNS]
    rows = t.select(keep).tail(limit).reverse().to_dicts() if t.height else []
    return {"status": "ok", "query": " ".join(query), "rows": json.loads(json.dumps(rows,
                                                                                    default=str)),
            "count": len(rows)}


@_audited
def get_backtest(backtest_id: int = 0) -> dict[str, Any]:
    """A saved Backtest Report (the latest when no id is given), marked HYPOTHETICAL."""
    st = store()
    row = st.get("backtests", backtest_id) if backtest_id else next(iter(st.all("backtests",
                                                                                limit=1)), None)
    if row is None:
        return {"status": "ok", "label": "HYPOTHETICAL", "report": None,
                "note": "No saved Backtest Report yet. Save one in Strategy › Backtest Report."}
    return {"status": "ok", "label": "HYPOTHETICAL", "report": json.loads(json.dumps(row,
                                                                                     default=str))}


@_audited
def run_backtest(rules: str, symbol: str = "NIFTY", market: str = "IN", start: str = "",
                 end: str = "", costs: str = "") -> dict[str, Any]:
    """Run a plain-English rule on local data with the lab's costs. Counts as a trial."""
    bt = _module("backtest")
    if bt is None or not hasattr(bt, "run"):
        return {"status": "not available",
                "error": "The backtest module is not available in this build."}
    from . import data
    mkt = market.upper() or "IN"
    profile = costs or ("IN-equity-delivery" if mkt == "IN" else "US-equity")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bars = data.get(symbol, market=mkt, start=start or None, end=end or None)
    res = bt.run(rules, bars, costs=profile, symbol=symbol)
    return {"status": "ok", "label": "HYPOTHETICAL", "facts": list(res.facts())}


@_audited
def get_paper_positions() -> dict[str, Any]:
    """Open paper positions mirrored from the Paper Desk."""
    rows = store().all("paper_positions", tag="open")
    return {"status": "ok", "label": "PAPER", "positions": json.loads(json.dumps(rows,
                                                                                 default=str))}


# ---------------------------------------------------------------- PAPER tool
@_audited
def paper_order(symbol: str, side: str, qty: int, market: str = "IN", kind: str = "market",
                price: float | None = None, stop: float | None = None,
                target: float | None = None, note: str = "") -> dict[str, Any]:
    """Create a PENDING paper order. It waits in Paper Desk until you click Accept or Reject.

    Nothing is filled, and nothing ever reaches a broker: PlugAI-Trade has no order code.
    """
    if not paper_order_enabled():
        return {"status": "refused", "error": "paper_order is switched off in Settings › MCP "
                                              "Server. This session is read-only."}
    side, kind = side.lower().strip(), (kind or "market").lower().strip()
    if side not in PAPER_SIDES or kind not in PAPER_KINDS or int(qty) <= 0 or not symbol:
        return {"status": "refused",
                "error": f"Need a symbol, side in {PAPER_SIDES}, kind in {PAPER_KINDS}, qty > 0."}
    order = {"symbol": symbol.upper(), "market": market.upper() or "IN", "side": side,
             "qty": int(qty), "kind": kind, "price": price, "stop": stop, "target": target,
             "note": note}
    pending = _module("paper.pending")
    if pending is not None and hasattr(pending, "draft_pending"):
        row_id = pending.draft_pending(order, source="MCP paper_order")
    else:
        row_id = store().add("paper_orders", {**order, "source": "MCP paper_order",
                                              "status": "PENDING"}, tag="pending")
    return {"status": "ok", "label": "PAPER", "pending_order_id": row_id,
            "note": "Pending paper order created. Open Paper Trading › Paper Desk and click "
                    "Accept or Reject. It is not an order at any broker."}


READ_TOOLS = (get_watchlist, get_journal, get_backtest, run_backtest, get_paper_positions)


def build_server(include_paper: bool | None = None) -> Any:
    """The MCP server with READ tools, plus paper_order when it is switched on."""
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:  # pragma: no cover - mcp 1.x
        from mcp.server.fastmcp import FastMCP as Server
    from mcp.types import ToolAnnotations
    srv = Server(SERVER_NAME, instructions=(
        "PlugAI-Trade lab: READ tools and one PAPER tool. There is no tool that places, "
        "modifies or cancels a real order. Quote numbers exactly as returned."))
    for fn in READ_TOOLS:
        srv.tool(name=fn.__name__, description=f"[READ] {TOOLS[fn.__name__]['does']}",
                 annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))(fn)
    if paper_order_enabled() if include_paper is None else include_paper:
        srv.tool(name="paper_order", description=f"[PAPER] {TOOLS['paper_order']['does']}",
                 annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                             openWorldHint=False))(paper_order)
    return srv


def main() -> None:
    """Run the stdio MCP server (`plugai-trade mcp`)."""
    print("PlugAI-Trade MCP server (stdio) — READ + PAPER tools only; no real orders.",
          file=sys.stderr)
    build_server().run("stdio")
