"""Research › Score-Tester: test a vendor's stock score point-in-time.

    from plugai_trade import scoretest
    raw = scoretest.sample_csv("IN")                  # or your vendor's export
    scores = scoretest.map_columns(scoretest.read_csv(raw),
                                   {"Date": "date", "Symbol": "symbol", "Score": "score"})
    rep = scoretest.run(scores, market="IN", horizon_days=63)
    print(rep.facts())

Each score is lined up with prices *after* it could have been used (the next
session after publication; next-day use is assumed when there is no
publication time). Delisted names keep their last traded price. Five score
buckets, returns after round-trip costs, top-minus-bottom spread, the share of
dates the top bucket beat the universe, and coverage.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import polars as pl

from .. import costs
from ..screener import universe as uni

FIELDS = ("Date", "Symbol", "Score", "Published at")
COST_PRESET = {"IN": "IN-equity-delivery", "US": "US-equity"}
THIN_DATE = 20  # fewer scored names than this on a date → "thin" warning


def read_csv(data: bytes | str) -> pl.DataFrame:
    """Read a vendor CSV (bytes from an upload, text, or a path)."""
    if isinstance(data, bytes):
        return pl.read_csv(io.BytesIO(data), infer_schema_length=0)
    if "\n" in data:
        return pl.read_csv(io.StringIO(data), infer_schema_length=0)
    return pl.read_csv(data, infer_schema_length=0)


def guess_mapping(columns: list[str]) -> dict[str, str | None]:
    """First guess for the column mapper: Date, Symbol, Score, Published at."""
    low = {c.lower().replace("_", " ").strip(): c for c in columns}
    hints = {
        "Date": ("date", "as of", "score date"),
        "Symbol": ("symbol", "ticker", "code"),
        "Score": ("score", "rating", "rank"),
        "Published at": ("published at", "published", "publish time", "timestamp"),
    }
    out: dict[str, str | None] = {}
    for fld, keys in hints.items():
        out[fld] = next((low[k] for k in keys if k in low), None)
    return out


def map_columns(df: pl.DataFrame, mapping: dict[str, str | None]) -> pl.DataFrame:
    """Rename vendor columns to date / symbol / score / published_at (optional)."""
    need = {"Date": "date", "Symbol": "symbol", "Score": "score"}
    for fld in need:
        if not mapping.get(fld):
            raise ValueError(f"Map a column to {fld}.")
    cols = [pl.col(mapping[f]).alias(n) for f, n in need.items()]  # type: ignore[index]
    if mapping.get("Published at"):
        cols.append(pl.col(mapping["Published at"]).alias("published_at"))  # type: ignore[arg-type]
    out = df.select(cols).with_columns(
        pl.col("date").str.slice(0, 10).str.to_date(strict=False),
        pl.col("score").cast(pl.Float64, strict=False),
        pl.col("symbol").str.strip_chars(),
    )
    if "published_at" in out.columns:
        out = out.with_columns(pl.col("published_at").str.slice(0, 10).str.to_date(strict=False))
    return out.drop_nulls(["date", "symbol", "score"])


@dataclass
class Report:
    """The Score-Tester report."""

    market: str
    horizon_days: int
    buckets: list[dict[str, Any]]  # label, avg return %, names
    universe_return: float
    spread: float
    hit_share: float
    hit_dates: int
    n_dates: int
    coverage: dict[str, float]  # min / median / max names scored per date
    cost_preset: str
    cost_pct: float
    include_delisted: bool
    warnings: list[str] = field(default_factory=list)

    def facts(self) -> list[str]:
        out = [
            f"Market {self.market}; horizon {self.horizon_days} calendar days; "
            f"cost preset {self.cost_preset} ({self.cost_pct:.2f}% round trip)",
            "Delisted names "
            + ("included at last traded price" if self.include_delisted else "EXCLUDED"),
        ]
        out += [
            f"Bucket {b['label']}: average return after costs {b['return']:+.2f}% "
            f"({b['names']} score-dates)"
            for b in self.buckets
        ]
        out += [
            f"Universe average: {self.universe_return:+.2f}%",
            f"Top-minus-bottom spread: {self.spread:+.2f} points",
            f"Top bucket beat the universe on {self.hit_dates} of {self.n_dates} dates "
            f"({self.hit_share:.0f}%)",
            f"Coverage: {self.coverage['min']:.0f}–{self.coverage['max']:.0f} names per date "
            f"(median {self.coverage['median']:.0f})",
        ]
        out += [f"Warning: {w}" for w in self.warnings]
        return out

    def table(self) -> pl.DataFrame:
        return pl.DataFrame(self.buckets)


def _entry_date(row: dict[str, Any]) -> date:
    """First session the score could be used: the day after publication (or after the date)."""
    d = (row.get("published_at") or row["date"]) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _price_on_or_after(df: pl.DataFrame, d: date) -> tuple[date, float] | None:
    sub = df.filter(pl.col("date") >= d)
    return (sub["date"][0], float(sub["close"][0])) if sub.height else None


def _price_on_or_before(df: pl.DataFrame, d: date) -> float | None:
    sub = df.filter(pl.col("date") <= d)
    return float(sub["close"][-1]) if sub.height else None


def _one_to_ten(df: pl.DataFrame) -> bool:
    return bool(df["score"].min() >= 1 and df["score"].max() <= 10)


def _bucketise(df: pl.DataFrame, n_buckets: int) -> pl.DataFrame:
    """Scores 1–10 go into fixed bands (1–2 … 9–10); other scales into per-date quintiles."""
    if n_buckets == 5 and _one_to_ten(df):
        return df.with_columns(
            ((pl.col("score") + 1) // 2).clip(1, 5).cast(pl.Int64).alias("bucket")
        )
    return df.with_columns(
        (pl.col("score").rank("ordinal").over("date") - 1).alias("_r"),
        pl.len().over("date").alias("_n"),
    ).with_columns(((pl.col("_r") * n_buckets) // pl.col("_n") + 1).cast(pl.Int64).alias("bucket"))


def _bucket_label(df: pl.DataFrame, b: int, n_buckets: int) -> str:
    if n_buckets == 5 and _one_to_ten(df):
        return f"{2 * b - 1}–{2 * b}"
    return f"Q{b}" + (" (lowest)" if b == 1 else " (highest)" if b == n_buckets else "")


def run(
    scores: pl.DataFrame,
    market: str = "IN",
    horizon_days: int = 63,
    include_delisted: bool = True,
    cost_preset: str | None = None,
    n_buckets: int = 5,
    known_symbols: list[str] | None = None,
) -> Report:
    """The point-in-time test. ``scores`` has date, symbol, score (, published_at)."""
    cost_preset = cost_preset or COST_PRESET[market]
    cost_pct = costs.rate(cost_preset) * 100
    known = set(known_symbols or uni.names("NIFTY 500" if market == "IN" else "S&P 500", market))
    warnings: list[str] = []
    rows = scores.to_dicts()
    unmatched = sorted({r["symbol"] for r in rows if r["symbol"] not in known})
    if unmatched:
        warnings.append(f"{len(unmatched)} unmatched symbols ignored: {', '.join(unmatched[:5])}")
    if "published_at" not in scores.columns:
        warnings.append("No Published at column: assumed next-day use for every score.")
    late = sum(1 for r in rows if r.get("published_at") and r["published_at"] > r["date"])
    if late:
        warnings.append(
            f"{late} scores were published after the date they are stamped with; "
            "the test uses the publication date (a naive test would look ahead)."
        )
    lo = min((r["date"] for r in rows), default=date.today())
    hi = max((r["date"] for r in rows), default=date.today()) + timedelta(days=horizon_days + 10)
    cache: dict[str, pl.DataFrame] = {}
    recs = []
    dropped_delisted = 0
    for r in rows:
        if r["symbol"] not in known:
            continue
        if r["symbol"] not in cache:
            cache[r["symbol"]] = uni.bars(r["symbol"], market, lo - timedelta(days=5), hi)
        df = cache[r["symbol"]]
        entry_d = _entry_date(r)
        entry = _price_on_or_after(df, entry_d)
        if entry is None:
            continue
        exit_d = entry[0] + timedelta(days=horizon_days)
        gone = uni.delisted_on(r["symbol"])
        if gone is not None and gone < exit_d and not include_delisted:
            dropped_delisted += 1
            continue
        px = _price_on_or_before(df, exit_d)
        if px is None:
            continue
        ret = (px / entry[1] - 1) * 100 - cost_pct
        recs.append({"date": r["date"], "symbol": r["symbol"], "score": r["score"], "ret": ret})
    if dropped_delisted:
        warnings.append(
            f"Include delisted is off: {dropped_delisted} score-dates of names that "
            "later delisted were dropped (survivorship bias)."
        )
    if not recs:
        return Report(
            market,
            horizon_days,
            [],
            0.0,
            0.0,
            0.0,
            0,
            0,
            {"min": 0, "median": 0, "max": 0},
            cost_preset,
            cost_pct,
            include_delisted,
            warnings + ["No score could be matched to prices."],
        )
    df = _bucketise(pl.DataFrame(recs), n_buckets)
    per_date = df.group_by("date").agg(pl.len().alias("n"), pl.col("ret").mean().alias("uni"))
    thin = per_date.filter(pl.col("n") < THIN_DATE).height
    if thin:
        warnings.append(f"{thin} thin dates with fewer than {THIN_DATE} scored names.")
    buckets = []
    for b in range(1, n_buckets + 1):
        sub = df.filter(pl.col("bucket") == b)
        buckets.append(
            {
                "label": _bucket_label(df, b, n_buckets),
                "return": round(float(sub["ret"].mean()), 2) if sub.height else 0.0,
                "names": sub.height,
            }
        )
    top = (
        df.filter(pl.col("bucket") == n_buckets)
        .group_by("date")
        .agg(pl.col("ret").mean().alias("top"))
    )
    joined = top.join(per_date, on="date")
    hits = int((joined["top"] > joined["uni"]).sum())
    n_dates = joined.height
    counts = per_date["n"].to_numpy()
    return Report(
        market,
        horizon_days,
        buckets,
        round(float(df["ret"].mean()), 2),
        round(buckets[-1]["return"] - buckets[0]["return"], 2),
        round(100 * hits / n_dates, 1) if n_dates else 0.0,
        hits,
        n_dates,
        {
            "min": float(counts.min()),
            "median": float(np.median(counts)),
            "max": float(counts.max()),
        },
        cost_preset,
        round(cost_pct, 3),
        include_delisted,
        warnings,
    )


def sample_csv(market: str = "IN", months: int = 24, names: int = 60, seed: int = 7) -> str:
    """A synthetic vendor export (scores 1–10, monthly) so the screen works offline.

    Scores are random (they contain no information), and about a tenth are
    published a day after their stamp, to exercise the warnings.
    """
    rng = np.random.default_rng(seed)
    syms = uni.names("NIFTY 500" if market == "IN" else "S&P 500", market)[:names]
    start = date(2023, 1, 31)
    lines = ["date,symbol,score,published_at"]
    for m in range(months):
        y, mo = divmod(start.month - 1 + m, 12)
        d = date(start.year + y, mo + 1, 28)
        for s in syms:
            if rng.random() < 0.08:
                continue
            score = int(np.clip(round(rng.normal(5.5, 2.3)), 1, 10))
            pub = d + timedelta(days=1 if rng.random() < 0.1 else 0)
            lines.append(f"{d},{s},{score},{pub}")
    lines.append(f"{start},SYN-XX-999,5,{start}")  # an unmatched symbol
    return "\n".join(lines)
