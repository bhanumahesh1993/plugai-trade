"""The journal's two shapes: a *fill* (one tradebook line) and a *trade* (one round trip).

Every importer produces fills in ``FILL_SCHEMA``; ``pairing.pair_fills`` turns them
into round trips in ``TRADE_SCHEMA``. Screens, detectors, Ask My Journal and the
Tax Export all read the trade shape, so a column added here is visible everywhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import polars as pl

#: Tags the lab understands. REAL is implied when no simulation tag is present.
TAGS = ("REAL", "PAPER", "REPLAY", "PILOT", "BLOCKED")
#: Tags that mark simulated rows: never part of tax, shown or hidden in the journal.
SIMULATED = ("PAPER", "REPLAY", "BLOCKED")

FILL_SCHEMA: dict[str, pl.DataType] = {
    "time": pl.Datetime("us"),
    "symbol": pl.Utf8,          # as printed by the broker (e.g. NIFTY26SEPFUT, SPY)
    "underlying": pl.Utf8,      # NIFTY, SPY, BTC …
    "instrument": pl.Utf8,      # EQ | FUT | CE | PE | CALL | PUT | CRYPTO
    "side": pl.Utf8,            # BUY | SELL
    "qty": pl.Float64,          # units (India F&O: units, not lots) or US contracts/shares
    "price": pl.Float64,
    "fees": pl.Float64,         # null when the tradebook has no charges
    "multiplier": pl.Float64,   # value per point per unit (US options 100)
    "market": pl.Utf8,          # IN | US
    "account": pl.Utf8,
    "strike": pl.Float64,
    "expiry": pl.Utf8,
    "source": pl.Utf8,          # file name and line number
}

TRADE_SCHEMA: dict[str, pl.DataType] = {
    "trade_id": pl.Int64,       # row number shown in the book ("row 50")
    "date": pl.Utf8,            # entry date, YYYY-MM-DD
    "entry_time": pl.Datetime("us"),
    "exit_time": pl.Datetime("us"),
    "symbol": pl.Utf8,
    "underlying": pl.Utf8,
    "instrument": pl.Utf8,
    "side": pl.Utf8,            # LONG | SHORT
    "qty": pl.Float64,
    "multiplier": pl.Float64,
    "entry_price": pl.Float64,
    "exit_price": pl.Float64,
    "gross": pl.Float64,        # P&L before charges, in the market's currency
    "charges": pl.Float64,
    "charges_source": pl.Utf8,  # "tradebook" | "cost table" | "none"
    "net": pl.Float64,
    "market": pl.Utf8,
    "account": pl.Utf8,
    "tags": pl.List(pl.Utf8),
    "plan_id": pl.Int64,
    "setup": pl.Utf8,
    "stop_distance": pl.Float64,  # planned stop, in price points per unit
    "risk": pl.Float64,           # 1R in money = stop_distance × qty × multiplier
    "r_multiple": pl.Float64,     # gross ÷ risk (before charges, as in Chapter 14)
    "strike": pl.Float64,
    "expiry": pl.Utf8,
    "source": pl.Utf8,
}

TRADE_COLUMNS = tuple(TRADE_SCHEMA)


def empty_fills() -> pl.DataFrame:
    """A zero-row fills frame with the right dtypes."""
    return pl.DataFrame(schema=FILL_SCHEMA)


def empty_trades() -> pl.DataFrame:
    """A zero-row trades frame with the right dtypes."""
    return pl.DataFrame(schema=TRADE_SCHEMA)


def _parse_dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    s = str(v).replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
                "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if "T" in s or " " in s else s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        return None


def conform_trades(df: pl.DataFrame) -> pl.DataFrame:
    """Add missing trade columns (as nulls) and cast to ``TRADE_SCHEMA`` order and types."""
    out = df
    for col, dtype in TRADE_SCHEMA.items():
        if col not in out.columns:
            out = out.with_columns(pl.lit(None, dtype=dtype).alias(col))
    casts = []
    for col, dtype in TRADE_SCHEMA.items():
        if out.schema[col] != dtype:
            if isinstance(dtype, pl.Datetime) and out.schema[col] == pl.Utf8:
                casts.append(pl.col(col).str.to_datetime(strict=False).cast(dtype))
            else:
                casts.append(pl.col(col).cast(dtype, strict=False))
    if casts:
        out = out.with_columns(casts)
    return out.select(TRADE_COLUMNS)


def trades_from_records(records: Iterable[dict[str, Any]]) -> pl.DataFrame:
    """Build a trades frame from stored dicts (tolerant of missing keys)."""
    rows = []
    for r in records:
        row = {c: r.get(c) for c in TRADE_COLUMNS}
        for c in ("entry_time", "exit_time"):
            row[c] = _parse_dt(row[c])
        tags = row.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if r.get("tag") and r["tag"] not in tags and r["tag"] in TAGS:
            tags = [*tags, r["tag"]]
        row["tags"] = list(tags)
        rows.append(row)
    if not rows:
        return empty_trades()
    return pl.DataFrame(rows, schema=TRADE_SCHEMA, strict=False)


def to_records(trades: pl.DataFrame) -> list[dict[str, Any]]:
    """Rows as JSON-friendly dicts (datetimes as ISO strings) for the store."""
    out = []
    for r in trades.iter_rows(named=True):
        d = dict(r)
        for c in ("entry_time", "exit_time"):
            if d.get(c) is not None:
                d[c] = d[c].isoformat(timespec="seconds")
        out.append(d)
    return out


def primary_tag(tags: list[str] | None) -> str:
    """The one tag used as the store row tag: a simulation tag wins, else PILOT, else REAL."""
    tags = tags or []
    for t in ("BLOCKED", "REPLAY", "PAPER", "PILOT"):
        if t in tags:
            return t
    return "REAL"
