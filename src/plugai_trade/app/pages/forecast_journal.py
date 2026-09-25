"""Portfolio › Forecast Journal (Chapter 26). US only; greyed out for IN.

Add forecast → Resolution rules → your probability (price hidden until you
commit) → fee-adjusted break-even → Resolve → Brier score and, after 30
forecasts, the calibration chart. The journal records forecasts, not positions.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import ai, forecast
from plugai_trade.app import ui

RULES_PROMPT = (
    "Below is the full rules text of an event contract.\n{rules}\n\n"
    "Do NOT estimate the probability, do NOT recommend buying or selling, and do NOT do any "
    "arithmetic with prices or fees.\n"
    "1. In one sentence: what exact observation makes YES pay?\n"
    "2. Name the source, the time (with time zone) and any rounding or revisions rule.\n"
    "3. List every ambiguity or edge case, and how the rules say it is resolved.\n"
    "4. List three ways a casual reader could misunderstand this contract."
)
IN_NOTE = ("Disabled for IN: in India, prediction markets are treated as prohibited online money "
           "games (Promotion and Regulation of Online Gaming Act, 2025) and the major platforms "
           "have been blocked. The calibration lesson below still runs offline: score your own "
           "forecasts about your markets, with no market and no money.")


def _add_forecast(disabled: bool) -> None:
    if st.button("Add forecast", key="fj_add", disabled=disabled):
        st.session_state["fj_step"] = "rules"
    step = st.session_state.get("fj_step")
    if not step or disabled:
        return
    q = st.text_input("Contract question", key="fj_q")
    rules = st.text_area("Rules text (paste the contract's rules, source and deadline)", key="fj_rules")
    platform = st.text_input("Platform", key="fj_platform")
    if rules.strip():
        _rules_panel(rules)
    hide = st.toggle("Hide price until I commit", value=True, key="fj_hide")
    c = st.columns(2)
    prob = c[0].number_input("Your probability (%)", 0.0, 100.0, 50.0, 1.0, key="fj_prob")
    reason = c[1].text_input("One-line reason", key="fj_reason")
    committed = st.session_state.get("fj_committed")
    if not hide or committed:
        _price_panel(prob / 100)
    if committed is None and st.button("Commit forecast", key="fj_commit", type="primary",
                                       disabled=not q.strip()):
        price = None if hide else st.session_state.get("fj_price", 0.0) / 100
        fee = 0.0 if hide else st.session_state.get("fj_fee", 0.0) / 100
        st.session_state["fj_committed"] = forecast.add(q.strip(), rules, prob / 100, reason,
                                                        price, fee, platform)
        st.rerun()
    if committed is not None and st.button("Save price and finish", key="fj_finish"):
        forecast.set_price(committed, st.session_state.get("fj_price", 0.0) / 100,
                           st.session_state.get("fj_fee", 0.0) / 100)
        for k in ("fj_step", "fj_committed"):
            st.session_state.pop(k, None)
        st.success("Forecast saved. Nothing is bought: the journal records forecasts only.")


def _rules_panel(rules: str) -> None:
    st.markdown("**Resolution rules**")
    found = forecast.resolution_rules(rules)
    for label, sentences in found.items():
        st.markdown(f"*{label}*")
        for s in sentences or ["(not found in the text — check the platform's rules page)"]:
            st.markdown(f"> {s}")
    if st.button("Read the rules with AI", key="fj_rules_ai"):
        out = ai.complete(RULES_PROMPT.format(rules=ai.fence_untrusted(rules)), section="Portfolio")
        st.session_state["fj_rules_ai_text"] = out.text or (
            "No AI model is connected; the quoted sentences above are what the rules say.")
    if st.session_state.get("fj_rules_ai_text"):
        st.info(st.session_state["fj_rules_ai_text"])


def _price_panel(prob: float) -> None:
    c = st.columns(3)
    price = c[0].number_input("YES price (¢)", 0.0, 100.0, 62.0, 1.0, key="fj_price")
    fee = c[1].number_input("Fee per contract (¢, platform's current schedule)", 0.0, 20.0, 1.0,
                            0.5, key="fj_fee")
    be = forecast.break_even(price / 100, fee / 100)
    c[2].metric("Fee-adjusted break-even", f"{be:.0%}", f"your {prob:.0%}", delta_color="off")
    st.caption("A YES contract only pays off on average if the true chance is above the "
               "break-even. Computed in code; nothing is bought.")


def _resolve(disabled: bool) -> None:
    frame = forecast.journal_frame()
    if frame.is_empty():
        st.info("No forecasts yet.")
        return
    st.dataframe(frame.to_pandas(), hide_index=True, width="stretch")
    open_ = frame.filter(frame["outcome"].is_null()) if "outcome" in frame.columns else frame
    if open_.is_empty():
        return
    c = st.columns(3)
    fid = c[0].selectbox("Forecast", open_["id"].to_list(),
                         format_func=lambda i: f"#{i} · {open_.filter(open_['id'] == i)['question'][0][:50]}",
                         key="fj_resolve_id", disabled=disabled)
    outcome = c[1].radio("Outcome", ["Happened (1)", "Did not (0)"], key="fj_outcome",
                         disabled=disabled, horizontal=True)
    if c[2].button("Resolve", key="fj_resolve", disabled=disabled):
        forecast.resolve(int(fid), 1 if outcome.startswith("Happened") else 0)
        st.rerun()


def _score(card: forecast.Scorecard, key: str, title: str) -> None:
    if card.n == 0:
        st.caption("Brier score appears after the first resolved forecast.")
        return
    c = st.columns(3)
    c[0].metric("Resolved forecasts", card.n)
    c[1].metric("Brier score", f"{card.brier:.3f}", f"{card.brier - forecast.BASELINE:+.3f} vs 0.25",
                delta_color="inverse")
    c[2].metric("Coin-flip baseline", f"{forecast.BASELINE:.2f}")
    if not card.ready:
        st.caption(f"{card.n}/{forecast.MIN_FOR_CALIBRATION} resolved — the calibration chart "
                   "appears after 30.")
    else:
        bins = pd.DataFrame([b.__dict__ for b in card.bins()])
        diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(
            strokeDash=[4, 3], color="#94A3B8").encode(x="x:Q", y="y:Q")
        dots = alt.Chart(bins).mark_circle(color="#7C3AED").encode(
            x=alt.X("mean_prob:Q", title="Probability you gave", scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("hit_rate:Q", title="How often it happened", scale=alt.Scale(domain=[0, 1])),
            size=alt.Size("n:Q", legend=None), tooltip=["mean_prob", "hit_rate", "n"])
        st.altair_chart((diag + dots).properties(height=300, title=title), width="stretch")
    ui.ai_block(card, key, section="Portfolio", sensitive=True)


def render() -> None:
    """Forecast Journal."""
    ui.page_header("Forecast Journal", "Portfolio", "US only · forecasts, not positions")
    disabled = ui.market() == "IN"
    if disabled:
        st.warning(IN_NOTE)
    _add_forecast(disabled)
    st.markdown("#### Your journal")
    _resolve(disabled)
    _score(forecast.scorecard(), "fj_score", "Your calibration")
    with st.expander("Calibration lesson (synthetic journal of 160 forecasts)", expanded=disabled):
        _score(forecast.sample_journal(), "fj_sample", "Synthetic, deliberately overconfident")
    ui.paper_only_note()
