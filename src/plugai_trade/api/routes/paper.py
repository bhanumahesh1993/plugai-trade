"""API routes: Paper Trading › Paper Desk. Paper only: nothing here can reach a broker.

One desk per market (kept in this process, like the classic page's session state).
Every number comes from ``plugai_trade.paper``; routes only pass inputs through.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import config
from ...store import default as store
from .. import clean as _clean

router = APIRouter()
DEFAULT_RULE = ("Buy at the next open on the first close above the 20-day average; sell at the "
                "next open when the close is below the 20-day average")

# ------------------------------------------------------------------ per-market desk state
_desks: dict[str, dict[str, Any]] = {}


def _account(market: str) -> float:
    acct = (config.get("sizing.account", {}) or {}).get(market)
    return float(acct or (1_500_000.0 if market == "IN" else 40_000.0))


def _load_replay(d: dict[str, Any], symbol: str, day: date, interval: str, warm: int = 0) -> None:
    from ...paper import Replay, instrument, session_bars
    inst = instrument(symbol, d["market"])
    bars = session_bars(inst.data_symbol, d["market"], day, interval)
    d.update(replay=Replay(symbol, bars, d.get("speed", 1)), symbol=symbol, day=day.isoformat(),
             interval=interval)
    if warm:
        d["replay"].step(d["desk"], warm)
        d["desk"].sync_store()


def _desk(market: str) -> dict[str, Any]:
    from ...paper import PaperDesk, default_symbols
    from ...paper.replay import last_session
    if market not in ("IN", "US"):
        raise HTTPException(400, "Market must be IN or US.")
    if market not in _desks:
        desk = PaperDesk(market, _account(market), mode="REPLAY")
        d = {"market": market, "desk": desk, "session": "Replay", "speed": 1, "drift": None}
        _desks[market] = d
        # Open on the last session with the first half hour already on the tape.
        _load_replay(d, default_symbols(market)[0], last_session(market), "5m", warm=6)
    return _desks[market]


def _order(o: Any) -> dict[str, Any]:
    return {"id": o.id, "symbol": o.symbol, "side": o.side, "qty": o.qty, "kind": o.kind,
            "price": o.price, "stop": o.stop, "target": o.target, "status": o.status,
            "filled_qty": o.filled_qty, "avg_fill": o.avg_fill, "reason": o.reason,
            "purpose": o.purpose, "unplanned": o.unplanned, "placed_at": o.placed_at,
            "plan_id": o.plan_id, "source": o.source}


def _pending_rows(market: str) -> list[dict[str, Any]]:
    from ...paper import pending
    out = []
    for r in pending(market):
        strat = r.get("strategy") or {}
        out.append({**r, "multi_leg": bool(strat.get("legs")) or not r.get("symbol"),
                    "strategy_name": strat.get("name"), "legs": strat.get("legs") or []})
    return out


def _state(market: str) -> dict[str, Any]:
    from ...paper import default_symbols, live_status, load_ticket
    from ...plans import all_plans
    d = _desk(market)
    desk, rp = d["desk"], d["replay"]
    live_ok, live_src = live_status()
    vis = rp.visible()
    ok, why = desk.guardrail_check()
    t = load_ticket()
    t = t if t and (t.get("market") or market) == market else None
    insts = {s: desk.inst(s) for s in {*default_symbols(market), *(p.symbol for p in desk.positions)}}
    return _clean({
        "market": market, "symbol": d["symbol"], "mode": desk.mode, "session": d["session"],
        "now": desk.now, "cash": desk.cash, "equity": desk.equity(), "day_pnl": desk.day_pnl(),
        "realised": desk.realised, "starting_balance": desk.starting_balance,
        "killed": desk.killed, "limits": desk.limits(), "guardrails": desk.guardrail_strip(),
        "blocked_now": None if ok else why,
        "live": {"ok": live_ok, "source": live_src},
        "replay": {"symbol": rp.symbol, "day": d["day"], "interval": d["interval"],
                   "speed": rp.speed, "cursor": rp.cursor, "total": rp.bars.height, "done": rp.done},
        "symbols": default_symbols(market),
        "instruments": {s: {"lot": i.lot, "kind": i.kind, "half_spread": i.half_spread,
                            "slippage": i.slippage, "cur": i.cur} for s, i in insts.items()},
        "orders": [_order(o) for o in desk.orders][-30:],
        "working": [_order(o) for o in desk.open_orders()],
        "positions": [{**p.__dict__, "open_pnl": p.open_pnl(),
                       "funding_rate": desk.funding_rate.get(p.symbol, 0.0001)
                       if p.symbol.endswith("-PERP") else None} for p in desk.positions],
        "trades": desk.trades[-50:], "blocked": desk.blocked[-20:],
        "funding_log": desk.funding_log[-20:],
        "last_bar": desk.last_bar.get(d["symbol"]),
        "last_prices": {s: b.get("close") for s, b in desk.last_bar.items()},
        "tape": vis.tail(150).to_dicts() if vis.height else [],
        "pending": _pending_rows(market),
        "ticket": t,
        "plans": [{"id": p.id, "name": p.name} for p in all_plans(market)],
        "drift": d.get("drift"),
        "handoff": d.get("handoff"),
    })


@router.get("/api/paper/state")
def paper_state(market: str = "IN") -> dict[str, Any]:
    return _state(market)


# ------------------------------------------------------------------ session: LIVE / Replay
class SessionIn(BaseModel):
    market: str = "IN"
    session: str = "Replay"      # LIVE | Replay


@router.post("/api/paper/session")
def paper_session(body: SessionIn) -> dict[str, Any]:
    from ...paper import live_status
    d = _desk(body.market)
    if body.session == "LIVE":
        ok, src = live_status()
        if not ok:
            raise HTTPException(400, f"LIVE unavailable: {src}. Use Replay instead.")
        d["desk"].mode, d["session"] = "PAPER", "LIVE"
    else:
        d["desk"].mode, d["session"] = "REPLAY", "Replay"
    return _state(body.market)


class ReplayIn(BaseModel):
    market: str = "IN"
    symbol: str
    day: str | None = None
    interval: str = "5m"
    speed: int = 1
    fills: list[dict[str, Any]] | None = None   # Journal › Trades › Replay: your fills that day
    source: str | None = None


@router.post("/api/paper/replay")
def paper_replay(body: ReplayIn) -> dict[str, Any]:
    from ...paper import SPEEDS
    from ...paper.replay import last_session
    d = _desk(body.market)
    if body.interval not in ("1m", "5m", "15m", "1d"):
        raise HTTPException(400, "Bars must be 1m, 5m, 15m or 1d.")
    if body.speed not in SPEEDS.values():
        raise HTTPException(400, "Speed must be 1, 5 or 20.")
    try:
        day = date.fromisoformat(body.day) if body.day else last_session(body.market)
    except ValueError as exc:
        raise HTTPException(400, "Session must be a date like 2026-09-24.") from exc
    d["speed"] = body.speed
    d["desk"].mode, d["session"] = "REPLAY", "Replay"
    try:
        _load_replay(d, body.symbol.strip().upper(), day, body.interval)
    except Exception as exc:
        raise HTTPException(400, f"No bars for {body.symbol} on {day}: {exc}") from exc
    d["handoff"] = ({"day": day.isoformat(), "source": body.source or "Journal › Trades",
                     "fills": body.fills} if body.fills is not None else None)
    return _state(body.market)


@router.post("/api/paper/speed")
def paper_speed(market: str = "IN", speed: int = 1) -> dict[str, Any]:
    from ...paper import SPEEDS
    if speed not in SPEEDS.values():
        raise HTTPException(400, "Speed must be 1, 5 or 20.")
    d = _desk(market)
    d["speed"] = d["replay"].speed = speed
    return _state(market)


@router.post("/api/paper/step")
def paper_step(market: str = "IN", n: int | None = None, to_end: bool = False) -> dict[str, Any]:
    """Next bar(s) at the replay speed; ``to_end`` feeds the rest of the session."""
    d = _desk(market)
    rp = d["replay"]
    if not rp.done:
        rp.step(d["desk"], rp.bars.height if to_end else n)
        d["desk"].sync_store()
    return _state(market)


# ------------------------------------------------------------------ ticket
class PaperOrderIn(BaseModel):
    market: str = "IN"
    symbol: str
    side: str
    qty: int
    kind: str = "market"
    price: float | None = None
    stop: float | None = None
    target: float | None = None
    plan_id: int | None = None
    ticket_id: int | None = None


@router.post("/api/paper/order")
def paper_order(body: PaperOrderIn) -> dict[str, Any]:
    from ...paper import load_ticket, ticket_used
    d = _desk(body.market)
    desk = d["desk"]
    t = load_ticket() if body.ticket_id else None
    risk = t.get("risk_money") if t and t.get("id") == body.ticket_id and t.get("plan_id") == body.plan_id else None
    try:
        o = desk.place_paper_order(body.symbol, body.side, body.qty, kind=body.kind,
                                   price=body.price if body.kind != "market" else None,
                                   stop=body.stop or None, target=body.target or None,
                                   plan_id=body.plan_id, risk_money=risk)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if t and t.get("id") == body.ticket_id:
        ticket_used(t["id"])
    return {**_state(body.market), "placed": _clean(_order(o))}


class AssumptionsIn(BaseModel):
    market: str = "IN"
    symbol: str
    half_spread: float
    slippage: float


@router.post("/api/paper/assumptions")
def paper_assumptions(body: AssumptionsIn) -> dict[str, Any]:
    if body.half_spread < 0 or body.slippage < 0:
        raise HTTPException(400, "Half spread and slippage cannot be negative.")
    _desk(body.market)["desk"].set_assumptions(body.symbol, body.half_spread, body.slippage)
    return _state(body.market)


class PreviewIn(BaseModel):
    market: str = "IN"
    symbol: str
    side: str = "buy"
    qty: int
    price: float | None = None
    target: float | None = None


@router.post("/api/paper/preview")
def paper_preview(body: PreviewIn) -> dict[str, Any]:
    """Cost preview and the Breakeven (pts) tile for the ticket (Chapter 21)."""
    from ... import reference
    from ...paper import cost_preview
    d = _desk(body.market)
    desk = d["desk"]
    px = body.price or (desk.last_bar.get(body.symbol) or {}).get("close")
    if not px or body.qty <= 0:
        return {"ready": False, "reason": "Needs a price: type one or feed a bar."}
    cp = cost_preview(desk.inst(body.symbol), float(px), body.qty, body.target or None,
                      side=body.side)
    return _clean({"ready": True, "price": px, "items": cp.items, "charges": cp.items["total"],
                   "slippage_per_side": cp.slippage_per_side, "slippage_money": cp.slippage_money,
                   "all_in": cp.all_in, "breakeven_pts": cp.breakeven_pts,
                   "target_pts": cp.target_pts, "amber": cp.amber, "facts": cp.facts(),
                   "table_as_of": reference.as_of(), "cur": cp.instrument.cur})


# ------------------------------------------------------------------ pending, orders, positions
@router.post("/api/paper/pending/{row_id}/accept")
def paper_pending_accept(row_id: int, market: str = "IN") -> dict[str, Any]:
    from ...paper import accept
    d = _desk(market)
    try:
        o = accept(row_id, d["desk"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc).strip("'\"")) from exc
    return {**_state(market), "accepted": None if o is None else _clean(_order(o))}


@router.post("/api/paper/pending/{row_id}/reject")
def paper_pending_reject(row_id: int, market: str = "IN") -> dict[str, Any]:
    from ...paper import reject
    try:
        reject(row_id, "rejected on the Paper Desk")
    except KeyError as exc:
        raise HTTPException(400, str(exc).strip("'\"")) from exc
    return _state(market)


@router.post("/api/paper/orders/{order_id}/cancel")
def paper_cancel(order_id: int, market: str = "IN") -> dict[str, Any]:
    _desk(market)["desk"].cancel(order_id)
    return _state(market)


class MoveStopIn(BaseModel):
    market: str = "IN"
    stop: float
    reason: str = ""


@router.post("/api/paper/positions/{position_id}/move-stop")
def paper_move_stop(position_id: int, body: MoveStopIn) -> dict[str, Any]:
    d = _desk(body.market)
    try:
        d["desk"].move_stop(position_id, body.stop, body.reason)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc).strip("'\"")) from exc
    d["desk"].sync_store()
    return _state(body.market)


@router.post("/api/paper/positions/{position_id}/close")
def paper_close(position_id: int, market: str = "IN") -> dict[str, Any]:
    d = _desk(market)
    if not any(p.id == position_id for p in d["desk"].positions):
        raise HTTPException(400, f"No open paper position #{position_id}.")
    d["desk"].close_at_next_bar(position_id)
    return _state(market)


class FundingIn(BaseModel):
    market: str = "IN"
    rate_pct: float      # per 8 h, in percent


@router.post("/api/paper/positions/{position_id}/funding")
def paper_funding(position_id: int, body: FundingIn) -> dict[str, Any]:
    d = _desk(body.market)
    p = next((p for p in d["desk"].positions if p.id == position_id), None)
    if p is None or not p.symbol.endswith("-PERP"):
        raise HTTPException(400, "Funding applies to open perpetual paper positions only.")
    if not -1 <= body.rate_pct <= 1:
        raise HTTPException(400, "Funding per 8 h must be between −1% and 1%.")
    d["desk"].funding_rate[p.symbol] = body.rate_pct / 100
    return _state(body.market)


@router.post("/api/paper/positions/{position_id}/crypto-monitor")
def paper_send_crypto(position_id: int, market: str = "IN") -> dict[str, Any]:
    d = _desk(market)
    p = next((p for p in d["desk"].positions if p.id == position_id), None)
    if p is None:
        raise HTTPException(400, f"No open paper position #{position_id}.")
    rid = store().add("notes", {"kind": "paper_perp", "symbol": p.symbol, "side": p.side,
                                "qty": p.qty, "entry": p.entry, "market": market},
                      tag="send-to-crypto-monitor")
    return {**_state(market), "note_id": rid}


@router.post("/api/paper/kill")
def paper_kill(market: str = "IN") -> dict[str, Any]:
    d = _desk(market)
    res = d["desk"].kill_switch()
    d["desk"].sync_store()
    return {**_state(market), "kill": res}


# ------------------------------------------------------------------ Compare with backtest
class CompareIn(BaseModel):
    market: str = "IN"
    rule: str = DEFAULT_RULE
    symbol: str
    start: str
    end: str


@router.post("/api/paper/compare")
def paper_compare(body: CompareIn) -> dict[str, Any]:
    """Run shadow backtest: same rule, same bars, same fills; split the gap (Chapter 13)."""
    from ...paper import (ShadowUnavailable, drift_report, instrument, live_status,
                          paper_rows_for_drift, run_shadow, session_bars, shadow_trades)
    d = _desk(body.market)
    try:
        start, end = date.fromisoformat(body.start), date.fromisoformat(body.end)
    except ValueError as exc:
        raise HTTPException(400, "From and To must be dates like 2026-09-01.") from exc
    if start > end:
        raise HTTPException(400, "From must be on or before To.")
    inst = instrument(body.symbol, body.market)
    bars = session_bars(inst.data_symbol, body.market, end, "1d")
    bars = bars.filter(bars["date"] >= start)
    try:
        res = run_shadow(body.rule, bars, costs=inst.profile or "IN-futures")
    except ShadowUnavailable as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"The rule could not be run: {exc}") from exc
    journal = [r for r in store().all("journal", tag="PAPER") + store().all("journal", tag="REPLAY")
               if r.get("symbol") == body.symbol and body.start <= str(r.get("date", "")) <= body.end]
    one_r = d["desk"].limits()["one_r"] or None
    sh = shadow_trades(res, one_r)
    rep = drift_report(paper_rows_for_drift(journal, {s["signal"] for s in sh}), sh)
    curve, cs, cp = [], 0.0, 0.0
    for r in sorted(rep.rows, key=lambda r: r.signal):
        cs += r.shadow_r or 0.0
        cp += r.paper_r or 0.0
        curve.append({"signal": r.signal, "shadow": round(cs, 4), "paper": round(cp, 4)})
    notes = {n.get("trade_id"): n.get("text") for n in store().all("notes", tag="drift-note")}
    out = _clean({
        "bars": bars.height,
        "source": live_status()[1] if d["session"] == "LIVE" else "REPLAY",
        "start": body.start, "end": body.end, "symbol": body.symbol, "rule": body.rule,
        "shadow_r": rep.shadow_r, "paper_r": rep.paper_r, "gap_r": rep.gap_r,
        "cost_gap_r": rep.cost_gap_r, "break_gap_r": rep.break_gap_r, "signals": rep.signals,
        "taken": rep.taken, "adherence": rep.adherence, "curve": curve,
        "breaks": [{**r.__dict__, "saved_note": notes.get(r.trade_id)} for r in rep.breaks],
        "facts": rep.facts(),
    })
    d["drift"] = out
    return out


class BreakNoteIn(BaseModel):
    market: str = "IN"
    signal: str
    trade_id: int | None = None
    text: str


@router.post("/api/paper/compare/note")
def paper_break_note(body: BreakNoteIn) -> dict[str, Any]:
    """One line on why a rule break happened; read by the weekly review (Chapter 14)."""
    if not body.text.strip():
        raise HTTPException(400, "Write one line on why the break happened.")
    rid = store().add("notes", {"kind": "drift_note", "signal": body.signal,
                                "trade_id": body.trade_id, "text": body.text.strip(),
                                "market": body.market}, tag="drift-note")
    d = _desk(body.market)
    if d.get("drift"):
        for b in d["drift"]["breaks"]:
            if b.get("signal") == body.signal:
                b["saved_note"] = body.text.strip()
    return {"id": rid}
