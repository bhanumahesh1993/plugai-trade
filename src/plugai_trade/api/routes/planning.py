"""API routes: Plan & Risk (Trade Plan, Position Sizer, Rule Card) and Paper Trading › Alerts.

Thin: every number comes from ``plans``, ``sizing``, ``rulecard`` and ``alerts``.
Store writes go through the same engine functions the classic pages call.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import ai, config, reference
from ...store import default as store
from .. import clean as _clean

router = APIRouter()
SECTION = "Plan & Risk"


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(400, str(exc).strip("'\""))


def _exp(out: Any) -> dict[str, Any]:
    return {"text": out.text, "sources": list(out.sources or []), "model": out.model,
            "where": out.where, "blocked": bool(out.blocked)}


# ================================================================== Trade Plan
def _plan_out(p: Any) -> dict[str, Any]:
    from ... import plans
    chk = plans.checklist(p)
    return _clean({**p.body(), "id": p.id, "owners": p.owners(), "facts": p.facts(),
                   "check": {"missing": chk.missing, "vague": chk.vague,
                             "contradictions": chk.contradictions}})


@router.get("/api/planning/templates")
def plan_templates() -> dict[str, Any]:
    from ... import plans
    return {"templates": {k: [{"field": f, "owner": o} for f, o in v]
                          for k, v in plans.TEMPLATES.items()}}


@router.get("/api/planning/plans")
def plan_list(market: str = "IN") -> list[dict[str, Any]]:
    from ... import plans
    return _clean([{"id": p.id, "name": p.name, "symbol": p.symbol, "version": p.version,
                    "template": p.template, "qty": p.qty, "side": p.side}
                   for p in plans.all_plans(market)])


class NewPlanIn(BaseModel):
    template: str = "Seven-field plan"
    market: str = "IN"
    symbol: str = ""


@router.post("/api/planning/plans")
def plan_new(body: NewPlanIn) -> dict[str, Any]:
    from ... import plans
    try:
        p = plans.new_plan(body.template, body.market, body.symbol.strip().upper())
    except ValueError as exc:
        raise _bad(exc) from exc
    return _plan_out(plans.save(p, note="created"))


def _load(plan_id: int) -> Any:
    from ... import plans
    p = plans.load(plan_id)
    if p is None:
        raise HTTPException(404, f"No saved plan #{plan_id}. Pick one from Saved plans or click New plan.")
    return p


@router.get("/api/planning/plans/{plan_id}")
def plan_get(plan_id: int) -> dict[str, Any]:
    return _plan_out(_load(plan_id))


class PlanEditIn(BaseModel):
    name: str | None = None
    side: str | None = None
    entry: float | None = None
    stop: float | None = None
    trigger_expiry: str | None = None
    fields: dict[str, str] | None = None
    note: str = "edited"


def _apply(p: Any, body: PlanEditIn) -> Any:
    if body.name is not None:
        p.name = body.name
    if body.side in ("long", "short"):
        p.side = body.side
    sent = body.model_fields_set          # a field left out keeps its saved value; 0 clears it
    if "entry" in sent:
        p.entry = body.entry or None
    if "stop" in sent:
        p.stop = body.stop or None
    if body.trigger_expiry is not None:
        p.trigger_expiry = body.trigger_expiry
    if body.fields is not None:
        p.fields = {**p.fields, **body.fields}
    return p


@router.post("/api/planning/plans/{plan_id}/check")
def plan_check(plan_id: int, body: PlanEditIn) -> dict[str, Any]:
    """The code checklist on the unsaved draft (no model call, nothing saved)."""
    return _plan_out(_apply(_load(plan_id), body))


@router.post("/api/planning/plans/{plan_id}/save")
def plan_save(plan_id: int, body: PlanEditIn) -> dict[str, Any]:
    from ... import plans
    return _plan_out(plans.save(_apply(_load(plan_id), body), note=body.note or "edited"))


@router.post("/api/planning/plans/{plan_id}/journal")
def plan_journal(plan_id: int, body: PlanEditIn) -> dict[str, Any]:
    from ... import plans
    p = plans.save(_apply(_load(plan_id), body), note="saved to journal")
    rid = plans.save_to_journal(p)
    return {"row": rid, "plan": _plan_out(p)}


@router.post("/api/planning/plans/{plan_id}/paper")
def plan_paper(plan_id: int, body: PlanEditIn) -> dict[str, Any]:
    from ... import plans
    p = _apply(_load(plan_id), body)
    try:
        plans.ticket_from(p)      # validate before saving a new version
    except ValueError as exc:
        raise _bad(exc) from exc
    plans.save(p, note="sent to Paper Desk")
    tid = plans.send_to_paper_desk(p)
    return {"ticket": tid, "plan": _plan_out(p)}


@router.post("/api/planning/plans/{plan_id}/critique")
def plan_critique(plan_id: int, body: PlanEditIn) -> dict[str, Any]:
    from ... import plans
    p = _apply(_load(plan_id), body)
    crit = plans.critique(p, SECTION)
    return _clean({"text": crit.text, "sources": crit.facts(), "model": crit.model,
                   "where": crit.where, "blocked": False, "missing": crit.missing,
                   "vague": crit.vague, "contradictions": crit.contradictions})


class CritiqueSecondIn(PlanEditIn):
    text: str = ""


@router.post("/api/planning/plans/{plan_id}/second-opinion")
def plan_critique_second(plan_id: int, body: CritiqueSecondIn) -> dict[str, Any]:
    p = _apply(_load(plan_id), body)
    return _exp(ai.second_opinion(body.text, p, SECTION))


# ================================================================== Position Sizer
def _sizer_defaults(mkt: str) -> dict[str, float]:
    s = config.get("sizing", {}) or {}
    acct = (s.get("account") or {}).get(mkt) or (1_500_000.0 if mkt == "IN" else 40_000.0)
    return {"account": float(acct), "risk_pct": float(s.get("risk_pct", 0.01)) * 100,
            "cap_pct": float(s.get("cap_pct", 0.25)) * 100,
            "total_cap_r": float(s.get("total_cap_r", 3.0)),
            "group_cap_r": float(s.get("group_cap_r", 2.0))}


def _market_numbers(symbol: str, mkt: str) -> dict[str, Any]:
    from ... import data, indicators, sizing
    end = date.today()
    df = data.get(sizing.base_symbol(symbol), market=mkt, start=end - timedelta(days=120), end=end)
    src = df["source"][-1] if "source" in df.columns and df.height else "synthetic"
    df = indicators.atr(indicators.returns(df), 14)
    last = df.tail(1)
    vol = float(df["ret"].tail(20).std() or 0.01)
    return {"last": float(last["close"][0]), "atr": float(last["atr_14"][0]), "daily_vol": vol,
            "asof": str(last["date"][0]), "source": src}


@router.get("/api/planning/sizer/context")
def sizer_context(symbol: str = "", market: str = "IN") -> dict[str, Any]:
    from ... import plans, sizing
    sym = (symbol or ("NIFTY FUT" if market == "IN" else "SPY")).strip().upper()
    try:
        nums = _market_numbers(sym, market)
        err = None
    except Exception as exc:  # data problems must not break sizing
        nums = {"last": 100.0, "atr": 1.0, "daily_vol": 0.01, "asof": "n/a", "source": "none"}
        err = f"No data for {sym}: {exc}"
    return _clean({"symbol": sym, "market": market, "lot": sizing.lot_for(sym, market),
                   "table_as_of": reference.as_of(), "defaults": _sizer_defaults(market),
                   **nums, "data_error": err,
                   "plans": [{"id": p.id, "name": p.name, "symbol": p.symbol, "entry": p.entry,
                              "stop": p.stop, "side": p.side, "qty": p.qty}
                             for p in plans.all_plans(market)]})


class SizeIn(BaseModel):
    method: str = "fixed"            # fixed | atr | vol
    market: str = "IN"
    symbol: str = "NIFTY FUT"
    account: float = 0.0
    risk_pct: float = 1.0            # percent
    cap_pct: float | None = 25.0     # percent; 0 / None = no cap
    entry: float = 0.0
    stop: float | None = None
    cost_per_lot: float | None = None  # None = the dated allowance
    atr: float | None = None
    multiple: float = 1.5
    side: str = "long"
    stop_typed: float | None = None
    target_vol: float = 12.0         # percent a year
    daily_vol: float = 1.0           # percent
    plan_id: int | None = None


def _size(body: SizeIn) -> tuple[Any, float | None]:
    from ... import sizing
    sym = body.symbol.strip().upper()
    lot = sizing.lot_for(sym, body.market)
    cap = (body.cap_pct / 100) if body.cap_pct else None
    risk = body.risk_pct / 100
    try:
        if body.method == "fixed":
            if body.stop is None or body.entry == body.stop:
                raise ValueError("Enter a stop different from the entry.")
            allow = (body.cost_per_lot if body.cost_per_lot is not None
                     else sizing.cost_allowance(sym, body.market, body.entry, body.stop, lot))
            return sizing.fixed_risk(body.account, risk, body.entry, body.stop, lot, allow, cap,
                                     sym, body.market), allow
        if body.method == "atr":
            if not body.atr or body.atr <= 0:
                raise ValueError("ATR (14) must be above zero.")
            sign = -1 if body.side == "long" else 1
            suggested = sizing.round_price(body.entry + sign * body.multiple * body.atr)
            stop = body.stop_typed if body.stop_typed is not None else suggested
            if stop == body.entry:
                raise ValueError("Enter a stop different from the entry.")
            allow = (body.cost_per_lot if body.cost_per_lot is not None
                     else sizing.cost_allowance(sym, body.market, body.entry, stop, lot))
            override = None if body.stop_typed is None or body.stop_typed == suggested else body.stop_typed
            return sizing.atr_stop(body.account, risk, body.entry, body.atr, body.multiple, lot,
                                   allow, cap, body.side, stop_override=override, symbol=sym,
                                   market=body.market), allow
        if body.method == "vol":
            if body.daily_vol <= 0 or body.entry <= 0:
                raise ValueError("Price and the instrument's daily move must be above zero.")
            return sizing.vol_target(body.account, body.target_vol / 100, body.entry,
                                     body.daily_vol / 100, lot, None, sym, body.market), None
    except (ValueError, ZeroDivisionError) as exc:
        raise _bad(exc) from exc
    raise HTTPException(400, "Method must be fixed, atr or vol.")


def _tiles(r: Any) -> list[dict[str, Any]]:
    """Tile labels match the text before ':' in ``r.facts()`` so citations light them."""
    from ... import sizing
    m, vol = r.market, r.method == "Vol target"
    s = "s" if r.size != 1 else ""
    return [
        {"label": "Daily risk target (÷16)" if vol else "Risk budget",
         "value": sizing.money(r.budget, m, 0 if m == "IN" else 2)},
        {"label": f"Daily move per {r.unit}" if vol else f"Risk per {r.unit}",
         "value": sizing.money(r.risk_per_lot, m, 2)},
        {"label": "Raw size", "value": f"{r.raw_size:.2f} {r.unit}s"},
        {"label": "Size (rounded down)", "value": f"{r.size} {r.unit}{s}", "big": True,
         "sub": f"{r.quantity} units" if r.lot > 1 else None},
        {"label": "Actual risk", "value": sizing.money(r.actual_risk, m, 2) if vol
         else f"{r.actual_risk_pct:.2%}", "sub": None if vol else sizing.money(r.actual_risk, m, 2)},
        {"label": "Notional exposure", "value": f"{r.notional_x:.2f}×", "sub": sizing.money(r.notional, m),
         "warn": r.notional_x > 1},
    ]


def _cap_check(r: Any, d: dict[str, float]) -> dict[str, Any] | None:
    from ... import sizing
    one_r = r.budget if r.method != "Vol target" else 0
    if not one_r or r.size == 0:
        return None
    open_pos = [{"symbol": p["symbol"], "risk_r": (p.get("risk_money") or 0) / one_r}
                for p in store().all("paper_positions", tag="open")]
    chk = sizing.check_caps(open_pos, r.symbol, r.actual_risk / one_r, d["total_cap_r"],
                            d["group_cap_r"])
    return {"ok": chk.ok, "total_open_r": chk.total_open_r, "total_cap_r": d["total_cap_r"],
            "group": chk.group, "group_effective_r": chk.group_effective_r,
            "group_cap_r": d["group_cap_r"], "messages": chk.messages, "facts": chk.facts()}


@router.post("/api/planning/sizer/size")
def sizer_size(body: SizeIn) -> dict[str, Any]:
    from ... import sizing
    r, allow = _size(body)
    warn = None
    if r.notional_x > 1:
        warn = (f"Notional exposure {sizing.money(r.notional, r.market)} is {r.notional_x:.2f}× the "
                "account. Stop-based sizing controls the loss at the stop, not a gap through it.")
    cap_msg = None
    if r.cap_size is not None:
        cap_msg = (f"Position cap {r.cap_pct:.0%}: allows {r.cap_size} {r.unit}s; risk rule gives "
                   f"{r.risk_size}. Binding rule: {r.binding}.")
    return _clean({
        "method": r.method, "unit": r.unit, "size": r.size, "quantity": r.quantity,
        "raw_size": r.raw_size, "binding": r.binding, "tiles": _tiles(r), "facts": r.facts(),
        "notional_warning": warn, "cap_message": cap_msg, "cap_binding": r.binding == "position cap",
        "choices": r.choices, "notes": r.notes, "cost_allowance": allow, "stop": r.stop,
        "suggested_stop": r.extra.get("suggested_stop"), "size_text": r.size_text(),
        "cap_check": _cap_check(r, _sizer_defaults(body.market)), "lot": r.lot,
    })


@router.post("/api/planning/sizer/use-in-plan")
def sizer_use_in_plan(body: SizeIn) -> dict[str, Any]:
    from ... import plans
    if body.plan_id is None:
        raise HTTPException(400, "Pick a plan first: Use in plan writes the size into that plan.")
    p = _load(body.plan_id)
    r, _ = _size(body)
    if r.size == 0:
        raise HTTPException(400, "Size is 0: nothing to write. Pick one of the choices listed first.")
    p = plans.use_size(p, r)
    return {"plan_id": p.id, "version": p.version, "size_text": r.size_text()}


class HedgeIn(BaseModel):
    exposure: float = 20_000.0
    side: str = "receivable"
    futures_price: float = 88.40
    ratio: float = 1.0


@router.post("/api/planning/sizer/hedge")
def sizer_hedge(body: HedgeIn) -> dict[str, Any]:
    from ... import sizing
    try:
        h = sizing.hedge(body.exposure, body.futures_price, body.side, hedge_ratio=body.ratio)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _clean({**asdict(h), "facts": h.facts(), "table_as_of": reference.as_of()})


class HedgeUsIn(BaseModel):
    risk: float
    distance: float = 0.0055
    contract_size: float | None = None


@router.post("/api/planning/sizer/hedge-us")
def sizer_hedge_us(body: HedgeUsIn) -> dict[str, Any]:
    """US: size a currency-futures view from the stop, never from the deposit."""
    table = float(reference.lookup("us.contracts.M6E.contract_size") or 0)
    size = body.contract_size if body.contract_size is not None else table
    if body.distance <= 0 or size <= 0:
        raise HTTPException(400, "Stop distance and contract size must both be above zero.")
    per = body.distance * size
    n = int(body.risk // per) if per else 0
    return _clean({"contract_size": size, "table_contract_size": table, "per_contract": per,
                   "contracts": n, "table_as_of": reference.as_of(),
                   "facts": [f"Risk per trade: ${body.risk:,.2f}", f"Stop distance: {body.distance}",
                             f"Contract size: {size:g}", f"Risk per contract: ${per:,.2f}",
                             f"Whole contracts (rounded down): {n}"]})


class StreakIn(BaseModel):
    win_rate: float = 40.0
    win_r: float = 1.6
    loss_r: float = -1.0
    risk_pct: float = 1.0
    sequences: int = Field(2000, ge=100, le=20_000)
    trades: int = Field(100, ge=10, le=1000)
    seed: int = 12
    use_journal: bool = False


@router.post("/api/planning/sizer/streaks")
def sizer_streaks(body: StreakIn) -> dict[str, Any]:
    from ... import sizing
    rv = None
    note = None
    if body.use_journal:
        rv = [float(r["r"]) for r in store().all("journal") if r.get("r") is not None] or None
        if rv is None:
            note = "No R-multiples in the journal yet; using the two-outcome model."
    risk = body.risk_pct / 100
    res = [sizing.simulate_streaks(body.win_rate / 100, body.win_r, body.loss_r, x,
                                   body.sequences, body.trades, body.seed, rv)
           for x in (risk, risk / 2)]
    return _clean({"note": note, "from_journal": rv is not None,
                   "rows": [{k: v for k, v in asdict(r).items() if k != "fan"} for r in res],
                   "fan": res[0].fan, "facts": res[0].facts()})


# ================================================================== Rule Card
class CardIn(BaseModel):
    card: dict[str, Any]
    note: str = ""


def _card(body: dict[str, Any]) -> Any:
    from ... import rulecard
    keys = rulecard.RuleCard.__dataclass_fields__
    try:
        return rulecard.RuleCard(**{k: v for k, v in body.items() if k in keys})
    except TypeError as exc:
        raise _bad(exc) from exc


def _card_out(card: Any) -> dict[str, Any]:
    from ... import rulecard
    return _clean({"card": asdict(card), "facts": card.facts(),
                   "limits": {m: card.money_limits(m) for m in ("IN", "US")},
                   "groups": list(rulecard.TEMPLATE_RULES),
                   "event_types": sorted(set(rulecard.EVENT_TYPES["IN"] + rulecard.EVENT_TYPES["US"])),
                   "synced_version": config.get("rulecard.synced_version")})


@router.get("/api/planning/rulecard")
def rulecard_get() -> dict[str, Any]:
    from ... import rulecard
    return _card_out(rulecard.current())


@router.post("/api/planning/rulecard/preview")
def rulecard_preview(body: CardIn) -> dict[str, Any]:
    return _card_out(_card(body.card))


class SuggestIn(CardIn):
    lines: list[str]
    group: str = "Behaviour"


@router.post("/api/planning/rulecard/suggest")
def rulecard_suggest(body: SuggestIn) -> dict[str, Any]:
    from ... import rulecard
    return _card_out(rulecard.suggest_rules(_card(body.card), body.lines, body.group))


@router.post("/api/planning/rulecard/new-version")
def rulecard_new_version(body: CardIn) -> dict[str, Any]:
    from ... import rulecard
    return _card_out(rulecard.new_version(_card(body.card), body.note))


@router.post("/api/planning/rulecard/sync")
def rulecard_sync(body: CardIn) -> dict[str, Any]:
    from ... import rulecard
    card = _card(body.card)
    vals = rulecard.sync_limits(card)
    return _clean({"values": vals, "version": card.version, "market": config.get("market", "IN")})


@router.get("/api/planning/rulecard/history")
def rulecard_history() -> list[dict[str, Any]]:
    from ... import rulecard
    return _clean([{"id": h["id"], "version": h.get("version"), "written": h.get("written"),
                    "note": h.get("note")} for h in rulecard.history()])


@router.get("/api/planning/rulecard/adherence")
def rulecard_adherence() -> dict[str, Any]:
    from ... import rulecard
    rows = [r for r in store().all("journal") if r.get("tag") in ("PAPER", "REPLAY", "PILOT")]
    return _clean(rulecard.adherence(rows))


class GoNoGoIn(BaseModel):
    account: str = "Paper"
    start: str | None = None
    end: str | None = None


@router.post("/api/planning/rulecard/gonogo")
def rulecard_gonogo(body: GoNoGoIn) -> dict[str, Any]:
    from ... import rulecard
    if body.account not in ("Paper", "Pilot"):
        raise HTTPException(400, "Account must be Paper or Pilot.")
    g = rulecard.go_no_go(account=body.account, marks=rulecard.current().pass_marks,
                          start=body.start, end=body.end)
    return _clean({"verdict": g.verdict, "go": g.verdict.startswith("GO"),
                   "measures": [asdict(m) for m in g.measures], "facts": g.facts()})


class PilotIn(BaseModel):
    market: str = "IN"
    budget: float
    trades_per_day: int
    review_date: str
    stop_conditions: list[str]
    size: str = ""


@router.post("/api/planning/rulecard/pilot")
def rulecard_pilot(body: PilotIn) -> dict[str, Any]:
    from ... import rulecard
    try:
        pid = rulecard.save_pilot_plan(body.market, body.budget, body.trades_per_day,
                                       body.review_date, [s for s in body.stop_conditions if s.strip()],
                                       body.size)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"id": pid}


@router.post("/api/planning/rulecard/audit/start")
def rulecard_audit_start() -> dict[str, Any]:
    from ... import rulecard
    return _clean(rulecard.start_audit())


class AuditIn(BaseModel):
    month: str
    items: list[dict[str, Any]]


@router.post("/api/planning/rulecard/audit/save")
def rulecard_audit_save(body: AuditIn) -> dict[str, Any]:
    from ... import rulecard
    return {"id": rulecard.save_audit(body.model_dump())}


# ================================================================== Alerts
def _alert_out(a: Any) -> dict[str, Any]:
    return _clean({**asdict(a), "describe": a.describe()})


def _alert(body: dict[str, Any]) -> Any:
    from ... import alerts
    keys = alerts.Alert.__dataclass_fields__
    try:
        a = alerts.Alert(**{k: v for k, v in body.items() if k in keys and k != "id"})
    except TypeError as exc:
        raise _bad(exc) from exc
    a.id = body.get("id")
    return a


@router.get("/api/planning/alerts")
def alerts_state(market: str = "IN") -> dict[str, Any]:
    from ... import alerts, keys, plans
    rows = alerts.load_all()
    email = config.get("alerts.email", {}) or {}
    perps = [p for p in store().all("paper_positions", tag="open")
             if str(p.get("symbol", "")).endswith("-PERP")]
    perps += store().all("notes", tag="send-to-crypto-monitor")
    return _clean({
        "alerts": [_alert_out(a) for a in rows if a.status in ("active", "fired", "expired", "paused")],
        "proposed": [_alert_out(a) for a in rows if a.status == "proposed"],
        "log": alerts.alert_log(),
        "plans": [{"id": p.id, "name": p.name, "symbol": p.symbol} for p in plans.all_plans(market)],
        "crypto_positions": [{"key": f"{p.get('id')}", "symbol": p.get("symbol"),
                              "side": p.get("side", "long"), "entry": p.get("entry"),
                              "label": f"{p['symbol']} {p.get('side', 'long')} @ {p.get('entry')}"}
                             for p in perps if p.get("symbol")],
        "channels": {"quiet_hours": config.get("alerts.quiet_hours", ""),
                     "telegram_chat_id": config.get("alerts.telegram_chat_id", ""),
                     "telegram_token": keys.masked("telegram_bot_token"),
                     "email_to": email.get("to", ""), "smtp_host": email.get("smtp_host", ""),
                     "smtp_port": int(email.get("smtp_port", 587))},
        "options": {"channels": list(alerts.CHANNELS), "bar_sizes": list(alerts.BAR_SIZES),
                    "conditions": ["touch above", "touch below", "close above", "close below"],
                    "indicators": ["sma_20", "sma_50", "ema_20", "rsi_14"]},
        "in_quiet_hours": alerts.in_quiet_hours(),
    })


class ProposeIn(BaseModel):
    source: str = "From plan"      # From plan | From Crypto Monitor | Blank
    market: str = "IN"
    plan_ids: list[int] = []
    position_key: str | None = None
    leverage: float = 5.0
    symbol: str = ""
    kind: str = "price"
    condition: str = "touch above"
    level: float | None = None
    indicator: str | None = None


@router.post("/api/planning/alerts/propose")
def alerts_propose(body: ProposeIn) -> list[dict[str, Any]]:
    """Proposals only: nothing is stored or active until Accept."""
    from ... import alerts
    if body.source == "From plan":
        if not body.plan_ids:
            raise HTTPException(400, "Choose at least one saved plan to propose alerts from.")
        out = [a for pid in body.plan_ids for a in alerts.from_plan(_load(pid), body.market)]
    elif body.source == "From Crypto Monitor":
        pos = next((p for p in alerts_state(body.market)["crypto_positions"]
                    if p["key"] == body.position_key), None)
        if pos is None:
            raise HTTPException(400, "Pick a paper perpetual position (Paper Desk › Send to Crypto Monitor).")
        out = alerts.from_crypto_monitor({**pos, "leverage": body.leverage, "market": body.market})
    else:
        sym = body.symbol.strip().upper()
        if not sym:
            raise HTTPException(400, "Type a symbol for the alert.")
        ind = body.indicator if body.kind == "indicator" else None
        if body.kind == "price" and not body.level:
            raise HTTPException(400, "A price alert needs a level.")
        out = [alerts.Alert(f"{sym} {body.condition} {ind or body.level}", sym, body.market,
                            body.kind, "new item" if body.kind == "event" else body.condition,
                            body.level or None, indicator=ind)]
    return [_alert_out(a) for a in out]


class AcceptIn(BaseModel):
    alerts: list[dict[str, Any]]


@router.post("/api/planning/alerts/accept")
def alerts_accept(body: AcceptIn) -> dict[str, Any]:
    from ... import alerts
    done = [alerts.accept(_alert(a)) for a in body.alerts]
    return {"accepted": len(done), "ids": [a.id for a in done]}


def _stored(alert_id: int) -> Any:
    from ... import alerts
    a = next((x for x in alerts.load_all() if x.id == alert_id), None)
    if a is None:
        raise HTTPException(404, f"No alert #{alert_id}.")
    return a


@router.post("/api/planning/alerts/{alert_id}/accept")
def alert_accept_saved(alert_id: int) -> dict[str, Any]:
    from ... import alerts
    return _alert_out(alerts.accept(_stored(alert_id)))


@router.post("/api/planning/alerts/{alert_id}/discard")
def alert_discard(alert_id: int) -> dict[str, Any]:
    _stored(alert_id)
    store().delete("alerts", alert_id)
    return {"deleted": alert_id}


@router.post("/api/planning/alerts/{alert_id}/pause")
def alert_pause(alert_id: int) -> dict[str, Any]:
    from ... import alerts
    a = _stored(alert_id)
    a.status = "paused"
    return _alert_out(alerts.save(a))


@router.post("/api/planning/alerts/{alert_id}/resume")
def alert_resume(alert_id: int) -> dict[str, Any]:
    from ... import alerts
    return _alert_out(alerts.accept(_stored(alert_id)))


@router.post("/api/planning/alerts/{alert_id}/test")
def alert_test(alert_id: int) -> dict[str, Any]:
    from ... import alerts
    msg, ok = alerts.send_test(_stored(alert_id))
    return {"message": msg, "delivered": ok}


class ChannelsIn(BaseModel):
    quiet_hours: str = ""
    telegram_chat_id: str = ""
    email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    telegram_token: str = ""


@router.post("/api/planning/alerts/channels")
def alerts_channels(body: ChannelsIn) -> dict[str, Any]:
    from ... import alerts, keys
    qh = body.quiet_hours.strip()
    if qh:
        try:
            alerts.in_quiet_hours(window=qh)
        except ValueError as exc:
            raise HTTPException(400, "Quiet hours must look like 23:00-06:00.") from exc
    config.set_value("alerts.quiet_hours", qh)
    config.set_value("alerts.telegram_chat_id", body.telegram_chat_id.strip())
    config.set_value("alerts.email", {"to": body.email_to.strip(), "smtp_host": body.smtp_host.strip(),
                                      "smtp_port": int(body.smtp_port)})
    if body.telegram_token.strip():
        keys.set_key("telegram_bot_token", body.telegram_token.strip())
    return {"saved": True, "telegram_token": keys.masked("telegram_bot_token")}


@router.get("/api/planning/sizer/vol-scenarios")
def sizer_vol_scenarios(market: str = "IN") -> dict[str, Any]:
    """Latest volatility bands sent from Automate › ML Lab (Send to Position Sizer), if any."""
    rows = [r for r in store().all("notes", tag="sizer")
            if r.get("kind") == "vol_scenarios" and r.get("market", market) == market]
    return _clean(rows[0]) if rows else {}
