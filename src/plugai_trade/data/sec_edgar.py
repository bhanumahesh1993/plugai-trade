"""SEC EDGAR — filings and XBRL company facts. Public information; no key.

The SEC asks every program to identify itself, so requests carry the contact
you set in Settings › Data Sources (``data.edgar_contact``, e.g. "Asha Rao
asha@example.com"), and stay well under 10 requests a second. Raw JSON is kept
in ``<lab>/raw/sec``.

EDGAR has no prices. Through the router (``plugai-trade fetch sec-edgar
--ticker AAPL``) it returns one row per filing date with empty price columns,
so the fetch lands tagged and cached; use :func:`filings` and :func:`facts`
for the real content.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import polars as pl

from .. import config
from . import SourceInfo, register
from .httpkit import NeedsKey, get, raw_path

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
MIN_INTERVAL = 0.15  # < 10 requests per second


def user_agent() -> str:
    contact = str(config.get("data.edgar_contact", "") or "").strip()
    if "@" not in contact:
        raise NeedsKey("SEC EDGAR needs a contact: set 'EDGAR contact' (name and email) in "
                       "Settings › Data Sources. The SEC requires it in every request.")
    return f"PlugAI-Trade {contact}"


def _json(url: str, cache_name: str) -> Any:
    resp = get(url, headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"},
               min_interval=MIN_INTERVAL)
    raw_path("sec", cache_name).write_bytes(resp.content)
    return resp.json()


def cik(ticker: str) -> str:
    """Ten-digit CIK for a ticker (the SEC's ticker list is cached for the day)."""
    if ticker.isdigit():
        return ticker.zfill(10)
    cached = raw_path("sec", f"company_tickers_{date.today():%Y%m%d}.json")
    table = (json.loads(cached.read_text(encoding="utf-8")) if cached.exists()
             else _json(TICKERS_URL, cached.name))
    for row in table.values():
        if str(row.get("ticker", "")).upper() == ticker.upper():
            return str(row["cik_str"]).zfill(10)
    raise ValueError(f"{ticker}: not in the SEC ticker list.")


def submissions(ticker: str) -> dict[str, Any]:
    c = cik(ticker)
    return _json(SUBMISSIONS.format(cik=c), f"submissions_{c}.json")


def company_facts(ticker: str) -> dict[str, Any]:
    c = cik(ticker)
    return _json(FACTS.format(cik=c), f"companyfacts_{c}.json")


def filings(ticker: str, forms: tuple[str, ...] = ()) -> pl.DataFrame:
    """Recent filings: ``filed, form, accession, document, report_date``."""
    recent = submissions(ticker).get("filings", {}).get("recent", {})
    df = pl.DataFrame({
        "filed": recent.get("filingDate", []), "form": recent.get("form", []),
        "accession": recent.get("accessionNumber", []),
        "document": recent.get("primaryDocument", []),
        "report_date": recent.get("reportDate", []),
    }, schema={c: pl.Utf8 for c in ("filed", "form", "accession", "document", "report_date")})
    df = df.with_columns(pl.col("filed").str.to_date(strict=False))
    return df.filter(pl.col("form").is_in(list(forms))) if forms else df


def facts(ticker: str, concept: str = "Revenues", unit: str = "USD") -> pl.DataFrame:
    """One XBRL concept over time: ``end, value, form, fiscal_period, filed``."""
    data = company_facts(ticker).get("facts", {})
    for taxonomy in data.values():
        if concept in taxonomy:
            rows = taxonomy[concept].get("units", {}).get(unit, [])
            return pl.DataFrame([{"end": r.get("end"), "value": r.get("val"),
                                  "form": r.get("form"), "fiscal_period": r.get("fp"),
                                  "filed": r.get("filed")} for r in rows])
    raise ValueError(f"{ticker}: no XBRL concept '{concept}'.")


def _fetch(symbol: str, market: str, start: date, end: date, interval: str = "1d") -> pl.DataFrame:
    df = filings(symbol)
    if start < end:  # a single --date (or none) means "latest filings"
        df = df.filter((pl.col("filed") >= start) & (pl.col("filed") <= end))
    nothing = pl.lit(None, dtype=pl.Float64)
    return df.select(pl.col("filed").alias("date"), *[nothing.alias(c) for c in
                                                      ("open", "high", "low", "close", "volume")])


register(SourceInfo(
    name="sec_edgar", tier="No signup", markets=("US", "ANY"), license_class="public",
    needs="Contact email (SEC rule)", fetch=_fetch,
    description="US filings and XBRL company facts. Public information: may be shared.",
))
