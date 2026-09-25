"""Pairs Lab: Engle–Granger in numpy, the lesson-26 sample pair, sizing, hand-offs."""

import json
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import pairs
from plugai_trade.pairs import sample


def test_snippet_14_runs_as_printed():
    snippets = json.loads((Path(__file__).parent / "book_snippets.json").read_text(encoding="utf-8"))
    code = next(s["code"] for s in snippets if s["file"] == "ch26.typ" and s["lang"] == "python")
    ns: dict = {}
    exec(compile("\n".join(line[2:] if line.startswith("  ") else line
                           for line in code.splitlines()), "snippet14", "exec"), ns)
    assert np.isfinite(ns["beta"]) and len(ns["z"]) == len(ns["spread"])


def test_sample_pair_matches_book():
    f = pairs.fit_symbols("SYN-A", "SYN-B")
    assert round(f.beta, 3) == 1.168
    assert round(f.sd, 4) == 0.0228
    assert round(f.half_life, 1) == 6.1
    assert round(f.adf_t, 2) == -3.71
    assert round(f.correlation, 2) == 0.84
    assert f.cointegrated


def test_snippet_maths_equals_lab_on_sample():
    a = sample.closes("SYN-A")["close"].to_numpy()
    b = sample.closes("SYN-B")["close"].to_numpy()
    F = 250
    beta, alpha = np.polyfit(np.log(b[:F]), np.log(a[:F]), 1)
    spread = np.log(a) - alpha - beta * np.log(b)
    lam = np.polyfit(spread[:F - 1], np.diff(spread[:F]), 1)[0]
    f = pairs.fit(a, b, F)
    assert f.beta == pytest.approx(beta) and f.half_life == pytest.approx(-np.log(2) / np.log(1 + lam))


def test_correlated_pair_fails_test():
    f = pairs.fit_symbols("SYN-C", "SYN-D")
    assert round(f.correlation, 2) == 0.94
    assert round(f.adf_t, 2) == -1.57 and not f.cointegrated
    assert 36 < f.half_life < 38


def test_find_pairs_side_by_side():
    cands = pairs.find_pairs(["SYN-A", "SYN-B", "SYN-C", "SYN-D"])
    by = {(c.a, c.b): c for c in cands}
    assert by[("SYN-A", "SYN-B")].passes and not by[("SYN-C", "SYN-D")].passes
    assert by[("SYN-C", "SYN-D")].correlation > by[("SYN-A", "SYN-B")].correlation


def test_rule_run_break_and_suspend():
    f = pairs.fit_symbols("SYN-A", "SYN-B")
    trades, suspended = pairs.run_rule(f.z, f.spread, f.formation, pairs.PairRule(2, 0.5, 3.5, 18))
    kinds = [t.exit_type for t in trades]
    assert len(trades) == 5 and "time stop" in kinds and kinds[-1] == "stop"
    assert suspended == sample.BREAK_SESSION
    assert trades[-1].exit_z < -3.5


def test_adf_on_random_walk_vs_stationary():
    rng = np.random.default_rng(0)
    rw = np.cumsum(rng.normal(size=500))
    ar = np.zeros(500)
    for t in range(1, 500):
        ar[t] = 0.5 * ar[t - 1] + rng.normal()
    crit = pairs.mackinnon_critical(499)
    assert pairs.adf_stat(ar) < crit < pairs.adf_stat(rw)
    assert pairs.adf_stat(ar, lags=2) < crit
    assert round(pairs.mackinnon_critical(249), 2) == -3.36


def test_india_lot_sizing_book():
    s = pairs.size_lots(1630, 885, 1000, 2000, 1.168)
    assert s.value_a == 1_630_000 and round(s.target_b) == 1_903_840
    assert round(s.target_lots_b, 2) == 1.08 and s.lots_b == 1 and s.value_b == 1_770_000
    assert round(s.achieved, 3) == 1.086 and round(s.error, 3) == -0.070
    near = pairs.lots_within(1630, 885, 1000, 2000, 1.168)
    assert (near.lots_a, near.lots_b) == (8, 9)
    assert round((near.value_a + near.value_b) / 1e7, 1) == 2.9


def test_us_share_sizing_book():
    s = pairs.size_shares(10_000, 81.66, 44.26, 1.168, 0.03, 16)
    assert (s.shares_a, s.value_a) == (122, 9962.52)
    assert (s.shares_b, s.value_b) == (263, 11640.38)
    assert round(s.target_b, 2) == 11636.22 and round(s.achieved, 3) == 1.168
    assert s.borrow_fee == 15.52


def test_link_rating_parse():
    assert pairs.link_rating("...\nRating: Strong") == "Strong"
    assert pairs.link_rating("Rating: **None** — nothing shared") == "None"
    assert pairs.link_rating("no idea") is None
    assert pairs.link_rating("Rate it Strong / Weak / None yourself.") is None


def test_check_link_offline_fallback(monkeypatch):
    from plugai_trade import ai
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ai.Explanation(text="", where="Fallback"))
    out = pairs.check_link("SYN-A", "SYN-B")
    assert out.text and pairs.link_rating(out.text) is None


def test_check_link_prompt_has_no_trade_advice(monkeypatch):
    from plugai_trade import ai
    seen = {}
    monkeypatch.setattr(ai, "complete", lambda prompt, **k: seen.setdefault("p", prompt) and
                        ai.Explanation(text="Shared drivers...\nRating: Weak"))
    out = pairs.check_link("SYN-A", "SYN-B", "two lines")
    assert pairs.link_rating(out.text) == "Weak"
    assert "Do NOT recommend trading" in seen["p"] and "UNTRUSTED" in seen["p"]


def test_send_to_paper_desk_and_backtest():
    from plugai_trade.store import default as store
    f = pairs.fit_symbols("SYN-A", "SYN-B")
    rule = pairs.PairRule()
    ids = pairs.send_to_paper_desk(f, 1, 122, 263, rule, "results 2026-07-20")
    rows = [store().get("paper_orders", i) for i in ids]
    assert [r["side"] for r in rows] == ["buy", "sell"]
    assert rows[0]["link_id"] == rows[1]["link_id"] and all(r["tag"] == "pending" for r in rows)
    trades, susp = pairs.run_rule(f.z, f.spread, f.formation, rule)
    bid = pairs.send_to_backtest(f, rule, trades, susp)
    assert store().get("backtests", bid)["source"] == "Pairs Lab"
    assert store().count("trials", tag="pairs") == 1


def test_page_flows():
    at = AppTest.from_string(
        "import streamlit as st\nst.session_state.setdefault('market', 'US')\n"
        "from plugai_trade.app.pages import pairs_lab as m\nm.render()\n", default_timeout=60)
    at.run()
    assert not at.exception
    assert any(m.label == "Half-life" and m.value == "6.1 sessions" for m in at.metric)
    assert any(m.label == "Hedge ratio" and m.value == "1.168" for m in at.metric)
    at.button(key="pl_find").click().run()
    at.button(key="pl_link").click().run()
    at.button(key="pl_send_bt").click().run()
    assert not at.exception
