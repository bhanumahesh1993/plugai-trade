"""Strategy › Backtest Report (Chapters 11 and 18).

Equity curve + drawdown (HYPOTHETICAL, with the buy-and-hold line), Costs
(delivery / intraday toggle, or the spread assumption in the US), Walk-forward,
Trades, and the Report Card: Robust / Fragile / Likely overfit, with the
trial-adjusted (deflated) score, survivorship warning and training-cutoff guard.
"""

from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import backtest, reference
from plugai_trade.app import strategy_ui as sui
from plugai_trade.app import ui
from plugai_trade.backtest import Result, Spec
from plugai_trade.store import default as store

SECTION = "Strategy"
SAMPLE_RULE = ("Buy at the next open on the first close above the 50-day average; sell at the "
               "next open when the close is below the 20-day average")
COST_LABELS = {"IN": {"Delivery": "IN-equity-delivery", "Intraday": "IN-equity-intraday",
                      "Futures": "IN-futures"}}


def _from_saved(row: dict) -> Result:
    """Rebuild a saved report from its spec and data window (re-running is not a new trial)."""
    spec = Spec.from_dict(row["spec"])
    start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
    synthetic = row.get("source") == "synthetic"
    bars = {s: sui.cached_bars(s, row["market"], start, end, "synthetic" if synthetic else None)
            for s in row.get("symbols") or [row["symbol"]]}
    return backtest.run(spec, bars, costs=row["profile"], count_trial=False)


def _pick_result() -> Result | None:
    res = st.session_state.get("bt_result")
    saved = store().all("backtests", limit=30)
    if saved:
        labels = {f"#{r['id']} · {r['symbol']} · {r['report']['grade']} · {r['created'][:16]}": r
                  for r in saved}
        choice = st.selectbox("Saved reports", ["(current)", *labels], key="btr_saved")
        if choice != "(current)":
            key = f"btr_loaded_{labels[choice]['id']}"
            if key not in st.session_state:
                st.session_state[key] = _from_saved(labels[choice])
            return st.session_state[key]
    if res is None:
        st.info("No backtest yet. Build one in Strategy › Strategy Builder or Trend Lab, or run "
                "the Lesson 11 sample rule on synthetic data.")
        if st.button("Run sample rule", key="btr_sample"):
            bars = sui.load_bars("NIFTY" if ui.market() == "IN" else "SPY", ui.market(), 5)
            prof = "IN-equity-delivery" if ui.market() == "IN" else "US-equity"
            res = backtest.run(SAMPLE_RULE, bars, costs=prof,
                               symbol="NIFTY" if ui.market() == "IN" else "SPY")
            res.save(tag="sample")
            st.session_state["bt_result"] = res
            st.rerun()
    return res


def _costs_tab(res: Result) -> None:
    st.caption("Re-prices the same rule. Not a new trial: the rule did not change.")
    if res.market == "IN":
        labels = COST_LABELS["IN"]
        cur = next((k for k, v in labels.items() if v == res.profile), "Delivery")
        pick = st.segmented_control("Cost profile", list(labels), default=cur, key="btr_prof")
        profile, slip = labels.get(pick or cur, res.profile), None
    else:
        profile = res.profile
        slip = st.number_input("Spread + slippage % a side", 0.0, 1.0,
                               float(res.spec.cost.slippage_pct or 0.02), 0.01, format="%.2f",
                               key="btr_spread")
    alt_res = res if profile == res.profile and slip in (None, res.spec.cost.slippage_pct) \
        else res.with_costs(profile, slip)
    sui.equity_chart(alt_res, gross=True)
    s = alt_res.stats()
    items: dict[str, float] = {}
    for f in alt_res.fills:
        for k, v in (f.get("items") or {}).items():
            items[k] = items.get(k, 0.0) + v
    items["slippage (assumed)"] = s["slippage"]
    rows = [{"Item": k, "Amount": alt_res.money(v)} for k, v in items.items() if v]
    rows.append({"Item": "Total", "Amount": alt_res.money(s["charges"] + s["slippage"])})
    c1, c2 = st.columns([1, 1.3])
    c1.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    g = alt_res.gross_stats()
    c2.metric("Before costs", f"{g['total_return'] * 100:+.1f}%")
    c2.metric("After costs", f"{s['total_return'] * 100:+.1f}%")
    c2.caption(f"{alt_res.profile} · charges from the dated tables ({reference.as_of()}); "
               "slippage is an assumption you can change on the SIZE · COST card.")


def _walk_forward_tab(res: Result) -> None:
    wf = res.walk_forward()
    if not wf.windows:
        st.info("Too little history for walk-forward windows (needs 2 years to choose + 6 months "
                "to score). Test a longer period.")
        return
    st.caption(f"{len(wf.windows)} windows: settings chosen on 2 years from {wf.variants} nearby "
               "variants, then scored on the next 6 months that the choice never saw.")
    c = st.columns(3)
    c[0].metric("Sharpe, choosing windows", f"{wf.in_sample_sharpe:.2f}")
    c[1].metric("Sharpe, unseen windows", f"{wf.oos_sharpe:.2f}")
    c[2].metric("Result, unseen windows", f"{wf.oos_return * 100:+.1f}%")
    st.dataframe(pd.DataFrame(wf.windows), hide_index=True, width="stretch")
    df = pd.DataFrame({"date": pd.to_datetime(wf.oos_dates), "unseen record": wf.oos_equity})
    ch = alt.Chart(df).mark_line(color="#D97706").encode(
        x=alt.X("date:T", title=None), y=alt.Y("unseen record:Q", scale=alt.Scale(zero=False)))
    st.altair_chart(ui.hypothetical_chart(ch.properties(height=200)), width="stretch")


def _accept(res: Result):
    def save(text: str) -> None:
        card = res.card()
        store().add("journal", {"kind": "backtest_report", "read_back": res.spec.read_back(),
                                "rule_cards": res.spec.cards(), "spec": res.spec.to_dict(),
                                "grade": card.grade, "report": card.to_dict(),
                                "ai_note": text, "symbol": res.symbol, "market": res.market},
                    tag="backtest")
        res.save(tag="accepted")
    return save


def render() -> None:
    ui.page_header("Backtest Report", SECTION, "All results are HYPOTHETICAL.")
    res = _pick_result()
    if res is None:
        return
    st.markdown(f"**{res.symbol}** · {res.source} · {res.dates[0]} to {res.dates[-1]} · "
                f"{res.profile}")
    st.caption(res.spec.read_back())
    sui.summary_tiles(res)
    tabs = st.tabs(["Equity & drawdown", "Costs", "Walk-forward", "Trades", "Report Card"])
    with tabs[0]:
        sui.equity_chart(res)
        sui.drawdown_chart(res)
    with tabs[1]:
        _costs_tab(res)
    with tabs[2]:
        _walk_forward_tab(res)
    with tabs[3]:
        sui.trades_table(res)
    card = res.card()
    with tabs[4]:
        sui.report_card(card)
    st.markdown(f"**Trials: {card.trials}** · Sharpe {card.sharpe:.2f} · trial-adjusted "
                f"{card.deflated_sharpe:.2f} · grade **{card.grade}**")
    ui.ai_block(res, "btr_ai", SECTION, on_accept=_accept(res))
