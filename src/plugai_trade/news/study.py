"""Comparing two scorers, and the event study with costs (Chapter 28).

All arithmetic is here, in code. The event study reads headline rows and price
bars only; it never sees a model. Results are HYPOTHETICAL.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import polars as pl

from .. import costs as _costs
from .. import data
from ..store import default as store
from . import sample

TRIAL_FAMILY = "news-event-study"
COST_ROWS_BPS = (0, 5, 10, 20, 40)
DRIFT = (1, 2)  # sessions after day 0 whose abnormal returns form the drift window
ORDER = ("negative", "neutral", "positive", "unclear")


class Comparison:
    """Two scorers on the same headlines: agreement table and disagreements."""

    def __init__(self, a: pl.DataFrame, b: pl.DataFrame):
        self.name_a = str(a["scorer"][0]) if a.height else "a"
        self.name_b = str(b["scorer"][0]) if b.height else "b"
        if self.name_a == self.name_b:
            self.name_b += "_2"
        self.used_a = str(a["scorer_used"][0]) if a.height else ""
        self.used_b = str(b["scorer_used"][0]) if b.height else ""
        right = b.select("id", pl.col("label").alias("label_b"),
                         pl.col("reason").alias("reason_b"))
        self.joined = a.rename({"label": "label_a", "reason": "reason_a"}).join(right, on="id")

    @property
    def n(self) -> int:
        return self.joined.height

    @property
    def agreement(self) -> float:
        """Share of headlines where both scorers gave the same label."""
        if not self.n:
            return 0.0
        return self.joined.filter(pl.col("label_a") == pl.col("label_b")).height / self.n

    def _labels(self) -> list[str]:
        seen = set(self.joined["label_a"].to_list()) | set(self.joined["label_b"].to_list())
        return [lab for lab in ORDER if lab in seen or lab != "unclear"]

    def table(self) -> pl.DataFrame:
        """Agreement counts: rows are scorer A's labels, columns scorer B's."""
        labs = self._labels()
        rows = []
        for la in labs:
            sub = self.joined.filter(pl.col("label_a") == la)
            row: dict[str, Any] = {f"{self.name_a} \\ {self.name_b}": la}
            for lb in labs:
                row[lb] = sub.filter(pl.col("label_b") == lb).height
            row["total"] = sub.height
            rows.append(row)
        return pl.DataFrame(rows)

    def opposite(self) -> int:
        """Headlines one scorer called positive and the other negative."""
        return self.joined.filter(
            ((pl.col("label_a") == "positive") & (pl.col("label_b") == "negative"))
            | ((pl.col("label_a") == "negative") & (pl.col("label_b") == "positive"))).height

    def disagreements(self) -> pl.DataFrame:
        """Rows the scorers labelled differently, opposite labels first. Read these yourself."""
        d = self.joined.filter(pl.col("label_a") != pl.col("label_b")).with_columns(
            (((pl.col("label_a") == "positive") & (pl.col("label_b") == "negative"))
             | ((pl.col("label_a") == "negative") & (pl.col("label_b") == "positive")))
            .alias("opposite"))
        cols = [c for c in ("opposite", "symbol", "headline", "original", "lang", "published",
                            "label_a", "label_b", "reason_a", "reason_b", "id") if c in d.columns]
        return d.sort(["opposite", "published"], descending=[True, False]).select(cols).rename(
            {"label_a": self.name_a, "label_b": self.name_b,
             "reason_a": f"{self.name_a}_reason", "reason_b": f"{self.name_b}_reason"})

    def agreed(self, label: str) -> pl.DataFrame:
        """Headlines both scorers gave ``label`` — an event group for :func:`event_study`."""
        return (self.joined.filter((pl.col("label_a") == label) & (pl.col("label_b") == label))
                .drop("label_b", "reason_b").rename({"label_a": "label", "reason_a": "reason"}))

    def facts(self) -> list[str]:
        return [f"Headlines compared: {self.n}",
                f"Scorer A: {self.used_a}", f"Scorer B: {self.used_b}",
                f"Agreement: {self.agreement:.0%}",
                f"Disagreements: {self.n - round(self.agreement * self.n)}",
                f"Opposite labels (positive vs negative): {self.opposite()}"]

    def __repr__(self) -> str:
        return f"Comparison({self.name_a} vs {self.name_b}: {self.n} headlines, " \
               f"{self.agreement:.0%} agree)"


@dataclass
class EventStudy:
    """Average abnormal path around day 0, with bands, costs and the trial count."""

    market: str
    benchmark: str
    entry: str
    costs: str
    window: tuple[int, int]
    path: pl.DataFrame  # day, mean_ar, car, lo, hi
    drift_bps: list[float] = field(default_factory=list)  # per event, direction-adjusted
    side: str = "long"
    trials: int = 0
    skipped: list[str] = field(default_factory=list)
    bench_source: str = ""

    @property
    def n(self) -> int:
        return len(self.drift_bps)

    def drift(self) -> tuple[float, float, float]:
        """Mean drift-window result per event in bps, with a 95% range for the mean."""
        if not self.drift_bps:
            return 0.0, 0.0, 0.0
        x = np.array(self.drift_bps)
        se = x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0
        m = float(x.mean())
        return m, m - 1.96 * se, m + 1.96 * se

    def preset_bps(self) -> float:
        """Round-trip cost of the chosen preset, in bps of notional."""
        return _costs.rate(self.costs) * 1e4

    def cost_table(self) -> pl.DataFrame:
        """Average drift-window result per event after each assumed round-trip cost."""
        gross = self.drift()[0]
        rows = [{"Round-trip cost assumed": "0 bps (no costs)" if c == 0 else f"{c} bps",
                 "cost_bps": float(c), "Result per event (bps)": round(gross - c, 1)}
                for c in COST_ROWS_BPS]
        p = self.preset_bps()
        rows.append({"Round-trip cost assumed": f"{self.costs} preset ({p:.1f} bps)",
                     "cost_bps": round(p, 1), "Result per event (bps)": round(gross - p, 1)})
        return pl.DataFrame(rows)

    def day0(self) -> float:
        """Average abnormal return on day 0, in percent."""
        row = self.path.filter(pl.col("day") == 0)
        return float(row["mean_ar"][0]) * 100 if row.height else 0.0

    def facts(self) -> list[str]:
        m, lo, hi = self.drift()
        at20 = m - 20
        return ["HYPOTHETICAL event study on past data; before taxes",
                f"Events: {self.n} ({self.side} side)",
                f"Day 0 = {self.entry.replace('_', ' ')} session; benchmark {self.benchmark}",
                f"Day 0 average abnormal move: {self.day0():+.2f}%",
                (f"Drift window (day 0 close to day +{DRIFT[1]} close): {m:+.1f} bps "
                 f"(95% range {lo:+.1f} to {hi:+.1f} bps)"),
                f"After 20 bps round-trip cost: {at20:+.1f} bps",
                (f"After the {self.costs} preset ({self.preset_bps():.1f} bps): "
                 f"{m - self.preset_bps():+.1f} bps"),
                f"Trials in this family: {self.trials}"]

    def text(self) -> str:
        """The report as plain text: average path, bands, cost table, trials."""
        lines = ["EVENT STUDY — HYPOTHETICAL", *self.facts(), "",
                 f"Average cumulative abnormal return (from day {self.window[0]}), with 95% band:"]
        for r in self.path.iter_rows(named=True):
            lines.append(f"  day {r['day']:+3d}  {r['car'] * 100:+6.2f}%   "
                         f"[{r['lo'] * 100:+6.2f}%, {r['hi'] * 100:+6.2f}%]")
        lines += ["", "Cost table (per event, drift window):"]
        for r in self.cost_table().iter_rows(named=True):
            lines.append(f"  {r['Round-trip cost assumed']:<36} {r['Result per event (bps)']:+7.1f}"
                         " bps")
        if self.skipped:
            lines += ["", "Skipped: " + "; ".join(self.skipped[:6])]
        return "\n".join(lines)

    def report(self, echo: bool = True) -> str | None:
        """Print the report (average path, bands, cost table, trials)."""
        if echo:
            print(self.text())
            return None
        return self.text()

    def __repr__(self) -> str:
        return f"EventStudy({self.n} events, day 0 {self.day0():+.2f}%, trials {self.trials})"


def _market_of(events: pl.DataFrame, benchmark: str) -> str:
    if "market" in events.columns and events.height:
        return str(events["market"][0])
    return "US" if benchmark.upper() in ("SPY", "QQQ", "DIA", "SPX", "IWM") else "IN"


def _closes(symbol: str, market: str, bench: pl.DataFrame, start: date, end: date
            ) -> np.ndarray | None:
    """Stock closes aligned to the benchmark's dates (NaN where missing)."""
    if sample.is_sample_symbol(symbol):
        px = sample.prices(symbol, market, bench)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            px = data.get(symbol, market=market, start=start, end=end, fallback=False)
        px = px.select("date", "close")
    j = bench.select("date").join(px, on="date", how="left")
    arr = j["close"].to_numpy().astype(float)
    return None if np.isnan(arr).all() else arr


def _digest(parts: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _count_trial(parts: dict[str, Any], detail: dict[str, Any]) -> int:
    st, dg = store(), _digest(parts)
    if not any(r.get("digest") == dg for r in st.all("trials", tag=TRIAL_FAMILY)):
        st.add("trials", {"family": TRIAL_FAMILY, "digest": dg, "source": "News Pipeline",
                          **detail}, tag=TRIAL_FAMILY)
    return st.count("trials", tag=TRIAL_FAMILY)


def event_study(events: pl.DataFrame, window: tuple[int, int] = (-5, 10),
                benchmark: str = "NIFTY", entry: str = "tradable_from",
                costs: str = "IN-equity-delivery") -> EventStudy:
    """Average abnormal return around each event's day 0, with bands and a cost table.

    ``entry="tradable_from"`` sets day 0 to the first session tradable after the
    headline was seen (the honest clock). ``entry="published_date"`` is the
    deliberate date-only join from Exercise 3: after-close news is matched to
    that day's close. Every distinct variant adds one trial.
    """
    if costs not in _costs.PROFILES:
        raise ValueError(f"unknown cost preset {costs!r}; choose one of {', '.join(_costs.PROFILES)}")
    if entry not in ("tradable_from", "published_date"):
        raise ValueError("entry must be 'tradable_from' or 'published_date'")
    lo_w, hi_w = int(window[0]), int(window[1])
    market = _market_of(events, benchmark)
    day_col = "tradable_day" if entry == "tradable_from" else "published_day"
    if events.height:
        days = events[day_col].to_list()
        start, end = min(days) - timedelta(days=60), max(days) + timedelta(days=60)
    else:
        start = end = date.today()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bench = data.get(benchmark, market=market, start=start, end=end).select(
            "date", "close", "source")
    dates = bench["date"].to_list()
    b_close = bench["close"].to_numpy().astype(float)
    b_ret = np.diff(b_close, prepend=np.nan) / np.concatenate([[np.nan], b_close[:-1]])
    label = str(events["label"].mode()[0]) if "label" in events.columns and events.height else ""
    sign = -1.0 if label == "negative" else 1.0
    cache: dict[str, np.ndarray | None] = {}
    paths, drift, skipped = [], [], []
    for ev in events.iter_rows(named=True):
        sym = str(ev.get("symbol") or "")
        if not sym:
            skipped.append("no symbol matched")
            continue
        if sym not in cache:
            try:
                cache[sym] = _closes(sym, market, bench, start, end)
            except Exception as exc:  # a missing symbol is normal; say so
                cache[sym] = None
                skipped.append(f"{sym}: {str(exc)[:60]}")
        px = cache[sym]
        if px is None:
            continue
        i0 = bisect.bisect_left(dates, ev[day_col])
        if i0 + lo_w < 1 or i0 + hi_w >= len(dates):
            skipped.append(f"{sym}: window outside price history")
            continue
        s_ret = px[i0 + lo_w:i0 + hi_w + 1] / px[i0 + lo_w - 1:i0 + hi_w] - 1
        ar = s_ret - b_ret[i0 + lo_w:i0 + hi_w + 1]
        if np.isnan(ar).any():
            skipped.append(f"{sym}: missing prices")
            continue
        paths.append(ar)
        drift.append(sign * float(ar[-lo_w + DRIFT[0]:-lo_w + DRIFT[1] + 1].sum()) * 1e4)
    offsets = list(range(lo_w, hi_w + 1))
    if paths:
        m = np.vstack(paths)
        car = np.cumsum(m, axis=1)
        se = car.std(axis=0, ddof=1) / np.sqrt(len(m)) if len(m) > 1 else np.zeros(car.shape[1])
        mean_car = car.mean(axis=0)
        path = pl.DataFrame({"day": offsets, "mean_ar": m.mean(axis=0), "car": mean_car,
                             "lo": mean_car - 1.96 * se, "hi": mean_car + 1.96 * se})
    else:
        z = [0.0] * len(offsets)
        path = pl.DataFrame({"day": offsets, "mean_ar": z, "car": z, "lo": z, "hi": z})
    ids = sorted(str(x) for x in events["id"].to_list()) if "id" in events.columns else []
    parts = {"entry": entry, "window": [lo_w, hi_w], "benchmark": benchmark, "costs": costs,
             "events": ids}
    trials = _count_trial(parts, {"entry": entry, "window": f"{lo_w}..{hi_w}",
                                  "benchmark": benchmark, "costs": costs, "events": len(paths),
                                  "label": label})
    return EventStudy(market=market, benchmark=benchmark, entry=entry, costs=costs,
                      window=(lo_w, hi_w), path=path, drift_bps=drift,
                      side="short" if sign < 0 else "long", trials=trials,
                      skipped=skipped, bench_source=str(bench["source"][0]) if bench.height else "")
