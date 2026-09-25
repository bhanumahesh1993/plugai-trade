"""Six deterministic detectors (Chapter 14). Code counts; the model only narrates.

1 Time of day · 2 Rule Card breaks · 3 Overtrading and charges · 4 Streaks, re-entries
and tilt · 5 Holding time · 6 Shape of results. Every finding keeps the rows and a
readable query, and any group under 30 trades is labelled "too few to conclude".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from .. import reference
from ..store import default as store
from .schema import SIMULATED

MIN_N = 30
TOO_FEW = "too few to conclude"
REENTRY_MINUTES = 30


def n_label(n: int) -> str:
    """'n = 11, too few to conclude' for small groups; 'n = 54' otherwise."""
    return f"n = {n}, {TOO_FEW}" if n < MIN_N else f"n = {n}"


# ------------------------------------------------------------------ Rule Card
@dataclass
class RuleCard:
    """The checkable lines of a Rule Card. None switches a line off."""

    version: str = "Chapter 14 sample"
    no_trade_first_minutes: int | None = 15
    max_trades_per_day: int | None = 3
    stop_breach_r: float | None = 1.2
    daily_loss_r: float | None = 2.0
    cooldown_minutes: int | None = None

    def lines(self) -> list[tuple[str, str]]:
        """(rule key, 'Rule Card line → how the code tests it') for every active line."""
        out = []
        if self.no_trade_first_minutes:
            out.append(("first_minutes", f"No trade in the first {self.no_trade_first_minutes} "
                        "min → entry before open + that many minutes"))
        if self.max_trades_per_day:
            out.append(("over_cap", f"Max {self.max_trades_per_day} new trades a day → "
                        f"trade number {self.max_trades_per_day + 1} and later of a day"))
        if self.stop_breach_r:
            out.append(("stop_moved",
                        f"Stop never moved away → loss beyond −{self.stop_breach_r}R"))
        if self.daily_loss_r:
            out.append(("after_daily_limit", f"Daily loss {self.daily_loss_r:g}R stops trading → "
                        f"trades after the day reached −{self.daily_loss_r:g}R"))
        if self.cooldown_minutes:
            out.append(("cooldown", f"Cooldown {self.cooldown_minutes} min after a loss → entry "
                        "within that many minutes of a losing exit"))
        return out

    @classmethod
    def from_store(cls) -> "RuleCard":
        """The latest saved Rule Card's checkable limits (defaults for anything missing)."""
        rows = store().all("rule_cards", limit=1)
        if not rows:
            return cls()
        r = rows[0]
        flat: dict[str, Any] = dict(r)
        for nest in ("limits", "guardrails", "checks", "intraday"):
            if isinstance(r.get(nest), dict):
                flat.update(r[nest])
        pick = _picker(flat)
        return cls(
            version=str(r.get("version") or r.get("name") or f"v{r['id']}"),
            no_trade_first_minutes=pick(("no_trade_first_minutes", "first_minutes",
                                         "skip_first_minutes"), 15, int),
            max_trades_per_day=pick(("max_trades_per_day", "max_trades"), 3, int),
            stop_breach_r=pick(("stop_breach_r",), 1.2, float),
            daily_loss_r=pick(("daily_loss_r", "daily_loss_limit_r"), 2.0, float),
            cooldown_minutes=pick(("cooldown_minutes", "cooldown_min", "cooldown"), None, int),
        )


def _picker(flat: dict[str, Any]):
    def pick(keys: tuple[str, ...], default: Any, cast: type) -> Any:
        for k in keys:
            if k in flat and flat[k] not in ("", None):
                try:
                    return cast(flat[k])
                except (TypeError, ValueError):
                    return default
        return default
    return pick


# ------------------------------------------------------------------ sessions
def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def session(market: str) -> tuple[int, int]:
    """(open, close) in minutes after midnight, local exchange time, from the dated table."""
    row = reference.lookup(f"{'india' if market == 'IN' else 'us'}.sessions.cash") or {}
    return _hm(row.get("open", "09:15")), _hm(row.get("close", "15:30"))


def expiry_weekday(market: str) -> int | None:
    """Weekday (Mon=0) of the weekly NIFTY expiry, parsed from the dated contract table."""
    if market != "IN":
        return None
    text = str((reference.lookup("india.contracts.NIFTY") or {}).get("expiry", ""))
    days = ("monday", "tuesday", "wednesday", "thursday", "friday")
    m = re.search(r"(monday|tuesday|wednesday|thursday|friday)", text.lower())
    return days.index(m.group(1)) if m else None


def bucket_edges(market: str, first_minutes: int = 15) -> list[int]:
    """Entry-time bucket starts: open, open + first window, then hourly on the half hour."""
    open_, close = session(market)
    edges = [open_, open_ + first_minutes]
    t = (edges[1] // 60 + 1) * 60 + 30 if edges[1] % 60 >= 30 else (edges[1] // 60) * 60 + 30
    if t <= edges[1]:
        t += 60
    while t < close - 30:
        edges.append(t)
        t += 60
    return edges


def _label(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


# ------------------------------------------------------------------ enrich
def real_trades(trades: pl.DataFrame) -> pl.DataFrame:
    """Drop BLOCKED rows (tickets that never filled): they are counted, not traded."""
    if trades.is_empty():
        return trades
    return trades.filter(~pl.col("tags").list.contains("BLOCKED").fill_null(False))


def enrich(trades: pl.DataFrame, card: RuleCard | None = None) -> pl.DataFrame:
    """Add the derived columns every detector and Ask My Journal query uses."""
    card = card or RuleCard()
    t = real_trades(trades)
    if t.is_empty():
        return t.with_columns([pl.lit(None).alias(c) for c in DERIVED])
    market = t["market"][0] or "IN"
    open_, close = session(market)
    first = card.no_trade_first_minutes or 15
    edges = bucket_edges(market, first)
    xwd = expiry_weekday(market)
    t = t.sort("entry_time").with_columns(
        entry_min=(pl.col("entry_time").dt.hour().cast(pl.Int32) * 60
                   + pl.col("entry_time").dt.minute().cast(pl.Int32)),
        hold_minutes=((pl.col("exit_time") - pl.col("entry_time")).dt.total_seconds() / 60)
        .round(1),
        win=pl.col("gross") > 0,
        weekday=pl.col("entry_time").dt.strftime("%a"),
        hour=pl.col("entry_time").dt.hour(),
        r=pl.col("r_multiple").fill_null(0.0),
    )
    t = t.with_columns(
        minutes_from_open=pl.col("entry_min") - open_,
        tod_bucket=pl.col("entry_min").map_elements(
            lambda m: _label(max([e for e in edges if e <= m], default=edges[0])),
            return_dtype=pl.Utf8),
        day_seq=pl.int_range(1, pl.len() + 1).over("date"),
        prev_exit=pl.col("exit_time").shift(1).over("date"),
        prev_win=pl.col("win").shift(1).over("date"),
        prev_r=pl.col("r").shift(1).over("date"),
        prev_loss_seq=(~pl.col("win")).shift(1).fill_null(False),
        prev2_loss_seq=(~pl.col("win")).shift(2).fill_null(False),
        day_r_before=(pl.col("r").cum_sum().over("date") - pl.col("r")),
    ).with_columns(day_r_low=pl.col("day_r_before").cum_min().over("date"))
    gap = ((pl.col("entry_time") - pl.col("prev_exit")).dt.total_seconds() / 60).round(1)
    t = t.with_columns(gap_minutes=gap).with_columns(
        prev_loss_same_day=(pl.col("prev_win") == False).fill_null(False),  # noqa: E712
        after_two_losses=pl.col("prev_loss_seq") & pl.col("prev2_loss_seq"),
        window=pl.when(pl.col("minutes_from_open") < first).then(pl.lit(f"first {first} min"))
        .when((pl.lit(market) == "US") & (pl.col("minutes_from_open") < 30))
        .then(pl.lit("first 30 min"))
        .when((pl.lit(market) == "US") & (pl.col("entry_min") >= close - 30))
        .then(pl.lit("last 30 min"))
        .when((pl.lit(xwd) == pl.col("entry_time").dt.weekday() - 1)
              & (pl.col("entry_min") >= 12 * 60)).then(pl.lit("expiry afternoon"))
        .otherwise(pl.lit("")),
    )
    t = t.with_columns(
        reentry_after_loss=pl.col("prev_loss_same_day")
        & (pl.col("gap_minutes") <= REENTRY_MINUTES).fill_null(False))
    return _flag_breaks(t, card)


def _flag_breaks(t: pl.DataFrame, card: RuleCard) -> pl.DataFrame:
    false = pl.lit(False)
    cols = {
        "br_first_minutes": (pl.col("minutes_from_open") < card.no_trade_first_minutes)
        if card.no_trade_first_minutes else false,
        "br_over_cap": (pl.col("day_seq") > card.max_trades_per_day)
        if card.max_trades_per_day else false,
        "br_stop_moved": (pl.col("r_multiple") < -card.stop_breach_r).fill_null(False)
        if card.stop_breach_r else false,
        "br_after_daily_limit": (pl.col("day_r_low") <= -card.daily_loss_r)
        if card.daily_loss_r else false,
        "br_cooldown": (pl.col("prev_loss_same_day")
                        & (pl.col("gap_minutes") <= card.cooldown_minutes).fill_null(False))
        if card.cooldown_minutes else false,
    }
    t = t.with_columns(**cols)
    names = {"br_first_minutes": "first minutes", "br_over_cap": "over daily cap",
             "br_stop_moved": "stop moved", "br_after_daily_limit": "after daily loss limit",
             "br_cooldown": "cooldown"}
    return t.with_columns(
        broke_rule=pl.any_horizontal(list(cols)),
        rules_broken=pl.concat_str(
            [pl.when(pl.col(c)).then(pl.lit(n)).otherwise(None) for c, n in names.items()],
            separator=", ", ignore_nulls=True),
    )


DERIVED = ("entry_min", "hold_minutes", "win", "weekday", "hour", "r", "minutes_from_open",
           "tod_bucket", "day_seq", "prev_exit", "prev_win", "prev_r", "prev_loss_seq",
           "prev2_loss_seq", "day_r_before", "day_r_low", "gap_minutes", "prev_loss_same_day",
           "after_two_losses", "window", "reentry_after_loss", "br_first_minutes",
           "br_over_cap", "br_stop_moved", "br_after_daily_limit", "br_cooldown", "broke_rule",
           "rules_broken")


# ------------------------------------------------------------------ findings
@dataclass
class Finding:
    """One counted fact with the rows and the query behind it."""

    label: str
    n: int
    total_r: float
    rows: list[int]
    query: str
    wins: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        r = f"{self.total_r:+.2f}R".replace("-", "−")
        return f"{self.label}: {self.n} trades, {self.wins} wins, {r} ({n_label(self.n)})"


def finding(e: pl.DataFrame, mask: pl.Expr, label: str, query: str) -> Finding:
    sub = e.filter(mask)
    return Finding(label=label, n=sub.height, total_r=round(float(sub["r"].sum() or 0), 2),
                   rows=sub["trade_id"].to_list(), query=query,
                   wins=int(sub["win"].sum() or 0) if sub.height else 0,
                   extra={"charges": round(float(sub["charges"].sum() or 0), 2)})


def _median(s: pl.Series) -> float | None:
    v = s.median()
    return None if v is None else round(float(v), 1)


@dataclass
class DetectorReport:
    """All six detectors over one set of trades."""

    market: str
    n: int
    card: RuleCard
    time_of_day: pl.DataFrame
    windows: list[Finding]
    rule_breaks: list[Finding]
    broke_any: Finding
    broke_none: Finding
    over_cap: Finding
    costs: dict[str, float | None]
    reentries: Finding
    after_two_losses: Finding
    rest_after_two: Finding
    gaps: dict[str, float | None]
    holding: dict[str, float | None]
    long_losers: Finding
    beyond_stop: Finding
    histogram: pl.DataFrame
    avg_winner_r: float | None
    blocked: int = 0

    @property
    def adherence(self) -> float | None:
        return None if not self.n else round(self.broke_none.n / self.n * 100, 1)

    def facts(self) -> list[str]:
        cur = "₹" if self.market == "IN" else "$"
        c = self.costs
        out = [f"Trades: {self.n} ({n_label(self.n)})",
               f"Adherence: {self.adherence}% ({self.broke_none.n} of {self.n} broke no line)",
               self.broke_any.text(), self.broke_none.text()]
        out += [f.text() for f in self.rule_breaks]
        pct = "n/a (gross ≤ 0)" if c["charges_pct_gross"] is None else f"{c['charges_pct_gross']}%"
        out += [f"Charges: {cur}{c['charges']:,.2f} = {pct} of gross "
                f"{cur}{c['gross']:,.2f}; net {cur}{c['net']:,.2f}",
                f"Average charges per trade: {cur}{c['avg_charges']:,.2f} "
                f"({c['charges_in_r']}R of average risk)",
                self.reentries.text() + f", charges {cur}{self.reentries.extra['charges']:,.2f}",
                f"Median wait after a win: {self.gaps['after_win']} min; after a loss: "
                f"{self.gaps['after_loss']} min",
                f"After two losses in a row: {self.after_two_losses.n} trades, mean "
                f"{self.after_two_losses.extra.get('mean_r')}R; rest mean "
                f"{self.rest_after_two.extra.get('mean_r')}R",
                f"Median hold: winners {self.holding['win_median']} min, losers "
                f"{self.holding['loss_median']} min (means {self.holding['win_mean']} vs "
                f"{self.holding['loss_mean']})",
                self.long_losers.text(), self.beyond_stop.text(),
                f"Average winner: {self.avg_winner_r}R"]
        for w in self.windows:
            out.append(w.text())
        for row in self.time_of_day.iter_rows(named=True):
            out.append(f"Entry bucket {row['bucket']}: {row['n']} trades, {row['wins']} wins, "
                       f"{row['total_r']:+.2f}R ({row['note']})")
        if self.blocked:
            out.append(f"Blocked tickets (never filled): {self.blocked}")
        return out


def run(trades: pl.DataFrame, card: RuleCard | None = None) -> DetectorReport:
    """Run all six detectors."""
    card = card or RuleCard()
    blocked = trades.height - real_trades(trades).height if not trades.is_empty() else 0
    e = enrich(trades, card)
    market = (e["market"][0] if e.height else None) or "IN"
    return DetectorReport(
        market=market, n=e.height, card=card, time_of_day=time_of_day(e),
        windows=_windows(e), rule_breaks=rule_breaks(e, card),
        broke_any=finding(e, pl.col("broke_rule"), "Broke at least one line",
                          "WHERE broke_rule") if e.height else _empty("Broke at least one line"),
        broke_none=finding(e, ~pl.col("broke_rule"), "Broke none",
                           "WHERE NOT broke_rule") if e.height else _empty("Broke none"),
        over_cap=finding(e, pl.col("br_over_cap"), "Over the daily cap", "WHERE day_seq > cap")
        if e.height else _empty("Over the daily cap"),
        costs=cost_summary(e), reentries=_reentries(e),
        after_two_losses=_after_two(e, True), rest_after_two=_after_two(e, False),
        gaps=_gaps(e), holding=_holding(e), long_losers=_long_losers(e),
        beyond_stop=_beyond(e, card), histogram=histogram(e),
        avg_winner_r=round(float(e.filter(pl.col("win"))["r"].mean()), 2)
        if e.height and e["win"].any() else None,
        blocked=blocked,
    )


def _empty(label: str) -> Finding:
    return Finding(label, 0, 0.0, [], "")


def time_of_day(e: pl.DataFrame) -> pl.DataFrame:
    """Detector 1: result in R, count and wins by entry-time bucket."""
    if e.is_empty():
        return pl.DataFrame(schema={"bucket": pl.Utf8, "n": pl.UInt32, "wins": pl.UInt32,
                                    "total_r": pl.Float64, "note": pl.Utf8,
                                    "rows": pl.List(pl.Int64)})
    return (e.group_by("tod_bucket").agg(
        n=pl.len(), wins=pl.col("win").sum(), total_r=pl.col("r").sum().round(2),
        rows=pl.col("trade_id"))
        .rename({"tod_bucket": "bucket"}).sort("bucket")
        .with_columns(note=pl.col("n").map_elements(lambda n: n_label(int(n)),
                                                     return_dtype=pl.Utf8))
        .select("bucket", "n", "wins", "total_r", "note", "rows"))


def _windows(e: pl.DataFrame) -> list[Finding]:
    if e.is_empty():
        return []
    return [finding(e, pl.col("window") == w, f"Window '{w}'", f"WHERE window = '{w}'")
            for w in sorted(set(e["window"].to_list()) - {""})]


def rule_breaks(e: pl.DataFrame, card: RuleCard) -> list[Finding]:
    """Detector 2: each Rule Card line tested on every trade."""
    if e.is_empty():
        return []
    return [finding(e, pl.col(f"br_{key}"), line.split(" → ")[0], f"WHERE {line.split(' → ')[1]}")
            for key, line in card.lines()]


def cost_summary(e: pl.DataFrame) -> dict[str, float | None]:
    """Detector 3: charges against gross, per trade and in R."""
    if e.is_empty():
        return {k: 0.0 for k in ("charges", "gross", "net", "charges_pct_gross", "avg_charges",
                                 "avg_risk", "charges_in_r", "total_r")}
    charges, gross = float(e["charges"].sum()), float(e["gross"].sum())
    avg_risk = e["risk"].mean()
    avg_ch = charges / e.height
    return {
        "charges": round(charges, 2), "gross": round(gross, 2), "net": round(gross - charges, 2),
        "charges_pct_gross": round(charges / gross * 100, 1) if gross > 0 else None,
        "avg_charges": round(avg_ch, 2),
        "avg_risk": round(float(avg_risk), 2) if avg_risk else None,
        "charges_in_r": round(avg_ch / float(avg_risk), 2) if avg_risk else None,
        "total_r": round(float(e["r"].sum()), 2),
    }


def _reentries(e: pl.DataFrame) -> Finding:
    """Detector 4a: trades opened within 30 min of a losing exit on the same day."""
    if e.is_empty():
        return _empty("Quick re-entries")
    return finding(e, pl.col("reentry_after_loss"),
                   f"Re-entry ≤ {REENTRY_MINUTES} min after a loss",
                   f"WHERE previous trade same day was a loss AND gap ≤ {REENTRY_MINUTES} min")


def _after_two(e: pl.DataFrame, inside: bool) -> Finding:
    if e.is_empty():
        return _empty("After two losses")
    mask = pl.col("after_two_losses") if inside else ~pl.col("after_two_losses")
    f = finding(e, mask, "After two losses in a row" if inside else "All other trades",
                "WHERE previous two trades were losses" if inside else
                "WHERE NOT previous two trades were losses")
    f.extra["mean_r"] = round(f.total_r / f.n, 2) if f.n else None
    return f


def _gaps(e: pl.DataFrame) -> dict[str, float | None]:
    if e.is_empty():
        return {"after_win": None, "after_loss": None}
    return {"after_win": _median(e.filter(pl.col("prev_win") == True)["gap_minutes"]),  # noqa: E712
            "after_loss": _median(e.filter(pl.col("prev_win") == False)["gap_minutes"])}  # noqa: E712


def _holding(e: pl.DataFrame) -> dict[str, float | None]:
    """Detector 5: minutes in the trade, winners vs losers (median and mean)."""
    if e.is_empty():
        return {k: None for k in ("win_median", "loss_median", "win_mean", "loss_mean")}
    w, lo = e.filter(pl.col("win"))["hold_minutes"], e.filter(~pl.col("win"))["hold_minutes"]
    mean = lambda s: None if s.is_empty() else round(float(s.mean()), 1)  # noqa: E731
    return {"win_median": _median(w), "loss_median": _median(lo), "win_mean": mean(w),
            "loss_mean": mean(lo)}


def _long_losers(e: pl.DataFrame) -> Finding:
    if e.is_empty():
        return _empty("Losers held over an hour")
    return finding(e, ~pl.col("win") & (pl.col("hold_minutes") > 60), "Losers held over an hour",
                   "WHERE loss AND hold_minutes > 60")


def _beyond(e: pl.DataFrame, card: RuleCard) -> Finding:
    """Detector 6: losses beyond the planned stop."""
    lim = card.stop_breach_r or 1.2
    if e.is_empty():
        return _empty(f"Losses beyond −{lim}R")
    return finding(e, pl.col("r") < -lim, f"Losses beyond −{lim}R", f"WHERE r < -{lim}")


def histogram(e: pl.DataFrame, step: float = 0.5) -> pl.DataFrame:
    """Detector 6: count of trades per R bin (bins centred on multiples of ``step``)."""
    if e.is_empty():
        return pl.DataFrame(schema={"bin": pl.Float64, "n": pl.UInt32})
    return (e.with_columns(bin=((pl.col("r") / step).round(0) * step))
            .group_by("bin").agg(n=pl.len()).sort("bin"))


def simulated_mask() -> pl.Expr:
    """True for PAPER / REPLAY / BLOCKED rows."""
    return pl.any_horizontal([pl.col("tags").list.contains(t) for t in SIMULATED]).fill_null(False)
