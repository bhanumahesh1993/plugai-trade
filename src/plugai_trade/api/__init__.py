"""HTTP API for the React UI. Thin: every number comes from the engine modules.

Run with ``plugai-trade start`` (serves the built UI and this API on one port).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import warnings

from .. import BOOK_EDITION, __version__, ai, config, data, reference

warnings.filterwarnings("ignore", message=".*live sources unavailable.*")
from ..store import default as store

app = FastAPI(title="PlugAI-Trade", version=__version__, docs_url="/api/docs",
              openapi_url="/api/openapi.json")
DIST = Path(__file__).resolve().parent.parent / "web_dist"


def _clean(x: Any) -> Any:
    """JSON-safe: numpy scalars → float, NaN/inf → None, dates → iso."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try:
            x = x.item()
        except Exception:
            return str(x)
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


# ------------------------------------------------------------------ status bar
@app.get("/api/status")
def status() -> dict[str, Any]:
    s = ai.status()
    return {"version": __version__, "edition": BOOK_EDITION, "market": config.get("market", "IN"),
            "ai": s, "as_of": reference.as_of(),
            "data": {"source": "synthetic", "age": "offline sample"}}


class MarketIn(BaseModel):
    market: str


@app.post("/api/market")
def set_market(body: MarketIn) -> dict[str, str]:
    if body.market not in ("IN", "US"):
        raise HTTPException(400, "market must be IN or US")
    config.set_value("market", body.market)
    return {"market": body.market}


# ------------------------------------------------------------------ home
@app.get("/api/clock")
def clock() -> dict[str, Any]:
    out = {}
    for mkt, key, tz in (("IN", "india", "Asia/Kolkata"), ("US", "us", "America/New_York")):
        sess = reference.lookup(f"{key}.sessions.cash") or {}
        now = datetime.now(ZoneInfo(tz))
        op = datetime.combine(now.date(), datetime.strptime(sess.get("open", "09:15"), "%H:%M").time(), ZoneInfo(tz))
        cl = datetime.combine(now.date(), datetime.strptime(sess.get("close", "15:30"), "%H:%M").time(), ZoneInfo(tz))
        weekday = now.weekday() < 5
        state = "open" if weekday and op <= now <= cl else ("pre-open" if weekday and now < op else "closed")
        out[mkt] = {"time": now.strftime("%H:%M"), "tz": tz, "open": sess.get("open"),
                    "close": sess.get("close"), "state": state}
    return out


@app.get("/api/watchlist")
def watchlist(market: str = "IN") -> list[dict[str, Any]]:
    syms = (config.get("watchlists", {}) or {}).get(market, [])
    rows = []
    for s in syms:
        df = data.get(s, market=market, start=date.today() - timedelta(days=60), end=date.today())
        closes = df["close"].to_list()
        if len(closes) < 2:
            continue
        rows.append({"symbol": s, "last": closes[-1], "change": closes[-1] / closes[-2] - 1,
                     "spark": closes[-30:], "source": df["source"][-1]})
    return _clean(rows)


@app.get("/api/bars")
def bars(symbol: str, market: str = "IN", days: int = 250) -> dict[str, Any]:
    df = data.get(symbol, market=market, start=date.today() - timedelta(days=int(days * 1.5)),
                  end=date.today())
    return _clean({"symbol": symbol, "source": df["source"][-1] if df.height else None,
                   "bars": df.select("date", "open", "high", "low", "close", "volume")
                   .tail(days).to_dicts()})


# ------------------------------------------------------------------ options
class LegIn(BaseModel):
    kind: str
    strike: float
    side: str = "buy"
    qty: int = 1
    expiry: str = "weekly"


class OptionsIn(BaseModel):
    symbol: str = "NIFTY"
    market: str | None = None
    legs: list[LegIn]
    days_left: float | None = None


@app.post("/api/options/quote")
def options_quote(body: OptionsIn) -> dict[str, Any]:
    from .. import options
    try:
        legs = [options.leg(body.symbol, kind=lg.kind, strike=lg.strike, expiry=lg.expiry,
                            side=lg.side, qty=lg.qty, market=body.market) for lg in body.legs]
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    strat = options.strategy(legs)
    if body.days_left is not None:
        strat = strat.at(body.days_left)
    single = legs[0] if len(legs) == 1 else None
    tiles = single.tiles().display() if single and body.days_left is None else strat.summary().tiles()
    pay = strat.payoff()
    spot = strat.spot
    em = strat.expected_move()
    greeks = strat.greeks()
    facts = (single.facts() if single else strat.summary().facts())
    return _clean({
        "symbol": strat.symbol, "market": strat.market, "spot": spot, "lot": strat.lot,
        "currency": legs[0].currency, "name": strat.name, "tiles": tiles,
        "payoff": {"spot": list(pay["spot"]), "expiry": list(pay["expiry"]),
                   "now": list(pay["now"])},
        "expected_move": em, "band": [spot - em, spot + em],
        "breakevens": strat.breakevens(), "greeks": greeks, "facts": facts,
        "legs": [{"kind": lg.kind, "strike": lg.strike, "side": lg.side, "qty": lg.qty,
                  "premium": lg.premium, "days": lg.days} for lg in legs],
    })


# ------------------------------------------------------------------ backtest
class BacktestIn(BaseModel):
    idea: str
    symbol: str = "NIFTY"
    market: str = "IN"
    costs: str | None = None
    start: str = "2016-01-01"


@app.post("/api/backtest/run")
def backtest_run(body: BacktestIn) -> dict[str, Any]:
    from .. import backtest
    try:
        spec = backtest.rules(body.idea)
    except Exception as exc:
        raise HTTPException(400, f"Could not read the rule: {exc}") from exc
    bars_df = data.get(body.symbol, market=body.market, start=body.start, end=date.today())
    profile = body.costs or ("IN-equity-delivery" if body.market == "IN" else "US-equity")
    res = backtest.run(spec, bars_df, costs=profile)
    card = res.card()
    eq = res.equity
    peak = [max(eq[: i + 1]) for i in range(len(eq))]
    dd = [e / p - 1 for e, p in zip(eq, peak)]
    return _clean({
        "read_back": spec.read_back(), "cards": spec.cards(), "stats": res.stats(),
        "dates": [d.isoformat() for d in res.dates], "equity": list(eq),
        "benchmark": list(res.benchmark), "drawdown": dd, "trades": res.trades[-50:],
        "card": card.to_dict(), "facts": res.facts(), "trials": res.trial_count(),
        "source": bars_df["source"][-1],
    })


# ------------------------------------------------------------------ paper desk
_desks: dict[str, Any] = {}


def _desk(market: str):
    from ..paper import PaperDesk, Replay, session_bars
    if market not in _desks:
        desk = PaperDesk(market=market, mode="REPLAY", write_journal=False,
                         starting_balance=1_500_000.0 if market == "IN" else 40_000.0)
        sym = "NIFTY FUT" if market == "IN" else "SPY"
        data_sym = "NIFTY" if market == "IN" else "SPY"
        replay = Replay(symbol=sym, bars=session_bars(data_sym, market, interval="1m"))
        replay.step(desk, 30)   # open the session with 30 minutes on the tape
        _desks[market] = {"desk": desk, "replay": replay, "symbol": sym}
    return _desks[market]


def _desk_state(market: str) -> dict[str, Any]:
    d = _desk(market)
    desk = d["desk"]
    return _clean({
        "market": market, "symbol": d["symbol"], "mode": desk.mode, "now": desk.now,
        "cash": desk.cash, "equity": desk.equity(), "day_pnl": desk.day_pnl(),
        "killed": desk.killed, "limits": desk.limits(), "guardrails": desk.guardrail_strip(),
        "orders": [o.__dict__ for o in desk.orders][-20:],
        "positions": [{**p.__dict__, "open_pnl": p.open_pnl()} for p in desk.positions],
        "trades": desk.trades[-20:], "blocked": desk.blocked[-10:],
        "last_bar": desk.last_bar.get(d["symbol"]),
        "tape": d["replay"].visible().tail(120).to_dicts(),
        "pending": store().all("paper_orders", tag="pending")[:20],
    })


@app.get("/api/paper/state")
def paper_state(market: str = "IN") -> dict[str, Any]:
    return _desk_state(market)


class PaperOrderIn(BaseModel):
    market: str = "IN"
    symbol: str
    side: str
    qty: int
    kind: str = "market"
    price: float | None = None
    stop: float | None = None
    target: float | None = None


@app.post("/api/paper/order")
def paper_order(body: PaperOrderIn) -> dict[str, Any]:
    desk = _desk(body.market)["desk"]
    try:
        desk.place_paper_order(body.symbol, body.side, body.qty, kind=body.kind, price=body.price,
                               stop=body.stop, target=body.target)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return _desk_state(body.market)


@app.post("/api/paper/step")
def paper_step(market: str = "IN", n: int = 1) -> dict[str, Any]:
    d = _desk(market)
    if not d["replay"].done:
        d["replay"].step(d["desk"], n)
    return _desk_state(market)


@app.post("/api/paper/kill")
def paper_kill(market: str = "IN") -> dict[str, Any]:
    _desk(market)["desk"].kill_switch()
    return _desk_state(market)


# ------------------------------------------------------------------ AI
class ExplainIn(BaseModel):
    facts: list[str]
    question: str | None = None
    section: str = "Research"


@app.post("/api/explain")
def explain(body: ExplainIn) -> dict[str, Any]:
    class _F:
        def facts(self_inner):
            return body.facts
    out = ai.explain(_F(), body.question, section=body.section)
    return {"text": out.text, "sources": out.sources, "model": out.model, "where": out.where,
            "blocked": out.blocked}


# ------------------------------------------------------------------ static UI
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
