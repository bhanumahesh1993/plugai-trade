"""API routes: Research (b) — Chart Helper, Earnings Desk, IPO Dashboard.

Thin wrappers over ``plugai_trade.charthelper``, ``plugai_trade.earnings`` and
``plugai_trade.ipo``. Every number is computed by those engines; the routes only
shape their results as JSON.
"""

from __future__ import annotations

import base64
from datetime import date, timedelta
from typing import Any

import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import clean as _clean

router = APIRouter()

P = "/api/research-b"


def _market(m: str) -> str:
    m = (m or "IN").upper()
    if m not in ("IN", "US"):
        raise HTTPException(400, "Market must be IN or US.")
    return m


def _rows(df: pl.DataFrame) -> list[dict[str, Any]]:
    return _clean(df.to_dicts())


# ================================================================== Chart Helper
DEFAULT_SYMBOL = {"IN": "NIFTY", "US": "SPY"}
SOURCES = {"Synthetic": "synthetic", "Data Sources (Settings)": None}


class ChartIn(BaseModel):
    symbol: str = ""
    market: str = "IN"
    timeframe: str = "Daily"
    data: str = "Synthetic"  # a key of SOURCES


def _load(body: ChartIn) -> tuple[pl.DataFrame, str, str]:
    from ... import charthelper as ch

    mkt = _market(body.market)
    sym = (body.symbol or DEFAULT_SYMBOL[mkt]).upper().strip()
    if body.timeframe not in ch.TIMEFRAMES:
        raise HTTPException(400, f"Timeframe must be one of {', '.join(ch.TIMEFRAMES)}.")
    if body.data not in SOURCES:
        raise HTTPException(400, f"Data must be one of {', '.join(SOURCES)}.")
    try:
        bars = ch.load(sym, mkt, body.timeframe, source=SOURCES[body.data])
    except Exception as exc:  # a source failure is shown, the screen keeps working
        raise HTTPException(400, f"Could not load {sym}: {exc}. Check the symbol, or switch "
                                 "Data to Synthetic.") from exc
    if bars.height < 20:
        raise HTTPException(400, f"Only {bars.height} bars for {sym}. Pick another symbol or "
                                 "timeframe.")
    return bars, sym, mkt


def _chart_bars(bars: pl.DataFrame) -> list[dict[str, Any]]:
    view = bars.tail(60)
    cols = ["date", "open", "high", "low", "close"] + (["time"] if "time" in view.columns else [])
    return _rows(view.select(cols))


def _provenance(bars: pl.DataFrame) -> dict[str, Any]:
    last = bars.row(-1, named=True)
    return _clean({"source": last.get("source"), "fetched_at": last.get("fetched_at"),
                   "license_class": last.get("license_class"),
                   "asof": last.get("time") or last.get("date"), "bars": bars.height})


@router.get(f"{P}/chart/options")
def chart_options() -> dict[str, Any]:
    from ... import charthelper as ch
    return {"timeframes": list(ch.TIMEFRAMES), "sources": list(SOURCES),
            "default_symbol": DEFAULT_SYMBOL, "or_minutes": [5, 15, 30]}


@router.post(f"{P}/chart/bars")
def chart_bars(body: ChartIn) -> dict[str, Any]:
    bars, sym, mkt = _load(body)
    return {"symbol": sym, "market": mkt, "timeframe": body.timeframe,
            "bars": _chart_bars(bars), "provenance": _provenance(bars)}


class DescribeIn(ChartIn):
    screenshot: bool = False


@router.post(f"{P}/chart/describe")
def chart_describe(body: DescribeIn) -> dict[str, Any]:
    from ... import charthelper as ch

    bars, sym, _ = _load(body)
    d = ch.describe(bars, sym, body.timeframe)
    out: dict[str, Any] = {"symbol": sym, "timeframe": body.timeframe, "asof": d.asof,
                           "values": d.values, "lines": d.lines, "facts": d.facts(),
                           "claims": None}
    if body.screenshot:
        claims = ch.screenshot_claims(d, ch.levels(bars, sym))
        out["claims"] = [{"Claim": c.text, "Check": c.check, "Against the table": c.why}
                         for c in claims]
        out["crosses"] = sum(c.check == "✗" for c in claims)
    return _clean(out)


class LevelsIn(ChartIn):
    set: str = "Zones"  # Zones | Intraday
    or_minutes: int = 15


def _levels(body: LevelsIn):
    from ... import charthelper as ch

    bars, sym, mkt = _load(body)
    if body.set == "Intraday":
        if body.or_minutes not in (5, 15, 30):
            raise HTTPException(400, "Opening range must be 5, 15 or 30 minutes.")
        intra = bars if "time" in bars.columns else ch.load(sym, mkt, "5-min")
        daily = ch.load(sym, mkt, "Daily", end=intra["date"][-1], source="synthetic")
        prev = daily.filter(pl.col("date") < intra["date"][-1]).row(-1, named=True)
        return ch.intraday_levels(intra, prev, body.or_minutes, sym), sym, mkt
    if body.set != "Zones":
        raise HTTPException(400, "Levels set must be Zones or Intraday.")
    return ch.levels(bars, sym), sym, mkt


@router.post(f"{P}/chart/levels")
def chart_levels(body: LevelsIn) -> dict[str, Any]:
    from ... import charthelper as ch

    lv, sym, _ = _levels(body)
    if isinstance(lv, ch.Levels):
        lines = [{"price": (z.low + z.high) / 2, "label": z.kind, "kind": z.kind}
                 for z in lv.zones if z.touches >= 2 or z.kind.startswith(("Pivot P", "POC"))]
        meta = {"close": lv.close, "atr": lv.atr, "asof": lv.asof}
    else:
        lines = [{"price": v, "label": k, "kind": k} for k, v in lv.values.items()]
        meta = {"values": lv.values, "or_minutes": lv.or_minutes}
    return _clean({"symbol": sym, "set": body.set, "table": lv.table().to_dicts(),
                   "lines": lines, "facts": lv.facts(), **meta})


@router.post(f"{P}/chart/levels/save")
def chart_levels_save(body: LevelsIn) -> dict[str, Any]:
    from ... import charthelper as ch

    lv, sym, mkt = _levels(body)
    return {"id": ch.save_levels_to_journal(sym, mkt, body.timeframe, lv)}


@router.post(f"{P}/chart/levels/send")
def chart_levels_send(body: LevelsIn) -> dict[str, Any]:
    from ... import charthelper as ch

    lv, sym, mkt = _levels(body)
    return {"id": ch.send_levels_to_paper_desk(sym, mkt, lv)}


class TimeframesIn(ChartIn):
    frames: list[str] = Field(default_factory=lambda: ["Daily", "Weekly", "15-min"])


@router.post(f"{P}/chart/timeframes")
def chart_timeframes(body: TimeframesIn) -> dict[str, Any]:
    from ... import charthelper as ch

    mkt = _market(body.market)
    sym = (body.symbol or DEFAULT_SYMBOL[mkt]).upper().strip()
    bad = [f for f in body.frames if f not in ch.TIMEFRAMES]
    if bad or not body.frames:
        raise HTTPException(400, f"Pick one or more of {', '.join(ch.TIMEFRAMES)}.")
    try:
        df = ch.timeframes(sym, mkt, body.frames, source=SOURCES.get(body.data))
    except Exception as exc:
        raise HTTPException(400, f"Could not load {sym}: {exc}") from exc
    return {"rows": _rows(df)}


# ================================================================== Earnings Desk
SAMPLE_WATCH = {"IN": ["SYN-IN-004", "SYN-IN-010", "SYN-IN-027"],
                "US": ["SYN-US-006", "SYN-US-012"]}
INDEX = {"IN": "NIFTY", "US": "SPY"}
MOVE_DEFAULT = {"IN": "NIFTY", "US": "SYN-US-006"}
DIGEST_SAMPLES = {"Kaveri Pumps (fictional) · Q2 FY27": "Kaveri_Q2-FY27_results"}


def _positions(mkt: str) -> list[str]:
    from ...store import default as store
    rows = store().all("paper_positions")
    return sorted({str(r.get("symbol")) for r in rows
                   if r.get("symbol") and r.get("market", mkt) == mkt})


@router.get(f"{P}/earnings/setup")
def earnings_setup(market: str = "IN") -> dict[str, Any]:
    """Screen load: saved watchlists, open paper positions, samples; fills actual moves."""
    from ... import earnings, screener

    mkt = _market(market)
    filled = earnings.fill_actual_moves()
    return _clean({"watchlists": [{"name": w["name"], "symbols": w["symbols"]}
                                  for w in screener.watchlists(mkt)],
                   "positions": _positions(mkt), "sample": SAMPLE_WATCH[mkt],
                   "samples": list(DIGEST_SAMPLES), "move_default": MOVE_DEFAULT[mkt],
                   "actual_moves_filled": filled, "today": date.today()})


class CalendarIn(BaseModel):
    market: str = "IN"
    symbols: list[str] = Field(default_factory=list)
    start: date | None = None
    days: int = 7
    macro: bool = False


def _calendar(body: CalendarIn) -> list[dict[str, Any]]:
    from ... import earnings

    mkt = _market(body.market)
    if not 5 <= body.days <= 60:
        raise HTTPException(400, "Days must be between 5 and 60.")
    syms = [s.strip().upper() for s in body.symbols if s.strip()]
    return earnings.results_calendar(syms, mkt, body.start or date.today(), body.days,
                                     body.macro, _positions(mkt))


@router.post(f"{P}/earnings/calendar")
def earnings_calendar(body: CalendarIn) -> dict[str, Any]:
    from ... import ai

    rows = _calendar(body)
    obj: dict[str, Any] = {"rows": len(rows)}
    for r in rows:  # same fact shape as the classic page; a second event at the same time is kept
        key, n = f"{r['Date']} {r['Time']}", 2
        while key in obj:
            key, n = f"{r['Date']} {r['Time']} ({n})", n + 1
        obj[key] = f"{r['Event']} ({r['Status']}; {r['Source']})" + (
            f" · OVERLAP: {r['Overlap']}" if r["Overlap"] else "")
    return _clean({"rows": rows, "facts": ai.facts_from(obj)})


class ImportIn(BaseModel):
    market: str = "IN"
    watchlists: list[str] = Field(default_factory=list)


@router.post(f"{P}/earnings/import")
def earnings_import(body: ImportIn) -> dict[str, Any]:
    """Import watchlist: the picked lists plus open paper positions (sample if empty)."""
    from ... import screener

    mkt = _market(body.market)
    saved = {w["name"]: w["symbols"] for w in screener.watchlists(mkt)}
    names = [s for p in body.watchlists for s in saved.get(p, [])] + _positions(mkt)
    return {"symbols": list(dict.fromkeys(names or SAMPLE_WATCH[mkt]))}


@router.post(f"{P}/earnings/alerts")
def earnings_alerts(body: CalendarIn) -> dict[str, Any]:
    from ... import earnings

    rows = _calendar(body)
    if not rows:
        raise HTTPException(400, "No events in this window to send. Widen Days or add names.")
    return {"ids": earnings.send_to_alerts(rows, _market(body.market))}


class DigestIn(BaseModel):
    market: str = "IN"
    company: str = "Kaveri Pumps (fictional)"
    sample: str = next(iter(DIGEST_SAMPLES))
    pdf_base64: str | None = None
    pdf_name: str | None = None


def _digest_json(d: Any) -> dict[str, Any]:
    from dataclasses import asdict
    return _clean({"digest": asdict(d), "facts": d.facts()})


@router.post(f"{P}/earnings/digest")
def earnings_digest(body: DigestIn) -> dict[str, Any]:
    from ... import docdesk, earnings

    mkt = _market(body.market)
    try:
        if body.pdf_base64:
            doc = docdesk.load_pdf(base64.b64decode(body.pdf_base64), name=body.pdf_name,
                                   market=mkt)
        else:
            if body.sample not in DIGEST_SAMPLES:
                raise HTTPException(400, "Pick a sample filing from the list.")
            doc = docdesk.sample(DIGEST_SAMPLES[body.sample])
    except docdesk.DocError as exc:
        raise HTTPException(400, f"{exc}. Try another PDF or use the sample filing.") from exc
    except ValueError as exc:
        raise HTTPException(400, "The file could not be decoded. Drop the PDF again.") from exc
    prior = earnings.last_guidance(body.company) or (
        {"quote": "For the full year we continue to guide for mid-teens revenue growth.",
         "cite": "[Q1 p. 4]"} if "Kaveri" in body.company else None)
    return _digest_json(earnings.digest(doc, body.company, prior))


class DigestBody(BaseModel):
    company: str
    rows: list[dict[str, Any]]
    guidance_now: str
    guidance_cite: str
    guidance_before: str = ""
    guidance_before_cite: str = ""
    chip: str = "no previous digest"
    consensus: list[dict[str, Any]] = Field(default_factory=list)


def _to_digest(b: DigestBody):
    from ... import earnings
    return earnings.Digest(**b.model_dump())


class ConsensusIn(BaseModel):
    digest: DigestBody
    item: str
    value: float
    source: str
    as_of: date | None = None


@router.post(f"{P}/earnings/consensus")
def earnings_consensus(body: ConsensusIn) -> dict[str, Any]:
    from ... import earnings

    if not body.source.strip():
        raise HTTPException(400, "Add the source of the consensus figure (where you copied it).")
    d = _to_digest(body.digest)
    if body.item not in [r["Item"] for r in d.rows]:
        raise HTTPException(400, "Pick an item from the digest table.")
    earnings.add_consensus(d, body.item, body.value, body.source.strip(),
                           (body.as_of or date.today()).isoformat())
    return _digest_json(d)


class AcceptDigestIn(BaseModel):
    digest: DigestBody
    market: str = "IN"


@router.post(f"{P}/earnings/digest/accept")
def earnings_digest_accept(body: AcceptDigestIn) -> dict[str, Any]:
    from ... import earnings
    return {"id": earnings.save_digest(_to_digest(body.digest), _market(body.market))}


@router.get(f"{P}/earnings/history")
def earnings_history(company: str) -> dict[str, Any]:
    from ... import earnings
    return _clean({"rows": [{"created": h["created"][:10], "guidance": h["guidance"]["quote"],
                             "cite": h["guidance"].get("cite", ""), "chip": h["chip"]}
                            for h in earnings.history(company)]})


def _move_events(sym: str, mkt: str) -> list[Any]:
    from ...earnings import calendar

    today = date.today()
    if sym in (INDEX[mkt], "NIFTY", "BANKNIFTY", "SPY"):
        return calendar.macro_events(mkt, today, today + timedelta(days=90))
    return calendar.results_dates(sym, mkt, today, today + timedelta(days=120))


@router.get(f"{P}/earnings/move/events")
def earnings_move_events(symbol: str, market: str = "IN") -> dict[str, Any]:
    mkt = _market(market)
    sym = symbol.upper().strip()
    return {"symbol": sym, "events": [e.label() for e in _move_events(sym, mkt)]}


class MoveIn(BaseModel):
    symbol: str
    market: str = "IN"
    event: str | None = None  # a label from /move/events; first row when omitted
    quiet_pct: float = 0.0  # Event split: normal-day move from a quiet week, %; 0 = realised vol


def _implied(body: MoveIn):
    from ... import earnings

    mkt = _market(body.market)
    sym = body.symbol.upper().strip()
    evs = _move_events(sym, mkt)
    if not evs:
        raise HTTPException(400, f"No scheduled event for {sym} in the next months. "
                                 "Try another symbol.")
    labels = [e.label() for e in evs]
    if body.event and body.event not in labels:
        raise HTTPException(400, "That calendar row is no longer listed. Pick a row again.")
    ev = evs[labels.index(body.event) if body.event else 0]
    return earnings.implied_move(sym, mkt, ev, date.today()), sym, mkt, ev


@router.post(f"{P}/earnings/move")
def earnings_move(body: MoveIn) -> dict[str, Any]:
    from ... import earnings

    im, sym, mkt, ev = _implied(body)
    if im is None:
        return _clean({"available": False, "symbol": sym, "event": ev.label(),
                       "moves": earnings.historical_moves(sym, mkt, date.today())})
    if not 0 <= body.quiet_pct <= 10:
        raise HTTPException(400, "Normal-day move must be between 0 and 10%.")
    return _clean({
        "available": True, "symbol": sym, "market": mkt, "event": ev.label(),
        "event_title": im.event, "event_date": im.event_date, "expiry": im.expiry,
        "spot": im.spot, "strike": im.strike, "call": im.call, "put": im.put,
        "straddle": im.straddle, "implied_move_pct": im.implied_move_pct,
        "chain_source": im.chain_source, "tiles": im.tiles(), "moves": im.moves,
        "scenarios": im.scenarios().to_dicts(),
        "split": im.event_split(body.quiet_pct / 100 if body.quiet_pct else None),
        "facts": im.facts(),
    })


@router.post(f"{P}/earnings/move/options-builder")
def earnings_move_options(body: MoveIn) -> dict[str, Any]:
    from ... import earnings

    im, *_ = _implied(body)
    if im is None:
        raise HTTPException(400, "No listed options for this name, so there is no straddle "
                                 "to open.")
    return _clean({"id": earnings.open_in_options_builder(im), "symbol": im.symbol,
                   "strike": im.strike, "expiry": im.expiry})


@router.post(f"{P}/earnings/move/journal")
def earnings_move_journal(body: MoveIn) -> dict[str, Any]:
    from ... import earnings

    im, *_ = _implied(body)
    if im is None:
        raise HTTPException(400, "No implied move for this name (not in the F&O list).")
    return {"id": earnings.save_move_to_journal(im)}


# ================================================================== IPO Dashboard
def _issue(name: str):
    from ... import ipo

    x = next((i for i in ipo.ipos_open() if i.name == name), None)
    if x is None:
        raise HTTPException(400, f"No open IPO named “{name}”. Pick one from IPOs open.")
    return x


@router.get(f"{P}/ipo/issues")
def ipo_issues() -> dict[str, Any]:
    from ... import ipo

    r = ipo.rules()
    return _clean({"issues": [i.as_record() for i in ipo.ipos_open()],
                   "rules_as_of": r.get("as_of"), "sme_source": r.get("sme", {}).get("source"),
                   "gmp_banner": ipo.GMP_BANNER, "scenarios": list(ipo.DEFAULT_SCENARIOS)})


class AddIpoIn(BaseModel):
    name: str
    board: str = "Mainboard"
    platform: str = ""
    price_low: float = 100.0
    price_high: float = 105.0
    lot: int = 140
    rhp_link: str = ""


@router.post(f"{P}/ipo/add")
def ipo_add(body: AddIpoIn) -> dict[str, Any]:
    from ... import ipo

    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Type the company name.")
    if body.board not in ("Mainboard", "SME"):
        raise HTTPException(400, "Board must be Mainboard or SME.")
    if body.price_high < body.price_low or body.lot < 1:
        raise HTTPException(400, "Price band high must be at least the low, and lot at least 1.")
    platform = body.platform or ("NSE / BSE" if body.board == "Mainboard" else "NSE Emerge")
    iid = ipo.add_ipo(ipo.Issue(
        name=name, board=body.board, platform=platform, price_low=body.price_low,
        price_high=body.price_high, lot=int(body.lot), fresh_shares=0, ofs_shares=0,
        pre_issue_shares=0, promoter_pre_shares=0, promoter_sell_shares=0, pat_cr=0.0,
        peer_pe=[], anchor_shares=0, objects_cr={}, offered={"Retail": float(body.lot)}),
        body.rhp_link)
    return {"id": iid, "name": name}


class IssueIn(BaseModel):
    name: str


@router.post(f"{P}/ipo/rhp")
def ipo_rhp(body: IssueIn) -> dict[str, Any]:
    from ... import ipo

    x = _issue(body.name)
    dg = ipo.rhp_digest(x)
    return _clean({"tiles": dg.tiles, "quotes": {k: dg.quote_for(k) for k in dg.tiles},
                   "rows": [{"Item": r.field, "Quote": r.quote or "not found", "Page": r.cite,
                             "status": r.status} for r in dg.rows],
                   "facts": dg.facts()})


@router.post(f"{P}/ipo/rhp/accept")
def ipo_rhp_accept(body: IssueIn) -> dict[str, Any]:
    from ... import ipo

    x = _issue(body.name)
    return {"id": ipo.save_record(x, "rhp_digest", {"tiles": ipo.rhp_digest(x).tiles})}


class SubIn(IssueIn):
    day: int = 3


@router.post(f"{P}/ipo/subscription")
def ipo_subscription(body: SubIn) -> dict[str, Any]:
    from ... import ipo

    if body.day not in (1, 2, 3):
        raise HTTPException(400, "Day must be 1, 2 or 3.")
    x = _issue(body.name)
    days = {d: ipo.subscription(x, ipo.sample_bids(x, d)) for d in (1, 2, 3)}
    return _clean({"rows": days[body.day], "by_day": days,
                   "source": "fictional sample bids"})


class OddsIn(IssueIn):
    applications: float = 0  # 0 = use the lab's estimate
    applicants: int = 1


@router.post(f"{P}/ipo/odds")
def ipo_odds(body: OddsIn) -> dict[str, Any]:
    from ... import ipo

    if not 1 <= body.applicants <= 20:
        raise HTTPException(400, "Applicants must be between 1 and 20.")
    if body.applications < 0:
        raise HTTPException(400, "Valid applications cannot be negative.")
    x = _issue(body.name)
    cat = "Retail" if "Retail" in x.offered else list(x.offered)[-1]
    o = ipo.allotment_odds(x, body.applications or None, body.applicants, cat,
                           min_lots=2 if x.board == "SME" else 1)
    return _clean({"category": cat, "p": o.p, "at_least_one": o.at_least_one,
                   "money_blocked": o.money_blocked, "lots_available": o.lots_available,
                   "applications": o.applications, "is_estimate": o.applications_is_estimate,
                   "applicants": o.applicants, "facts": o.facts()})


class GmpIn(BaseModel):
    figures: dict[str, float] = Field(default_factory=dict)


@router.post(f"{P}/ipo/gmp")
def ipo_gmp(body: GmpIn) -> dict[str, Any]:
    from ... import ipo
    return _clean(ipo.gmp_panel(body.figures))


@router.post(f"{P}/ipo/sme")
def ipo_sme(body: IssueIn) -> dict[str, Any]:
    """SME checker header and Liquidity panel (checks run separately)."""
    from ... import docdesk, ipo

    x = _issue(body.name)
    if x.board != "SME":
        return {"sme": False}
    doc = docdesk.sample(x.rhp_sample) if x.rhp_sample else None
    r = ipo.rules()
    return _clean({"sme": True, "platform": x.platform, "lot": x.lot,
                   "rules_as_of": r["as_of"], "source": r["sme"]["source"],
                   "has_doc": doc is not None,
                   "liquidity": ipo.liquidity(x, doc) if doc else None})


def _sme_checks(x: Any) -> list[Any]:
    from ... import docdesk, ipo

    if x.board != "SME":
        raise HTTPException(400, "Pick an SME issue (NSE Emerge / BSE SME) from IPOs open.")
    if not x.rhp_sample:
        raise HTTPException(400, "Load this issue's RHP in the Document Desk first.")
    return ipo.sme_checks(docdesk.sample(x.rhp_sample))


@router.post(f"{P}/ipo/sme/run")
def ipo_sme_run(body: IssueIn) -> dict[str, Any]:
    from ... import ai

    checks = _sme_checks(_issue(body.name))
    facts = {c.rule: f"{c.status} — {c.quote} {c.cite}" for c in checks}
    return _clean({"checks": [{"Rule": c.rule, "Quoted figure": c.quote or "—", "Page": c.cite,
                               "Status": c.status, "searched": c.searched} for c in checks],
                   "facts": ai.facts_from(facts)})


@router.post(f"{P}/ipo/sme/accept")
def ipo_sme_accept(body: IssueIn) -> dict[str, Any]:
    from ... import ipo

    x = _issue(body.name)
    facts = {c.rule: f"{c.status} — {c.quote} {c.cite}" for c in _sme_checks(x)}
    return {"id": ipo.save_record(x, "sme_check", {"checks": facts})}


class PlanIn(IssueIn):
    shares: int | None = None
    scenarios: list[float] | None = None
    actions: list[str] | None = None


def _plan(body: PlanIn):
    from ... import ipo

    x = _issue(body.name)
    shares = body.shares if body.shares is not None else x.lot * (2 if x.board == "SME" else 1)
    if shares < 0:
        raise HTTPException(400, "Shares allotted cannot be negative.")
    scen = tuple(body.scenarios) if body.scenarios else ipo.DEFAULT_SCENARIOS
    acts = list(body.actions or [])
    acts = (acts + [""] * len(scen))[: len(scen)]
    return x, int(shares), ipo.listing_plan(x, int(shares), scen, acts)


@router.post(f"{P}/ipo/plan")
def ipo_plan(body: PlanIn) -> dict[str, Any]:
    x, shares, plan = _plan(body)
    return _clean({"shares": shares, "issue_price": x.price_high,
                   "listing_date": x.listing_date or None, "plan": plan})


@router.post(f"{P}/ipo/plan/critique")
def ipo_plan_critique(body: PlanIn) -> dict[str, Any]:
    from ... import ipo
    from ...store import default as store

    _, _, plan = _plan(body)
    cards = store().all("rule_cards", limit=1)
    return {"text": ipo.critique(plan, str(cards[0]) if cards else "")}


@router.post(f"{P}/ipo/plan/lockin")
def ipo_plan_lockin(body: IssueIn) -> dict[str, Any]:
    from ... import ipo

    x = _issue(body.name)
    rows = ipo.lock_in_calendar(x)
    ids = ipo.add_lock_ins_to_alerts(x)
    return _clean({"rows": rows, "alerts": len(ids)})


@router.post(f"{P}/ipo/plan/save")
def ipo_plan_save(body: PlanIn) -> dict[str, Any]:
    from ... import ipo

    x, shares, plan = _plan(body)
    return {"id": ipo.save_plan_to_journal(x, shares, plan)}
