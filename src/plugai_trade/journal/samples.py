"""Synthetic journals for the lessons. Seeded, offline, and clearly labelled synthetic.

``sample("kavita")`` — India, NIFTY futures, one lot, 17 Aug – 11 Sep 2026 (Chapter 14)
``sample("marcus")`` — US, SPY and QQQ, same dates, ≈ $400 risk per trade (Chapter 14)
``sample("meera")``  — India, the ten F&O round trips of Chapter 32's turnover example
``sample("dan")``    — US, the XYZ wash sale of Chapter 32 plus SPX and SPY options
``sample("farhan")`` — India, the three VDA trades of Chapter 25's ledger

The Chapter 14 journals are regenerated from a fixed seed with the same design as the
book's (rule breaks, quick re-entries, long-held losers); exact totals differ from
the printed ones, which came from the author's own run.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from .. import reference
from .pairing import price_charges
from .plans import with_r
from .schema import conform_trades

SAMPLES = ("kavita", "marcus", "meera", "dan", "farhan")
START, END = date(2026, 8, 17), date(2026, 9, 11)
SETUPS = ("Opening range", "Pullback", "VWAP reclaim", "Breakout")


def _days() -> list[date]:
    d, out = START, []
    while d <= END:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _counts(rng: np.random.Generator, total: int, n_days: int) -> list[int]:
    counts = list(rng.choice([1, 2, 3, 4, 5], size=n_days, p=[0.12, 0.3, 0.3, 0.2, 0.08]))
    while sum(counts) != total:
        i = int(rng.integers(0, n_days))
        if sum(counts) < total and counts[i] < 5:
            counts[i] += 1
        elif sum(counts) > total and counts[i] > 1:
            counts[i] -= 1
    return counts


def _outcome(rng: np.random.Generator, risky: bool, loser_hold: float,
             win_p: float) -> tuple[float, float]:
    """(R, minutes held). Risky trades (rule breaks, tilt) win less often."""
    u = rng.random()
    if u < (0.28 if risky else win_p):
        return round(float(rng.uniform(0.5, 3.4)), 2), float(np.clip(rng.normal(30, 12), 4, 95))
    if u < win_p + 0.05 if not risky else u < 0.33:
        return round(float(rng.uniform(-0.3, 0.3)), 2), float(rng.uniform(5, 30))
    if rng.random() < (0.22 if risky else 0.05):  # stop moved away: a long, hopeful hold
        return round(float(rng.uniform(-2.0, -1.3)), 2), float(rng.uniform(61, 127))
    return round(float(rng.uniform(-1.08, -0.95)), 2), float(np.clip(rng.normal(loser_hold, 15),
                                                                     5, 110))


def _intraday(name: str, seed: int, total: int, market: str) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    days = _days()
    counts = _counts(rng, total, len(days))
    open_h, open_m = map(int, (reference.lookup(
        f"{'india' if market == 'IN' else 'us'}.sessions.cash.open") or "09:15").split(":"))
    lot = reference.lot_size("NIFTY") or 1
    levels = {"NIFTY": 24800.0, "SPY": 560.0, "QQQ": 480.0}
    rows = []
    for day, n in zip(days, counts):
        t = datetime(day.year, day.month, day.day, open_h, open_m)
        t += timedelta(minutes=int(rng.integers(1, 14)) if rng.random() < 0.11
                       else int(rng.integers(20, 110)))
        day_r, quick = 0.0, False
        close_at = t.replace(hour=15, minute=20)
        for k in range(n):
            sym = "NIFTY" if market == "IN" else ("SPY" if rng.random() < 0.55 else "QQQ")
            levels[sym] *= float(1 + rng.normal(0, 0.003))
            first15 = (t - t.replace(hour=open_h, minute=open_m)).seconds < 15 * 60
            risky = first15 or k >= 3 or day_r <= -2 or quick
            r, hold = _outcome(rng, risky, 37 if market == "IN" else 50,
                               0.52 if market == "IN" else 0.54)
            hold = max(3.0, min(hold, (close_at - t).total_seconds() / 60 - (n - k) * 4))
            if market == "IN":
                stop, qty = float(rng.integers(20, 41) * 5), float(lot)
            else:
                stop = round(float(rng.uniform(1.0, 4.0)) * 20) / 20
                qty = float(int(400 // stop))
            side = 1 if rng.random() < 0.55 else -1
            entry = round(levels[sym] * 20) / 20
            exit_ = round((entry + side * r * stop) * 20) / 20
            exit_t = t + timedelta(minutes=round(hold))
            rows.append({"entry_time": t, "exit_time": exit_t, "underlying": sym,
                         "symbol": (f"NIFTY26{'AUG' if day <= date(2026, 8, 25) else 'SEP'}FUT"
                                    if market == "IN" else sym),
                         "instrument": "FUT" if market == "IN" else "EQ",
                         "side": "LONG" if side == 1 else "SHORT", "qty": qty,
                         "entry_price": entry, "exit_price": exit_, "stop_distance": stop,
                         "setup": SETUPS[int(rng.integers(0, len(SETUPS)))]})
            real_r = side * (exit_ - entry) / stop
            day_r += real_r
            loss = real_r < 0
            gap = rng.uniform(2, 22) if loss and rng.random() < 0.6 else rng.uniform(25, 100)
            left = (close_at - exit_t).total_seconds() / 60 - (n - k - 1) * 8
            gap = max(1.0, min(gap, left / max(n - k - 1, 1)))
            quick = loss and gap <= 30
            t = exit_t + timedelta(minutes=round(gap))
    df = pl.DataFrame(rows)
    return _finish(df, market, account=name.title(), source=f"sample:{name}")


def _finish(df: pl.DataFrame, market: str, account: str, source: str,
            price: bool = True) -> pl.DataFrame:
    df = df.sort("entry_time").with_columns(
        trade_id=pl.int_range(1, pl.len() + 1).cast(pl.Int64),
        date=pl.col("entry_time").dt.strftime("%Y-%m-%d"),
        multiplier=pl.lit(1.0) if "multiplier" not in df.columns else pl.col("multiplier"),
        market=pl.lit(market), source=pl.lit(source),
        account=pl.lit(account) if "account" not in df.columns else pl.col("account"),
    )
    sign = pl.when(pl.col("side") == "LONG").then(1.0).otherwise(-1.0)
    df = df.with_columns(gross=((pl.col("exit_price") - pl.col("entry_price")) * sign
                                * pl.col("qty") * pl.col("multiplier")).round(2))
    charges = []
    for r in df.iter_rows(named=True):
        if not price:
            charges.append(0.0)
            continue
        long = r["side"] == "LONG"
        v_in = r["entry_price"] * r["qty"] * r["multiplier"]
        v_out = r["exit_price"] * r["qty"] * r["multiplier"]
        c = price_charges(market, r["instrument"], v_in if long else v_out,
                          v_out if long else v_in,
                          r["entry_time"].date() == r["exit_time"].date(), r["qty"])
        charges.append(c or 0.0)
    df = df.with_columns(charges=pl.Series(charges, dtype=pl.Float64),
                         charges_source=pl.lit("cost table" if price else "none"))
    df = df.with_columns(net=(pl.col("gross") - pl.col("charges")).round(2))
    if "tags" not in df.columns:
        df = df.with_columns(tags=pl.lit([], dtype=pl.List(pl.Utf8)))
    return with_r(conform_trades(df))


def _fo(rows: list[tuple], market: str, account: str, source: str,
        price: bool = False) -> pl.DataFrame:
    recs = []
    for sym, under, inst, side, qty, entry, exit_, t0, t1, *rest in rows:
        mult = rest[0] if rest else 1.0
        recs.append({"symbol": sym, "underlying": under, "instrument": inst, "side": side,
                     "qty": float(qty), "entry_price": float(entry), "exit_price": float(exit_),
                     "entry_time": t0, "exit_time": t1, "multiplier": float(mult),
                     "account": rest[1] if len(rest) > 1 else account})
    return _finish(pl.DataFrame(recs), market, account, source, price=price)


def _meera() -> pl.DataFrame:
    d = lambda day, h=10, m=0: datetime(2026, 2, day, h, m)  # noqa: E731
    rows = [
        ("NIFTY26FEB25000CE", "NIFTY", "CE", "LONG", 65, 89, 121, d(2), d(2, 11)),
        ("NIFTY26FEB24800PE", "NIFTY", "PE", "LONG", 65, 110, 72, d(4), d(4, 13)),
        ("NIFTY26FEBFUT", "NIFTY", "FUT", "LONG", 65, 24850, 24930, d(5), d(5, 14)),
        ("NIFTY26FEB25200CE", "NIFTY", "CE", "SHORT", 130, 64, 31, d(9), d(10, 11)),
        ("NIFTY26FEB24500PE", "NIFTY", "PE", "LONG", 65, 95, 40, d(11), d(11, 12)),
        ("NIFTY26MARFUT", "NIFTY", "FUT", "SHORT", 65, 25010, 25120, d(13), d(13, 15)),
        ("BANKNIFTY26FEB56000CE", "BANKNIFTY", "CE", "LONG", 60, 240, 305, d(16), d(16, 14)),
        ("NIFTY26FEB25100CE", "NIFTY", "CE", "LONG", 65, 70, 0, d(17), d(24, 15, 30)),
        ("NIFTY26FEB24700PE", "NIFTY", "PE", "SHORT", 65, 58, 0, d(18), d(24, 15, 30)),
        ("NIFTY26MARFUT", "NIFTY", "FUT", "LONG", 65, 24920, 24880, d(20), d(20, 13)),
    ]
    return _fo(rows, "IN", "Meera", "sample:meera", price=False)


def _dan() -> pl.DataFrame:
    d = lambda mo, day: datetime(2026, mo, day, 10, 0)  # noqa: E731
    rows = [
        ("XYZ", "XYZ", "EQ", "LONG", 100, 50, 42, d(3, 2), d(3, 20)),
        ("XYZ", "XYZ", "EQ", "LONG", 100, 44, 47, d(4, 8), d(6, 15)),
        ("SPX 260918C05600000", "SPX", "CALL", "LONG", 2, 40, 90, d(9, 1), d(9, 4), 100.0),
        ("SPY 260918C00560000", "SPY", "CALL", "LONG", 20, 4.0, 9.0, d(9, 1), d(9, 4), 100.0),
    ]
    return _fo(rows, "US", "Taxable", "sample:dan", price=False)


def _farhan() -> pl.DataFrame:
    d = lambda mo, day: datetime(2026, mo, day, 21, 0)  # noqa: E731
    rows = [
        ("BTCINR", "BTC", "CRYPTO", "LONG", 1, 150000, 200000, d(5, 4), d(8, 10)),
        ("ETHINR", "ETH", "CRYPTO", "LONG", 1, 80000, 60000, d(5, 20), d(9, 2)),
        ("BTCINR", "BTC", "CRYPTO", "LONG", 1, 100000, 112000, d(9, 5), d(11, 18)),
    ]
    return _fo(rows, "IN", "Farhan", "sample:farhan", price=False)


def sample(name: str) -> pl.DataFrame:
    """A seeded synthetic journal (round trips). See the module docstring for names."""
    key = name.lower()
    if key == "kavita":
        return _intraday("kavita", seed=10, total=54, market="IN")
    if key == "marcus":
        return _intraday("marcus", seed=12, total=61, market="US")
    if key == "meera":
        return _meera()
    if key == "dan":
        return _dan()
    if key == "farhan":
        return _farhan()
    raise ValueError(f"Unknown sample {name!r}. Choose one of: {', '.join(SAMPLES)}")


def to_tradebook(trades: pl.DataFrame, broker: str = "Zerodha") -> str:
    """Write round trips back out as a broker-shaped fills CSV (for lessons and tests)."""
    lines = []
    for r in trades.iter_rows(named=True):
        long = r["side"] == "LONG"
        for when, px, is_buy in ((r["entry_time"], r["entry_price"], long),
                                 (r["exit_time"], r["exit_price"], not long)):
            lines.append((when, r, px, is_buy))
    lines.sort(key=lambda x: x[0])
    if broker == "Zerodha":
        out = ["symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,"
               "price,trade_id,order_id,order_execution_time,expiry_date"]
        for i, (when, r, px, is_buy) in enumerate(lines, 1):
            seg = "FO" if r["instrument"] in ("FUT", "CE", "PE") else "EQ"
            out.append(f"{r['symbol']},,{when:%Y-%m-%d},NSE,{seg},,{'buy' if is_buy else 'sell'},"
                       f"false,{r['qty']:g},{px:.2f},{900000 + i},{800000 + i},"
                       f"{when:%Y-%m-%dT%H:%M:%S},")
        return "\n".join(out) + "\n"
    if broker == "IBKR":
        out = ["ClientAccountID,CurrencyPrimary,AssetClass,Symbol,UnderlyingSymbol,DateTime,"
               "Buy/Sell,Quantity,TradePrice,IBCommission,Multiplier"]
        for when, r, px, is_buy in lines:
            q = r["qty"] if is_buy else -r["qty"]
            fee = round(r["charges"] / 2, 2)
            out.append(f"U0000000,USD,STK,{r['symbol']},{r['underlying']},{when:%Y%m%d;%H%M%S},"
                       f"{'BUY' if is_buy else 'SELL'},{q:g},{px:.2f},{-fee},1")
        return "\n".join(out) + "\n"
    raise ValueError("to_tradebook supports Zerodha and IBKR")


def write_tradebook(trades: pl.DataFrame, path: str | Path, broker: str = "Zerodha") -> Path:
    """Save ``to_tradebook`` output to a file and return its path."""
    p = Path(path)
    p.write_text(to_tradebook(trades, broker))
    return p
