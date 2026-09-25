"""Automate › ML Lab — features, labels and honest tests (Chapter 29).

Dataset (each feature with its *Known at* line, plus Noise (control)), Label,
Split in time (Purge ≥ label, Embargo), Train baseline, Results vs baselines,
Overfit curve, Feature importance, Shuffle test (for learning only), and the
Scenarios tab (Volatility scenarios, Scored history, Send to Position Sizer).
The ML Lab never produces a trade signal.
"""

from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import data, ml
from plugai_trade.app import ui
from plugai_trade.store import default as store

SECTION = "Automate"
DEFAULT_SYMBOL = {"IN": "NIFTY", "US": "SPY"}


def _bars(symbol: str, mkt: str, start: date, end: date):
    df = data.get(symbol, market=mkt, start=start, end=end)
    ui.set_data_status(df)
    return df


def _dataset_panel() -> tuple[list[str], bool]:
    st.caption("Tick features. Each is computed only from data up to the row's close.")
    feats = []
    for f in ml.FEATURES:
        if st.checkbox(f, value=True, key=f"ml_feat_{f}"):
            feats.append(f)
        st.caption(f"Known at: {ml.KNOWN_AT[f]}")
    noise = st.checkbox("Noise (control)", value=True, key="ml_noise",
                        help="Random numbers. Any feature ranked at or below it is not earning its place.")
    st.caption(f"Known at: {ml.KNOWN_AT[ml.NOISE]}")
    return feats, noise


def _label_panel() -> str:
    names = list(ml.LABELS)
    label = st.radio("Label", names, format_func=lambda k: ml.LABELS[k], key="ml_label")
    st.caption(ml.LABEL_QUESTION[label])
    return label


def _split_panel() -> tuple[float, float, int, int]:
    a, b = st.slider("Train | validation | test boundaries (% of history, in time order)",
                     10, 95, (60, 80), step=5, key="ml_bounds")
    c1, c2 = st.columns(2)
    purge = c1.number_input("Purge (rows)", min_value=ml.features.HORIZON, value=ml.features.HORIZON,
                            step=1, key="ml_purge",
                            help="Set to the label length automatically; it cannot be set lower.")
    embargo = c2.number_input("Embargo (rows)", min_value=0, value=0, step=1, key="ml_embargo",
                              help="Applies to walk-forward runs; here it drops rows at the start "
                                   "of the validation and test blocks.")
    st.caption(f"Train {a}% · validation {b - a}% · sealed test {100 - b}%. No shuffle option.")
    return a / 100, (b - a) / 100, int(purge), int(embargo)


def _train(feats: list[str], noise: bool, label: str, split_cfg: tuple, symbol: str, mkt: str,
           start: date, end: date, rule: str) -> None:
    train, valid, purge, embargo = split_cfg
    bars = _bars(symbol, mkt, start, end)
    ds = ml.dataset(bars, label=label, features=feats, noise_column=noise)
    ds.symbol = symbol
    split = ml.time_split(ds, train=train, valid=valid, test=round(1 - train - valid, 6),
                          purge=purge, embargo=embargo)
    model = ml.boosting(split)
    baselines = ["majority"] + ([rule] if rule.strip() else [])
    st.session_state["ml_card"] = ml.report(model, split, baselines=baselines)
    st.session_state.pop("ml_shuffle", None)


def _results(card: ml.ModelCard | None) -> None:
    if card is None:
        st.info("Click **Train baseline** to fill Results vs baselines, the Overfit curve and "
                "Feature importance.")
        return
    rows = [("Training years (flattering)", card.scores["train"]),
            ("Validation years", card.scores["valid"]),
            ("Sealed test years", card.scores["test"])]
    rows += [(f"{'Majority guess' if k == 'majority' else 'One-line rule: ' + k}, test years", v)
             for k, v in card.baselines.items()]
    shuffle = st.session_state.get("ml_shuffle")
    if shuffle:
        rows.append((f"Shuffled {shuffle.folds}-fold (leaky) — for learning only", shuffle.score))
    st.dataframe(pd.DataFrame(rows, columns=["Accuracy, %", "Score"]).round(1),
                 hide_index=True, width="stretch")
    color = {"Robust": st.success, "Fragile": st.warning}.get(card.grade, st.error)
    color(f"Grade: **{card.grade}** — {card.why}")
    st.caption(f"Trials counter (this ML family): {card.trials} · {card.model.engine} · "
               "HYPOTHETICAL")
    with st.expander("Model card"):
        st.code(card.text(), language=None)
    ui.ai_block(card, "ml_card", section=SECTION, on_accept=lambda text: _save_card(card, text))


def _save_card(card: ml.ModelCard, text: str) -> None:
    store().add("notes", {"kind": "model_card", **card.to_dict(), "explanation": text},
                tag="journal")


def _overfit(card: ml.ModelCard | None) -> None:
    if card is None:
        st.caption("Train a model first.")
        return
    df = pd.DataFrame(card.overfit).melt("depth", var_name="block", value_name="accuracy")
    ch = alt.Chart(df).mark_line(point=True).encode(
        x=alt.X("depth:Q", title="Tree depth (yes/no questions)"),
        y=alt.Y("accuracy:Q", title="Accuracy, %", scale=alt.Scale(zero=False)),
        strokeDash="block:N", color="block:N").properties(height=260)
    st.altair_chart(ui.hypothetical_chart(ch), width="stretch")
    st.caption("One decision tree allowed to go deeper: training keeps rising, validation does not.")


def _importance(card: ml.ModelCard | None) -> None:
    if card is None:
        st.caption("Train a model first.")
        return
    df = pd.DataFrame({"feature": list(card.importance), "points": list(card.importance.values())})
    df["control"] = df["feature"].eq(ml.NOISE)
    ch = alt.Chart(df).mark_bar().encode(
        y=alt.Y("feature:N", sort="-x", title=None),
        x=alt.X("points:Q", title="Accuracy lost when shuffled (points, test years)"),
        color=alt.condition("datum.control", alt.value("#94A3B8"), alt.value("#0EA5E9")))
    st.altair_chart(ch.properties(height=28 * len(df) + 40), width="stretch")
    st.caption("Importance describes the model, not the market. Anything at or below the "
               "Noise (control) bar has not shown it helps.")


def _scenarios(symbol: str, mkt: str, start: date, end: date) -> None:
    horizon = st.number_input("Horizon (sessions)", 5, 30, 10, key="ml_sc_h")
    st.caption("A time-series foundation model (Chronos, TimesFM) is optional and runs locally "
               f"when installed; otherwise: {ml.scenarios.ENGINE}.")
    if st.button("Volatility scenarios", key="ml_sc_btn"):
        bars = _bars(symbol, mkt, start, end)
        st.session_state["ml_sc"] = ml.vol_scenarios(bars, horizon=int(horizon))
        st.session_state["ml_hist"] = ml.scored_history(bars, horizon=int(horizon))
    sc = st.session_state.get("ml_sc")
    if not sc:
        return
    c = st.columns(4)
    c[0].metric("Low (calm)", f"{sc.low:.2f}%")
    c[1].metric("Middle", f"{sc.middle:.2f}%")
    c[2].metric("High (stormy)", f"{sc.high:.2f}%")
    c[3].metric("Last 20 sessions continue", f"{sc.baseline:.2f}%")
    st.caption(f"Average daily high–low range over the next {sc.horizon} sessions, as of "
               f"{sc.as_of}. Not a forecast of direction.")
    if st.button("Send to Position Sizer", key="ml_sc_send"):
        st.session_state["ml_sc_pending"] = True
    if st.session_state.get("ml_sc_pending"):
        st.info("Size a paper position for the calm and the stormy band. Nothing is applied "
                "until you click Accept.")
        if st.button("Accept", key="ml_sc_accept", type="primary"):
            st.session_state["position_sizer_vol_scenarios"] = sc.to_dict()
            store().add("notes", {"kind": "vol_scenarios", "symbol": symbol, **sc.to_dict()},
                        tag="sizer")
            st.session_state["ml_sc_pending"] = False
            st.success("Sent to Plan & Risk › Position Sizer.")
    ui.ai_block(sc, "ml_sc_ai", section=SECTION)


def _history() -> None:
    hist = st.session_state.get("ml_hist")
    if hist is None or hist.is_empty():
        st.caption("Click Volatility scenarios first.")
        return
    for f in ml.history_facts(hist):
        st.markdown(f"- {f}")
    ui.line_chart(hist.to_pandas(), "date", ["realised", "middle", "baseline"],
                  title="Scored at each past month-end", hypothetical=True)
    st.caption("Each forecast used only data up to its own month-end. A foundation model is "
               "scored only after its published training cutoff.")


def render() -> None:
    ui.page_header("ML Lab", SECTION, "Honest tests: time-ordered split, purge, baselines, trials.")
    mkt = ui.market()
    c1, c2, c3 = st.columns([1.2, 1, 1])
    symbol = c1.text_input("Symbol", DEFAULT_SYMBOL.get(mkt, "NIFTY"), key=f"ml_sym_{mkt}")
    start = c2.date_input("From", date(2010, 1, 1), key="ml_start")
    end = c3.date_input("To", date(2026, 5, 29), key="ml_end")
    tabs = st.tabs(["Dataset", "Label", "Split in time", "Results vs baselines", "Overfit curve",
                    "Feature importance", "Scenarios", "Scored history"])
    with tabs[0]:
        feats, noise = _dataset_panel()
    with tabs[1]:
        label = _label_panel()
    with tabs[2]:
        split_cfg = _split_panel()
    b1, b2, b3 = st.columns([1, 1, 2])
    rule = b3.text_input("One-line rule baseline", "vol_20 > 1", key="ml_rule",
                         help="feature > value, e.g. vol_20 > 1 (20-day volatility above normal)")
    if b1.button("Train baseline", type="primary", key="ml_train"):
        try:
            _train(feats, noise, label, split_cfg, symbol, mkt, start, end, rule)
        except ValueError as exc:
            st.error(str(exc))
    card: ml.ModelCard | None = st.session_state.get("ml_card")
    if b2.button("Shuffle test", key="ml_shuffle_btn", disabled=card is None,
                 help="The leaky shuffled k-fold score, for learning only."):
        st.session_state["ml_shuffle"] = ml.shuffle_test(card.split, honest=card.scores["test"])
    with tabs[3]:
        _results(card)
    with tabs[4]:
        _overfit(card)
    with tabs[5]:
        _importance(card)
    with tabs[6]:
        _scenarios(symbol, mkt, start, end)
    with tabs[7]:
        _history()
    st.caption("HYPOTHETICAL · A model's output can go to the Position Sizer as a volatility "
               "estimate or to your journal as a note — never to an order.")
