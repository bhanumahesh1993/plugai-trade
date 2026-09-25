"""ML Lab (Chapter 29): known-at features, time split with purge, baselines, trials, snippet [22]."""

import json
import textwrap
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from plugai_trade import ai, data, ml


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)
    monkeypatch.setattr(ai, "_ollama_chat", lambda *a, **k: (_ for _ in ()).throw(OSError()))


@pytest.fixture(scope="module")
def bars():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return data.get("NIFTY", market="IN", start="2010-01-01", end="2026-05-29",
                        source="synthetic")


def test_features_are_known_at_the_close(bars):
    """Changing every bar after row t must not change any feature at row t."""
    ds = ml.dataset(bars, label="direction_next_10", noise_column=False)
    t = 1500
    cut = ds.frame["date"][t]
    later = bars.with_columns(
        pl.when(pl.col("date") > cut).then(pl.col(c) * 1.7).otherwise(pl.col(c)).alias(c)
        for c in ("open", "high", "low", "close", "volume"))
    ds2 = ml.dataset(later, label="direction_next_10", noise_column=False)
    row = ds.frame.filter(pl.col("date") == cut).select(ml.FEATURES)
    row2 = ds2.frame.filter(pl.col("date") == cut).select(ml.FEATURES)
    assert np.allclose(row.to_numpy(), row2.to_numpy())
    assert set(ds.known_at) == set(ml.FEATURES)


def test_noise_column_and_labels(bars):
    ds = ml.dataset(bars, label="triple_barrier", noise_column=True)
    assert ml.NOISE in ds.features and ds.known_at[ml.NOISE].startswith("random")
    assert set(ds.classes) <= {-1, 0, 1}
    assert ds.frame["date"].is_sorted()


def test_time_split_purges_and_refuses_short_purge(bars):
    ds = ml.dataset(bars, label="high_vol_next_10")
    split = ml.time_split(ds, train=0.6, valid=0.2, test=0.2)
    assert split.purge == 10
    assert split.valid[0] - split.train[-1] > 10 and split.test[0] - split.valid[-1] > 10
    assert split.train.max() < split.valid.min() < split.test.min()   # time order
    with pytest.raises(ValueError, match="purge"):
        ml.time_split(ds, purge=5)
    with pytest.raises(TypeError):
        ml.time_split(ds, shuffle=True)  # no shuffle option
    emb = ml.time_split(ds, embargo=5)
    assert emb.test[0] - split.test[0] == 5


def test_boosting_counts_trials_and_card_grades(bars):
    ds = ml.dataset(bars, label="high_vol_next_10")
    split = ml.time_split(ds)
    m1 = ml.boosting(split)
    m2 = ml.boosting(split)
    assert m2.trial_no == m1.trial_no + 1
    card = ml.report(m2, split, baselines=["majority", "vol_20 > 1"])
    assert card.trials == m2.trial_no
    assert card.grade in ("Robust", "Fragile", "Likely overfit")
    assert ml.NOISE in card.importance and len(card.overfit) == 14
    assert card.overfit[-1]["train"] > card.overfit[0]["train"]      # deeper → memorises
    assert card.scores["test"] > card.baselines["majority"]           # volatility pattern found
    assert any(f.startswith("Grade:") for f in card.facts())


def test_direction_model_is_not_robust(bars):
    ds = ml.dataset(bars, label="direction_next_10")
    split = ml.time_split(ds)
    card = ml.report(ml.boosting(split), split, baselines=["majority"])
    assert card.grade != "Robust"


def test_numpy_stumps_learn_a_simple_rule():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(600, 3))
    y = (X[:, 1] > 0.2).astype(int)
    model = ml.StumpBooster(n_estimators=50).fit(X, y)
    assert (model.predict(X) == y).mean() > 0.95


def test_shuffle_test_is_for_learning_only(bars):
    ds = ml.dataset(bars, label="direction_next_10")
    before = ml.ml_trials(f"ml:{ds.symbol}:{ds.label}")
    res = ml.shuffle_test(ml.time_split(ds), folds=3)
    assert res.label == "for learning only" and "FOR LEARNING ONLY" in res.text()
    assert ml.ml_trials(f"ml:{ds.symbol}:{ds.label}") == before     # not a trial


def test_rule_baseline_parser(bars):
    split = ml.time_split(ml.dataset(bars))
    assert set(np.unique(ml.rule_baseline("vol_20 > 1", split))) <= {0, 1}
    with pytest.raises(ValueError):
        ml.rule_baseline("buy when vol is high", split)


def test_vol_scenarios_and_scored_history(bars):
    sc = ml.vol_scenarios(bars, horizon=10)
    assert sc.low <= sc.middle <= sc.high and sc.baseline > 0
    hist = ml.scored_history(bars)
    assert hist.height > 24 and {"inside", "err_model", "err_baseline"} <= set(hist.columns)
    assert any("Month-ends scored" in f for f in ml.history_facts(hist))


def test_book_snippet_22_runs_offline(capsys):
    snips = json.loads((Path(__file__).parent / "book_snippets.json").read_text())
    code = textwrap.dedent(snips[22]["code"])
    assert "ml.dataset" in code
    exec(compile(code, "snippet-22", "exec"), {})  # noqa: S102 - book snippet
    out = capsys.readouterr().out
    assert "MODEL CARD" in out and "Grade:" in out and "noise (control)" in out


def test_ml_lab_screen_train_shuffle_scenarios():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(
        "from plugai_trade import ai\nai.ollama_ok = lambda timeout=1.5: False\n"
        "from plugai_trade.app.pages import ml_lab as m\nm.render()\n", default_timeout=120)
    at.run()
    labels = [b.label for b in at.button]
    for label in ("Train baseline", "Shuffle test", "Volatility scenarios"):
        assert label in labels
    at.button(key="ml_train").click().run()
    assert not at.exception and any("Grade:" in w.value for w in [*at.warning, *at.error, *at.success])
    at.button(key="ml_shuffle_btn").click().run()
    at.button(key="ml_sc_btn").click().run()
    assert [m.label for m in at.metric][:3] == ["Low (calm)", "Middle", "High (stormy)"]
    at.button(key="ml_sc_send").click().run()
    at.button(key="ml_sc_accept").click().run()
    assert not at.exception and at.session_state["position_sizer_vol_scenarios"]["horizon"] == 10
