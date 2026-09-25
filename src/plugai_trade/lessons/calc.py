"""The numbers behind each lesson's exercise and checks — all computed in code.

Inputs printed in the book (a premium, a straddle, a funding rate) are passed in
as the book prints them; anything dated (lot sizes, charges) comes from the
reference tables; anything market-shaped comes from the synthetic sample.
Other lab modules are imported lazily so a lesson degrades gracefully.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import polars as pl

from .. import config, costs, privacy, reference
from ..store import default as store
from .model import Exercise


def sym(market: str) -> str:
    return "NIFTY" if market == "IN" else "SPY"


def cur(market: str) -> str:
    return "₹" if market == "IN" else "$"


def bars(market: str, start: date | None = None, end: date | None = None) -> pl.DataFrame:
    """The book's synthetic sample for the market's index (fixed dates)."""
    from .. import data, wizard
    return data.get(sym(market), market=market, start=start or wizard.SAMPLE_START,
                    end=end or wizard.SAMPLE_END, source="synthetic", use_cache=False)


def nifty_lot() -> int:
    lot = reference.lot_size("NIFTY")
    if not lot:
        raise ValueError("NIFTY lot size missing from the reference tables")
    return int(lot)


def pct(a: float, b: float) -> float:
    """(a ÷ b − 1) in percent."""
    return (a / b - 1) * 100


def _table(df: pl.DataFrame, n: int = 6) -> pl.DataFrame:
    return df.select("date", "open", "high", "low", "close", "volume", "source").tail(n)


# ---------------------------------------------------------------- Chapter 1
def last_close(market: str) -> float:
    return round(float(bars(market)["close"][-1]), 2)


def five_day_change(market: str) -> float:
    c = bars(market)["close"]
    return round(pct(float(c[-1]), float(c[-6])), 2)


def ex_close_table(market: str) -> Exercise:
    df = bars(market)
    return Exercise(f"Last six {sym(market)} sample bars (synthetic)",
                    [f"Symbol {sym(market)} ({market}), source {df['source'][-1]}",
                     f"Bars loaded: {df.height}", f"Last date: {df['date'][-1]}"],
                    _table(df))


# ---------------------------------------------------------------- Chapter 4
def spy_bars_2026() -> int:
    from .. import data
    return data.get("SPY", market="US", start="2026-01-01", end="2026-05-29",
                    source="synthetic", use_cache=False).height


# ---------------------------------------------------------------- Chapter 5
def compare_frames(market: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Source A = the sample; source B = a copy with three prices 1% off and one day missing."""
    a = bars(market, date(2026, 5, 1), date(2026, 5, 29))
    b = a.with_row_index("i").with_columns(
        pl.when(pl.col("i").is_in([2, 7, 13])).then(pl.col("close") * 1.01)
        .otherwise(pl.col("close")).alias("close")).filter(pl.col("i") != 17).drop("i")
    return a, b


def compare_counts(market: str) -> dict[str, int]:
    from .. import data
    a, b = compare_frames(market)
    st = data.compare(a, b, tol=0.005)["status"].to_list()
    return {"disagree": st.count("disagree"), "missing": st.count("missing"), "rows": len(st)}


def ex_compare(market: str) -> Exercise:
    from .. import data
    a, b = compare_frames(market)
    cmp = data.compare(a, b, tol=0.005)
    return Exercise(f"Compare sources: {sym(market)}, 1–29 May 2026 (lesson copy as source B)",
                    ["Source A: synthetic sample", "Source B: lesson copy with deliberate errors",
                     "Tolerance: 0.5%", f"Rows compared: {cmp.height}"],
                    cmp.with_columns((pl.col("diff") * 100).round(3).alias("diff %")).drop("diff"))


# ---------------------------------------------------------------- Chapter 6
def mcp_read_tools() -> int:
    from .. import mcp_server
    return sum(1 for t in mcp_server.TOOLS.values() if str(t.get("tag")).upper() == "READ")


# ---------------------------------------------------------------- Chapters 9, 10, 27
def dist_from_high(market: str) -> float:
    df = bars(market)
    return round(pct(float(df["close"][-1]), float(df["high"].tail(252).max())), 2)


def pivot(market: str) -> float:
    r = bars(market).row(-1, named=True)
    return round((r["high"] + r["low"] + r["close"]) / 3, 2)


def gap_pct(market: str) -> float:
    df = bars(market)
    return round(pct(float(df["open"][-1]), float(df["close"][-2])), 2)


def ex_last_bars(market: str) -> Exercise:
    df = bars(market)
    return Exercise(f"{sym(market)} sample, last bars (synthetic)",
                    [f"252-day high: {df['high'].tail(252).max():,.2f}",
                     f"Last close: {df['close'][-1]:,.2f}"], _table(df))


# ---------------------------------------------------------------- Chapters 11–13
def delivery_round_trip() -> float:
    return costs.india_round_trip(100_000, 102_000, "delivery")["total"]


def rule_card_daily_limit(market: str) -> float:
    from .. import rulecard
    return rulecard.RuleCard().money_limits(market)["daily"]


def paper_net(market: str) -> float:
    if market == "IN":
        lot = nifty_lot()
        buy, sell = 24_800 * lot, 24_900 * lot
        return round(sell - buy - costs.india_round_trip(buy, sell, "futures")["total"], 2)
    buy, sell = 560.0 * 100, 565.0 * 100
    return round(sell - buy - costs.us_round_trip(buy, sell)["total"], 2)


def ex_paper(market: str) -> Exercise:
    if market == "IN":
        lot = nifty_lot()
        c = costs.india_round_trip(24_800 * lot, 24_900 * lot, "futures")
        head = [f"NIFTY FUT, 1 lot of {lot} (reference tables as of {reference.as_of()})",
                "Paper buy 24,800 · paper sell 24,900"]
    else:
        c = costs.us_round_trip(56_000, 56_500)
        head = ["SPY, 100 shares", "Paper buy $560.00 · paper sell $565.00"]
    return Exercise("One paper round trip, charges from the dated table",
                    head + [f"{k}: {v:,.2f}" for k, v in c.items()])


# ---------------------------------------------------------------- Chapter 14
def journal_sample(market: str) -> pl.DataFrame:
    from .. import journal
    return journal.sample("kavita" if market == "IN" else "marcus")


def journal_count(market: str) -> int:
    return journal_sample(market).height


def journal_net(market: str) -> float:
    return round(float(journal_sample(market)["net"].sum()), 2)


def ex_journal(market: str) -> Exercise:
    t = journal_sample(market)
    who = "Kavita (NIFTY futures)" if market == "IN" else "Marcus (SPY and QQQ)"
    return Exercise(f"Lesson 14 synthetic journal: {who}",
                    [f"Round trips: {t.height}", "Charges from the dated cost table" if market ==
                     "IN" else "Fees from the export"],
                    t.select("trade_id", "date", "symbol", "side", "qty", "gross", "charges", "net",
                             "r_multiple").head(12))


# ---------------------------------------------------------------- Chapter 15
def sip_value(monthly: float = 15_000, years: int = 15, annual: float = 0.08) -> float:
    """Future value, contributions at each month end, monthly compounding (illustrative)."""
    r, n = annual / 12, years * 12
    return round(monthly * ((1 + r) ** n - 1) / r, 0)


# ---------------------------------------------------------------- Chapter 17
def swing_size() -> int:
    return min(math.floor(300 / 1.17), math.floor(6_000 / 41.15))


# ---------------------------------------------------------------- Chapter 18
SLEEVE = {"IN": 800_000.0, "US": 60_000.0}


def daily_move(market: str) -> float:
    r = bars(market)["close"].pct_change().tail(20)
    return float(r.std())


def vol_units(market: str) -> int:
    price = float(bars(market)["close"][-1])
    return math.floor(SLEEVE[market] * 0.12 / 16 / daily_move(market) / price)


def ex_vol(market: str) -> Exercise:
    price = float(bars(market)["close"][-1])
    return Exercise("Volatility sizing inputs (computed in code)",
                    [f"Sleeve: {cur(market)}{SLEEVE[market]:,.0f}", "Target: 12% a year",
                     f"Daily move (std of last 20 daily returns): {daily_move(market):.6f}",
                     f"Price: {price:,.2f}",
                     "Units = sleeve × target ÷ 16 ÷ daily move ÷ price, rounded down"])


# ---------------------------------------------------------------- Chapter 26
def half_life() -> float:
    from .. import pairs
    return round(pairs.fit_symbols("SYN-A", "SYN-B").half_life, 1)


# ---------------------------------------------------------------- Chapter 29
def majority_share(market: str, horizon: int = 10) -> float:
    c = bars(market)["close"]
    up = (c.shift(-horizon) / c - 1 > 0).drop_nulls()
    share = float(up.mean())
    return round(max(share, 1 - share) * 100, 1)


# ---------------------------------------------------------------- Chapter 31
def _fit():
    from .. import wizard
    return wizard.fit_check(wizard.MODELS[1], 8192, ram=16.0, used=4.0)


def fit_total() -> float:
    return _fit().total_gb


def ex_fit(market: str) -> Exercise:
    return Exercise("Fit check (an estimate): 9B model, 8k context, 16 GB RAM", _fit().facts())


# ---------------------------------------------------------------- Chapter 32
TURNOVER_ROWS = (2_080, 2_470, 5_200, 4_290, 3_575, 7_150, 3_900, 4_550, 3_770, 2_600)


# ---------------------------------------------------------------- state checks
def use_for_local(*sections: str) -> tuple[bool, str]:
    uf = config.get("ai.use_for", {}) or {}
    forced = set(privacy.local_only_sections())
    bad = [s for s in sections if s not in forced and uf.get(s, "Local only") != "Local only"]
    return not bad, ("Local only: " + ", ".join(sections)) if not bad else (
        "still Cloud allowed: " + ", ".join(bad))


def budget_set() -> tuple[bool, str]:
    b = float(config.get("ai.monthly_budget", 0) or 0)
    return b > 0, f"monthly budget {b:g}" if b > 0 else "no monthly budget set"


def ask_before_cloud() -> tuple[bool, str]:
    on = privacy.settings().ask_before_cloud
    return on, "Ask before sending to cloud is on" if on else "switch it on in Settings › Privacy"


def privacy_defaults() -> tuple[bool, str]:
    ok = privacy.defaults_on() and privacy.education_lag() == 90
    return ok, (f"defaults on; Education lag {privacy.education_lag()} days" if ok else
                f"toggles changed or lag {privacy.education_lag()} days (book assumes 90)")


def self_test_passed() -> tuple[bool, str]:
    st = config.get("wizard.self_test") or {}
    if not st:
        return False, "run the self-test on Home (Run self-test)"
    return bool(st.get("passed")), "all six checks passed" if st.get("passed") else (
        "failed: " + ", ".join(st.get("failed", [])))


def both_markets_loaded() -> tuple[bool, str]:
    done = set(config.get("wizard.sample_loaded", []) or [])
    ok = {"IN", "US"} <= done
    return ok, "sample data loaded for IN and US" if ok else (
        f"loaded so far: {', '.join(sorted(done)) or 'none'} — load both")


def trials_recorded() -> tuple[bool, str]:
    n = store().count("trials")
    return n > 0, f"Trials counter: {n}" if n else "run one backtest so the counter records it"


def plugin_created() -> tuple[bool, str]:
    from .. import plugin
    names = plugin.installed()
    return bool(names), f"plugins: {', '.join(names)}" if names else "create gap_report first"


def proposal_decided() -> tuple[bool, str]:
    rows = store().all("proposals")
    done = [r for r in rows if r.get("status") in ("accepted", "rejected", "sent")]
    return bool(done), f"{len(done)} proposal(s) accepted, rejected or sent" if done else (
        "run a team and Accept, Reject or Send its proposal")


def audit_exported_this_month() -> tuple[bool, str]:
    ym = date.today().strftime("%Y-%m")
    rows = [r for r in store().all("audit_log", tag="audit_export") if r["created"].startswith(ym)]
    return bool(rows), "exported this month" if rows else "click Export log in Settings › Security"


def strip_on() -> tuple[bool, str]:
    on = privacy.settings().strip_identifiers
    return on, "account numbers and PAN/SSN are stripped" if on else "switch it on in Privacy"


def workspace_applied() -> tuple[bool, str]:
    t = config.get("workspace.template", "")
    return bool(t), f"template: {t}" if t else "apply a template in Settings › Workspace"


def tables_fresh(days: int = 31) -> tuple[bool, str]:
    try:
        as_of = datetime.fromisoformat(reference.as_of()).date()
    except ValueError:
        return False, "reference tables carry no date"
    ok = date.today() - as_of <= timedelta(days=days)
    return ok, f"reference tables as of {as_of:%d %b %Y}" + ("" if ok else
                                                             " — run plugai-trade update")


def keys_masked() -> tuple[bool, str]:
    from .. import keys
    text = config.path("settings.json").read_text() if config.path("settings.json").exists() else ""
    leaked = [n for n in keys.listed() if (v := keys.get_key(n)) and len(v) > 6 and v in text]
    return not leaked, "keys only in the keychain" if not leaked else "a key is in settings.json"
