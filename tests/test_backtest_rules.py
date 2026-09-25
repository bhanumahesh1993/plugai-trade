"""Rule parsing, spec validation, the Report Card, deflated Sharpe, walk-forward, heatmap."""

from __future__ import annotations

import json

import pytest

from plugai_trade import ai, data
from plugai_trade.backtest import (
    Spec,
    SpecError,
    deflated_sharpe,
    expected_max_sharpe,
    heatmap,
    ma_crossover,
    rules,
    run,
    trials,
    ts_momentum,
    walk_forward,
)
from plugai_trade.backtest.report import FRAGILE, OVERFIT, ROBUST


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)
    monkeypatch.setattr(ai, "_ollama_chat", lambda *a, **k: (_ for _ in ()).throw(OSError()))


@pytest.fixture(scope="module")
def bars5():
    return data.get("NIFTY", "IN", "2021-01-01", "2025-12-31", source="synthetic")


def _conds(cs):
    return [(c.op, c.left.kind, c.left.n, c.right.kind, c.right.n, c.right.value) for c in cs]


@pytest.mark.parametrize("text, entry, exit_", [
    (("Buy at the next open on the first close above the 50-day average; sell at the next open "
      "when the close is below the 20-day average"),
     [("cross_above", "close", None, "sma", 50, None)], [("below", "close", None, "sma", 20, None)]),
    ("Buy when close > 50-day average; exit below 20-day average",
     [("above", "close", None, "sma", 50, None)], [("below", "close", None, "sma", 20, None)]),
    ("Buy when the 20-day EMA crosses above the 50-day EMA; sell when it crosses below",
     [("cross_above", "ema", 20, "ema", 50, None)], [("cross_below", "ema", 20, "ema", 50, None)]),
    ("Buy when RSI(2) is below 10; sell when RSI(2) is above 70",
     [("below", "rsi", 2, "value", None, 10.0)], [("above", "rsi", 2, "value", None, 70.0)]),
    ("Buy when close crosses above the 20-day high; sell when close crosses below the 10-day low",
     [("cross_above", "close", None, "high_n", 20, None)],
     [("cross_below", "close", None, "low_n", 10, None)]),
    ("When the 20-day crosses above the 50-day, buy. Sell when the 20-day crosses below the 50-day.",
     [("cross_above", "sma", 20, "sma", 50, None)], [("cross_below", "sma", 20, "sma", 50, None)]),
])
def test_parser_phrasings(text, entry, exit_):
    s = rules(text)
    assert _conds(s.entry) == entry and _conds(s.exit) == exit_


def test_hold_while_snippet_phrasing():
    s = rules("Hold while the 50-day average is above the 200-day average; check Fridays; "
              "fill next open; size to 12% volatility, 10% buffer, no borrowing")
    assert s.mode == "hold_while" and s.check == "weekly"
    assert s.size.method == "vol_target" and s.size.target_vol == 0.12 and s.size.buffer == 0.10
    assert s.size.cap == 1.0 and not s.size.borrowing
    assert "fill" not in s.assumed and "size.buffer" not in s.assumed
    assert "entry.average" in s.assumed  # "average" did not say simple or exponential


def test_52_week_high_time_stop_stop_loss():
    s = rules("Buy on a new 52-week high; exit after 20 days; stop loss 8%")
    assert _conds(s.entry) == [("above", "close", None, "high_n", 252, None)]
    assert s.time_stop == 20 and s.stop_loss_pct == 8.0


def test_momentum_and_monthly_check():
    s = rules("Hold while the 12-month return is positive; check monthly")
    assert _conds(s.entry) == [("above", "close", None, "close_ago", 252, None)]
    assert s.check == "monthly"


def test_assumed_fields_marked_amber():
    s = rules("Buy when the price is above the 50-day average; get out when it falls below the "
              "20-day average")
    for k in ("entry.basis", "entry.average", "fill", "check", "size.method", "cost.slippage"):
        assert k in s.assumed
    rb = s.read_back()
    assert "(assumed)" in rb and "next session's open" in rb
    titles = [c["title"] for c in s.cards()]
    assert titles == ["ENTRY", "EXIT", "FILL", "SIZE · COST"]
    assert any(flag for c in s.cards() for _, flag in c["lines"])


def test_read_back_plain_english():
    s = rules("Buy at the next open on the first close above the 50-day average; sell at the next "
              "open when the close is below the 20-day average")
    rb = s.read_back()
    assert rb.startswith("Buys at the next session's open on the first close above the 50-day")
    assert "Sells at the next session's open when the close is below the 20-day" in rb


def test_nothing_to_parse_raises():
    with pytest.raises(SpecError):
        rules("I like trends")
    with pytest.raises(SpecError, match="EXIT"):
        rules("Buy when close > 50-day average")


def test_spec_json_roundtrip():
    s = rules("Hold while the 50-day average is above the 200-day average; weekly; size to 12% "
              "volatility")
    d = json.loads(s.to_json())
    back = Spec.from_dict(d)
    assert back.to_dict() == s.to_dict() and back.digest() == s.digest()


@pytest.mark.parametrize("bad", [
    {"mode": "entry_exit", "entry": [{"op": "above", "left": {"kind": "close"},
                                      "right": {"kind": "sma", "n": 0}}], "time_stop": 5},
    {"mode": "entry_exit", "entry": [{"op": "sideways", "left": {"kind": "close"},
                                      "right": {"kind": "sma", "n": 5}}], "time_stop": 5},
    {"mode": "hold_while", "entry": [{"op": "above", "left": {"kind": "close"},
                                      "right": {"kind": "sma", "n": 5}}],
     "size": {"method": "vol_target", "cap": 2.0}},
    {"mode": "hold_while", "entry": [{"op": "above", "left": {"kind": "close"},
                                      "right": {"kind": "sma", "n": 5}}],
     "cost": {"profile": "MARS-equity"}},
])
def test_invalid_specs_rejected(bad):
    with pytest.raises(SpecError):
        Spec.from_dict(bad).validate()


def test_model_path_used_only_when_parser_fails(monkeypatch):
    calls = []

    def fake_complete(prompt, section="Research", schema=None, **k):
        calls.append(schema)
        return ai.Explanation(text=json.dumps({
            "mode": "hold_while", "check": "weekly",
            "entry": [{"op": "above", "left": {"kind": "close"}, "right": {"kind": "sma", "n": 100}}],
            "assumed": ["entry.average"]}), model="test")

    monkeypatch.setattr(ai, "complete", fake_complete)
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: True)
    rules("Buy when close > 50-day average; sell when close < 20-day average")
    assert calls == []
    s = rules("stay with the trend as long as it's healthy")
    assert calls and calls[0] is not None and s.origin == "model"
    assert s.entry[0].right.n == 100 and s.fill == "next_open"


# ------------------------------------------------------------------ deflated Sharpe
def test_deflated_sharpe_properties():
    assert expected_max_sharpe(1, 0.01) == 0.0
    assert expected_max_sharpe(200, 0.01) > expected_max_sharpe(20, 0.01) > 0
    p1, _ = deflated_sharpe(0.05, 1000, 1)
    p50, sr0 = deflated_sharpe(0.05, 1000, 50)
    assert p1 > p50 and sr0 > 0
    p, _ = deflated_sharpe(0.0, 1000, 1)
    assert p == pytest.approx(0.5, abs=1e-9)


# ------------------------------------------------------------------ Report Card
def test_report_card_grades_and_checks(bars5):
    res = run(rules("Hold while the 50-day average is above the 200-day average; check Fridays; "
                    "fill next open"), bars5)
    card = res.report(echo=False)
    assert card.grade in (ROBUST, FRAGILE, OVERFIT)
    names = [c.name for c in card.checks]
    assert names == ["Costs", "Sample size", "Unseen data", "Trial count", "Neighbours",
                     "Concentration"]
    sample = card.checks[1]
    assert res.stats()["round_trips"] < 30 and sample.status == "fail"
    assert card.grade != ROBUST
    assert any(w.startswith("Survivorship") for w in card.warnings)
    facts = res.facts()
    assert any(f.startswith("Report Card grade") for f in facts)
    assert any("HYPOTHETICAL" in f for f in facts)
    exp = ai.explain(res)
    assert exp.sources == facts


def test_walk_forward_five_years_has_six_windows(bars5):
    wf = walk_forward(ma_crossover(50, 200, check="daily", vol_target=False), bars5)
    assert len(wf.windows) == 6
    assert all(w["score_from"] > w["choose_to"] for w in wf.windows)


def test_heatmap_counts_every_cell(bars5):
    spec = ma_crossover(50, 200)
    run(spec, bars5)
    hm = heatmap(spec, bars5, rows=("entry.0.left.n", [10, 20, 30, 50, 75, 100]),
                 cols=("entry.0.right.n", [100, 150, 200, 250, 300]), skip=lambda a, b: a >= b)
    assert hm.cells == 29 and hm.trials == 29  # the earlier 50/200 run is one of the 29
    assert hm.tuning[-1][0] is None
    assert "Settings tried: 29" in hm.text()
    assert trials.count(spec.family_key()) == 29


def test_trend_presets_and_after_tax(bars5):
    res = run(ts_momentum(12), bars5, costs="IN-equity-delivery")
    tax = res.after_tax()
    assert tax["total_tax"] >= 0
    assert tax["equity"][-1] <= res.equity[-1] + 1e-6
    assert tax["short_rate"] == 0.20  # from the dated India tax table
