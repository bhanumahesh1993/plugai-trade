"""Plan & Risk › Position Sizer — Fixed risk % / ATR stop / Vol target / Hedge.

Every tile is computed in code (``plugai_trade.sizing``); lot sizes and costs
come from the dated tables. The sizer never rounds up: a 0 comes with choices.
"""

from __future__ import annotations

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import config, data, indicators, plans, reference, sizing
from plugai_trade.app import ui
from plugai_trade.store import default as store

SECTION = "Plan & Risk"


def _defaults(mkt: str) -> dict:
    s = config.get("sizing", {}) or {}
    acct = (s.get("account") or {}).get(mkt) or (1_500_000.0 if mkt == "IN" else 40_000.0)
    return {"account": float(acct), "risk_pct": float(s.get("risk_pct", 0.01)) * 100,
            "cap_pct": float(s.get("cap_pct", 0.25)) * 100,
            "total_cap_r": float(s.get("total_cap_r", 3.0)),
            "group_cap_r": float(s.get("group_cap_r", 2.0))}


def _plan_prefill(mkt: str) -> plans.Plan | None:
    options = {f"#{p.id} {p.name} ({p.symbol})": p for p in plans.all_plans(mkt)}
    pid = st.session_state.get("sizer_plan_id")
    labels = ["(no plan)", *options]
    idx = next((i for i, (k, p) in enumerate(options.items(), 1) if p.id == pid), 0)
    choice = st.selectbox("Plan", labels, index=idx, key="sz_plan")
    return options.get(choice)


def _market_numbers(symbol: str, mkt: str) -> tuple[float, float, float, str]:
    """(last close, ATR 14, daily vol, as-of date) from the lab's data (synthetic offline)."""
    end = date.today()
    df = data.get(sizing.base_symbol(symbol), market=mkt, start=end - timedelta(days=120), end=end)
    ui.set_data_status(df)
    df = indicators.atr(indicators.returns(df), 14)
    last = df.tail(1)
    vol = float(df["ret"].tail(20).std() or 0.01)
    return (float(last["close"][0]), float(last["atr_14"][0]), vol, str(last["date"][0]))


def _tiles(r: sizing.SizeResult) -> None:
    m = r.market
    c = st.columns(6)
    c[0].metric("Risk budget" if r.method != "Vol target" else "Daily risk target",
                sizing.money(r.budget, m, 0 if m == "IN" else 2))
    c[1].metric(f"Risk / {r.unit}" if r.method != "Vol target" else f"Daily move / {r.unit}",
                sizing.money(r.risk_per_lot, m, 2))
    c[2].metric("Raw size", f"{r.raw_size:.2f} {r.unit}s")
    c[3].metric("Size ↓", f"{r.size} {r.unit}{'s' if r.size != 1 else ''}")
    c[4].metric("Actual risk", f"{r.actual_risk_pct:.2%}" if r.method != "Vol target"
                else sizing.money(r.actual_risk, m, 2))
    c[5].metric("Notional", f"{r.notional_x:.2f}×", help=sizing.money(r.notional, m))
    if r.notional_x > 1:
        st.warning(f"Notional exposure {sizing.money(r.notional, m)} is {r.notional_x:.2f}× the "
                   "account. Stop-based sizing controls the loss at the stop, not a gap through it.")
    if r.cap_size is not None:
        msg = (f"Position cap {r.cap_pct:.0%}: allows {r.cap_size} {r.unit}s; risk rule gives "
               f"{r.risk_size}. Binding rule: **{r.binding}**.")
        (st.warning if r.binding == "position cap" else st.caption)(msg)
    if r.choices:
        st.error("Size 0 — the sizer never rounds up. Your choices:")
        for ch in r.choices:
            st.markdown(f"- {ch}")
    for n in r.notes:
        st.caption(n)


def _cap_check(r: sizing.SizeResult, d: dict) -> None:
    one_r = r.budget if r.method != "Vol target" else 0
    if not one_r or r.size == 0:
        return
    open_pos = [{"symbol": p["symbol"],
                 "risk_r": (p.get("risk_money") or 0) / one_r}
                for p in store().all("paper_positions", tag="open")]
    chk = sizing.check_caps(open_pos, r.symbol, r.actual_risk / one_r,
                            d["total_cap_r"], d["group_cap_r"])
    (st.success if chk.ok else st.warning)(
        f"Open risk incl. this trade {chk.total_open_r:.2f}R (cap {d['total_cap_r']:g}R) · "
        f"group '{chk.group}' behaves like {chk.group_effective_r:.2f}R (cap {d['group_cap_r']:g}R)"
        + ("" if chk.ok else " — " + "; ".join(chk.messages)))


def _use_in_plan(plan: plans.Plan | None, r: sizing.SizeResult, key: str) -> None:
    ui.ai_block(r, key=f"sz_{key}", section=SECTION)
    if st.button("Use in plan", key=f"use_{key}", disabled=plan is None or r.size == 0,
                 help="Writes the size (and an ATR stop) into the plan's Size field"):
        plans.use_size(plan, r)
        st.success(f"Plan #{plan.id} updated to version {plan.version}: {r.size_text()}")


def _common_inputs(key: str, mkt: str, d: dict, symbol: str) -> tuple:
    c1, c2, c3 = st.columns(3)
    account = c1.number_input("Account", min_value=0.0, value=d["account"], step=1000.0, key=f"{key}_acct")
    risk = c2.number_input("Risk per trade (%)", 0.0, 10.0, d["risk_pct"], 0.05, key=f"{key}_risk") / 100
    cap = c3.number_input("Position cap (% of account)", 0.0, 500.0, d["cap_pct"], 1.0, key=f"{key}_cap") / 100
    lot = sizing.lot_for(symbol, mkt)
    return account, risk, (cap or None), lot


def render() -> None:
    ui.page_header("Position Sizer", SECTION, "Size = risk budget ÷ risk per unit, rounded down.")
    mkt = ui.market()
    d = _defaults(mkt)
    plan = _plan_prefill(mkt)
    default_sym = (plan.symbol if plan and plan.symbol else ("NIFTY FUT" if mkt == "IN" else "SPY"))
    symbol = st.text_input("Symbol", default_sym, key=f"sz_sym_{mkt}").strip().upper() or default_sym
    try:
        last, atr14, dvol, asof = _market_numbers(symbol, mkt)
    except Exception as exc:  # data problems must not break sizing
        st.caption(f"No data for {symbol}: {exc}")
        last, atr14, dvol, asof = 100.0, 1.0, 0.01, "n/a"
    entry0 = float(plan.entry) if plan and plan.entry else round(last, 2)
    stop0 = float(plan.stop) if plan and plan.stop else None
    lot = sizing.lot_for(symbol, mkt)
    if lot > 1:
        st.caption(f"Lot size {lot} · dated table, as of {reference.as_of()} "
                   "(Derivatives › Contract Table)")

    t_fixed, t_atr, t_vol, t_hedge = st.tabs(["Fixed risk %", "ATR stop", "Vol target", "Hedge"])
    with t_fixed:
        account, risk, cap, lot = _common_inputs("fx", mkt, d, symbol)
        c1, c2, c3 = st.columns(3)
        entry = c1.number_input("Entry", value=entry0, key="fx_entry", format="%.2f")
        stop = c2.number_input("Stop", value=stop0 if stop0 else round(entry0 * 0.99, 2),
                               key="fx_stop", format="%.2f")
        allow = sizing.cost_allowance(symbol, mkt, entry, stop, lot) if entry != stop else 0.0
        costs_pl = c3.number_input(f"Costs / {'lot' if lot > 1 else 'share'} (allowance)",
                                   value=float(allow), key=f"fx_cost_{symbol}_{entry}_{stop}", format="%.2f",
                                   help=f"Charges from the dated cost table (as of "
                                        f"{reference.as_of()}) plus slippage; edit to yours")
        if entry == stop:
            st.info("Enter a stop different from the entry.")
        else:
            r = sizing.fixed_risk(account, risk, entry, stop, lot, costs_pl, cap, symbol, mkt)
            _tiles(r)
            _cap_check(r, d)
            _use_in_plan(plan, r, "fixed")

    with t_atr:
        account, risk, cap, lot = _common_inputs("at", mkt, d, symbol)
        c1, c2, c3, c4 = st.columns(4)
        entry = c1.number_input("Trigger / entry", value=entry0, key="at_entry", format="%.2f")
        atr = c2.number_input("ATR (14)", value=round(atr14, 2), key=f"at_atr_{symbol}", format="%.4f",
                              help=f"From the lab's data, as of {asof}")
        mult = c3.number_input("ATR multiple", 0.1, 10.0, 1.5 if mkt == "IN" else 2.0, 0.1, key="at_mult")
        side = c4.segmented_control("Side", ["long", "short"], default="long", key="at_side") or "long"
        suggested = sizing.round_price(entry - mult * atr if side == "long" else entry + mult * atr)
        c5, c6 = st.columns(2)
        stop_typed = c5.number_input("Stop (tile suggests; type to round to your tick)",
                                     value=suggested, key=f"at_stop_{suggested}", format="%.2f")
        allow = sizing.cost_allowance(symbol, mkt, entry, stop_typed, lot) if entry != stop_typed else 0.0
        costs_pl = c6.number_input(f"Costs / {'lot' if lot > 1 else 'share'}", value=float(allow),
                                   key=f"at_cost_{symbol}_{entry}_{stop_typed}", format="%.2f")
        st.metric("Stop", f"{suggested:,.2f}", help=f"{entry:,.2f} ∓ {mult:g} × {atr:,.4g}")
        if atr > 0 and entry != stop_typed:
            r = sizing.atr_stop(account, risk, entry, atr, mult, lot, costs_pl, cap, side,
                                stop_override=None if stop_typed == suggested else stop_typed,
                                symbol=symbol, market=mkt)
            _tiles(r)
            _cap_check(r, d)
            _use_in_plan(plan, r, "atr")

    with t_vol:
        c1, c2, c3, c4 = st.columns(4)
        account = c1.number_input("Account", min_value=0.0, value=d["account"], step=1000.0, key="vt_acct")
        target = c2.number_input("Target volatility (% a year)", 1.0, 100.0, 12.0, 0.5, key="vt_tgt") / 100
        price = c3.number_input("Price", value=entry0, key="vt_px", format="%.2f")
        dv = c4.number_input("Instrument's daily move (%)", 0.01, 20.0, max(round(dvol * 100, 2), 0.01), 0.05,
                             key=f"vt_dv_{symbol}", help=f"From the lab's data, as of {asof}") / 100
        r = sizing.vol_target(account, target, price, dv, lot, None, symbol, mkt)
        _tiles(r)
        st.caption("The sizer shows the choices side by side and applies none of them until you "
                   "click Accept or Use in plan.")
        _use_in_plan(plan, r, "vol")

    with t_hedge:
        _hedge(mkt, d)

    _streaks(d)


def _hedge(mkt: str, d: dict) -> None:
    if mkt == "IN":
        st.caption("Currency derivatives only to hedge a genuine exposure (RBI directions).")
        c1, c2, c3, c4 = st.columns(4)
        exp = c1.number_input("Exposure ($)", 0.0, 1e9, 20_000.0, 1000.0, key="hd_exp")
        side = c2.selectbox("Exposure is a", ["receivable", "payable"], key="hd_side")
        fut = c3.number_input("USDINR futures price", 1.0, 500.0, 88.40, 0.01, key="hd_fut")
        ratio = c4.slider("Hedge ratio", 0.0, 1.0, 1.0, 0.25, key="hd_ratio")
        try:
            h = sizing.hedge(exp, fut, side, hedge_ratio=ratio)
        except ValueError as exc:
            st.error(str(exc))
            return
        c = st.columns(3)
        c[0].metric("Lots", f"{h.lots} · {h.futures_side}")
        c[1].metric("Lot", f"${h.lot_usd:,.0f}", help=f"Dated table, as of {reference.as_of()}")
        c[2].metric("Rupee value locked", sizing.money(h.locked_inr, "IN"))
        st.dataframe(pd.DataFrame(h.scenarios).rename(columns={
            "rate": "USDINR at expiry", "invoice_inr": "Invoice (₹)", "futures_pnl": "Futures (₹)",
            "total": "Total (₹)"}), hide_index=True, width="stretch")
        st.caption("Illustrative; brokerage, taxes and the bank's conversion spread are left out.")
        ui.ai_block(h, key="sz_hedge", section=SECTION)
        return
    st.caption("US: size a currency-futures view from the stop, never from the deposit.")
    c1, c2, c3 = st.columns(3)
    risk_amt = c1.number_input("Risk per trade ($)", 0.0, 1e7, d["account"] * d["risk_pct"] / 100, 10.0,
                               key="hd_risk")
    dist = c2.number_input("Stop distance (price)", 0.0001, 10.0, 0.0055, 0.0005, format="%.4f",
                           key="hd_dist")
    csize = float(reference.lookup("us.contracts.M6E.contract_size") or 0)
    size = c3.number_input("Contract size (units)", 0.0, 1e7, csize, 500.0, key="hd_cs",
                           help="From Derivatives › Contract Table")
    if not csize:
        st.caption("The dated table has no row for this contract yet: type its size from the "
                   "exchange's contract specifications.")
    if dist > 0 and size > 0:
        per = dist * size
        n = int(risk_amt // per) if per else 0
        st.metric("Whole micro contracts", n, help=f"${per:,.2f} risk per contract at the stop")
        if n == 0:
            st.error("Size 0: one contract risks more than your budget. Choices: a nearer stop "
                     "that the market supports, a smaller instrument, or pass.")
        ui.ai_block({"Risk per trade": f"${risk_amt:,.2f}", "Stop distance": dist,
                     "Contract size": size, "Risk per contract": f"${per:,.2f}",
                     "Whole contracts (rounded down)": n}, key="sz_hedge_us", section=SECTION)


def _streaks(d: dict) -> None:
    with st.expander("Simulate streaks", expanded=False):
        st.caption("Monte Carlo of made-up trade sequences with a fixed seed. HYPOTHETICAL.")
        c1, c2, c3, c4 = st.columns(4)
        wr = c1.number_input("Win rate (%)", 1.0, 99.0, 40.0, 1.0, key="ss_wr") / 100
        win_r = c2.number_input("Average win (R)", 0.1, 20.0, 1.6, 0.1, key="ss_win")
        loss_r = c3.number_input("Average loss (R)", -20.0, -0.1, -1.0, 0.1, key="ss_loss")
        risk = c4.number_input("Risk per trade (%)", 0.1, 10.0, d["risk_pct"], 0.1, key="ss_risk") / 100
        c5, c6, c7, c8 = st.columns(4)
        n_seq = c5.number_input("Sequences", 100, 20_000, 2000, 100, key="ss_n")
        n_tr = c6.number_input("Trades each", 10, 1000, 100, 10, key="ss_t")
        seed = c7.number_input("Seed", 0, 10_000, 12, 1, key="ss_seed")
        use_j = c8.checkbox("Use my journal's R-multiples", key="ss_j")
        if st.button("Simulate streaks", key="ss_go", type="primary"):
            rv = [float(r["r"]) for r in store().all("journal") if r.get("r") is not None] if use_j else None
            if use_j and not rv:
                st.info("No R-multiples in the journal yet; using the two-outcome model.")
                rv = None
            res = [sizing.simulate_streaks(wr, win_r, loss_r, x, int(n_seq), int(n_tr), int(seed), rv)
                   for x in (risk, risk / 2)]
            st.session_state["ss_res"] = res
        res = st.session_state.get("ss_res")
        if not res:
            return
        st.dataframe(pd.DataFrame([{
            "Risk": f"{r.risk_pct:.2%}", "Typical fall": f"{r.typical_fall:.1%}",
            "Bad-luck fall (95th)": f"{r.bad_luck_fall:.1%}", "≥ 30% fall": f"{r.share_dd_30:.1%}",
            "Touch 50%": f"{r.share_touch_50:.1%}", "Median end": f"{r.median_final:.1%}",
            "Longest losing streak (median · 10–90th)":
                f"{r.streak_median:g} · {r.streak_p10:g}–{r.streak_p90:g}"} for r in res]),
            hide_index=True, width="stretch")
        fan = pd.DataFrame(res[0].fan)
        band = alt.Chart(fan).mark_area(opacity=0.25).encode(x="trade:Q", y="p5:Q", y2="p95:Q")
        mid = alt.Chart(fan).mark_area(opacity=0.45).encode(x="trade:Q", y="p25:Q", y2="p75:Q")
        med = alt.Chart(fan).mark_line().encode(x=alt.X("trade:Q", title="Trade"),
                                                y=alt.Y("p50:Q", title="% of start",
                                                        scale=alt.Scale(zero=False)))
        st.altair_chart(ui.hypothetical_chart(alt.layer(band, mid, med).properties(height=240)),
                        width="stretch")
        ui.ai_block(res[0], key="sz_streaks", section=SECTION)
