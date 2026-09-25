"""Shared pieces for the Strategy screens: data loading, HYPOTHETICAL charts, the Report Card.

Used by Strategy Builder, Backtest Report and Trend Lab. Every number drawn
here was computed by ``plugai_trade.backtest``; charts only display it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import altair as alt
import pandas as pd
import polars as pl
import streamlit as st

from .. import data
from ..backtest import Heatmap, ReportCard, Result
from . import ui

INSTRUMENTS = {"IN": ["NIFTY", "BANKNIFTY", "SENSEX", "SYN-A"], "US": ["SPY", "QQQ", "DIA", "IWM"]}
SECTORS = {
    "IN": ["NIFTYIT", "NIFTYBANK", "NIFTYFMCG", "NIFTYPHARMA", "NIFTYAUTO", "NIFTYMETAL",
           "NIFTYENERGY", "NIFTYREALTY"],
    "US": ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"],
}
PROFILES = {"IN": ["IN-equity-delivery", "IN-equity-intraday", "IN-futures"], "US": ["US-equity"]}
TEST_END = date(2025, 12, 31)
GRADE_COLOUR = {"Robust": "green", "Fragile": "orange", "Likely overfit": "red"}


@st.cache_data(show_spinner=False)
def cached_bars(symbol: str, market: str, start: date, end: date, source: str | None
                ) -> pl.DataFrame:
    """Bars for a fixed window, cached per session so reruns stay fast."""
    return data.get(symbol, market=market, start=start, end=end, source=source)


def load_bars(symbol: str, market: str, years: int, synthetic: bool = True,
              end: date = TEST_END) -> pl.DataFrame:
    """Daily bars for a test; falls back to synthetic (with a message) if a free source fails."""
    start = date(end.year - years + 1, 1, 1)
    try:
        df = cached_bars(symbol, market, start, end, "synthetic" if synthetic else None)
    except data.DataUnavailable as exc:
        st.warning(f"{exc} — using synthetic data instead.")
        df = cached_bars(symbol, market, start, end, "synthetic")
    ui.set_data_status(df)
    return df


def data_choice(key: str) -> bool:
    """The Synthetic / Free source choice. Returns True for synthetic."""
    choice = st.radio("Data", ["Synthetic", "Free source"], horizontal=True, key=key,
                      help="Synthetic is offline and matches the book. Free source uses the order "
                           "in Settings › Data Sources and falls back to synthetic.")
    return choice == "Synthetic"


# ------------------------------------------------------------------ charts
def equity_chart(res: Result, extra: dict[str, Any] | None = None, gross: bool = False,
                 height: int = 260) -> None:
    """Equity after costs and buy-and-hold (and optional lines), scaled to 100. HYPOTHETICAL."""
    f = res.frame(gross=gross).to_pandas()
    cols = {"equity": "rule, after costs", "buy_and_hold": "buy and hold"}
    if gross:
        cols["before_costs"] = "rule, before costs"
    long = f.rename(columns=cols).melt("date", list(cols.values()), var_name="series",
                                      value_name="value")
    if extra:
        for name, values in extra.items():
            long = pd.concat([long, pd.DataFrame({"date": f["date"], "series": name,
                                                  "value": values})])
    ch = alt.Chart(long).mark_line().encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("value:Q", title="Start = 100", scale=alt.Scale(zero=False)),
        color=alt.Color("series:N", legend=alt.Legend(orient="bottom", title=None)),
        strokeDash=alt.condition(alt.datum.series == "buy and hold", alt.value([4, 3]),
                                 alt.value([1, 0])),
        tooltip=["date:T", "series:N", alt.Tooltip("value:Q", format=",.1f")],
    ).properties(height=height)
    st.altair_chart(ui.hypothetical_chart(ch), width="stretch")


def drawdown_chart(res: Result, height: int = 140) -> None:
    """Drawdown of the rule (area) and of buy-and-hold (dashed). Hover shows depth and date."""
    f = res.frame().to_pandas()
    area = alt.Chart(f).mark_area(color="#DC2626", opacity=0.35).encode(
        x=alt.X("date:T", title=None), y=alt.Y("drawdown:Q", title="Drawdown %"),
        tooltip=[alt.Tooltip("date:T"), alt.Tooltip("drawdown:Q", format=".1f", title="depth %")])
    bh = alt.Chart(f).mark_line(color="#64748B", strokeDash=[3, 3]).encode(
        x="date:T", y="bh_drawdown:Q")
    st.altair_chart(ui.hypothetical_chart(alt.layer(area, bh).properties(height=height)),
                    width="stretch")
    story = res.drawdown_story()
    if story["start"]:
        rec = f"recovered {story['recovered']}" if story["recovered"] else "not yet recovered"
        st.caption(f"Deepest drawdown {story['depth'] * 100:.1f}% · began {story['start']} · "
                   f"bottom {story['trough']} · {story['months_below']} months below the earlier "
                   f"high ({rec}). Buy-and-hold worst: {res.stats()['bh_max_drawdown'] * 100:.1f}%.")


def summary_tiles(res: Result) -> None:
    """The first table a Backtest Report shows (Chapter 11), as tiles."""
    s, g = res.stats(), res.gross_stats()
    c = st.columns(4)
    c[0].metric("Round trips", s["round_trips"],
                help=f"Winning: {s['winners']}" + (f" ({s['winners'] / s['round_trips']:.1%})"
                                                   if s["round_trips"] else ""))
    c[1].metric("After costs", f"{s['total_return'] * 100:+.1f}%",
                delta=f"before costs {g['total_return'] * 100:+.1f}%", delta_color="off")
    c[2].metric("Worst drawdown", f"{s['max_drawdown'] * 100:.1f}%")
    c[3].metric("Buy and hold", f"{s['bh_return'] * 100:+.1f}%")
    c = st.columns(4)
    c[0].metric("Charges / fees", res.money(s["charges"]))
    c[1].metric("Assumed slippage", res.money(s["slippage"]))
    c[2].metric("Sharpe (after costs)", f"{s['sharpe']:.2f}")
    c[3].metric("Trials", res.trial_count())


def report_card(card: ReportCard) -> None:
    """Grade, the line that explains it, the six checks and the separate warnings."""
    colour = GRADE_COLOUR.get(card.grade, "gray")
    st.markdown(f"#### Report Card: :{colour}-badge[{card.grade}]")
    st.caption(f"Why: {card.reason}")
    st.markdown(f"**Sharpe {card.sharpe:.2f}** · trial-adjusted (deflated) **{card.deflated_sharpe:.2f}** "
                f"· Trials: {card.trials} · probability the true Sharpe beats the best of "
                f"{card.trials} tries on noise: {card.dsr_probability:.0%}")
    mark = {"pass": "✓", "fail": "✗", "warn": "!", "info": "·"}
    st.dataframe(pd.DataFrame([{"": mark[c.status], "Check": c.name, "What the lab measured":
                                c.measured, "Pulls the grade to": c.pulls_to if c.status in
                                ("fail", "warn") else ""} for c in card.checks]),
                 hide_index=True, width="stretch")
    for w in card.warnings:
        st.warning(w)
    st.caption("The grade is about the test, not the idea. Not a forecast; not a recommendation.")


def heatmap_chart(hm: Heatmap, height: int = 220) -> None:
    """Tuning years and unseen years side by side; the setting chosen before the test is outlined."""
    recs = []
    for panel, grid in (("Tuning years", hm.tuning), ("Unseen years", hm.unseen)):
        for i, r in enumerate(hm.rows):
            for j, c in enumerate(hm.cols):
                v = grid[i][j]
                recs.append({"panel": panel, "row": str(r), "col": str(c) if hm.col_label else "—",
                             "sharpe": v, "label": "—" if v is None else f"{v:.2f}",
                             "mine": hm.base is not None and (r, c) == hm.base})
    df = pd.DataFrame(recs)
    base = alt.Chart(df).encode(
        x=alt.X("col:O", title=hm.col_label or None, sort=[str(c) for c in hm.cols]),
        y=alt.Y("row:O", title=hm.row_label, sort=[str(r) for r in hm.rows]))
    rect = base.mark_rect().encode(
        color=alt.Color("sharpe:Q", scale=alt.Scale(scheme="blueorange", domainMid=0),
                        title="Sharpe"),
        stroke=alt.condition(alt.datum.mine, alt.value("#111827"), alt.value(None)),
        strokeWidth=alt.condition(alt.datum.mine, alt.value(2.5), alt.value(0)))
    text = base.mark_text(fontSize=11).encode(text="label:N")
    ch = alt.layer(rect, text, data=df).properties(width=260, height=height).facet(
        column=alt.Column("panel:N", title=None, sort=["Tuning years", "Unseen years"]))
    st.altair_chart(ch)
    st.caption(f"Split at {hm.split_date}. Buy-and-hold Sharpe {hm.benchmark_tuning:.2f} tuning, "
               f"{hm.benchmark_unseen:.2f} unseen. {hm.cells} settings = {hm.cells} trials; the "
               "family counter now reads "
               f"{hm.trials}. Look for a plateau, not a lone bright cell. HYPOTHETICAL.")


def trades_table(res: Result) -> None:
    tf = res.trade_frame()
    if tf.is_empty():
        st.info("No trades in this period.")
        return
    keep = ["symbol", "entry_date", "exit_date", "bars", "units", "buy_value", "sell_value",
            "gross_pnl", "charges", "slippage", "net_pnl", "return_pct", "open"]
    st.dataframe(tf.select([c for c in keep if c in tf.columns]).to_pandas(), hide_index=True,
                 width="stretch")
