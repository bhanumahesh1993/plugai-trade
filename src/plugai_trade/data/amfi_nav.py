"""AMFI mutual-fund NAVs — ``NAVAll.txt`` for today, the history report for past days.

The file is semicolon-separated with category header lines in between. The
parser reads column positions from the header row, so it copes with AMFI's
format change (the old layout is kept only until 30 Sep 2026). History comes in
windows of at most 90 days, AMFI's own limit. The ``symbol`` is a scheme code
(``120503``) or a unique part of the scheme name. Bars carry NAV as O/H/L/C.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl

from . import SourceInfo, register
from .httpkit import BROWSER_UA, get, raw_path, windows

NAV_ALL = "https://portal.amfiindia.com/spages/NAVAll.txt"
HISTORY = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
WINDOW_DAYS = 90
HEADERS = {"User-Agent": BROWSER_UA}


def _field(header: list[str], *needles: str) -> int | None:
    for i, h in enumerate(header):
        low = h.lower()
        if all(n in low for n in needles):
            return i
    return None


def _parse_date(text: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse(text: str) -> pl.DataFrame:
    """AMFI NAV text → ``scheme_code, scheme_name, nav, date`` (one row per scheme-day)."""
    rows: list[dict] = []
    idx: dict[str, int | None] = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 4:
            continue  # blank line or a category / fund-house heading
        if _field(parts, "scheme code") is not None:
            name = _field(parts, "scheme name")
            idx = {"code": _field(parts, "scheme code"),
                   "name": name if name is not None else _field(parts, "nav name"),
                   "nav": _field(parts, "net asset value"), "date": _field(parts, "date")}
            continue
        if not idx or None in idx.values():
            continue
        try:
            nav = float(parts[idx["nav"]].replace(",", ""))
        except (ValueError, IndexError):
            continue  # "N.A." rows
        day = _parse_date(parts[idx["date"]])
        if day:
            rows.append({"scheme_code": parts[idx["code"]], "scheme_name": parts[idx["name"]],
                         "nav": nav, "date": day})
    if not rows:
        return pl.DataFrame(schema={"scheme_code": pl.Utf8, "scheme_name": pl.Utf8,
                                    "nav": pl.Float64, "date": pl.Date})
    return pl.DataFrame(rows)


def latest() -> pl.DataFrame:
    """Today's NAVAll.txt (raw copy kept in ``<lab>/raw/amfi``)."""
    text = get(NAV_ALL, headers=HEADERS).text
    raw_path("amfi", f"NAVAll_{date.today():%Y%m%d}.txt").write_text(text, encoding="utf-8")
    return parse(text)


def history(start: date, end: date) -> pl.DataFrame:
    """All schemes' NAVs between two dates, fetched in ≤90-day windows."""
    frames = []
    for lo, hi in windows(start, end, WINDOW_DAYS):
        raw = raw_path("amfi", f"history_{lo:%Y%m%d}_{hi:%Y%m%d}.txt")
        if raw.exists() and hi < date.today():
            text = raw.read_text(encoding="utf-8")  # past windows never change
        else:
            params = {"tp": "1", "frmdt": f"{lo:%d-%b-%Y}", "todt": f"{hi:%d-%b-%Y}"}
            text = get(HISTORY, params=params, headers=HEADERS, min_interval=1.0).text
            raw.write_text(text, encoding="utf-8")
        frames.append(parse(text))
    return pl.concat(frames) if frames else parse("")


def pick_scheme(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """Rows for one scheme, by code or by a unique part of its name."""
    by_code = df.filter(pl.col("scheme_code") == symbol)
    if not by_code.is_empty():
        return by_code
    hits = df.filter(pl.col("scheme_name").str.to_lowercase().str.contains(symbol.lower(),
                                                                           literal=True))
    names = hits["scheme_name"].unique().to_list()
    if len(names) > 1:
        raise ValueError(f"'{symbol}' matches {len(names)} schemes; use the scheme code.")
    return hits


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    if interval != "1d":
        raise ValueError("AMFI publishes one NAV per day.")
    df = latest() if start >= date.today() - timedelta(days=3) else history(start, end)
    rows = pick_scheme(df, symbol).filter((pl.col("date") >= start) & (pl.col("date") <= end))
    return rows.select("date", *[pl.col("nav").alias(c) for c in ("open", "high", "low", "close")],
                       pl.lit(0.0).alias("volume"))


register(SourceInfo(
    name="amfi_nav", tier="No signup", markets=("IN",), license_class="personal-use",
    needs="Nothing", fetch=_fetch,
    description="Daily mutual-fund NAVs from AMFI (NAVAll.txt + 90-day history report). Terms unverified: keep it personal.",
))
