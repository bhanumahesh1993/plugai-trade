"""API routes: strategy (Strategy Builder, Trend Lab, Pairs Lab — Chapters 11, 16, 18, 26).

Thin wrappers over ``plugai_trade.backtest`` and ``plugai_trade.pairs``. Nothing an AI
drafts is applied here: drafts are returned to the screen and only become the rule
the user tests after they click Accept there. Paper hand-offs write *pending* paper
orders that fill only after Accept on the Paper Desk.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import reference
from ...store import default as store
from .. import clean as _clean
from .backtest import (
    INSTRUMENTS,
    PROFILES,
    RESULT_LABELS,
    SECTORS,
    get_run,
    load_bars,
    relabel,
    remember_run,
    remember_saved,
    summary_payload,
)

router = APIRouter()

FUTURES = "Back-adjusted futures (from Futures & Roll)"


def _bt():
    from ... import backtest
    return backtest


def _spec(d: dict[str, Any], market: str) -> Any:
    bt = _bt()
    try:
        spec = bt.Spec.from_dict(d)
        spec.market = market
        return spec.validate()
    except (bt.SpecError, TypeError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


def _result_block(res: Any) -> dict[str, Any]:
    return {**summary_payload(res), "facts": relabel(res.facts(), RESULT_LABELS),
            "grade": res.card().grade}


# ------------------------------------------------------------------ options
@router.get("/api/strategy/options")
def strategy_options(market: str = "IN") -> dict[str, Any]:
    bt = _bt()
    return {"instruments": INSTRUMENTS.get(market, []), "profiles": PROFILES.get(market, []),
            "sectors": SECTORS.get(market, []),
            "default_slippage": bt.spec.DEFAULT_SLIPPAGE_PCT.get(market, 0.05),
            "default_sleeve": bt.spec.DEFAULT_SLEEVE.get(market, 0.0),
            "futures": _futures_note(), "as_of": reference.as_of()}


# ------------------------------------------------------------------ Strategy Builder
class DraftIn(BaseModel):
    idea: str
    market: str = "IN"


@router.post("/api/strategy/draft")
def strategy_draft(body: DraftIn) -> dict[str, Any]:
    """Describe your idea → draft rule cards. Nothing is applied until Accept."""
    bt = _bt()
    if not body.idea.strip():
        raise HTTPException(400, "Type your idea first, for example: buy when the close is above "
                                 "the 50-day average; sell when it falls below the 20-day average.")
    try:
        spec = bt.rules(body.idea)
    except bt.SpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _clean({"spec": spec.to_dict(), "cards": spec.cards(), "read_back": spec.read_back()})


@router.get("/api/strategy/proposals")
def strategy_proposals() -> list[dict[str, Any]]:
    """Agent proposals waiting (Automate › Agents › Send to Strategy Builder)."""
    bt = _bt()
    out = []
    for p in store().all("proposals", tag="PROPOSED")[:10]:
        if not p.get("spec"):
            continue
        row = {"id": p["id"], "subject": p.get("subject") or p.get("symbol") or "",
               "created": p.get("created", "")[:10], "team": p.get("team")}
        try:
            spec = bt.Spec.from_dict(p["spec"])
            spec.origin = "agent"
            spec.validate()
            row.update(spec=spec.to_dict(), cards=spec.cards())
        except (bt.SpecError, TypeError, ValueError) as exc:
            row["error"] = f"The proposal could not be turned into rule cards: {exc}"
        out.append(row)
    return _clean(out)


class SpecIn(BaseModel):
    spec: dict[str, Any]
    market: str = "IN"


@router.post("/api/strategy/check")
def strategy_check(body: SpecIn) -> dict[str, Any]:
    """Validate edited rule cards; return the read-back, the cards and the Trials counter."""
    bt = _bt()
    spec = _spec(body.spec, body.market)
    return _clean({"spec": spec.to_dict(), "cards": spec.cards(), "read_back": spec.read_back(),
                   "facts": spec.facts(), "family": spec.family_key(), "digest": spec.digest(),
                   "trials": bt.trials.count(spec.family_key())})


class RunIn(BaseModel):
    spec: dict[str, Any]
    market: str = "IN"
    symbol: str = "NIFTY"
    years: int = Field(5, ge=1, le=15)
    synthetic: bool = True


@router.post("/api/strategy/chart-check")
def strategy_chart_check(body: RunIn) -> dict[str, Any]:
    """Entries and exits on the chart plus the churn chip. Does not add a trial."""
    bt = _bt()
    from ...backtest.view import Series
    spec = _spec(body.spec, body.market)
    bars, notice = load_bars(body.symbol, body.market, body.years, body.synthetic)
    profile = spec.cost.profile or PROFILES[body.market][0]
    try:
        cc = bt.chart_check(spec, bars, costs=profile)
    except bt.SpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    bars = bars.sort("date")
    ser = Series(bars)
    lines: dict[str, list[float]] = {}
    for c in spec.entry + spec.exit:
        for o in c.operands():
            if o.kind in ("sma", "ema") and o.n:
                name = f"{o.n}-day {'average' if o.kind == 'sma' else 'EMA'}"
                lines.setdefault(name, ser.indicator(o.kind, int(o.n)).tolist())
    px = dict(zip(bars["date"].to_list(), bars["close"].to_list()))
    return _clean({
        "symbol": body.symbol, "source": bars["source"][-1], "notice": notice,
        "dates": bars["date"].to_list(), "close": bars["close"].to_list(), "lines": lines,
        "buys": [{"date": d, "price": px.get(d)} for d in cc["buys"]],
        "sells": [{"date": d, "price": px.get(d)} for d in cc["sells"]],
        "chip": cc["chip"].replace("⚠", "").strip(), "round_trips": cc["round_trips"],
    })


@router.post("/api/strategy/backtest")
def strategy_backtest(body: RunIn) -> dict[str, Any]:
    """*Backtest*: run, count the trial, save the report for the Backtest Report."""
    bt = _bt()
    spec = _spec(body.spec, body.market)
    bars, notice = load_bars(body.symbol, body.market, body.years, body.synthetic)
    profile = spec.cost.profile or PROFILES[body.market][0]
    try:
        res = bt.run(spec, bars, costs=profile, symbol=body.symbol)
    except bt.SpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    rid = remember_saved(res, "strategy_builder")
    return _clean({"id": rid, "notice": notice, **_result_block(res)})


# ------------------------------------------------------------------ Trend Lab
class TrendIn(BaseModel):
    preset: str = "MA crossover"         # MA crossover | Time-series momentum | Rotation
    market: str = "IN"
    symbol: str = "NIFTY"
    years: int = Field(15, ge=3, le=15)
    synthetic: bool = True
    fast: int = 50
    slow: int = 200
    months: int = 12
    check: str = "weekly"
    sleeve: float | None = None
    target: float = 12.0                 # % a year
    buffer: float = 10.0                 # %
    cap: float = 100.0                   # %
    lookback: int = 20                   # sessions
    profile: str | None = None
    slippage_pct: float | None = None
    universe: list[str] = Field(default_factory=list)
    rot_lookback: int = 6
    top_n: int = 2


def _futures_note() -> dict[str, Any] | None:
    rows = store().all("notes", tag="trend_lab", limit=1)
    if not rows or rows[0].get("kind") != "back_adjusted_series":
        return None
    return {"symbol": rows[0].get("symbol"), "rows": rows[0].get("rows"),
            "roll_dates": rows[0].get("roll_dates", [])}


def _futures_bars(market: str) -> pl.DataFrame:
    from ... import futures
    note = _futures_note()
    if note is None:
        raise HTTPException(400, "No back-adjusted series yet. In Derivatives › Futures & Roll, "
                                 "click Send to Trend Lab first.")
    s = futures.contract_series(note["symbol"], market=market)
    px = pl.col("adjusted")
    return s.select("date", px.alias("open"), px.alias("high"), px.alias("low"),
                    px.alias("close"), pl.lit(0.0).alias("volume"),
                    pl.lit("futures back-adjusted").alias("source"))


def _trend(body: TrendIn) -> tuple[Any, Any, str, str | None, str]:
    """(spec, bars, profile, notice, name) for the Trend Lab settings."""
    bt = _bt()
    mkt = body.market
    profiles = PROFILES.get(mkt)
    if not profiles:
        raise HTTPException(400, "Market must be IN or US.")
    slip = bt.spec.DEFAULT_SLIPPAGE_PCT[mkt] if body.slippage_pct is None else body.slippage_pct
    if not 0 <= slip <= 2:
        raise HTTPException(400, "Slippage must be between 0% and 2% a side.")
    if body.check not in ("daily", "weekly", "monthly"):
        raise HTTPException(400, "Check must be daily, weekly or monthly.")
    notice = None
    if body.preset == "Rotation":
        uni = [s for s in body.universe if s]
        if len(uni) < 2 or not 1 <= body.top_n < len(uni):
            raise HTTPException(400, "Choose at least two instruments and a Top N smaller than "
                                     "the universe.")
        profile = body.profile if body.profile in profiles else profiles[0]
        bars = {}
        for s in uni:
            bars[s], n = load_bars(s, mkt, body.years, body.synthetic)
            notice = notice or n
        try:
            spec = bt.rotation(uni, int(body.rot_lookback), int(body.top_n), slippage_pct=slip)
            spec.cost.profile, spec.market = profile, mkt
            spec.validate()
        except bt.SpecError as exc:
            raise HTTPException(400, str(exc)) from exc
        return spec, bars, profile, notice, f"{len(uni)} instruments"
    futures = body.symbol == FUTURES
    if futures:
        bars, name = _futures_bars(mkt), "FUT (back-adjusted)"
    else:
        bars, notice = load_bars(body.symbol, mkt, body.years, body.synthetic)
        name = body.symbol
    default_prof = "IN-futures" if futures and "IN-futures" in profiles else profiles[0]
    profile = body.profile if body.profile in profiles else default_prof
    kw = {"check": body.check, "target_vol": body.target / 100, "buffer": body.buffer / 100,
          "cap": body.cap / 100, "sleeve": body.sleeve or bt.spec.DEFAULT_SLEEVE[mkt]}
    try:
        if body.preset == "MA crossover":
            if body.fast >= body.slow:
                raise HTTPException(400, "The fast average must be shorter than the slow one.")
            spec = bt.ma_crossover(int(body.fast), int(body.slow), **kw)
        elif body.preset == "Time-series momentum":
            spec = bt.ts_momentum(int(body.months), **kw)
        else:
            raise HTTPException(400, f"Unknown preset {body.preset!r}.")
        spec.size.vol_lookback = int(body.lookback)
        spec.cost.profile, spec.cost.slippage_pct, spec.market = profile, slip, mkt
        spec.validate()
    except bt.SpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    return spec, bars, profile, notice, name


def _sizing(body: TrendIn, bars: pl.DataFrame) -> dict[str, Any]:
    """Volatility sizing tiles, exactly as the classic Trend Lab computes them."""
    bt = _bt()
    sleeve = body.sleeve or bt.spec.DEFAULT_SLEEVE[body.market]
    close = bars.sort("date")["close"].to_numpy()
    lb = int(body.lookback)
    r = close[-lb:] / close[-lb - 1:-1] - 1
    dv = float(r.std(ddof=1)) if len(r) > 1 else float("nan")
    weight = min(body.cap / 100, (body.target / 100) / 16 / dv) if dv > 0 else 0.0
    price = float(close[-1])
    exposure = weight * sleeve
    units = math.floor(exposure / price) if price > 0 else 0
    raw = sleeve * body.target / 100 / 16 / dv if dv > 0 else 0.0
    return {"sleeve": sleeve, "daily_vol": dv, "annual_vol": dv * 16, "weight": weight,
            "exposure": exposure, "units": units, "price": price, "uncapped": raw,
            "formula": (f"Sleeve × {body.target:.0f}% ÷ 16 ÷ daily move {dv:.2%} = "
                        f"{bt.fmt_money(raw, body.market)}, capped at {body.cap:.0f}% of the "
                        "sleeve, ÷ price, rounded down. Computed in code.")}


@router.post("/api/strategy/trend/preview")
def trend_preview(body: TrendIn) -> dict[str, Any]:
    """Read back, the Trials counter and (for trend presets) the volatility sizing tiles."""
    bt = _bt()
    spec, bars, profile, notice, _ = _trend(body)
    out: dict[str, Any] = {"read_back": spec.read_back(), "digest": spec.digest(),
                           "trials": bt.trials.count(spec.family_key()), "profile": profile,
                           "notice": notice}
    if body.preset != "Rotation":
        out["sizing"] = _sizing(body, bars)
    return _clean(out)


@router.post("/api/strategy/trend/run")
def trend_run(body: TrendIn) -> dict[str, Any]:
    bt = _bt()
    spec, bars, profile, notice, name = _trend(body)
    try:
        res = bt.run(spec, bars, costs=profile,
                     symbol=None if isinstance(bars, dict) else name)
    except bt.SpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _clean({"run_id": remember_run(res), "notice": notice, **_result_block(res)})


HEATMAP_AXES = {
    "MA crossover": (("entry.0.left.n", "Fast (days)", "10, 20, 30, 50, 75, 100"),
                     ("entry.0.right.n", "Slow (days)", "100, 150, 200, 250, 300")),
    "Time-series momentum": (("entry.0.right.n", "Lookback (sessions)",
                              "63, 126, 189, 252, 378, 504"), None),
    "Rotation": (("lookback_months", "Lookback (months)", "3, 6, 9, 12"),
                 ("top_n", "Top N", "1, 2, 3")),
}


def _ints(text: str) -> list[int]:
    out = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            out.append(int(part))
    return sorted(set(out))


class HeatmapIn(BaseModel):
    settings: TrendIn
    rows: str | None = None
    cols: str | None = None
    split: float = Field(2 / 3, ge=0.5, le=0.85)


@router.get("/api/strategy/trend/heatmap-axes")
def trend_heatmap_axes() -> dict[str, Any]:
    return {k: {"rows": {"label": r[1], "default": r[2]},
                "cols": {"label": c[1], "default": c[2]} if c else None}
            for k, (r, c) in HEATMAP_AXES.items()}


@router.post("/api/strategy/trend/heatmap")
def trend_heatmap(body: HeatmapIn) -> dict[str, Any]:
    """*Sweep*: every cell is one trial, scored on the tuning years and the unseen years."""
    bt = _bt()
    spec, bars, profile, _, _ = _trend(body.settings)
    rows, cols = HEATMAP_AXES[body.settings.preset]
    rv = _ints(body.rows if body.rows is not None else rows[2])
    cv = _ints(body.cols if body.cols is not None else cols[2]) if cols else None
    if not rv or (cols and not cv):
        raise HTTPException(400, "Type whole numbers separated by commas, for example 10, 20, 50.")
    if len(rv) * len(cv or [1]) > 60:
        raise HTTPException(400, "That sweep has more than 60 settings. Every cell is a trial; "
                                 "choose fewer values.")
    skip = (lambda a, b: a >= b) if body.settings.preset == "MA crossover" else None
    try:
        hm = bt.heatmap(spec, bars, rows=(rows[0], rv), cols=(cols[0], cv) if cols else None,
                        costs=profile, split=body.split, skip=skip)
    except bt.SpecError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _clean({
        "rows": hm.rows, "cols": hm.cols, "tuning": hm.tuning, "unseen": hm.unseen,
        "base": list(hm.base) if hm.base else None, "split_date": hm.split_date,
        "benchmark_tuning": hm.benchmark_tuning, "benchmark_unseen": hm.benchmark_unseen,
        "trials": hm.trials, "cells": hm.cells, "row_label": rows[1],
        "col_label": cols[1] if cols else "", "text": hm.text(),
        "facts": relabel(hm.facts(), {"Trials in this family": "Trials"}),
    })


class RunRef(BaseModel):
    run_id: str
    short_rate: float | None = None     # US: your ordinary-income rate, as a fraction


@router.post("/api/strategy/after-tax")
def strategy_after_tax(body: RunRef) -> dict[str, Any]:
    """*After-tax*: each year's realised gains taxed at the dated table's rates."""
    res = get_run(body.run_id)
    if body.short_rate is not None and not 0 <= body.short_rate <= 0.6:
        raise HTTPException(400, "Your short-term rate must be between 0% and 60%.")
    tax = res.after_tax(short_rate=body.short_rate if res.market == "US" else None)
    return _clean({
        "taxes": {str(k): v for k, v in tax["taxes"].items()}, "total_tax": tax["total_tax"],
        "after_tax_return": tax["after_tax_return"], "short_rate": tax["short_rate"],
        "long_rate": tax["long_rate"], "short_rate_assumed": tax["short_rate_assumed"],
        "line": (np.asarray(tax["equity"]) * 100 / res.capital).tolist(),
        "as_of": reference.as_of(),
    })


class SendIn(BaseModel):
    run_id: str
    tag: str = "trend_lab"


@router.post("/api/strategy/send-backtest")
def strategy_send_backtest(body: SendIn) -> dict[str, Any]:
    """*Send to Backtest Report*: save the run; the report opens it as the current one."""
    res = get_run(body.run_id)
    return {"id": remember_saved(res, body.tag)}


@router.post("/api/strategy/send-paper")
def strategy_send_paper(body: SendIn) -> dict[str, Any]:
    """*Send to Paper Desk*: pending paper orders for the next open. Nothing fills until Accept."""
    from ...paper.pending import draft_pending
    res = get_run(body.run_id)
    orders = res.next_orders()
    grade = res.card().grade
    ids = []
    for o in orders:
        o["note"] = (f"Trend Lab: {res.spec.read_back()} Report Card: {grade}. Fills at the "
                     "next session's open after you Accept.")
        ids.append(draft_pending(o, source="Trend Lab"))
    return _clean({"ids": ids, "orders": orders, "grade": grade})


# ------------------------------------------------------------------ Pairs Lab
PAIR_LABELS = {"Hedge ratio (beta)": "Hedge ratio", "Engle–Granger t": "Cointegration t",
               "Spread standard deviation (log)": "Spread width (sd)"}


@router.get("/api/strategy/pairs/universes")
def pairs_universes() -> list[dict[str, Any]]:
    from ... import pairs
    lists = [{"name": "Lesson 26 sample (SYN-A to SYN-D)", "symbols": list(pairs.SAMPLE_UNIVERSE)}]
    for w in store().all("watchlists"):
        syms = w.get("symbols") or []
        if syms:
            lists.append({"name": f"Watchlist: {w.get('name', w['id'])}", "symbols": list(syms)})
    return lists


class FindIn(BaseModel):
    symbols: list[str]
    market: str = "US"
    formation: int = Field(250, ge=60, le=1000)


@router.post("/api/strategy/pairs/find")
def pairs_find(body: FindIn) -> list[dict[str, Any]]:
    """Pair finder: correlation and the Engle–Granger test side by side."""
    from ... import pairs
    syms = [s.strip().upper() for s in body.symbols if s.strip()]
    if len(syms) < 2:
        raise HTTPException(400, "Choose at least two symbols to test.")
    return _clean([{"a": c.a, "b": c.b, "correlation": c.correlation, "adf_t": c.adf_t,
                    "critical_5": c.critical_5, "passes": c.passes, "half_life": c.half_life,
                    "beta": c.beta}
                   for c in pairs.find_pairs(syms, body.market, body.formation)])


class FitIn(BaseModel):
    a: str
    b: str
    market: str = "US"
    formation: int = Field(250, ge=60, le=1000)
    entry: float = Field(2.0, ge=0.5, le=5.0)
    exit: float = Field(0.5, ge=0.0, le=3.0)
    stop: float = Field(3.5, ge=1.0, le=10.0)
    time_stop: int | None = Field(None, ge=1, le=500)


def _fit(body: FitIn) -> tuple[Any, Any, list[Any], int | None, int]:
    from ... import pairs
    try:
        fit = pairs.fit_symbols(body.a, body.b, body.market, body.formation)
    except Exception as exc:
        raise HTTPException(400, f"Could not load {body.a} / {body.b}: {exc}") from exc
    default_ts = max(1, round(3 * fit.half_life)) if fit.half_life < 1e6 else 60
    rule = pairs.PairRule(body.entry, body.exit, body.stop, body.time_stop or default_ts)
    trades, suspended = pairs.run_rule(fit.z, fit.spread, fit.formation, rule)
    return fit, rule, trades, suspended, default_ts


@router.post("/api/strategy/pairs/fit")
def pairs_fit(body: FitIn) -> dict[str, Any]:
    """Spread z-score on the frozen formation window, the written rule, and its trades."""
    fit, rule, trades, suspended, default_ts = _fit(body)
    return _clean({
        "a": fit.a, "b": fit.b, "formation": fit.formation, "beta": fit.beta,
        "half_life": fit.half_life, "adf_t": fit.adf_t, "critical_5": fit.critical_5,
        "cointegrated": fit.cointegrated, "sd": fit.sd, "correlation": fit.correlation,
        "z": fit.z.tolist(), "default_time_stop": default_ts, "rule": rule.__dict__,
        "trades": [{**t.__dict__, "sessions": t.sessions} for t in trades],
        "suspended": suspended, "latest_z": float(fit.z[-1]),
        "facts": relabel(fit.facts(), PAIR_LABELS),
        "lots": {"a": reference.lot_size(fit.a), "b": reference.lot_size(fit.b)},
    })


class SizeIn(BaseModel):
    market: str = "US"
    beta: float
    price_a: float = Field(gt=0)
    price_b: float = Field(gt=0)
    lot_a: int = Field(1000, ge=1)
    lot_b: int = Field(2000, ge=1)
    capital: float = Field(10_000.0, ge=0)
    borrow_pct: float = Field(3.0, ge=0, le=100)
    days: int = Field(16, ge=1, le=365)


def _size_facts(facts: list[str], market: str) -> list[str]:
    out = []
    for f in facts:
        head, _, tail = f.partition(":")
        if head == "Rounded":
            out.append(f"{'Short B (rounded)' if market == 'IN' else 'Short B'}:{tail}")
        elif head == "Hedge ratio achieved":
            out.append(f"Hedge-ratio error: achieved{tail}")
        elif head.startswith("Borrow fee at"):
            out.append(f"Borrow fee:{tail} ({head[len('Borrow fee '):]})")
        else:
            out.append(f)
    return out


@router.post("/api/strategy/pairs/size")
def pairs_size(body: SizeIn) -> dict[str, Any]:
    """Sizing panel: India in whole futures lots, US in whole shares plus the borrow fee."""
    from ... import pairs
    if body.market == "IN":
        s = pairs.size_lots(body.price_a, body.price_b, body.lot_a, body.lot_b, body.beta)
        near = pairs.lots_within(body.price_a, body.price_b, body.lot_a, body.lot_b, body.beta)
        return _clean({
            "market": "IN", "lots_a": s.lots_a, "lots_b": s.lots_b, "value_a": s.value_a,
            "value_b": s.value_b, "target_lots_b": s.target_lots_b, "error": s.error,
            "achieved": s.achieved, "qty_a": s.lots_a * body.lot_a, "qty_b": s.lots_b * body.lot_b,
            "near": None if near is None else {"lots_a": near.lots_a, "lots_b": near.lots_b,
                                               "gross": near.value_a + near.value_b},
            "facts": _size_facts(s.facts(), "IN")})
    if body.capital < body.price_a:
        raise HTTPException(400, "Capital for the long leg is less than one share of A.")
    s = pairs.size_shares(body.capital, body.price_a, body.price_b, body.beta,
                          body.borrow_pct / 100, body.days)
    return _clean({
        "market": "US", "shares_a": s.shares_a, "shares_b": s.shares_b, "value_a": s.value_a,
        "value_b": s.value_b, "error": s.error, "achieved": s.achieved,
        "borrow_fee": s.borrow_fee, "qty_a": s.shares_a, "qty_b": s.shares_b,
        "facts": _size_facts(s.facts(), "US")})


class LinkIn(BaseModel):
    a: str
    b: str
    description: str = ""
    market: str = "US"


@router.post("/api/strategy/pairs/check-link")
def pairs_check_link(body: LinkIn) -> dict[str, Any]:
    """*Check link*: the AI's economic-link note. Nothing is kept until Accept."""
    from ... import pairs
    out = pairs.check_link(body.a, body.b, body.description,
                           "NSE" if body.market == "IN" else "NYSE")
    return {"text": out.text, "rating": pairs.link_rating(out.text), "where": out.where,
            "model": out.model}


class LinkAcceptIn(BaseModel):
    a: str
    b: str
    text: str
    rating: str


@router.post("/api/strategy/pairs/accept-link")
def pairs_accept_link(body: LinkAcceptIn) -> dict[str, Any]:
    if body.rating not in ("Strong", "Weak", "None"):
        raise HTTPException(400, "Only a rated note (Strong, Weak or None) can be kept.")
    nid = store().add("notes", {"screen": "Pairs Lab", "pair": f"{body.a}/{body.b}",
                                "rating": body.rating, "text": body.text}, tag="pair_link")
    return {"id": nid, "rating": body.rating}


@router.post("/api/strategy/pairs/send-backtest")
def pairs_send_backtest(body: FitIn) -> dict[str, Any]:
    """Store the pair run for the Backtest Report and add one to the Trials counter."""
    from ... import pairs
    fit, rule, trades, suspended, _ = _fit(body)
    bid = pairs.send_to_backtest(fit, rule, trades, suspended)
    return {"id": bid, "trials": store().count("trials", tag="pairs")}


class PairPaperIn(FitIn):
    qty_a: float = Field(gt=0)
    qty_b: float = Field(gt=0)
    events: str = ""


@router.post("/api/strategy/pairs/send-paper")
def pairs_send_paper(body: PairPaperIn) -> dict[str, Any]:
    """Two linked pending paper orders. Nothing fills until Accept on the Paper Desk."""
    from ... import pairs
    fit, rule, _, suspended, _ = _fit(body)
    if not fit.cointegrated or suspended:
        raise HTTPException(400, "Send to Paper Desk needs a pair that passes the test and is "
                                 "not suspended.")
    side = 1 if fit.z[-1] < 0 else -1
    ids = pairs.send_to_paper_desk(fit, side, body.qty_a, body.qty_b, rule, body.events,
                                   body.market)
    return {"ids": ids, "side": "long A / short B" if side > 0 else "short A / long B"}
