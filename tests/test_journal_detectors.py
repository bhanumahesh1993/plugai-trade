"""The six detectors, the Rule Card tests and the 'too few to conclude' label."""

from datetime import datetime

import polars as pl

from plugai_trade import journal
from plugai_trade.journal import detectors
from plugai_trade.journal.samples import _finish


def _trades(rows):
    recs = [{"entry_time": a, "exit_time": b, "underlying": "NIFTY", "symbol": "NIFTY26SEPFUT",
             "instrument": "FUT", "side": "LONG", "qty": 65.0, "entry_price": 24800.0,
             "exit_price": 24800.0 + r * 100, "stop_distance": 100.0} for a, b, r in rows]
    return _finish(pl.DataFrame(recs), "IN", "Test", "test")


def d(h, m, day=8):
    return datetime(2026, 9, day, h, m)


def test_samples_are_seeded_and_sized_like_the_book():
    k1, k2 = journal.sample("kavita"), journal.sample("kavita")
    assert k1.height == 54 and journal.sample("marcus").height == 61
    assert k1["r_multiple"].to_list() == k2["r_multiple"].to_list()
    assert k1["date"].min() == "2026-08-17" and k1["date"].max() <= "2026-09-11"
    assert (k1["risk"] > 0).all() and k1["charges_source"].unique().to_list() == ["cost table"]


def test_rule_breaks_each_line():
    t = _trades([
        (d(9, 20), d(9, 40), -1.0),     # 1 first 15 min
        (d(10, 0), d(10, 20), -1.0),    # 2 day now −2R
        (d(10, 30), d(10, 50), 1.0),    # 3 after daily limit
        (d(11, 0), d(12, 30), -1.6),    # 4 4th trade: over cap; stop moved (< −1.2R)
    ])
    e = detectors.enrich(t)
    assert e["br_first_minutes"].to_list() == [True, False, False, False]
    assert e["br_after_daily_limit"].to_list() == [False, False, True, True]
    assert e["br_over_cap"].to_list() == [False, False, False, True]
    assert e["br_stop_moved"].to_list() == [False, False, False, True]
    rep = detectors.run(t)
    assert rep.broke_none.n == 1 and rep.adherence == 25.0
    assert "too few to conclude" in rep.broke_any.text()


def test_reentries_gaps_and_holding_time():
    t = _trades([
        (d(10, 0), d(10, 20), -1.0),
        (d(10, 25), d(11, 30), -1.0),   # 5 min after a loss → quick re-entry
        (d(12, 30), d(12, 50), 2.0),    # 60 min after a loss
        (d(13, 50), d(14, 0), 1.0),     # 60 min after a win
    ])
    rep = detectors.run(t)
    assert rep.reentries.n == 1 and rep.reentries.rows == [2]
    assert rep.gaps == {"after_win": 60.0, "after_loss": 32.5}
    assert rep.holding["loss_median"] == 42.5 and rep.holding["win_median"] == 15.0
    assert rep.after_two_losses.rows == [3]


def test_time_of_day_buckets_use_the_session_table():
    assert detectors.bucket_edges("IN")[:3] == [555, 570, 630]         # 09:15, 09:30, 10:30
    assert detectors.bucket_edges("US")[:3] == [570, 585, 630]         # 09:30, 09:45, 10:30
    rep = detectors.run(journal.sample("kavita"))
    tod = rep.time_of_day
    assert tod["bucket"][0] == "09:15" and int(tod["n"].sum()) == 54
    assert all("too few to conclude" in n for n in tod["note"].to_list())


def test_costs_detector_and_charges_share():
    rep = detectors.run(journal.sample("kavita"))
    c = rep.costs
    assert c["net"] == round(c["gross"] - c["charges"], 2)
    assert c["charges_pct_gross"] == round(c["charges"] / c["gross"] * 100, 1)
    assert 0.05 < c["charges_in_r"] < 0.15                            # ≈ 0.10R per trade
    us = detectors.run(journal.sample("marcus")).costs
    assert us["charges_pct_gross"] < c["charges_pct_gross"]            # US far cheaper


def test_blocked_rows_are_counted_not_traded():
    t = _trades([(d(10, 0), d(10, 20), 1.0), (d(11, 0), d(11, 0), 0.0)])
    t = t.with_columns(tags=pl.Series([[], ["BLOCKED"]], dtype=pl.List(pl.Utf8)))
    rep = detectors.run(t)
    assert rep.n == 1 and rep.blocked == 1


def test_rule_card_from_store(lab_home):
    from plugai_trade.store import default as store
    store().add("rule_cards", {"version": 4, "limits": {"max_trades_per_day": 2,
                                                        "cooldown_minutes": 30}})
    card = detectors.RuleCard.from_store()
    assert card.max_trades_per_day == 2 and card.cooldown_minutes == 30
    assert card.no_trade_first_minutes == 15
    assert any(k == "cooldown" for k, _ in card.lines())


def test_facts_cite_counts_for_the_narrator():
    facts = journal.detect(journal.sample("marcus")).facts()
    assert facts[0].startswith("Trades: 61")
    assert any(f.startswith("Adherence:") for f in facts)
