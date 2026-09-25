"""Import holdings: CAS PDF (password, read locally), broker holdings CSV, generic CSV.

The file never leaves the computer and is never sent to an AI model. Parsing is
best-effort: every row the importer cannot match to a known fund is flagged
(amber on screen) so the user can pick the scheme or ticker by hand.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from .funds import Fund


@dataclass
class Holding:
    """One line of the Holdings table."""

    name: str
    units: float
    price: float
    value: float
    asset_class: str = "Equity"
    account: str = ""
    plan: str = ""  # Direct | Regular (India) or share class (US)
    isin: str = ""
    match: str | None = None  # fund_id in the catalogue
    extra: dict = field(default_factory=dict)

    @property
    def matched(self) -> bool:
        """False rows are shown in amber until picked by hand."""
        return self.match is not None


def _num(x: object) -> float | None:
    s = re.sub(r"[₹$,\s]|INR|USD", "", str(x or ""))
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ------------------------------------------------------------------ CAS
_CLOSING = re.compile(
    r"Closing Unit Balance:\s*([\d,]+\.?\d*).*?NAV on [^:]*:\s*(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*)"
    r"(?:.*?Market Value on [^:]*:\s*(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*))?", re.I | re.S)
_SCHEME = re.compile(r"^\s*[A-Z0-9]{2,12}-(.+?)(?:\s*\(Advisor|\s*Registrar|\s*ISIN|\s*-\s*ISIN|$)", re.I)
_DEMAT = re.compile(r"(INF[A-Z0-9]{9})\s+(.+?)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s*$")


def parse_cas_text(text: str) -> list[Holding]:
    """Holdings from the text of a CAMS / KFintech / NSDL / CDSL consolidated statement."""
    out: list[Holding] = []
    scheme = ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _DEMAT.search(line)
        if m:
            isin, name, units, nav, value = m.groups()
            out.append(Holding(name.strip(), _num(units) or 0.0, _num(nav) or 0.0,
                               _num(value) or 0.0, plan=_plan(name), isin=isin))
            continue
        s = _SCHEME.match(line)
        if s and ("fund" in line.lower() or "plan" in line.lower() or "growth" in line.lower()):
            scheme = s.group(1).strip(" -")
            continue
        if "closing unit balance" in line.lower():
            window = " ".join(lines[i:i + 3])
            c = _CLOSING.search(window)
            if c:
                units, nav = _num(c.group(1)) or 0.0, _num(c.group(2)) or 0.0
                value = _num(c.group(3)) if c.group(3) else units * nav
                out.append(Holding(scheme or "Unknown scheme", units, nav, value or units * nav,
                                   plan=_plan(scheme)))
    return out


def _plan(name: str) -> str:
    n = name.lower()
    if "direct" in n:
        return "Direct"
    if "regular" in n:
        return "Regular"
    return ""


class CasPasswordError(ValueError):
    """The CAS PDF is encrypted and the password did not open it."""


def read_cas_pdf(source: str | Path | bytes | BinaryIO, password: str = "") -> list[Holding]:
    """Open a (usually password-protected) CAS PDF locally with pypdf and parse it."""
    from pypdf import PdfReader

    stream = io.BytesIO(source) if isinstance(source, bytes) else source
    reader = PdfReader(stream)
    if reader.is_encrypted:
        if not password or not reader.decrypt(password):
            raise CasPasswordError("The password did not open this CAS (often your PAN in capitals, "
                                   "or as set when you requested it).")
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return parse_cas_text(text)


# ------------------------------------------------------------------ CSV
_SYNONYMS = {
    "name": ("instrument", "scheme name", "scheme", "fund name", "fund", "description",
             "security", "name", "trading symbol", "symbol", "ticker"),
    "units": ("qty.", "qty", "quantity", "units", "balance units", "shares"),
    "price": ("ltp", "nav", "last price", "price", "current nav", "close price", "current price"),
    "value": ("cur. val", "current value", "market value", "value", "present value",
              "current value (inr)"),
    "account": ("account type", "account", "account name"),
    "asset_class": ("asset class", "asset type", "category", "type"),
    "plan": ("plan", "share class"),
}


def _columns(fieldnames: list[str]) -> dict[str, str]:
    low = {f.lower().strip(): f for f in fieldnames if f}
    found = {}
    for key, options in _SYNONYMS.items():
        for o in options:
            if o in low:
                found[key] = low[o]
                break
    return found


def parse_holdings_csv(text: str, account: str = "") -> list[Holding]:
    """Broker holdings export (Zerodha, Groww, Upstox, Fidelity, Schwab …) or a generic CSV.

    Needs a name column and either units + price or a value column.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = _columns(reader.fieldnames or [])
    if "name" not in cols or not ({"units", "price"} <= cols.keys() or "value" in cols):
        raise ValueError("Could not find the columns: need a name/symbol column and units + "
                         "price, or a value column. Rename the headers or use the generic "
                         "template: name, units, price, value, asset_class, account.")
    out = []
    for r in reader:
        name = (r.get(cols["name"]) or "").strip()
        if not name or name.lower().startswith("total"):
            continue
        units = _num(r.get(cols.get("units", ""), "")) or 0.0
        price = _num(r.get(cols.get("price", ""), "")) or 0.0
        value = _num(r.get(cols.get("value", ""), ""))
        value = value if value is not None else units * price
        out.append(Holding(name, units, price, value,
                           asset_class=(r.get(cols.get("asset_class", ""), "") or "Equity").strip(),
                           account=(r.get(cols.get("account", ""), "") or account).strip(),
                           plan=(r.get(cols.get("plan", ""), "") or _plan(name)).strip()))
    return out


# ------------------------------------------------------------------ matching
def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9&]+", s.lower())
            if t not in {"fund", "plan", "growth", "direct", "regular", "the", "etf", "idcw", "option"}}


def match(holdings: list[Holding], catalogue: dict[str, Fund]) -> list[Holding]:
    """Attach each holding to a known fund by id, name or name tokens; others stay unmatched."""
    for h in holdings:
        if h.match in catalogue:
            continue
        h.match = None
        for fid, f in catalogue.items():
            if h.name == fid or h.name.lower() == f.name.lower():
                h.match = fid
                break
        if h.match is None:
            best, score = None, 0.0
            for fid, f in catalogue.items():
                a, b = _tokens(h.name), _tokens(f.name)
                if a and b:
                    j = len(a & b) / len(a | b)
                    if j > score:
                        best, score = fid, j
            if score >= 0.6:
                h.match = best
        if h.match:
            h.asset_class = catalogue[h.match].asset_class
    return holdings


def sample_holdings(market: str) -> list[Holding]:
    """Lesson 15 sample portfolios (synthetic): Priya (IN) and Mark (US)."""
    if market == "IN":
        from .funds import PRIYA_FUNDS
        rows = [Holding(name, round(value / nav, 3), nav, value, "Equity", "CAS", "Regular",
                        match=fid)
                for (fid, (name, _r, _d, value)), nav in zip(PRIYA_FUNDS.items(),
                                                             (61.25, 88.40, 125.0, 47.5, 250.0), strict=True)]
        rows += [Holding("Short-duration debt fund", 14_000.0, 34.2, 478_800, "Debt", "CAS",
                         "Regular", match="DEBT"),
                 Holding("Gold ETF", 2_300.0, 68.0, 156_400, "Gold", "Demat", "", match="GOLD"),
                 Holding("Unlisted scheme XYZ (synthetic)", 500.0, 20.0, 10_000, "Equity", "CAS",
                         "Regular")]
        return rows
    return [Holding("S&P 500 index fund (401k)", 180.0, 150.0, 27_000, "US stocks", "401(k)", match="S"),
            Holding("Total US market ETF (Roth IRA)", 40.0, 290.0, 11_600, "US stocks", "IRA", match="T"),
            Holding("Large-cap growth ETF (brokerage)", 12.0, 340.0, 4_080, "US stocks", "Brokerage", match="G"),
            Holding("International index fund", 350.0, 32.0, 11_200, "Intl", "401(k)", match="INTL"),
            Holding("US bond index fund", 1_060.0, 10.0, 10_600, "Bonds", "401(k)", match="BOND"),
            Holding("SYNTECH (single stock)", 5.0, 164.0, 820, "US stocks", "Brokerage")]
