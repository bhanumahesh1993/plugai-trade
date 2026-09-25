"""Strategy › Trend Lab (Chapters 16, 18 and 24).

Presets *MA crossover*, *Time-series momentum* and *Rotation*; Volatility sizing
(sleeve, target vol, buffer, cap, Weekly check) with tiles computed in code;
Run; Parameter heatmap (tuning years vs unseen years, every cell a trial);
After-tax toggle; Send to Backtest Report; Send to Paper Desk (a *pending*
paper order that fills only after you click Accept there).
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl
import streamlit as st

from plugai_trade import backtest, reference
from plugai_trade.app import strategy_ui as sui
from plugai_trade.app import ui
from plugai_trade.backtest import Result, Spec
from plugai_trade.paper.pending import draft_pending

SECTION = "Strategy"
PRESETS = ["MA crossover", "Time-series momentum", "Rotation"]
CHECKS = {"Weekly": "weekly", "Daily": "daily", "Monthly": "monthly"}
FUTURES = "Back-adjusted futures (from Futures & Roll)"


def _ints(text: str) -> list[int]:
    out = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            out.append(int(part))
    return sorted(set(out))


def _futures_bars() -> pl.DataFrame | None:
    s = st.session_state.get("trend_lab_series")
    if s is None or "adjusted" not in getattr(s, "columns", []):
        return None
    px = pl.col("adjusted")
    return s.select("date", px.alias("open"), px.alias("high"), px.alias("low"),
                    px.alias("close"), pl.lit(0.0).alias("volume"),
                    pl.lit("futures back-adjusted").alias("source"))


# ------------------------------------------------------------------ sizing panel
def _sizing(mkt: str, bars: pl.DataFrame) -> dict[str, float]:
    """Volatility sizing inputs and tiles: realised vol, target exposure, units (rounded down)."""
    with st.container(border=True):
        st.markdown("**Volatility sizing**")
        c = st.columns(5)
        default = backtest.spec.DEFAULT_SLEEVE[mkt]
        sleeve = c[0].number_input("Sleeve", 1000.0, 1e9, default, step=10_000.0, key=f"tl_sleeve_{mkt}")
        target = c[1].number_input("Target vol % a year", 1.0, 60.0, 12.0, key="tl_tv")
        buffer = c[2].number_input("Buffer %", 0.0, 50.0, 10.0, key="tl_buf")
        cap = c[3].number_input("Cap %", 1.0, 100.0, 100.0, key="tl_cap",
                                help="100% = no borrowing")
        lookback = c[4].number_input("Vol lookback (sessions)", 5, 250, 20, key="tl_lb")
        close = bars["close"].to_numpy()
        r = close[-int(lookback):] / close[-int(lookback) - 1:-1] - 1
        dv = float(r.std(ddof=1)) if len(r) > 1 else float("nan")
        weight = min(cap / 100, (target / 100) / 16 / dv) if dv > 0 else 0.0
        price = float(close[-1])
        exposure = weight * sleeve
        units = math.floor(exposure / price) if price > 0 else 0
        t = st.columns(4)
        t[0].metric("Realised volatility", f"{dv * 16:.1%} a year", help=f"Daily move {dv:.2%}")
        t[1].metric("Target exposure", backtest.fmt_money(exposure, mkt), help=f"{weight:.0%} of sleeve")
        t[2].metric("Units (rounded down)", f"{units:,}")
        t[3].metric("Last close", f"{price:,.2f}")
        st.caption(f"Sleeve × {target:.0f}% ÷ 16 ÷ daily move {dv:.2%} = "
                   f"{backtest.fmt_money(sleeve * target / 100 / 16 / dv if dv > 0 else 0, mkt)}, "
                   f"capped at {cap:.0f}% of the sleeve, ÷ price, rounded down. Computed in code.")
    return {"sleeve": sleeve, "target": target / 100, "buffer": buffer / 100, "cap": cap / 100,
            "lookback": int(lookback)}


def _costs(mkt: str, key: str, futures: bool = False) -> tuple[str, float]:
    c1, c2 = st.columns(2)
    profiles = sui.PROFILES[mkt]
    idx = profiles.index("IN-futures") if futures and "IN-futures" in profiles else 0
    prof = c1.selectbox("Costs", profiles, index=idx, key=f"{key}_prof")
    slip = c2.number_input("Slippage % a side", 0.0, 2.0,
                           backtest.spec.DEFAULT_SLIPPAGE_PCT[mkt], 0.01, format="%.2f",
                           key=f"{key}_slip")
    return prof, slip


# ------------------------------------------------------------------ results
def _result_block(res: Result, key: str, spec: Spec) -> None:
    if res.spec.digest() != spec.digest():
        st.caption("Settings changed since this run — click Run to test the new version.")
    sui.summary_tiles(res)
    extra: dict[str, Any] = {}
    if st.toggle("After-tax", key=f"{key}_tax"):
        bracket = None
        if res.market == "US":
            bracket = st.number_input("Your short-term (ordinary income) rate %", 0.0, 50.0, 24.0,
                                      key=f"{key}_bracket") / 100
        tax = res.after_tax(short_rate=bracket)
        extra["rule, after costs and tax"] = tax["equity"] * 100 / res.capital
        c = st.columns(3)
        c[0].metric("Tax paid (all years)", res.money(tax["total_tax"]))
        c[1].metric("After costs and tax", f"{tax['after_tax_return'] * 100:+.1f}%")
        c[2].metric("Rates used", f"{tax['short_rate']:.0%} short · {tax['long_rate']:.1%} long")
        src = "your rate (assumed)" if tax["short_rate_assumed"] else "the dated tax table"
        st.caption(f"Short-term rate from {src}; long-term from the dated tax table "
                   f"({reference.as_of()}). Losses offset gains within a year; carry-forward not "
                   "modelled. Buy-and-hold never sells, so it pays no tax here.")
    sui.equity_chart(res, extra=extra)
    sui.drawdown_chart(res)


def _heatmap(spec: Spec, bars: Any, profile: str, key: str, rows: tuple[str, str, str],
             cols: tuple[str, str, str] | None, skip=None) -> None:
    with st.expander("Parameter heatmap", expanded=bool(st.session_state.get(f"{key}_hm"))):
        c = st.columns(3)
        rtxt = c[0].text_input(rows[1], rows[2], key=f"{key}_rows")
        ctxt = c[1].text_input(cols[1], cols[2], key=f"{key}_cols") if cols else ""
        split = c[2].slider("Tuning share of the years", 0.5, 0.85, 2 / 3, 0.05, key=f"{key}_split")
        st.caption("Every cell is one trial. Look at the whole map before any single cell, and "
                   "do not sweep again around a bright corner.")
        if st.button("Sweep", key=f"{key}_sweep"):
            with st.spinner("Running every setting…"):
                st.session_state[f"{key}_hm"] = backtest.heatmap(
                    spec, bars, rows=(rows[0], _ints(rtxt)),
                    cols=(cols[0], _ints(ctxt)) if cols else None, costs=profile, split=split,
                    skip=skip)
            st.rerun()
        hm = st.session_state.get(f"{key}_hm")
        if hm is not None:
            sui.heatmap_chart(hm)
            st.code(hm.text(), language=None)
            ui.ai_block(hm, f"{key}_hm_ai", SECTION,
                        question="Is the tuning grid a broad plateau or a lone peak? Describe "
                                 "only what is in the grids.")


def _send(res: Result | None, key: str) -> None:
    c1, c2 = st.columns(2)
    if c1.button("Send to Backtest Report", key=f"{key}_send_bt", disabled=res is None):
        res.save(tag="trend_lab")
        st.session_state["bt_result"] = res
        st.success("Sent. Open Strategy › Backtest Report for costs, walk-forward and the Report "
                   "Card, which counts every trial.")
    if c2.button("Send to Paper Desk", key=f"{key}_send_pd", disabled=res is None):
        orders = res.next_orders()
        grade = res.card().grade
        if not orders:
            st.info("At the latest completed bar the rule says hold nothing, so no paper order "
                    "was drafted. Check again after the next weekly close.")
        for o in orders:
            o["note"] = (f"Trend Lab · {res.spec.read_back()} · Report Card: {grade} · "
                         f"fills at the next session's open after you Accept")
            draft_pending(o, source="Trend Lab")
        if orders:
            st.success(f"{len(orders)} pending paper order(s) drafted in Paper Trading › Paper "
                       "Desk. Nothing fills until you click Accept there.")
    ui.paper_only_note()


# ------------------------------------------------------------------ presets
def _trend(mkt: str, preset: str) -> None:
    c1, c2, c3 = st.columns([1.3, 1, 1.4])
    options = sui.INSTRUMENTS[mkt] + ([FUTURES] if _futures_bars() is not None else [])
    symbol = c1.selectbox("Instrument", options, key=f"tl_sym_{mkt}")
    years = c2.number_input("Years", 3, 15, 15, key="tl_years")
    with c3:
        synthetic = sui.data_choice("tl_data")
    futures = symbol == FUTURES
    bars = _futures_bars() if futures else sui.load_bars(symbol, mkt, int(years), synthetic)
    name = "FUT (back-adjusted)" if futures else symbol
    c1, c2, c3 = st.columns(3)
    if preset == "MA crossover":
        fast = c1.number_input("Fast average (days)", 2, 400, 50, key="tl_fast")
        slow = c2.number_input("Slow average (days)", 3, 600, 200, key="tl_slow")
    else:
        months = c1.number_input("Lookback (months)", 1, 36, 12, key="tl_months")
    check = CHECKS[c3.radio("Check", list(CHECKS), horizontal=True, key="tl_check")]
    size = _sizing(mkt, bars)
    profile, slip = _costs(mkt, "tl", futures)
    kw = {"check": check, "target_vol": size["target"], "buffer": size["buffer"],
          "cap": size["cap"], "sleeve": size["sleeve"]}
    if preset == "MA crossover":
        if fast >= slow:
            st.error("The fast average must be shorter than the slow one.")
            return
        spec = backtest.ma_crossover(int(fast), int(slow), **kw)
    else:
        spec = backtest.ts_momentum(int(months), **kw)
    spec.size.vol_lookback = size["lookback"]
    spec.cost.profile, spec.cost.slippage_pct, spec.market = profile, slip, mkt
    st.caption("Read back: " + spec.read_back())
    key = "tl_ma" if preset == "MA crossover" else "tl_ts"
    b1, b2 = st.columns([1, 3])
    if b1.button("Run", key=f"{key}_run", type="primary"):
        st.session_state[key] = backtest.run(spec, bars, costs=profile, symbol=name)
        st.rerun()
    b2.metric("Trials", backtest.trials.count(spec.family_key()))
    res = st.session_state.get(key)
    if res is not None:
        _result_block(res, key, spec)
    if preset == "MA crossover":
        _heatmap(spec, bars, profile, key, ("entry.0.left.n", "Fast (days)", "10, 20, 30, 50, 75, 100"),
                 ("entry.0.right.n", "Slow (days)", "100, 150, 200, 250, 300"),
                 skip=lambda a, b: a >= b)
    else:
        _heatmap(spec, bars, profile, key,
                 ("entry.0.right.n", "Lookback (sessions)", "63, 126, 189, 252, 378, 504"), None)
    _send(res, key)
    if res is not None:
        ui.ai_block(res, f"{key}_ai", SECTION)


def _rotation(mkt: str) -> None:
    sectors = sui.SECTORS[mkt]
    universe = st.multiselect("Universe", sectors, default=sectors, key=f"tl_uni_{mkt}")
    c = st.columns(4)
    lookback = c[0].number_input("Lookback (months)", 1, 24, 6, key="tl_rlb")
    top = c[1].number_input("Top N", 1, 10, 2, key="tl_top")
    years = c[2].number_input("Years", 3, 15, 15, key="tl_ryears")
    with c[3]:
        synthetic = sui.data_choice("tl_rdata")
    st.caption("Rebalance & costs: monthly, after the last session's close; switches fill at the "
               f"next open. Benchmark: equal weight, all {len(universe)}, bought once and held.")
    profile, slip = _costs(mkt, "tl_rot")
    if len(universe) < 2 or top >= len(universe):
        st.error("Choose at least two instruments and a Top N smaller than the universe.")
        return
    bars = {s: sui.load_bars(s, mkt, int(years), synthetic) for s in universe}
    spec = backtest.rotation(universe, int(lookback), int(top), slippage_pct=slip)
    spec.cost.profile, spec.market = profile, mkt
    st.caption("Read back: " + spec.read_back())
    b1, b2 = st.columns([1, 3])
    if b1.button("Run", key="tl_rot_run", type="primary"):
        st.session_state["tl_rot"] = backtest.run(spec, bars, costs=profile)
        st.rerun()
    b2.metric("Trials", backtest.trials.count(spec.family_key()))
    res = st.session_state.get("tl_rot")
    if res is not None:
        _result_block(res, "tl_rot", spec)
    _heatmap(spec, bars, profile, "tl_rot", ("lookback_months", "Lookback (months)", "3, 6, 9, 12"),
             ("top_n", "Top N", "1, 2, 3"))
    _send(res, "tl_rot")
    if res is not None:
        ui.ai_block(res, "tl_rot_ai", SECTION)


def render() -> None:
    ui.page_header("Trend Lab", SECTION, "Signal → size → buffer → weekly clock. All results are "
                                         "HYPOTHETICAL.")
    mkt = ui.market()
    preset = st.segmented_control("Preset", PRESETS, default=PRESETS[0], key="tl_preset")
    if preset == "Rotation":
        _rotation(mkt)
    else:
        _trend(mkt, preset or PRESETS[0])
