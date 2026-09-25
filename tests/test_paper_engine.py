"""Paper engine fill model: next-bar fills, trade-through limits, gaps at the open, volume cap."""

from datetime import date

import polars as pl
import pytest

from plugai_trade import paper
from plugai_trade.store import default as store


def bar(t, o, h, lo, c, v=100_000, day="2026-05-26"):
    return {"date": day, "time": f"{day}T{t}", "open": o, "high": h, "low": lo, "close": c, "volume": v}


def desk(**kw):
    return paper.PaperDesk("IN", 1_500_000, mode=kw.pop("mode", "REPLAY"), **kw)


def test_market_order_fills_at_next_bar_open_never_current_bar():
    d = desk()
    d.on_bar("NIFTY FUT", bar("09:15", 24800, 24840, 24790, 24830))
    o = d.place_paper_order("NIFTY FUT", "buy", 65)
    assert o.status == "WORKING" and not d.positions      # nothing fills on the bar already seen
    d.on_bar("NIFTY FUT", bar("09:20", 24835, 24900, 24820, 24890))
    assert o.status == "FILLED"
    assert o.avg_fill == 24835 + 2                         # next open + half spread + slippage
    assert o.fills[0]["at"] == "2026-05-26T09:20"


def test_fill_does_not_depend_on_later_bars():
    bars = [bar("09:15", 100, 101, 99, 100), bar("09:20", 100.5, 102, 100, 101)]
    fills = []
    for future_close in (50.0, 500.0):   # wildly different "future" bars
        d = paper.PaperDesk("US", 40_000, write_journal=False)
        feed = bars + [bar("09:25", future_close, future_close, future_close, future_close)]
        d.on_bar("SPY", feed[0])
        o = d.place_paper_order("SPY", "buy", 10)
        d.on_bar("SPY", feed[1])
        fills.append(o.avg_fill)
    assert fills[0] == fills[1] == pytest.approx(100.52)


def test_replay_never_shows_future_bars():
    bars = pl.DataFrame([bar(f"09:{15 + i:02d}", 100 + i, 101 + i, 99 + i, 100 + i) for i in range(10)])
    rp = paper.Replay("SPY", bars, speed=5)
    d = paper.PaperDesk("US", 40_000, write_journal=False)
    assert rp.visible().height == 0
    rp.step(d)
    assert rp.visible().height == 5 and d.now == "2026-05-26T09:19"
    rp.step(d, 100)
    assert rp.done and rp.visible().height == 10


def test_limit_needs_trade_through_touch_is_not_a_fill():
    d = desk(write_journal=False)
    d.on_bar("NIFTY FUT", bar("09:15", 24850, 24860, 24820, 24840))
    o = d.place_paper_order("NIFTY FUT", "buy", 65, kind="limit", price=24800)
    d.on_bar("NIFTY FUT", bar("09:20", 24830, 24840, 24800, 24810))   # low == limit: touch only
    assert o.status == "WORKING"
    d.on_bar("NIFTY FUT", bar("09:25", 24810, 24815, 24790, 24800))   # trades through
    assert o.status == "FILLED" and o.avg_fill == 24800


def test_limit_gap_through_fills_at_open():
    d = desk(write_journal=False)
    d.on_bar("NIFTY FUT", bar("09:15", 24850, 24860, 24820, 24840))
    o = d.place_paper_order("NIFTY FUT", "buy", 65, kind="limit", price=24800)
    d.on_bar("NIFTY FUT", bar("09:20", 24750, 24780, 24700, 24760))
    assert o.avg_fill == 24750


def test_stop_entry_and_gap_fill_at_open():
    d = desk(write_journal=False)
    d.on_bar("NIFTY FUT", bar("09:15", 24800, 24840, 24790, 24830))
    o = d.place_paper_order("NIFTY FUT", "buy", 65, kind="stop", price=24850, stop=24700)
    d.on_bar("NIFTY FUT", bar("09:20", 24900, 24950, 24890, 24940))   # gapped above the trigger
    assert o.avg_fill == 24902                                          # open + 2, not the trigger


def test_protective_stop_gap_fills_at_open():
    d = desk(write_journal=False)
    d.on_bar("NIFTY FUT", bar("09:15", 24800, 24840, 24790, 24830))
    d.place_paper_order("NIFTY FUT", "buy", 65, stop=24700)
    d.on_bar("NIFTY FUT", bar("09:20", 24830, 24840, 24800, 24810))
    d.on_bar("NIFTY FUT", bar("09:25", 24600, 24650, 24550, 24620))   # gap through the stop
    t = d.trades[-1]
    assert t["exit_reason"] == "stop" and t["exit"] == 24598          # open − 2, not 24,700
    assert not d.positions


def test_volume_cap_fills_across_bars():
    d = paper.PaperDesk("US", 1_000_000, volume_cap=0.1, write_journal=False)
    d.on_bar("SPY", bar("09:30", 100, 101, 99, 100, v=1000))
    o = d.place_paper_order("SPY", "buy", 250)
    d.on_bar("SPY", bar("09:35", 100, 101, 99, 100, v=1000))
    assert o.filled_qty == 100 and o.status == "WORKING"
    d.on_bar("SPY", bar("09:40", 101, 102, 100, 101, v=1000))
    d.on_bar("SPY", bar("09:45", 101, 102, 100, 101, v=1000))
    assert o.filled_qty == 250 and o.status == "FILLED" and d.positions[0].qty == 250


def test_ch13_nifty_round_trip_costs_from_table():
    d = desk()
    d.on_bar("NIFTY FUT", bar("09:15", 24800, 24840, 24790, 24830))
    d.place_paper_order("NIFTY FUT", "buy", 65, kind="stop", price=24850, stop=24700, plan_id=1)
    d.on_bar("NIFTY FUT", bar("09:20", 24830, 24870, 24820, 24860))
    d.close_at_next_bar(d.positions[0].id)
    d.on_bar("NIFTY FUT", bar("09:25", 25000, 25010, 24980, 25000))
    t = d.trades[0]
    assert (t["entry"], t["exit"]) == (24852, 24998)
    assert t["chart_move"] == 9750 and t["slippage"] == 260
    assert t["costs"]["stt"] == 812.44                    # 0.05% of ₹16,24,870
    assert t["net"] == round(9750 - 260 - t["costs_total"], 2)
    row = store().all("journal", tag="REPLAY")[0]
    assert row["kind"] == "paper_trade" and row["net"] == t["net"]


def test_ch13_spy_round_trip():
    d = paper.PaperDesk("US", 40_000, mode="PAPER")
    d.on_bar("SPY", bar("09:30", 559, 560, 558, 559.5))
    d.place_paper_order("SPY", "buy", 60, kind="stop", price=560.00, plan_id=1)
    d.on_bar("SPY", bar("09:35", 559.8, 561, 559.7, 560.8))
    d.close_at_next_bar(d.positions[0].id)
    d.on_bar("SPY", bar("09:40", 566.00, 566.5, 565.5, 566))
    t = d.trades[0]
    assert (t["entry"], t["exit"]) == (560.02, 565.98)
    assert t["chart_move"] == 360.00 and t["slippage"] == 2.40
    assert t["costs"]["regulatory"] == 1.02 and t["net"] == 356.58
    assert store().all("journal", tag="PAPER")


def test_crypto_perp_funding_postings():
    d = paper.PaperDesk("IN", 500_000, write_journal=False)
    d.funding_rate["BTC-PERP"] = 0.0001
    day = {"open": 60000, "high": 60500, "low": 59500, "close": 60000, "volume": 1e6}
    d.on_bar("BTC-PERP", {"date": date(2026, 5, 25), **day})
    d.place_paper_order("BTC-PERP", "buy", 8)
    d.on_bar("BTC-PERP", {"date": date(2026, 5, 26), **day})
    assert len(d.funding_log) == 3                           # three prints a day
    assert d.positions[0].funding == pytest.approx(3 * 8 * 60000 * 0.0001)


def test_unplanned_and_stop_move_rules():
    d = desk(write_journal=False)
    d.on_bar("NIFTY FUT", bar("09:15", 24800, 24840, 24790, 24830))
    o = d.place_paper_order("NIFTY FUT", "buy", 65, stop=24700)
    assert o.unplanned
    d.on_bar("NIFTY FUT", bar("09:20", 24830, 24840, 24800, 24810))
    p = d.positions[0]
    with pytest.raises(ValueError):
        d.move_stop(p.id, 24650, "")                           # reason required
    d.move_stop(p.id, 24650, "felt too tight")
    assert "stop moved away" in p.rule_breaks and p.stop_moves[0]["reason"] == "felt too tight"
    d.move_stop(p.id, 24750, "trail")
    assert p.stop_moves[-1]["away_from_entry"] is False


def test_cost_preview_breakeven_ch21():
    nifty = paper.cost_preview(paper.instrument("NIFTY FUT", "IN"), 24940, 65, target=24960,
                               slippage_per_side=1)
    assert nifty.items["total"] == 960.85 and nifty.slippage_money == 130
    assert round(nifty.breakeven_pts, 1) == 16.8
    assert nifty.amber                                        # 20-pt target < 2 × breakeven
    spy = paper.cost_preview(paper.instrument("SPY", "US"), 561.20, 100, target=561.40)
    assert spy.all_in == 5.68 and round(spy.breakeven_pts * 100, 1) == 5.7


def test_bad_paper_orders_rejected():
    d = desk(write_journal=False)
    with pytest.raises(ValueError):
        d.place_paper_order("NIFTY FUT", "hold", 65)
    with pytest.raises(ValueError):
        d.place_paper_order("NIFTY FUT", "buy", 65, kind="limit")
