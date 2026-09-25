"""API routes: backtest (Strategy › Backtest Report, Chapters 11 and 18).

Every number comes from ``plugai_trade.backtest``. Results are kept in memory by
their ``backtests`` row id, so a hand-off (Strategy Builder *Backtest*, Trend Lab
*Send to Backtest Report*) is simply "the newest saved report"; a saved report that
is no longer in memory is rebuilt from its spec and data window without adding a
trial. The strategy routes (``strategy.py``) import the helpers here.
"""

from __future__ import annotations

import uuid
from datetime import date
from functools import lru_cache
from typing import Any

import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import data, reference
from ...store import default as store
from .. import clean as _clean

router = APIRouter()

# ------------------------------------------------------------------ shared constants
INSTRUMENTS = {"IN": ["NIFTY", "BANKNIFTY", "SENSEX", "SYN-A"], "US": ["SPY", "QQQ", "DIA", "IWM"]}
SECTORS = {
    "IN": ["NIFTYIT", "NIFTYBANK", "NIFTYFMCG", "NIFTYPHARMA", "NIFTYAUTO", "NIFTYMETAL",
           "NIFTYENERGY", "NIFTYREALTY"],
    "US": ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"],
}
PROFILES = {"IN": ["IN-equity-delivery", "IN-equity-intraday", "IN-futures"], "US": ["US-equity"]}
COST_LABELS = {"Delivery": "IN-equity-delivery", "Intraday": "IN-equity-intraday",
               "Futures": "IN-futures"}
TEST_END = date(2025, 12, 31)
SAMPLE_RULE = ("Buy at the next open on the first close above the 50-day average; sell at the "
               "next open when the close is below the 20-day average")

# Tile names are the book's (Chapter 11 table); facts are relabelled to match so a
# citation lights the tile it came from. Only the label moves, never the number.
RESULT_LABELS = {
    "Result after costs": "After costs",
    "Result before costs": "Before costs",
    "Worst drawdown after costs": "Worst drawdown",
    "Buy and hold over the same period": "Buy and hold",
    "Assumed slippage paid": "Assumed slippage",
    "Sharpe ratio after costs": "Sharpe (after costs)",
    "Trials in this family": "Trials",
}


def relabel(facts: list[str], labels: dict[str, str]) -> list[str]:
    """Rename the part before ':' (``Charges paid (X): v`` → ``Charges / fees: v (X)``)."""
    out = []
    for f in facts:
        head, sep, tail = f.partition(":")
        if sep and head.startswith("Charges paid ("):
            out.append(f"Charges / fees:{tail} ({head[len('Charges paid ('):-1]})")
        elif sep and head in labels:
            out.append(f"{labels[head]}:{tail}")
        else:
            out.append(f)
    return out


# ------------------------------------------------------------------ bars
@lru_cache(maxsize=256)
def _cached_bars(symbol: str, market: str, start: date, end: date, source: str | None
                 ) -> pl.DataFrame:
    return data.get(symbol, market=market, start=start, end=end, source=source)


def load_bars(symbol: str, market: str, years: int, synthetic: bool = True,
              end: date = TEST_END) -> tuple[pl.DataFrame, str | None]:
    """Daily bars for a test window, plus a notice when a free source fell back to synthetic."""
    start = date(end.year - int(years) + 1, 1, 1)
    try:
        df = _cached_bars(symbol, market, start, end, "synthetic" if synthetic else None)
    except data.DataUnavailable as exc:
        return _cached_bars(symbol, market, start, end, "synthetic"), \
            f"{exc}. Using synthetic data instead."
    if df.is_empty():
        raise HTTPException(400, f"No bars for {symbol} in {market}. Choose another instrument.")
    return df, None


# ------------------------------------------------------------------ results in memory
_BY_ID: dict[tuple[str, int], Any] = {}  # (lab database, backtests row id) → Result
_RUNS: dict[str, Any] = {}      # run id → Result (Trend Lab runs not yet sent anywhere)


def remember_saved(res: Any, tag: str) -> int:
    rid = res.save(tag=tag)
    _BY_ID[(store().db_path, rid)] = res
    return rid


def remember_run(res: Any) -> str:
    key = uuid.uuid4().hex[:12]
    _RUNS[key] = res
    if len(_RUNS) > 64:
        _RUNS.pop(next(iter(_RUNS)))
    return key


def get_run(run_id: str) -> Any:
    res = _RUNS.get(run_id)
    if res is None:
        raise HTTPException(400, "This run is no longer in memory (the lab was restarted). "
                                 "Click Run again.")
    return res


def _from_saved(row: dict[str, Any]) -> Any:
    """Rebuild a saved report from its spec and data window (not a new trial)."""
    from ... import backtest
    spec = backtest.Spec.from_dict(row["spec"])
    start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
    synthetic = row.get("source") == "synthetic"
    if row.get("source", "").startswith("futures"):
        raise HTTPException(400, "This report was run on a back-adjusted futures series that is "
                                 "no longer in memory. Send it again from the Trend Lab.")
    bars = {s: _cached_bars(s, row["market"], start, end, "synthetic" if synthetic else None)
            for s in row.get("symbols") or [row["symbol"]]}
    return backtest.run(spec, bars, costs=row["profile"], count_trial=False)


def result_for(rid: int) -> Any:
    key = (store().db_path, rid)
    if key in _BY_ID:
        return _BY_ID[key]
    row = store().get("backtests", rid)
    if row is None:
        raise HTTPException(400, f"No saved report #{rid}. Pick another from Saved reports.")
    if row.get("source") == "Pairs Lab" or "spec" not in row:
        raise HTTPException(400, f"Report #{rid} is a Pairs Lab run, not a rule backtest.")
    try:
        _BY_ID[key] = _from_saved(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Could not rebuild report #{rid}: {exc}") from exc
    return _BY_ID[key]


# ------------------------------------------------------------------ payloads
def _frame(res: Any, gross: bool = False) -> dict[str, Any]:
    f = res.frame(gross=gross)
    out = {"dates": [d.isoformat() for d in f["date"].to_list()],
           "equity": f["equity"].to_list(), "buy_and_hold": f["buy_and_hold"].to_list(),
           "drawdown": f["drawdown"].to_list(), "bh_drawdown": f["bh_drawdown"].to_list()}
    if gross:
        out["before_costs"] = f["before_costs"].to_list()
    return out


def summary_payload(res: Any) -> dict[str, Any]:
    """The Chapter 11 summary table as tiles, plus the equity/drawdown frame."""
    s, g = res.stats(), res.gross_stats()
    return {
        "meta": {"symbol": res.symbol, "symbols": res.symbols, "market": res.market,
                 "source": res.source, "start": res.dates[0], "end": res.dates[-1],
                 "profile": res.profile, "capital": res.capital, "origin": res.spec.origin,
                 "slippage_pct": res.spec.cost.slippage_pct},
        "read_back": res.spec.read_back(), "cards": res.spec.cards(), "digest": res.spec.digest(),
        "stats": s, "gross": g, "trials": res.trial_count(),
        "frame": _frame(res), "drawdown_story": res.drawdown_story(),
    }


def report_payload(res: Any) -> dict[str, Any]:
    card = res.card()
    wf = res.walk_forward()
    tf = res.trade_frame()
    keep = ["symbol", "entry_date", "exit_date", "bars", "units", "buy_value", "sell_value",
            "gross_pnl", "charges", "slippage", "net_pnl", "return_pct", "open"]
    trades = tf.select([c for c in keep if c in tf.columns]).to_dicts() if tf.height else []
    return {
        **summary_payload(res), "kind": "rule",
        "card": card.to_dict(), "facts": relabel(res.facts(), RESULT_LABELS),
        "walk_forward": {"windows": wf.windows, "in_sample_sharpe": wf.in_sample_sharpe,
                         "oos_sharpe": wf.oos_sharpe, "oos_return": wf.oos_return,
                         "oos_dates": wf.oos_dates, "oos_equity": wf.oos_equity,
                         "variants": wf.variants, "facts": wf.facts()},
        "trades": trades,
        "cost_labels": COST_LABELS if res.market == "IN" else {},
        "as_of": reference.as_of(),
    }


def _pairs_payload(row: dict[str, Any]) -> dict[str, Any]:
    trades = row.get("trades") or []
    net = row.get("net_log_returns") or []
    facts = [
        "All results are HYPOTHETICAL (spread trades on past or synthetic data).",
        f"Pair: {row.get('name', '').replace('Pair ', '')}",
        f"Hedge ratio: {row.get('hedge_ratio', 0):.3f}",
        f"Half-life: {row.get('half_life', 0):.1f} sessions",
        f"Cointegration t: {row.get('adf_t', 0):.2f}",
        f"Round trips: {len(trades)}",
        f"Spread P&L (log): {sum(net):+.4f}",
        f"Trials: {store().count('trials', tag='pairs')} pairs tested in the Pairs Lab",
    ]
    if row.get("suspended_at"):
        facts.append(f"Suspended at session {row['suspended_at']} after the stop")
    return {"kind": "pairs", "id": row["id"], "name": row.get("name"), "rule": row.get("rule"),
            "formation": row.get("formation"), "hedge_ratio": row.get("hedge_ratio"),
            "half_life": row.get("half_life"), "adf_t": row.get("adf_t"),
            "suspended_at": row.get("suspended_at"), "trades": trades, "z": row.get("z") or [],
            "net_total": sum(net), "trials": store().count("trials", tag="pairs"),
            "created": row.get("created"), "facts": facts}


# ------------------------------------------------------------------ routes
class BacktestIn(BaseModel):
    idea: str
    symbol: str = "NIFTY"
    market: str = "IN"
    costs: str | None = None
    start: str = "2016-01-01"


@router.post("/api/backtest/run")
def backtest_run(body: BacktestIn) -> dict[str, Any]:
    """Plain-English rule → backtest (kept for the design sample and scripts)."""
    from ... import backtest
    try:
        spec = backtest.rules(body.idea)
    except Exception as exc:
        raise HTTPException(400, f"Could not read the rule: {exc}") from exc
    bars_df = data.get(body.symbol, market=body.market, start=body.start, end=date.today())
    profile = body.costs or ("IN-equity-delivery" if body.market == "IN" else "US-equity")
    res = backtest.run(spec, bars_df, costs=profile, symbol=body.symbol)
    rid = remember_saved(res, "idea")
    card = res.card()
    eq = res.equity
    peak = [max(eq[: i + 1]) for i in range(len(eq))]
    dd = [e / p - 1 for e, p in zip(eq, peak)]
    return _clean({
        "id": rid, "read_back": spec.read_back(), "cards": spec.cards(), "stats": res.stats(),
        "dates": [d.isoformat() for d in res.dates], "equity": list(eq),
        "benchmark": list(res.benchmark), "drawdown": dd, "trades": res.trades[-50:],
        "card": card.to_dict(), "facts": res.facts(), "trials": res.trial_count(),
        "source": bars_df["source"][-1],
    })


class SampleIn(BaseModel):
    market: str = "IN"


@router.post("/api/backtest/sample")
def backtest_sample(body: SampleIn) -> dict[str, Any]:
    """*Run sample rule*: the Lesson 11 rule on five years of synthetic data."""
    from ... import backtest
    sym = "NIFTY" if body.market == "IN" else "SPY"
    bars, _ = load_bars(sym, body.market, 5)
    prof = "IN-equity-delivery" if body.market == "IN" else "US-equity"
    res = backtest.run(SAMPLE_RULE, bars, costs=prof, symbol=sym)
    return {"id": remember_saved(res, "sample")}


@router.get("/api/backtest/saved")
def backtest_saved(limit: int = 30) -> list[dict[str, Any]]:
    """Saved reports, newest first (Strategy Builder, Trend Lab, Pairs Lab, samples)."""
    rows = []
    for r in store().all("backtests", limit=limit):
        pairs = r.get("source") == "Pairs Lab"
        rows.append({"id": r["id"], "created": r["created"], "tag": r.get("tag"),
                     "kind": "pairs" if pairs else "rule",
                     "symbol": r.get("name") if pairs else r.get("symbol"),
                     "market": r.get("market"),
                     "grade": None if pairs else (r.get("report") or {}).get("grade")})
    return _clean(rows)


@router.get("/api/backtest/current")
def backtest_current() -> dict[str, Any]:
    """The hand-off: the newest report sent here (None when nothing has been run yet)."""
    rows = store().all("backtests", limit=1)
    return {"id": rows[0]["id"] if rows else None}


@router.get("/api/backtest/report")
def backtest_report(id: int | None = None) -> dict[str, Any]:
    rid = id if id is not None else backtest_current()["id"]
    if rid is None:  # an empty lab is a normal state, not an error
        return {"id": None, "empty": True,
                "message": "No backtest yet. Build one in Strategy Builder or Trend Lab, "
                           "or run the sample rule."}
    row = store().get("backtests", rid)
    if row is not None and (row.get("source") == "Pairs Lab" or "spec" not in row):
        return _clean(_pairs_payload(row))
    res = result_for(rid)
    return _clean({"id": rid, **report_payload(res)})


class CostsIn(BaseModel):
    id: int
    profile: str | None = None
    slippage_pct: float | None = None


@router.post("/api/backtest/costs")
def backtest_costs(body: CostsIn) -> dict[str, Any]:
    """Costs tab: the same rule re-priced. Not a new trial: the rule did not change."""
    res = result_for(body.id)
    profile = body.profile or res.profile
    if profile not in PROFILES.get(res.market, []):
        raise HTTPException(400, f"{profile} is not a cost profile for the {res.market} market.")
    if body.slippage_pct is not None and not 0 <= body.slippage_pct <= 2:
        raise HTTPException(400, "Slippage must be between 0% and 2% a side.")
    same = profile == res.profile and body.slippage_pct in (None, res.spec.cost.slippage_pct)
    alt = res if same else res.with_costs(profile, body.slippage_pct)
    s, g = alt.stats(), alt.gross_stats()
    items: dict[str, float] = {}
    for f in alt.fills:
        for k, v in (f.get("items") or {}).items():
            items[k] = items.get(k, 0.0) + v
    items["slippage (assumed)"] = s["slippage"]
    rows = [{"item": k, "amount": round(v, 2)} for k, v in items.items() if v]
    return _clean({
        "profile": alt.profile, "slippage_pct": alt.spec.cost.slippage_pct,
        "frame": _frame(alt, gross=True), "items": rows,
        "total": round(s["charges"] + s["slippage"], 2),
        "before": g["total_return"], "after": s["total_return"],
        "charges": s["charges"], "slippage": s["slippage"], "as_of": reference.as_of(),
    })


class AcceptIn(BaseModel):
    id: int
    ai_note: str = ""


@router.post("/api/backtest/accept")
def backtest_accept(body: AcceptIn) -> dict[str, Any]:
    """*Accept*: save the rule cards and the report to the journal."""
    res = result_for(body.id)
    card = res.card()
    jid = store().add("journal", {"kind": "backtest_report", "read_back": res.spec.read_back(),
                                  "rule_cards": res.spec.cards(), "spec": res.spec.to_dict(),
                                  "grade": card.grade, "report": card.to_dict(),
                                  "ai_note": body.ai_note, "symbol": res.symbol,
                                  "market": res.market}, tag="backtest")
    remember_saved(res, "accepted")
    return {"journal_id": jid, "grade": card.grade}
