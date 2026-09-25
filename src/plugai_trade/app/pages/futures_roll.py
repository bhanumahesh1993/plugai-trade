"""Derivatives › Futures & Roll (Chapter 24)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import futures
from plugai_trade.app import ui
from plugai_trade.options.chain import fmt_money, fmt_num

_DEFAULT = {"IN": "NIFTY", "US": "MES"}
_CHOICES = {"IN": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "USDINR", "CRUDEOIL",
                   "CRUDEOILM", "GOLD"],
            "US": ["MES", "MNQ", "MCL", "MGC", "ES", "CL"]}


@dataclass
class _Facts:
    lines: list[str]

    def facts(self) -> list[str]:
        return self.lines


def _contracts(mkt: str) -> list[str]:
    key = f"fr_contracts_{mkt}"
    if key not in st.session_state:
        st.session_state[key] = [_DEFAULT[mkt]]
    return st.session_state[key]


def _spot_of(symbol: str, mkt: str) -> float:
    from plugai_trade import data

    base = symbol if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY") else (
        "SPY" if symbol in ("MES", "ES") else symbol)
    px = float(data.get(base, market=mkt, source="synthetic")["close"][-1])
    return px * 10 if symbol in ("MES", "ES") else px


# ---------------------------------------------------------------- Contract tab
def _contract_tab(mkt: str) -> list[str]:
    names = _contracts(mkt)
    c1, c2 = st.columns([2, 1])
    pick = c1.selectbox("Contract", [s for s in _CHOICES[mkt] if s not in names] or _CHOICES[mkt],
                        key=f"fr_pick_{mkt}")
    if c2.button("Add contract") and pick not in names:
        names.append(pick)
        st.rerun()
    facts: list[str] = []
    rows = []
    for sym in names:
        sp = futures.spec(sym)
        rows.append({"Contract": f"{sym} FUT", "Exchange": sp.exchange,
                     "Lot / multiplier": fmt_num(sp.multiplier, sp.market), "Unit": sp.unit,
                     "Settlement": sp.settlement, "Expiry": sp.expiry, "Source": sp.source})
        facts.append(f"{sym}: {fmt_num(sp.multiplier, sp.market)} per {sp.unit}, "
                     f"{sp.settlement}-settled, expiry {sp.expiry} ({sp.source})")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.markdown("**OI build-up**")
    oi = futures.oi_snapshot(names)
    st.dataframe(oi.to_pandas(), hide_index=True, width="stretch")
    st.caption("Labels describe one day's activity (synthetic OI) — they are not signals. "
               "Near month falling while next month rises usually means a roll.")
    facts += [f"{r['contract']}: price {r['price_change_pct']:+.2f}%, near OI "
              f"{r['oi_change_near_pct']:+.2f}%, next OI {r['oi_change_next_pct']:+.2f}% → "
              f"{r['label']}; {r['roll_check']}" for r in oi.iter_rows(named=True)]

    mcx = [s for s in names if futures.spec(s).exchange == "MCX"]
    if mkt == "IN" and st.button("USDINR split", disabled=not mcx,
                                 help="Add an MCX contract (e.g. CRUDEOIL) first."):
        st.session_state["fr_split_on"] = True
    if mkt == "IN" and mcx and st.session_state.get("fr_split_on"):
        facts += _usdinr_split(mcx[0])
    return facts


def _usdinr_split(symbol: str) -> list[str]:
    st.markdown(f"**USDINR split** · {symbol}")
    c = st.columns(4)
    b0 = c[0].number_input("Benchmark yesterday ($)", value=70.0, key="fr_b0")
    b1 = c[1].number_input("Benchmark today ($)", value=70.0, key="fr_b1")
    f0 = c[2].number_input("USDINR yesterday", value=88.00, key="fr_f0", format="%.2f")
    f1 = c[3].number_input("USDINR today", value=88.80, key="fr_f1", format="%.2f")
    sp = futures.usdinr_split(b0, b1, f0, f1, symbol=symbol)
    m = st.columns(3)
    m[0].metric("Benchmark part / lot", fmt_money(sp.benchmark_part * sp.units, "IN"))
    m[1].metric("Currency part / lot", fmt_money(sp.currency_part * sp.units, "IN"))
    m[2].metric("Rupee price", f"{fmt_money(sp.inr_from, 'IN')} → {fmt_money(sp.inr_to, 'IN')}")
    st.caption("Computed in code. Import duty and local premium sit in real MCX prices too.")
    return sp.facts()


# ---------------------------------------------------------------- Basis tab
def _basis_tab(mkt: str) -> list[str]:
    sym = st.selectbox("Index", ["NIFTY", "BANKNIFTY"] if mkt == "IN" else ["SPY"], key="fr_basis_sym")
    c1, c2 = st.columns(2)
    rate = c1.number_input("Interest rate %", value=6.5 if mkt == "IN" else 4.0, step=0.1) / 100
    div = c2.number_input("Dividend yield %", value=1.3, step=0.1) / 100
    df = futures.basis_series(sym, rate=rate, dividend_yield=div, market=mkt).to_pandas()
    top = df.melt("date", ["spot", "futures"], var_name="series", value_name="price")
    st.altair_chart(alt.Chart(top).mark_line().encode(
        x=alt.X("date:T", title=None), y=alt.Y("price:Q", scale=alt.Scale(zero=False), title=None),
        color="series:N").properties(height=200), width="stretch")
    bot = df.melt("date", ["basis", "fair_basis"], var_name="series", value_name="points")
    st.altair_chart(alt.Chart(bot).mark_line().encode(
        x=alt.X("date:T", title=None), y=alt.Y("points:Q", title="basis (pts)"),
        color="series:N").properties(height=160), width="stretch")
    last = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
    label = futures.basis_label(last["basis"], last["fair_basis"])
    st.caption(f"Synthetic convergence; fair basis = spot × ({rate * 100:.1f}% − {div * 100:.1f}%) "
               f"× days left ÷ 365. Yesterday: basis {last['basis']:.1f} vs fair "
               f"{last['fair_basis']:.1f} → {label} (a description, not a signal).")
    spot = float(df["spot"].iloc[-1])
    rows = []
    for exp in futures.expiries(sym if mkt == "IN" else "MES", 3):
        days = (exp - date.today()).days
        fv = futures.fair_value(spot, days, rate, div)
        rows.append({"Expiry": exp.isoformat(), "Days": days, "Spot": round(spot, 2),
                     "Fair value": round(fv, 2), "Fair basis": round(fv - spot, 2)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    return [f"{r['Expiry']}: fair value {r['Fair value']:,.2f}, fair basis {r['Fair basis']:+.2f} "
            f"({r['Days']} days)" for r in rows] + [f"Latest basis reading: {label}"]


# ---------------------------------------------------------------- Roll calendar tab
def _roll_tab(mkt: str) -> list[str]:
    sym = st.selectbox("Contract", ["NIFTY", "BANKNIFTY"] if mkt == "IN" else ["MES", "MNQ"],
                       key="fr_roll_sym")
    exps = futures.expiries(sym, 3)
    before = st.slider("Roll window opens (sessions before expiry)", 1, 10, 5, key="fr_before")
    rows = []
    for e in exps:
        w0, w1 = futures.roll_window(e, before)
        rows.append({"Contract": f"{sym} {e:%b %Y}", "Expiry / last trading day": e.isoformat(),
                     "Roll window": f"{w0:%d %b} – {w1:%d %b}"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("India: last Tuesday of the month; US micros: third Friday of Mar/Jun/Sep/Dec. "
               "Holiday shifts apply when the reference tables carry a holiday list.")
    base = _spot_of(sym, mkt)
    c = st.columns(4)
    spot = c[0].number_input("Spot", value=round(base, 2), key="fr_r_spot")
    near = c[1].number_input("Near price", value=round(futures.fair_value(base, before), 2), key="fr_r_near")
    nxt = c[2].number_input("Next price", value=round(futures.fair_value(base, before + 28), 2), key="fr_r_next")
    slip = c[3].number_input("Slippage (pts per leg)", value=0.0, step=0.25, key="fr_r_slip")
    plan = futures.roll_cost(sym, near, nxt, spot, days_near=before, slippage_points=slip)
    m = st.columns(3)
    m[0].metric("Calendar spread", f"{plan.spread:+,.2f} pts")
    m[1].metric("Fair spread", f"{plan.fair_spread:+,.2f} pts")
    m[2].metric("Roll cost", fmt_money(plan.costs["total"], mkt, 2))
    st.dataframe(pd.DataFrame([{"Item": k, "Amount": v} for k, v in plan.costs.items()]),
                 hide_index=True, width="stretch")
    b1, b2 = st.columns(2)
    if b1.button("Set roll alert"):
        w0, _ = futures.roll_window(exps[0], before)
        ui.lab_store().add("alerts", {"label": "SIMULATED", "kind": "roll",
                                      "text": f"Roll window opens for {sym} {exps[0]:%b %Y}",
                                      "date": w0.isoformat(), "symbol": sym}, tag="roll")
        st.success(f"Alert set for {w0:%d %b %Y} in Paper Trading › Alerts (SIMULATED).")
    if b2.button("Send to Trend Lab"):
        series = futures.contract_series(sym, market=mkt, roll_days_before=before)
        st.session_state["trend_lab_series"] = series
        ui.lab_store().add("notes", {"screen": "Futures & Roll", "kind": "back_adjusted_series",
                                     "symbol": sym, "rows": series.height,
                                     "roll_dates": [d.isoformat() for d in
                                                    series.filter(series["roll"])["date"].to_list()]},
                           tag="trend_lab")
        st.success("Back-adjusted series and roll dates sent to Trend Lab.")
    series = futures.contract_series(sym, market=mkt, roll_days_before=before).to_pandas()
    long = series.melt("date", ["joined", "adjusted"], var_name="series", value_name="price")
    st.altair_chart(alt.Chart(long).mark_line().encode(
        x=alt.X("date:T", title=None), y=alt.Y("price:Q", scale=alt.Scale(zero=False), title=None),
        color="series:N").properties(height=200), width="stretch")
    st.caption("Joined end to end vs back-adjusted (difference method): the adjusted line has no "
               "roll-day jump for a trend rule to mistake for a move.")
    return plan.facts() + [f"{r['Contract']}: expiry {r['Expiry / last trading day']}, window "
                           f"{r['Roll window']}" for r in rows]


# ---------------------------------------------------------------- Margin & MTM tab
def _margin_tab(mkt: str) -> list[str]:
    sym = st.selectbox("Contract", ["NIFTY", "BANKNIFTY", "CRUDEOIL"] if mkt == "IN"
                       else ["MES", "MNQ", "MCL"], key="fr_m_sym")
    book = futures.BOOK_PATHS.get(sym, {})
    sp = futures.spec(sym)
    c = st.columns(4)
    entry = c[0].number_input("Entry price", value=float(book.get("entry", round(_spot_of(sym, mkt), 2))),
                              key=f"fr_m_entry_{sym}")
    cash = c[1].number_input("Account cash", value=float(book.get("cash", 0.25 * entry * sp.multiplier)),
                             key=f"fr_m_cash_{sym}")
    qty = int(c[2].number_input("Contracts", 1, 50, 1, key="fr_m_qty"))
    side = c[3].selectbox("Side", ["long", "short"], key="fr_m_side")
    if mkt == "IN":
        rate = st.number_input("Margin % of notional (illustrative)", value=12.0, step=0.5) / 100
        init = maint = None
    else:
        d1, d2 = st.columns(2)
        init = d1.number_input("Initial margin / contract", value=float(book.get("initial", 0.08 * entry * sp.multiplier)))
        maint = d2.number_input("Maintenance / contract", value=float(book.get("maintenance", 0.9 * init)))
        rate = None
    src = st.radio("Path", ["Book sample (Ch 24)", "Synthetic"] if book else ["Synthetic"],
                   horizontal=True, key=f"fr_m_src_{sym}")
    if st.button("Replay path"):
        st.session_state["fr_replay"] = sym
    settles = (book["settles"] if src.startswith("Book") and book
               else futures.synthetic_settles(sym, entry, 10))
    pos = futures.position(sym, entry, qty, margin_rate=rate or 0.12, initial=init)
    t = st.columns(4)
    for col, line in zip(t, pos.facts()[1:]):
        k, v = line.split(": ", 1)
        col.metric(k.replace(" (illustrative)", " (illus.)"), v)
    facts = pos.facts()
    if st.session_state.get("fr_replay") != sym:
        st.caption("Click Replay path to run the position over the settlement prices.")
        return facts
    led = futures.mtm_ledger(sym, entry, settles, cash, qty=qty, side=side, margin_rate=rate,
                             initial=init, maintenance=maint)
    day = st.slider("After session", 1, led.rows.height, min(4, led.rows.height) if book else led.rows.height,
                    key=f"fr_m_day_{sym}")
    now = led.upto(day)
    last = now.last
    pts, px = now.move_to_margin_call()
    m = st.columns(3)
    m[0].metric("MTM today", fmt_money(last["mtm"], mkt))
    m[1].metric("Free cash", fmt_money(last["free_cash"], mkt))
    m[2].metric("Move to margin call",
                "call due now" if last["free_cash"] < 0 else f"≈ {pts:+,.0f} pts".replace("-", "−"),
                help=f"Price where free cash reaches zero: {fmt_num(px, mkt, 2)}")
    show = led.rows.to_pandas()
    st.dataframe(show, hide_index=True, width="stretch")
    chart = alt.Chart(show).mark_bar().encode(
        x=alt.X("day:O"), y=alt.Y("mtm:Q", title="daily MTM"),
        color=alt.condition("datum.mtm >= 0", alt.value("#15803D"), alt.value("#DC2626")))
    st.altair_chart(ui.hypothetical_chart(chart.properties(height=170)), width="stretch")
    gap = st.number_input("Shock (%)", value=-3.0, step=0.5, key="fr_m_gap")
    if st.button("Add shock"):
        st.session_state["fr_shock"] = gap
    facts += now.facts()
    if "fr_shock" in st.session_state:
        sh = now.shock(st.session_state["fr_shock"] / 100)
        label = f"{sh.gap * 100:+.1f}% gap".replace("-", "−")
        st.metric(f"{label}: short" if sh.shortfall > 0 else label,
                  fmt_money(sh.shortfall, mkt) if sh.shortfall > 0 else "covered")
        facts += sh.facts()
    return facts


def render() -> None:
    ui.page_header("Futures & Roll", "Derivatives")
    mkt = ui.market()
    st.session_state["data_status"] = "Synthetic · offline"
    tabs = st.tabs(["Contract", "Basis", "Roll calendar", "Margin & MTM"])
    facts: list[str] = []
    with tabs[0]:
        facts += _contract_tab(mkt)
    with tabs[1]:
        facts += _basis_tab(mkt)
    with tabs[2]:
        facts += _roll_tab(mkt)
    with tabs[3]:
        facts += _margin_tab(mkt)
    ui.ai_block(_Facts(facts), key="fr_ai", section="Derivatives",
                question="Narrate the ledger, shock, basis and roll numbers in plain words, citing "
                         "each number. Do not recommend any trade.")
    ui.paper_only_note()
    ui.dated_note("Margins are illustrative; your broker's file is the real figure.")
