"""Research › IPO Dashboard: RHP digest, subscription, odds, SME checks, listing-day plan.

    from plugai_trade import ipo
    x = ipo.example()                    # the fictional Example Ltd
    print(ipo.digest_tiles(x))           # issue size, fresh/OFS, both P/Es, promoters …
    odds = ipo.allotment_odds(x, applications=2_460_000, applicants=2)
    print(odds.facts())

Every tile and odds figure is computed in code from quoted RHP numbers. The
grey-market premium is shown only in its own panel, labelled unofficial, and
is excluded from every tile, plan and odds calculation.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from .. import ai, alerts, reference
from ..docdesk import Document, extract, sample
from ..docdesk.extract import Field, find
from ..store import default as store

GMP_BANNER = "UNOFFICIAL · UNREGULATED · NOT A FORECAST"
CR = 1e7  # one crore
LAKH = 1e5


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    """Dated IPO rules: the reference tables first (india.ipo), else the bundled file."""
    ref = reference.lookup("india.ipo")
    if ref:
        return ref
    return yaml.safe_load(resources.files(__package__).joinpath("rules.yaml").read_text())


@dataclass
class Issue:
    """One IPO record (figures as quoted in the RHP)."""

    name: str
    board: str  # Mainboard | SME
    platform: str
    price_low: float
    price_high: float
    lot: int
    fresh_shares: float
    ofs_shares: float
    pre_issue_shares: float
    promoter_pre_shares: float
    promoter_sell_shares: float
    pat_cr: float
    peer_pe: list[float]
    anchor_shares: float
    objects_cr: dict[str, float]
    offered: dict[str, float]  # shares on offer per category, anchors excluded
    open_date: str = ""
    close_date: str = ""
    listing_date: str = ""
    allotment_date: str = ""
    pre_ipo_shares: float = 0.0
    rhp_sample: str = ""  # name of the fictional sample RHP in the Document Desk
    status: str = "open"

    @property
    def issue_shares(self) -> float:
        return self.fresh_shares + self.ofs_shares

    @property
    def post_issue_shares(self) -> float:
        return self.pre_issue_shares + self.fresh_shares

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


def example() -> Issue:
    """Example Ltd (fictional), the Chapter 20 mainboard issue."""
    return Issue(
        name="Example Ltd",
        board="Mainboard",
        platform="NSE / BSE",
        price_low=270,
        price_high=284,
        lot=50,
        fresh_shares=1.4 * CR,
        ofs_shares=2.1 * CR,
        pre_issue_shares=10 * CR,
        promoter_pre_shares=7.8 * CR,
        promoter_sell_shares=1.5 * CR,
        pat_cr=96.0,
        peer_pe=[28.4, 35.2, 41.0],
        anchor_shares=1.05 * CR,
        objects_cr={
            "Debt repayment": 180.0,
            "Capital expenditure": 120.0,
            "General corporate purposes": 80.0,
            "Issue expenses": 17.6,
        },
        offered={"QIB (ex-anchor)": 0.70 * CR, "NII": 0.525 * CR, "Retail": 1.225 * CR},
        open_date="2026-10-06",
        close_date="2026-10-08",
        allotment_date="2026-10-09",
        listing_date="2026-10-13",
        pre_ipo_shares=1.6 * CR,
        rhp_sample="Example-Ltd_RHP",
    )


def example_sme() -> Issue:
    """Example SME Ltd (fictional), an NSE Emerge issue for the SME checker."""
    return Issue(
        name="Example SME Ltd",
        board="SME",
        platform="NSE Emerge",
        price_low=90,
        price_high=90,
        lot=1200,
        fresh_shares=20 * LAKH,
        ofs_shares=4.4 * LAKH,
        pre_issue_shares=60 * LAKH,
        promoter_pre_shares=48 * LAKH,
        promoter_sell_shares=4.4 * LAKH,
        pat_cr=0.7,
        peer_pe=[18.0, 22.0],
        anchor_shares=0.0,
        objects_cr={
            "Working capital": 12.0,
            "General corporate purposes": 4.0,
            "Issue expenses": 2.0,
        },
        offered={"NII": 10 * LAKH, "Retail": 14.4 * LAKH},
        open_date="2026-10-07",
        close_date="2026-10-09",
        allotment_date="2026-10-12",
        listing_date="2026-10-14",
        rhp_sample="Example-SME-Ltd_RHP",
    )


def ipos_open() -> list[Issue]:
    """The IPOs open list: the fictional samples plus any you added."""
    out = [example(), example_sme()]
    for row in store().all("ipos", tag="issue"):
        fields = {k: row[k] for k in Issue.__dataclass_fields__ if k in row}
        if fields.get("status", "open") == "open" and fields["name"] not in {i.name for i in out}:
            out.append(Issue(**fields))
    return out


def add_ipo(issue: Issue, rhp_link: str = "") -> int:
    """Add IPO: save the record (the RHP link goes to the Document Desk)."""
    return store().add("ipos", {**issue.as_record(), "rhp_link": rhp_link}, tag="issue")


# ---------------------------------------------------------------- RHP digest tiles
def digest_tiles(x: Issue) -> dict[str, str]:
    """Issue size, fresh/OFS split, both P/E figures, peer median, promoters, anchor book.

    Empty until the RHP figures are filled in (a newly added IPO has none).
    """
    if not (x.issue_shares and x.pre_issue_shares and x.pat_cr and x.peer_pe):
        return {}
    size_cr = x.issue_shares * x.price_high / CR
    ofs_pct = x.ofs_shares / x.issue_shares * 100
    eps_pre = x.pat_cr * CR / x.pre_issue_shares
    eps_post = x.pat_cr * CR / x.post_issue_shares
    prom_pre = x.promoter_pre_shares / x.pre_issue_shares * 100
    prom_post = (x.promoter_pre_shares - x.promoter_sell_shares) / x.post_issue_shares * 100
    tiles = {
        "Issue size (upper)": f"₹{size_cr:,.1f} cr",
        "Fresh / OFS": f"{100 - ofs_pct:.0f}% / {ofs_pct:.0f}%",
        "P/E · pre-issue": f"{x.price_high / eps_pre:.1f}×",
        "P/E · post-issue": (
            f"{x.price_high / eps_post:.1f}× ({x.price_low / eps_post:.1f}× at lower band)"
        ),
        "Peer median P/E": f"{statistics.median(x.peer_pe):.1f}×",
        "Promoters": f"{prom_pre:.1f}% → {prom_post:.1f}%",
    }
    if x.anchor_shares:
        tiles["Anchor book"] = f"₹{x.anchor_shares * x.price_high / CR:,.1f} cr"
    gcp = x.objects_cr.get("General corporate purposes")
    if gcp is not None:
        tiles["General corporate purposes"] = (
            f"{gcp / (x.fresh_shares * x.price_high / CR) * 100:.1f}% of fresh issue"
        )
    return tiles


TILE_FIELD = {
    "Issue size (upper)": "Fresh issue and offer for sale",
    "Fresh / OFS": "Fresh issue and offer for sale",
    "P/E · pre-issue": "Financials (revenue, EBITDA, PAT, debt, CFO)",
    "P/E · post-issue": "Share count and promoter holding",
    "Peer median P/E": "Peers and P/E",
    "Promoters": "Share count and promoter holding",
    "Anchor book": "Lock-in periods",
    "General corporate purposes": "Objects of the issue",
}


@dataclass
class RHPDigest:
    """Tiles plus the quoted extraction behind them."""

    issue: Issue
    tiles: dict[str, str]
    rows: list[Any]

    def quote_for(self, tile: str) -> str:
        want = TILE_FIELD.get(tile, "")
        row = next((r for r in self.rows if r.field == want), None)
        return f"“{row.quote}” {row.cite}" if row and row.quote else "not found in source"

    def facts(self) -> list[str]:
        out = [
            f"{self.issue.name} ({self.issue.board}), price band ₹{self.issue.price_low:g}–"
            f"₹{self.issue.price_high:g}"
        ]
        out += [f"{k}: {v}" for k, v in self.tiles.items()]
        out += [
            f"{r.field}: “{r.quote}” {r.cite}" if r.quote else f"{r.field}: not found in source"
            for r in self.rows
        ]
        return out


def rhp_digest(x: Issue, doc: Document | None = None) -> RHPDigest:
    """Extract to table with the RHP digest template, then compute the tiles."""
    doc = doc or (sample(x.rhp_sample) if x.rhp_sample else None)
    rows = extract(doc, "RHP digest").rows if doc else []
    return RHPDigest(x, digest_tiles(x), rows)


# ---------------------------------------------------------------- subscription
def subscription(x: Issue, bids: dict[str, float]) -> list[dict[str, Any]]:
    """Category multiples (bids ÷ shares offered), anchors excluded, plus Overall."""
    rows = [
        {
            "Category": c,
            "Shares offered": int(x.offered[c]),
            "Shares bid": int(bids.get(c, 0)),
            "Times": round(bids.get(c, 0) / x.offered[c], 2),
        }
        for c in x.offered
    ]
    tot_o, tot_b = sum(x.offered.values()), sum(bids.get(c, 0) for c in x.offered)
    rows.append(
        {
            "Category": "Overall (excl. anchors)",
            "Shares offered": int(tot_o),
            "Shares bid": int(tot_b),
            "Times": round(tot_b / tot_o, 2),
        }
    )
    if x.anchor_shares:
        rows.append(
            {
                "Category": "Anchors (shown separately)",
                "Shares offered": int(x.anchor_shares),
                "Shares bid": int(x.anchor_shares),
                "Times": None,
            }
        )
    return rows


def sample_bids(x: Issue, day: int = 3) -> dict[str, float]:
    """Fictional day-by-day bids for the Example Ltd chart (day 1–3)."""
    times = {1: (0.9, 2.1, 1.6), 2: (3.4, 11.7, 4.9), 3: (142.6, 58.3, 11.8)}[day]
    cats = list(x.offered)
    if len(cats) == 2:  # SME: NII, Retail
        times = times[1:]
    return {c: t * x.offered[c] for c, t in zip(cats, times)}


@dataclass
class Odds:
    """Allotment odds for one category (lottery of one minimum lot each)."""

    lots_available: float
    applications: float
    applications_is_estimate: bool
    applicants: int
    min_application_value: float

    @property
    def p(self) -> float:
        return min(1.0, self.lots_available / self.applications) if self.applications else 0.0

    @property
    def at_least_one(self) -> float:
        return 1 - (1 - self.p) ** self.applicants

    @property
    def money_blocked(self) -> float:
        return self.applicants * self.min_application_value

    def facts(self) -> list[str]:
        est = " (estimate)" if self.applications_is_estimate else ""
        return [
            f"Lots available: {self.lots_available:,.0f}",
            f"Valid applications{est}: {self.applications:,.0f}",
            f"Chance of one lot per application: {self.p * 100:.2f}%",
            f"Applicants: {self.applicants}; chance at least one is allotted: "
            f"{self.at_least_one * 100:.2f}% (1 − (1 − p)^n, draws treated as independent)",
            f"Money blocked in total: ₹{self.money_blocked:,.0f}",
            "Applying for more lots does not change the chance of a lot.",
        ]


def allotment_odds(
    x: Issue,
    applications: float | None = None,
    applicants: int = 1,
    category: str = "Retail",
    bid_lots: float | None = None,
    lots_per_application: float = 1.18,
    min_lots: int = 1,
) -> Odds:
    """Odds from lots available and valid applications (or the lab's labelled estimate)."""
    lots = x.offered[category] / x.lot
    est = applications is None
    if est:
        bid_lots = bid_lots if bid_lots is not None else sample_bids(x)[category] / x.lot
        applications = bid_lots / lots_per_application
    return Odds(
        lots, float(applications), est, max(1, int(applicants)), min_lots * x.lot * x.price_high
    )


# ---------------------------------------------------------------- GMP · unofficial
def gmp_panel(figures: dict[str, float]) -> dict[str, Any]:
    """Every source's figure side by side and the spread. Excluded from every calculation."""
    vals = list(figures.values())
    return {
        "banner": GMP_BANNER,
        "rows": [{"Source": k, "GMP (₹)": v} for k, v in figures.items()],
        "spread": (max(vals) - min(vals)) if vals else None,
        "note": "Claims about unverifiable trades. Not used in any tile, plan or odds.",
    }


# ---------------------------------------------------------------- SME checker
@dataclass
class Check:
    rule: str
    quote: str
    cite: str
    status: str  # meets | does not meet | not found
    searched: list[str] = field(default_factory=list)


def sme_checks(doc: Document) -> list[Check]:
    """Each dated SME rule → the quoted RHP figure, its page and a status."""
    out = []
    for r in rules()["sme"]["rules"]:
        kw = {
            "ebitda": ("ebitda", "operating profit"),
            "ofs_cap": ("offer for sale",),
            "seller_cap": ("selling shareholders", "their holding"),
            "min_lots": ("minimum application",),
        }[r["id"]]
        row = find(doc, Field(r["id"], kw))
        if row.status != "found":
            out.append(Check(r["text"], "", "", "not found", row.searched))
            continue
        low = row.quote.lower()
        ok: bool | None = None
        if r["id"] == "ebitda":
            crs = [float(v) for v in re.findall(r"₹\s?(\d+(?:\.\d+)?)\s*crore", row.quote)]
            ok = (
                sum(v >= r["min_cr"] for v in crs[:3]) >= r["years_needed"]
                if len(crs) >= 3
                else None
            )
        elif r["id"] == "ofs_cap":
            pct = re.search(r"(\d+(?:\.\d+)?)%\s+of the issue", low)
            ok = float(pct.group(1)) <= r["max_pct"] if pct else None
        elif r["id"] == "seller_cap":
            pct = re.search(r"(\d+(?:\.\d+)?)%\s+of\s+their holding", low)
            ok = float(pct.group(1)) <= r["max_pct"] if pct else None
        elif r["id"] == "min_lots":
            words = {"one": 1, "two": 2, "three": 3, "four": 4}
            m = re.search(r"\b(one|two|three|four|\d+)\s+lots?", low)
            n = (words.get(m.group(1)) or int(m.group(1))) if m else None
            ok = n >= r["min_lots"] if n else None
        status = "not found" if ok is None else ("meets" if ok else "does not meet")
        out.append(
            Check(r["text"], row.quote, row.cite, status, row.searched if ok is None else [])
        )
    return out


def liquidity(x: Issue, doc: Document) -> dict[str, str]:
    """SME Liquidity panel: minimum application in rupees, the market maker, a note."""
    mm = find(doc, Field("Market maker", ("market maker",)))
    mins = find(doc, Field("Minimum application", ("minimum application",)))
    return {
        "Minimum application": (
            f"₹{2 * x.lot * x.price_high:,.0f} (2 lots × {x.lot} × ₹{x.price_high:g})"
            if x.board == "SME"
            else f"₹{x.lot * x.price_high:,.0f}"
        ),
        "Quoted": f"“{mins.quote}” {mins.cite}" if mins.quote else "not found",
        "Market maker": f"“{mm.quote}” {mm.cite}" if mm.quote else "not found",
        "Post-listing volumes": "shown only after listing",
    }


# ---------------------------------------------------------------- listing-day plan
DEFAULT_SCENARIOS = (25.0, 10.0, 0.0, -10.0)


def listing_plan(
    x: Issue,
    shares: int,
    scenarios: tuple[float, ...] = DEFAULT_SCENARIOS,
    actions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Price, value and change for each opening scenario (before charges and tax)."""
    actions = actions or [""] * len(scenarios)
    out = []
    for pct, act in zip(scenarios, actions):
        px = x.price_high * (1 + pct / 100)
        out.append(
            {
                "Opening vs issue price": f"{pct:+g}%" if pct else "Flat",
                "Price": round(px, 2),
                "Value": round(px * shares, 2),
                "Change": round((px - x.price_high) * shares, 2),
                "Your action": act,
            }
        )
    return out


def critique(plan: list[dict[str, Any]], rule_card: str = "", section: str = "Research") -> str:
    """The AI sceptic reads the plan against your Rule Card; checks in code come first."""
    checks = []
    if any(not str(r.get("Your action", "")).strip() for r in plan):
        checks.append("Every scenario row needs a written action.")
    losing = [r for r in plan if r["Change"] < 0]
    if losing and not any(
        re.search(r"no averag", str(r.get("Your action", "")), re.IGNORECASE) for r in losing
    ):
        checks.append("A falling row has no 'no averaging down' line.")
    if not any(
        re.search(r"day \d+|review", str(r.get("Your action", "")), re.IGNORECASE) for r in plan
    ):
        checks.append("No review date in the plan (the first anchor unlock is day 30).")
    prompt = (
        "Critique this listing-day plan against the trader's Rule Card. Point out vague "
        "actions, missing exits and rule conflicts. Do not recommend buying or selling.\n"
        f"RULE CARD:\n{rule_card or '(none saved)'}\nPLAN:\n" + "\n".join(str(r) for r in plan)
    )
    out = ai.complete(prompt, section=section)
    head = "Checks in code: " + (
        "; ".join(checks) if checks else "all rows have actions, exits and a review date."
    )
    return head + (
        "\n\n" + out.text if out.text else "\n\nNo model connected; only the code checks ran."
    )


def lock_in_calendar(x: Issue) -> list[dict[str, Any]]:
    """Unlock dates from the allotment date, with shares and % of post-issue capital."""
    start = date.fromisoformat(x.allotment_date) if x.allotment_date else date.today()
    total = x.post_issue_shares or 1.0
    promoter_post = x.promoter_pre_shares - x.promoter_sell_shares
    pools = {
        "anchor": x.anchor_shares,
        "pre_ipo": x.pre_ipo_shares,
        "promoter_min": 0.20 * total,
        "promoter_excess": max(promoter_post - 0.20 * total, 0.0),
    }
    rows = []
    for r in rules()["lock_in"]["mainboard"]:
        shares = pools[r["of"]] * r.get("share", 1.0)
        if not shares:
            continue
        rows.append(
            {
                "Holder": r["holder"],
                "Unlocks": (start + timedelta(days=r["days"])).isoformat(),
                "Day": r["days"],
                "Shares": int(shares),
                "% of all shares": round(shares / total * 100, 1),
            }
        )
    return rows


def add_lock_ins_to_alerts(x: Issue) -> list[int]:
    """Lock-in dates as SIMULATED alerts (pending until you Accept them in Alerts)."""
    return [
        alerts.save(
            alerts.Alert(
                name=f"{x.name}: {r['Holder']} lock-in ends {r['Unlocks']}",
                symbol=x.name,
                kind="event",
                condition="new item",
                bar_size="daily close",
                expires=r["Unlocks"],
                plan_name="IPO Dashboard",
            )
        ).id
        for r in lock_in_calendar(x)
    ]


def save_plan_to_journal(x: Issue, shares: int, plan: list[dict[str, Any]]) -> int:
    """Save to journal and set the Post-listing review reminder for day 30."""
    listing = date.fromisoformat(x.listing_date) if x.listing_date else date.today()
    review = listing + timedelta(days=int(rules().get("post_listing_review_days", 30)))
    jid = store().add(
        "notes",
        {
            "screen": "IPO Dashboard",
            "kind": "ipo_plan",
            "ipo": x.name,
            "shares": shares,
            "issue_price": x.price_high,
            "listing_date": listing.isoformat(),
            "plan": plan,
            "post_listing_review": review.isoformat(),
            "text": f"Listing-day plan for {x.name}: {shares} shares at "
            f"₹{x.price_high:g}; post-listing review {review}",
        },
        tag="journal",
    )
    alerts.save(
        alerts.Alert(
            name=f"Post-listing review: {x.name} on {review}",
            symbol=x.name,
            kind="event",
            condition="new item",
            bar_size="daily close",
            expires=review.isoformat(),
            plan_name="IPO Dashboard",
        )
    )
    return jid


def save_record(x: Issue, kind: str, payload: dict[str, Any]) -> int:
    """Accept: attach a digest or check to the IPO's record."""
    return store().add("ipos", {"name": x.name, "kind": kind, **payload}, tag=kind)
