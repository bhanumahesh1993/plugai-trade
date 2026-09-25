"""Research › Chart Helper: describe a chart from numbers, and compute its levels.

    from plugai_trade import data, charthelper
    bars = data.get("NIFTY", market="IN", start="2025-01-01", end="2026-05-29")
    d = charthelper.describe(bars)           # numbers mode: every line cites a value
    lv = charthelper.levels(bars)            # zones with distance in ATR
    print(lv.table())

Swing points, pivots, the volume profile and every distance are computed in
code. The model, when asked to Explain, receives only these numbers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import polars as pl

from .. import data
from .. import indicators as ind
from ..data import synthetic
from ..store import default as store

TIMEFRAMES = ("Daily", "Weekly", "15-min", "5-min")


def _f(x: float) -> str:
    return f"{x:,.2f}"


MIN_BARS = 60  # fewer daily bars than this from a live source → synthetic sample instead


def load(
    symbol: str,
    market: str,
    timeframe: str = "Daily",
    end: date | None = None,
    days: int = 400,
    source: str | None = None,
) -> pl.DataFrame:
    """Bars for a timeframe, with provenance columns.

    ``NIFTY FUT`` is read as the NIFTY series. Intraday bars come from the
    synthetic session generator offline (last three sessions). When the
    configured sources return too little history for levels, the synthetic
    sample is used and its ``source`` column says so.
    """
    sym = symbol.upper().replace(" FUT", "").strip()
    end = end or date.today()
    if timeframe in ("15-min", "5-min"):
        step = "15m" if timeframe == "15-min" else "5m"
        frames, d = [], end
        while len(frames) < 3:
            if d.weekday() < 5:
                frames.append(synthetic.intraday(sym, d, step))
            d -= timedelta(days=1)
        stamp = pl.lit(date.today().isoformat())
        return pl.concat(frames[::-1]).with_columns(
            pl.lit("synthetic").alias("source"),
            stamp.alias("fetched_at"),
            pl.lit("public").alias("license_class"),
        )
    start = end - timedelta(days=days)
    daily = data.get(sym, market=market, start=start, end=end, source=source)
    if daily.height < MIN_BARS and source is None:
        daily = data.get(sym, market=market, start=start, end=end, source="synthetic")
    if timeframe == "Weekly":
        return weekly(daily)
    return daily


def weekly(daily: pl.DataFrame) -> pl.DataFrame:
    """Resample daily bars to weeks (Monday-labelled)."""
    return (
        daily.sort("date")
        .group_by_dynamic("date", every="1w")
        .agg(
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
        )
    )


# ---------------------------------------------------------------- describe
@dataclass
class Description:
    """Numbers mode: short lines, each built from computed values."""

    symbol: str
    timeframe: str
    asof: str
    values: dict[str, float]
    lines: list[str]

    def facts(self) -> list[str]:
        return [f"{self.symbol} · {self.timeframe} · last bar {self.asof}"] + self.lines


def _indicators(df: pl.DataFrame) -> pl.DataFrame:
    df = ind.sma(ind.sma(df, 20), 50)
    return ind.atr(ind.rsi(df, 14), 14)


def describe(bars: pl.DataFrame, symbol: str = "", timeframe: str = "Daily") -> Description:
    """Close vs averages, RSI now and five bars ago, ATR, and the nearest zone's touches."""
    df = _indicators(bars)
    last = df.row(-1, named=True)
    close, atr = float(last["close"]), float(last["atr_14"])
    v: dict[str, float] = {"close": close, "atr_14": atr, "rsi_14": float(last["rsi_14"])}
    lines = [f"Close {_f(close)}."]
    for n in (20, 50):
        m = last.get(f"sma_{n}")
        if m is not None:
            v[f"sma_{n}"] = float(m)
            gap = close - float(m)
            lines.append(
                f"{_f(abs(gap))} pts {'above' if gap >= 0 else 'below'} SMA{n} ({_f(float(m))})."
            )
    if df.height > 6:
        prev = float(df["rsi_14"][-6])
        v["rsi_14_5ago"] = prev
        lines.append(
            f"RSI(14) {v['rsi_14']:.1f}, {'up' if v['rsi_14'] >= prev else 'down'} "
            f"from {prev:.1f} five bars ago."
        )
    lines.append(f"ATR(14) {_f(atr)} pts ({atr / close * 100:.2f}% of the close).")
    hi20, lo20 = float(df["high"][-20:].max()), float(df["low"][-20:].min())
    v.update(high_20=hi20, low_20=lo20)
    lines.append(f"20-bar range {_f(lo20)}–{_f(hi20)}.")
    lv = levels(bars)
    above = [z for z in lv.zones if z.low > close and z.touches >= 2]
    if above:
        z = min(above, key=lambda z: z.low)
        lines.append(
            f"Nearest resistance zone {_f(z.low)}–{_f(z.high)}: {z.touches} touches, "
            f"{z.distance_text()}."
        )
    below = [z for z in lv.zones if z.high < close and z.touches >= 2]
    if below:
        z = max(below, key=lambda z: z.high)
        lines.append(
            f"Nearest support zone {_f(z.low)}–{_f(z.high)}: {z.touches} touches, "
            f"{z.distance_text()}."
        )
    return Description(symbol, timeframe, str(last["date"]), v, lines)


# ---------------------------------------------------------------- levels
@dataclass
class Level:
    """A price zone (low == high for a single line) with its distance in ATR."""

    kind: str
    low: float
    high: float
    touches: int
    source: str
    close: float
    atr: float

    @property
    def distance_atr(self) -> float:
        """0 inside the zone; else signed distance from the nearest edge, in ATR."""
        if self.low <= self.close <= self.high:
            return 0.0
        edge = self.low if self.low > self.close else self.high
        return (edge - self.close) / self.atr

    def distance_text(self) -> str:
        d = self.distance_atr
        return "inside" if d == 0.0 else f"{d:+.2f} ATR"

    def within_one_atr(self) -> bool:
        return abs(self.distance_atr) <= 1.0

    def zone_text(self) -> str:
        return (
            _f(self.low) if abs(self.high - self.low) < 1e-9 else f"{_f(self.low)}–{_f(self.high)}"
        )


@dataclass
class Levels:
    """The Levels card."""

    symbol: str
    asof: str
    close: float
    atr: float
    zones: list[Level]
    profile: pl.DataFrame = field(default_factory=pl.DataFrame)

    def table(self) -> pl.DataFrame:
        rows = [
            {
                "Level": z.kind,
                "Zone": z.zone_text(),
                "Touches": z.touches,
                "Distance": z.distance_text(),
                "±1 ATR": "yes" if z.within_one_atr() else "",
                "From": z.source,
            }
            for z in sorted(self.zones, key=lambda z: -z.high)
        ]
        return pl.DataFrame(rows)

    def facts(self) -> list[str]:
        out = [f"{self.symbol} last close {_f(self.close)} on {self.asof}; ATR(14) {_f(self.atr)}"]
        out += [
            f"{z.kind} {z.zone_text()} ({z.touches} touches, {z.source}): {z.distance_text()}"
            for z in self.zones
        ]
        return out

    def as_records(self) -> list[dict]:
        return [
            {
                "kind": z.kind,
                "low": round(z.low, 2),
                "high": round(z.high, 2),
                "touches": z.touches,
                "distance": z.distance_text(),
            }
            for z in self.zones
        ]


def swing_points(
    df: pl.DataFrame, k: int = 3
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Swing highs/lows: a bar whose high (low) beats the ``k`` bars on either side."""
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    highs, lows = [], []
    for i in range(k, len(hi) - k):
        win_h, win_l = np.delete(hi[i - k : i + k + 1], k), np.delete(lo[i - k : i + k + 1], k)
        if hi[i] > win_h.max():
            highs.append((i, float(hi[i])))
        if lo[i] < win_l.min():
            lows.append((i, float(lo[i])))
    return highs, lows


def _cluster(points: list[float], tol: float) -> list[list[float]]:
    groups: list[list[float]] = []
    for p in sorted(points):
        if groups and p - groups[-1][0] <= tol:
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


def pivots(h: float, lo: float, c: float) -> dict[str, float]:
    """Classic floor pivots: P = (H+L+C)/3, R1 = 2P − L, S1 = 2P − H."""
    p = (h + lo + c) / 3
    return {"P": p, "R1": 2 * p - lo, "S1": 2 * p - h}


def _nice_step(span: float, bins: int = 12) -> float:
    raw = span / bins
    mag = 10 ** np.floor(np.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return float(m * mag)
    return float(10 * mag)


def volume_profile(df: pl.DataFrame, sessions: int = 40) -> pl.DataFrame:
    """Volume by price bin (typical price) over the last ``sessions`` bars."""
    sub = df.tail(sessions)
    tp = ((sub["high"] + sub["low"] + sub["close"]) / 3).to_numpy()
    vol = sub["volume"].to_numpy()
    step = _nice_step(float(sub["high"].max() - sub["low"].min()))
    floors = np.floor(tp / step) * step
    prof = (
        pl.DataFrame({"bin": floors, "volume": vol})
        .group_by("bin")
        .agg(pl.col("volume").sum())
        .sort("bin")
    )
    total = prof["volume"].sum() or 1
    return prof.with_columns(
        (pl.col("bin") + step).alias("top"), (pl.col("volume") / total * 100).round(1).alias("pct")
    )


def levels(bars: pl.DataFrame, symbol: str = "", window: int = 60) -> Levels:
    """Swing zones, yesterday's high/low, 20-bar high/low, next-session pivots, POC band."""
    df = _indicators(bars)
    close, atr = float(df["close"][-1]), float(df["atr_14"][-1])
    recent = df.tail(window)
    highs, lows = swing_points(recent)
    tol = 0.25 * atr
    zones: list[Level] = []
    for grp in _cluster([p for _, p in highs], tol):
        kind = "Resistance" if max(grp) >= close else "Support (old high)"
        zones.append(Level(kind, min(grp), max(grp), len(grp), "swing highs", close, atr))
    for grp in _cluster([p for _, p in lows], tol):
        kind = "Support" if min(grp) <= close else "Resistance (old low)"
        zones.append(Level(kind, min(grp), max(grp), len(grp), "swing lows", close, atr))
    zones = [z for z in zones if z.touches >= 2] or zones
    y = df.row(-1, named=True)
    zones += [
        Level("Last bar high", y["high"], y["high"], 1, "last bar", close, atr),
        Level("Last bar low", y["low"], y["low"], 1, "last bar", close, atr),
        Level(
            "20-bar high",
            float(df["high"][-20:].max()),
            float(df["high"][-20:].max()),
            1,
            "20 bars",
            close,
            atr,
        ),
        Level(
            "20-bar low",
            float(df["low"][-20:].min()),
            float(df["low"][-20:].min()),
            1,
            "20 bars",
            close,
            atr,
        ),
    ]
    for name, val in pivots(y["high"], y["low"], y["close"]).items():
        zones.append(Level(f"Pivot {name}", val, val, 1, "next-session pivot", close, atr))
    prof = volume_profile(df)
    poc = prof.sort("volume", descending=True).row(0, named=True)
    zones.append(
        Level("POC", poc["bin"], poc["top"], 1, "volume profile (busiest band)", close, atr)
    )
    return Levels(symbol, str(y["date"]), close, atr, zones, prof)


# ---------------------------------------------------------------- intraday
@dataclass
class IntradayLevels:
    """Levels › Intraday: PDH, PDL, opening range and VWAP."""

    symbol: str
    values: dict[str, float]
    or_minutes: int

    def table(self) -> pl.DataFrame:
        return pl.DataFrame([{"Level": k, "Value": round(v, 2)} for k, v in self.values.items()])

    def facts(self) -> list[str]:
        return [f"{k}: {_f(v)}" for k, v in self.values.items()] + [
            f"Opening range uses the first {self.or_minutes} minutes"
        ]

    def as_records(self) -> list[dict]:
        return [{"name": k, "price": round(v, 2)} for k, v in self.values.items()]


def intraday_levels(
    intraday: pl.DataFrame, prev_day: dict, or_minutes: int = 15, symbol: str = ""
) -> IntradayLevels:
    """PDH/PDL from the previous daily bar; OR from the first ``or_minutes``; session VWAP."""
    day = intraday.filter(pl.col("date") == intraday["date"][-1])
    t0 = day["time"][0]
    mins = [
        (int(t[11:13]) * 60 + int(t[14:16])) - (int(t0[11:13]) * 60 + int(t0[14:16]))
        for t in day["time"]
    ]
    orng = day.filter(pl.Series(mins) < or_minutes)
    if orng.height == 0:
        orng = day.head(1)
    vw = ind.vwap(day)["vwap"][-1]
    vals = {
        "PDH": float(prev_day["high"]),
        "PDL": float(prev_day["low"]),
        "OR high": float(orng["high"].max()),
        "OR low": float(orng["low"].min()),
        "VWAP": float(vw),
    }
    return IntradayLevels(symbol, vals, or_minutes)


# ---------------------------------------------------------------- timeframes
def timeframe_row(df: pl.DataFrame, timeframe: str) -> dict:
    """One row of the Add timeframe table."""
    d = _indicators(df)
    last = d.row(-1, named=True)
    sma = last.get("sma_20")
    return {
        "Timeframe": timeframe,
        "Close": round(float(last["close"]), 2),
        "SMA20": None if sma is None else round(float(sma), 2),
        "Close vs SMA20": "—" if sma is None else ("above" if last["close"] >= sma else "below"),
        "RSI(14)": round(float(last["rsi_14"]), 1),
        "ATR(14)": round(float(last["atr_14"]), 2),
        "20-bar high": round(float(d["high"][-20:].max()), 2),
        "20-bar low": round(float(d["low"][-20:].min()), 2),
    }


def timeframes(
    symbol: str, market: str, frames: list[str], end: date | None = None, source: str | None = None
) -> pl.DataFrame:
    """Daily / Weekly / 15-min side by side; rows that disagree are easy to spot."""
    return pl.DataFrame(
        [timeframe_row(load(symbol, market, f, end, source=source), f) for f in frames]
    )


# ---------------------------------------------------------------- screenshot mode
@dataclass
class Claim:
    text: str
    check: str  # ✓ or ✗
    why: str


def screenshot_claims(desc: Description, lv: Levels) -> list[Claim]:
    """A *simulated* screenshot reading, checked against the table claim by claim.

    This lab build does not send images to a model. The simulation reproduces
    the typical eyeballing errors (rounded, shifted levels; guessed readings;
    pattern names) deterministically, so the ✓/✗ comparison can be taught
    offline. Each claim is checked against the computed values.
    """
    rng = np.random.default_rng(
        int(hashlib.sha256((lv.symbol + lv.asof).encode()).hexdigest()[:8], 16)
    )
    atr, close = lv.atr, lv.close
    step = _nice_step(atr, 4)
    out: list[Claim] = []
    res = [z for z in lv.zones if z.kind == "Resistance" and z.touches >= 2]
    sup = [z for z in lv.zones if z.kind == "Support" and z.touches >= 2]
    for name, zs in (("resistance", res), ("support", sup)):
        if not zs:
            continue
        z = min(zs, key=lambda z: abs(z.distance_atr))
        guess = round((z.high + rng.normal(0.25, 0.3) * atr) / step) * step
        ok = z.low - 0.1 * atr <= guess <= z.high + 0.1 * atr
        out.append(
            Claim(
                f"{name.capitalize()} around {guess:,.0f}",
                "✓" if ok else "✗",
                f"table zone {z.zone_text()} ({(guess - z.high) / atr:+.2f} ATR from its top)",
            )
        )
    rsi = desc.values["rsi_14"]
    rsi_guess = round(rsi + rng.normal(0, 6))
    out.append(
        Claim(
            f"RSI looks about {rsi_guess}",
            "✓" if abs(rsi_guess - rsi) <= 5 else "✗",
            f"table RSI(14) {rsi:.1f}",
        )
    )
    trend = "uptrend" if rng.random() < 0.6 else "downtrend"
    sma50 = desc.values.get("sma_50", close)
    actual = "uptrend" if close >= sma50 else "downtrend"
    out.append(
        Claim(
            f"Price is in an {trend}",
            "✓" if trend == actual else "✗",
            f"close {'above' if close >= sma50 else 'below'} SMA50 ({sma50:,.2f})",
        )
    )
    pattern = str(
        rng.choice(
            ["a double top", "a bull flag", "a head-and-shoulders top", "an ascending triangle"]
        )
    )
    out.append(
        Claim(
            f"The chart shows {pattern}",
            "✗",
            "no rule in the table defines this pattern; unverifiable",
        )
    )
    return out


# ---------------------------------------------------------------- save / send
def save_levels_to_journal(
    symbol: str, market: str, timeframe: str, lv: Levels | IntradayLevels
) -> int:
    """Keep the zones and their date for the weekly review (journal notes, local only)."""
    asof = getattr(lv, "asof", str(date.today()))
    body = {
        "screen": "Chart Helper",
        "kind": "levels",
        "symbol": symbol,
        "market": market,
        "timeframe": timeframe,
        "asof": asof,
        "levels": lv.as_records(),
        "text": f"Levels for {symbol} ({timeframe}, {asof}): "
        + "; ".join(
            f"{r.get('kind', r.get('name'))} {r.get('low', r.get('price'))}"
            for r in lv.as_records()
        ),
    }
    return store().add("notes", body, tag="journal")


def send_levels_to_paper_desk(symbol: str, market: str, lv: Levels | IntradayLevels) -> int:
    """Named lines ("OR high", "VWAP", …) for the paper chart and alerts."""
    if isinstance(lv, IntradayLevels):
        lines = lv.as_records()
    else:
        lines = [{"name": z.kind, "price": round((z.low + z.high) / 2, 2)} for z in lv.zones]
    return store().add(
        "notes",
        {
            "kind": "paper_levels",
            "symbol": symbol,
            "market": market,
            "levels": lines,
            "source": "Chart Helper",
        },
        tag="paper_levels",
    )
