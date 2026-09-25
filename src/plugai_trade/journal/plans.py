"""Planned risk: match round trips to saved trade plans and compute R-multiples.

1R is the planned risk of one trade (Chapter 12). R needs the planned stop, and
the planned stop comes from the trade plan saved *before* the entry, or from a
value the trader types in. R is computed before charges, as in Chapter 14.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import polars as pl

from ..store import default as store


def with_r(trades: pl.DataFrame) -> pl.DataFrame:
    """Recompute ``risk`` and ``r_multiple`` from ``stop_distance`` (null when unknown)."""
    risk = pl.col("stop_distance") * pl.col("qty") * pl.col("multiplier").fill_null(1.0)
    return trades.with_columns(risk=risk.round(2)).with_columns(
        r_multiple=pl.when(pl.col("risk") > 0)
        .then((pl.col("gross") / pl.col("risk")).round(2))
        .otherwise(None))


def _plan_time(p: dict[str, Any]) -> datetime | None:
    for k in ("saved_at", "created"):
        v = p.get(k)
        if v:
            try:
                return datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=None)
            except ValueError:
                continue
    return None


def _plan_stop(p: dict[str, Any]) -> float | None:
    for k in ("stop_distance", "stop_points", "stop_pts"):
        if p.get(k) not in (None, ""):
            return abs(float(p[k]))
    entry, stop = p.get("entry"), p.get("stop")
    try:
        return abs(float(entry) - float(stop)) if entry not in (None, "") and stop not in (
            None, "") else None
    except (TypeError, ValueError):
        return None


def _plan_symbol(p: dict[str, Any]) -> str:
    return str(p.get("symbol") or p.get("instrument") or "").upper()


def match_plans(trades: pl.DataFrame, plans: list[dict[str, Any]] | None = None,
                max_days: int = 5) -> tuple[pl.DataFrame, list[int]]:
    """Link each unplanned trade to the latest plan for its symbol saved before entry.

    Returns (trades, trade_ids still unmatched). A plan is used once. Trades that
    already carry a stop keep it.
    """
    plans = plans if plans is not None else store().all("plans")
    usable = []
    for p in plans:
        t, stop = _plan_time(p), _plan_stop(p)
        if t is not None and stop:
            usable.append((t, _plan_symbol(p), stop, p))
    usable.sort(key=lambda x: x[0])
    used: set[int] = set()
    updates: dict[int, tuple[int | None, float, str | None]] = {}
    unmatched: list[int] = []
    for r in trades.iter_rows(named=True):
        if r["stop_distance"]:
            continue
        best = None
        for t, sym, stop, p in usable:
            pid = p.get("id")
            if pid in used or sym not in (str(r["underlying"]).upper(), str(r["symbol"]).upper()):
                continue
            if t <= r["entry_time"] and r["entry_time"] - t <= timedelta(days=max_days):
                best = (t, stop, p)
        if best is None:
            unmatched.append(r["trade_id"])
            continue
        _, stop, p = best
        used.add(p.get("id"))
        updates[r["trade_id"]] = (p.get("id"), stop, p.get("setup"))
    if updates:
        ids = list(updates)
        upd = pl.DataFrame({"trade_id": ids,
                            "_pid": [updates[i][0] for i in ids],
                            "_stop": [float(updates[i][1]) for i in ids],
                            "_setup": [updates[i][2] for i in ids]},
                           schema={"trade_id": pl.Int64, "_pid": pl.Int64, "_stop": pl.Float64,
                                   "_setup": pl.Utf8})
        trades = trades.join(upd, on="trade_id", how="left").with_columns(
            plan_id=pl.coalesce("plan_id", "_pid"),
            stop_distance=pl.coalesce("stop_distance", "_stop"),
            setup=pl.coalesce("setup", "_setup"),
        ).drop("_pid", "_stop", "_setup")
    return with_r(trades), unmatched


def set_stop(trades: pl.DataFrame, trade_id: int, stop_distance: float) -> pl.DataFrame:
    """Type in a planned stop (points per unit) for one trade and recompute its R."""
    out = trades.with_columns(
        stop_distance=pl.when(pl.col("trade_id") == trade_id).then(pl.lit(float(stop_distance)))
        .otherwise(pl.col("stop_distance")))
    return with_r(out)
