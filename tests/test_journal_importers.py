"""Importers: every broker fixture → fills → round trips, with charges priced when missing."""

from pathlib import Path

import polars as pl
import pytest

from plugai_trade import costs, journal
from plugai_trade.journal import importers

FIX = Path(__file__).parent / "fixtures" / "journal"

CASES = [  # file, broker, fills, round trips, unpaired, market
    ("zerodha_tradebook.csv", "Zerodha", 6, 3, 1, "IN"),
    ("upstox_tradebook.csv", "Upstox", 4, 2, 0, "IN"),
    ("groww_orders.csv", "Groww", 4, 2, 0, "IN"),
    ("dhan_tradebook.csv", "Dhan", 2, 1, 0, "IN"),
    ("angel_tradebook.csv", "Angel One", 2, 1, 0, "IN"),
    ("ibkr_flex.csv", "IBKR", 4, 2, 0, "US"),
    ("schwab_history.csv", "Schwab", 2, 1, 0, "US"),
    ("robinhood_activity.csv", "Robinhood", 2, 1, 0, "US"),
    ("webull_orders.csv", "Webull", 2, 1, 0, "US"),
]


@pytest.mark.parametrize("name,broker,fills,trips,unpaired,market", CASES)
def test_each_broker_detected_and_paired(name, broker, fills, trips, unpaired, market):
    res = journal.import_tradebook(FIX / name)
    assert res.broker == broker
    assert res.fills == fills
    assert res.trades.height == trips
    assert res.unpaired.height == unpaired
    assert set(res.trades["market"].to_list()) == {market}
    assert res.trades["trade_id"].to_list() == list(range(1, trips + 1))


def test_zerodha_charges_priced_from_cost_table_match_book():
    t = journal.load(FIX / "zerodha_tradebook.csv")
    fut = t.row(0, named=True)
    assert fut["instrument"] == "FUT" and fut["gross"] == 9750.0
    assert fut["charges_source"] == "cost table"
    assert fut["charges"] == costs.india_round_trip(24800 * 65, 24950 * 65, "futures")["total"]
    assert fut["charges"] == 960.14                                   # Chapter 14 box


def test_partial_exit_splits_one_entry_fifo_without_double_brokerage():
    t = journal.load(FIX / "zerodha_tradebook.csv").filter(pl.col("instrument") == "CE")
    assert t["qty"].to_list() == [30.0, 35.0]
    assert t["gross"].to_list() == [330.0, 280.0]
    brokerage = costs.india_round_trip(1.0, 1.0, "options")["brokerage"]
    both = costs.india_round_trip(120 * 65, 131 * 30 + 128 * 35, "options", orders=3)
    assert round(float(t["charges"].sum()), 0) == round(both["total"], 0)
    assert brokerage == 40.0


def test_identifiers_never_copied():
    fills = importers.parse_fills(FIX / "zerodha_tradebook.csv")
    assert "trade_id" not in fills.columns and "order_id" not in fills.columns


def test_us_fees_from_file_and_option_multiplier():
    t = journal.load(FIX / "ibkr_flex.csv")
    opt = t.filter(pl.col("instrument") == "CALL").row(0, named=True)
    assert opt["multiplier"] == 100 and opt["gross"] == 100.0
    assert opt["charges_source"] == "tradebook" and opt["charges"] == 2.61


def test_non_trade_rows_skipped():
    assert journal.import_tradebook(FIX / "schwab_history.csv").fills == 2      # dividend
    assert journal.import_tradebook(FIX / "robinhood_activity.csv").fills == 2  # CDIV
    assert journal.import_tradebook(FIX / "webull_orders.csv").fills == 2       # cancelled


def test_options_and_shares_do_not_pair_together():
    t = journal.load(FIX / "robinhood_activity.csv")
    assert t["symbol"][0] == "SPY 2026-09-18 560CALL"
    assert t["gross"][0] == -80.0


def test_short_intraday_equity_round_trip():
    r = journal.load(FIX / "angel_tradebook.csv").row(0, named=True)
    assert r["side"] == "SHORT" and r["gross"] == 125.0 and r["underlying"] == "SBIN"


def test_generic_csv_with_column_mapper_and_reversal():
    mapping = {"time": "When", "symbol": "Ticker", "side": "Direction", "qty": "Units",
               "price": "Fill", "fees": "Commission", "market": "Mkt"}
    res = journal.import_tradebook(FIX / "generic_custom.csv", "Generic CSV", mapping=mapping)
    assert res.trades["qty"].to_list() == [4.0, 6.0]
    assert res.unpaired.height == 1 and res.unpaired["side"][0] == "SELL"  # reversed to short


def test_generic_mapper_reports_missing_columns():
    with pytest.raises(importers.ImportError_, match="Map these columns"):
        journal.import_tradebook(FIX / "generic_custom.csv", "Generic CSV", mapping={})


def test_sample_round_trips_through_zerodha_and_ibkr_exports():
    k = journal.sample("kavita")
    back = journal.load(journal.to_tradebook(k, "Zerodha").encode())
    assert back.height == k.height
    assert back["gross"].sum() == pytest.approx(k["gross"].sum())
    m = journal.sample("marcus")
    back = journal.load(journal.to_tradebook(m, "IBKR").encode())
    assert back.height == m.height


def test_india_symbol_parser():
    p = importers.parse_india_symbol("NIFTY26SEP25000CE")
    assert (p.underlying, p.instrument, p.strike) == ("NIFTY", "CE", 25000.0)
    assert importers.parse_india_symbol("BANKNIFTY26SEPFUT").instrument == "FUT"
    assert importers.parse_india_symbol("BTCINR").instrument == "CRYPTO"
    assert importers.parse_india_symbol("INFY").instrument == "EQ"


def test_accept_saves_locked_rows_once_and_tags_edit(lab_home):
    res = journal.import_tradebook(FIX / "zerodha_tradebook.csv", tags=["PILOT"])
    assert journal.save(res.trades) == 3
    assert journal.save(res.trades) == 0                     # already there
    saved = journal.trades()
    assert saved.height == 3 and saved["tags"][0].to_list() == ["PILOT"]
    rid = int(saved["trade_id"][0])
    journal.set_tags(rid, ["PAPER", "late entry"], setup="ORB", stop_distance=150)
    row = journal.trades().filter(pl.col("trade_id") == rid).row(0, named=True)
    assert "PAPER" in row["tags"] and row["setup"] == "ORB"
    assert row["r_multiple"] == 1.0                          # 150 points on a 150-point stop
    assert journal.trades(include_simulated=False).height == 2


def test_match_plans_links_the_plan_saved_before_entry():
    t = journal.load(FIX / "zerodha_tradebook.csv")
    plans = [{"id": 7, "symbol": "NIFTY", "entry": 24800, "stop": 24650, "setup": "ORB",
              "created": "2026-09-08T09:30:00"},
             {"id": 8, "symbol": "NIFTY", "entry": 24800, "stop": 24700,
              "created": "2026-09-08T12:00:00"}]                         # after: not used
    out, unmatched = journal.match_plans(t, plans)
    first = out.row(0, named=True)
    assert first["plan_id"] == 7 and first["stop_distance"] == 150.0
    assert first["risk"] == 150.0 * 65 and first["r_multiple"] == 1.0
    assert len(unmatched) == 2
