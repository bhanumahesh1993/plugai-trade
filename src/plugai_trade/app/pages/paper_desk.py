"""Paper Trading › Paper Desk — paper orders, positions, limits and a kill switch.

LIVE uses a live feed when one is connected; otherwise Replay feeds a recorded
or synthetic session bar by bar (1× / 5× / 20×). Paper only: nothing here can
reach a broker.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from plugai_trade import config, paper, plans, sizing
from plugai_trade.app import ui
from plugai_trade.paper import drift
from plugai_trade.store import default as store

SECTION = "Paper Trading"


# ---------------------------------------------------------------- state
def _desk(mkt: str) -> paper.PaperDesk:
    key = f"pd_desk_{mkt}"
    if key not in st.session_state:
        acct = (config.get("sizing.account", {}) or {}).get(mkt) or (1_500_000.0 if mkt == "IN" else 40_000.0)
        st.session_state[key] = paper.PaperDesk(mkt, float(acct), mode="REPLAY")
    return st.session_state[key]


def _replay(mkt: str) -> paper.Replay | None:
    return st.session_state.get(f"pd_replay_{mkt}")


# ---------------------------------------------------------------- session strip
def _session_strip(mkt: str, desk: paper.PaperDesk) -> None:
    live_ok, live_src = paper.live_status()
    c1, c2 = st.columns([1, 3])
    mode = c1.segmented_control("Session", ["LIVE", "Replay"], default="Replay" if not live_ok else "LIVE",
                                key=f"pd_mode_{mkt}") or "Replay"
    if mode == "LIVE":
        if live_ok:
            desk.mode = "PAPER"
            c2.success(f"LIVE · {live_src}")
        else:
            c2.warning(f"LIVE unavailable — {live_src}. Use Replay instead.")
        return
    desk.mode = "REPLAY"
    c2.info("REPLAY · replayed trades are tagged REPLAY in the journal, never PAPER.")
    c = st.columns([2, 1.3, 1, 1.2, 1])
    syms = paper.default_symbols(mkt)
    sym = c[0].selectbox("Symbol", syms, key=f"pd_rsym_{mkt}")
    day = c[1].date_input("Session", paper.replay.last_session(mkt), key=f"pd_rday_{mkt}")
    interval = c[2].selectbox("Bars", ["5m", "1m", "15m", "1d"], key=f"pd_rint_{mkt}")
    speed = c[3].segmented_control("Speed", list(paper.SPEEDS), default="1×", key=f"pd_rspd_{mkt}") or "1×"
    if c[4].button("Replay", key=f"pd_rload_{mkt}", type="primary"):
        inst = paper.instrument(sym, mkt)
        bars = paper.session_bars(inst.data_symbol, mkt, day, interval)
        st.session_state[f"pd_replay_{mkt}"] = paper.Replay(sym, bars, paper.SPEEDS[speed])
    rp = _replay(mkt)
    if rp is None:
        return
    rp.speed = paper.SPEEDS[speed]
    a, b, c3 = st.columns([1, 1, 3])
    if a.button(f"Next {rp.speed} bar{'s' if rp.speed > 1 else ''}", key=f"pd_step_{mkt}",
                disabled=rp.done):
        rp.step(desk)
        desk.sync_store()
    if b.button("To session end", key=f"pd_end_{mkt}", disabled=rp.done):
        rp.step(desk, rp.bars.height)
        desk.sync_store()
    c3.caption(f"{rp.symbol}: bar {rp.cursor} of {rp.bars.height}"
               + (f" · last {desk.now}" if desk.now else " · no bar fed yet"))
    vis = rp.visible()
    if vis.height:
        x = "time" if "time" in vis.columns else "date"
        ui.line_chart(vis.select(x, "close").to_pandas(), x, "close", hypothetical=True, height=200)


def _guardrail_strip(mkt: str, desk: paper.PaperDesk) -> None:
    g = desk.guardrail_strip()
    c = st.columns(5)
    c[0].metric("Trades left", "—" if g["trades_left"] is None else g["trades_left"])
    c[1].metric("Cooldown", f"{g['cooldown_min']} min")
    c[2].metric("Day result", "—" if g["day_r"] is None else f"{g['day_r']:+.2f}R",
                help=sizing.money(g["day_pnl"], mkt, 2))
    c[3].metric("Daily loss limit", sizing.money(g["daily_loss_limit"], mkt) if g["daily_loss_limit"] else "not set",
                help="From Rule Card › Sync limits. No override button.")
    c[4].metric("Next lockout", g["next_lockout"] or "—")
    ok, why = desk.guardrail_check()
    if not ok:
        st.error(f"BLOCKED · {why}. New paper orders are blocked; change rules on the Rule Card in "
                 "the evening, where the change is dated.")
    c1, c2 = st.columns([1, 4])
    if c1.button("Kill switch", key=f"pd_kill_{mkt}", type="primary",
                 help="Cancel pending paper orders, close all paper positions at the next bar's "
                      "open, block new paper orders for the session"):
        res = desk.kill_switch()
        desk.sync_store()
        st.warning(f"Kill switch: {res['cancelled']} paper orders cancelled, {res['closing']} "
                   "positions close at the next bar's open. New paper orders blocked for the session.")
    c2.caption(f"Equity {sizing.money(desk.equity(), mkt, 2)} · realised "
               f"{sizing.money(desk.realised, mkt, 2)} · starting {sizing.money(desk.starting_balance, mkt)}")


# ---------------------------------------------------------------- ticket
def _ticket(mkt: str, desk: paper.PaperDesk) -> None:
    st.markdown("**Paper order ticket**")
    t = paper.load_ticket()
    t = t if t and (t.get("market") or mkt) == mkt else None
    if t:
        st.caption(f"Filled in from {t.get('source')} — check it, then Place paper order.")
    syms = paper.default_symbols(mkt)
    if t and t["symbol"] not in syms:
        syms = [t["symbol"], *syms]
    c = st.columns(4)
    sym = c[0].selectbox("Contract", syms, index=syms.index(t["symbol"]) if t else 0, key=f"pd_sym_{mkt}")
    inst = desk.inst(sym)
    side = c[1].segmented_control("Side", ["Buy", "Sell"], default=(t.get("side", "buy").title() if t else "Buy"),
                                  key=f"pd_side_{mkt}") or "Buy"
    lots_default = int((t or {}).get("qty") or inst.lot) // inst.lot or 1
    lots = int(c[2].number_input("Lots" if inst.lot > 1 else "Quantity", 1, 100_000, lots_default, 1,
                                 key=f"pd_qty_{mkt}_{sym}"))
    qty = lots * inst.lot
    kinds = {"Market": "market", "Limit": "limit", "Stop-entry": "stop"}
    k0 = {"market": "Market", "limit": "Limit", "stop": "Stop-entry"}[(t or {}).get("kind") or "market"]
    kind = c[3].selectbox("Type", list(kinds), index=list(kinds).index(k0), key=f"pd_kind_{mkt}")
    last = desk.last_bar.get(sym, {}).get("close")
    c = st.columns(4)
    price = c[0].number_input("Limit / trigger price", value=float((t or {}).get("price") or last or 0.0),
                              key=f"pd_px_{mkt}_{sym}", format="%.2f", disabled=kind == "Market")
    stop = c[1].number_input("Stop", value=float((t or {}).get("stop") or 0.0), key=f"pd_stop_{mkt}_{sym}",
                             format="%.2f")
    target = c[2].number_input("Planned target (optional)", value=float((t or {}).get("target") or 0.0),
                               key=f"pd_tgt_{mkt}_{sym}", format="%.2f")
    plan_opts = {"(no plan — unplanned)": None, **{f"#{p.id} {p.name}": p.id for p in plans.all_plans(mkt)}}
    pid0 = (t or {}).get("plan_id")
    pidx = next((i for i, v in enumerate(plan_opts.values()) if v == pid0 and v), 0)
    plan_label = c[3].selectbox("Plan", list(plan_opts), index=pidx, key=f"pd_plan_{mkt}")
    plan_id = plan_opts[plan_label]
    with st.expander("Slippage setting (same meaning as the backtester's)"):
        a, b = st.columns(2)
        hs = a.number_input("Half spread (price units)", 0.0, 1e4, inst.half_spread, 0.01, key=f"pd_hs_{mkt}_{sym}")
        sl = b.number_input("Slippage (price units)", 0.0, 1e4, inst.slippage, 0.01, key=f"pd_sl_{mkt}_{sym}")
        desk.set_assumptions(sym, hs, sl)
        inst = desk.inst(sym)
    ref_px = (price if kind != "Market" else last) or price or last or 0.0
    cp = paper.cost_preview(inst, ref_px, qty, target or None, side=side.lower()) if ref_px else None
    a, b = st.columns([1, 3])
    a.metric("Breakeven (pts)", f"{cp.breakeven_pts:.2f}" if cp else "—",
             help=f"All-in {sizing.money(cp.all_in, mkt, 2)} ÷ {qty} units" if cp
             else "Needs a price: type one or feed a bar")
    if b.button("Cost preview", key=f"pd_cp_{mkt}", disabled=cp is None):
        st.session_state["pd_cp_show"] = not st.session_state.get("pd_cp_show", False)
    if cp and st.session_state.get("pd_cp_show"):
        rows = [{"Item": k, "Amount": v} for k, v in cp.items.items() if k != "total"]
        rows += [{"Item": "Charges", "Amount": cp.items["total"]},
                 {"Item": f"Slippage {cp.slippage_per_side:g} a side", "Amount": cp.slippage_money},
                 {"Item": "All-in", "Amount": cp.all_in}]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        ui.dated_note("Charges from the dated cost table.")
    if cp and cp.amber:
        st.warning(cp.amber)
    if plan_id is None:
        st.caption("⚑ Unplanned: this paper order is not linked to a saved Trade Plan; the journal counts it.")
    if st.button("Place paper order", type="primary", key=f"pd_place_{mkt}"):
        try:
            risk = (t or {}).get("risk_money") if t and t.get("plan_id") == plan_id else None
            o = desk.place_paper_order(sym, side.lower(), qty, kinds[kind],
                                       price if kind != "Market" else None, stop or None,
                                       target or None, plan_id, risk)
            if t:
                paper.ticket_used(t["id"])
            if o.status == "BLOCKED":
                st.error(f"BLOCKED · {o.reason}. Logged in Journal › Trades.")
            else:
                st.success(f"Paper order #{o.id} WORKING — it fills on a later bar, never the current one.")
        except ValueError as exc:
            st.warning(str(exc))


# ---------------------------------------------------------------- pending, orders, positions
def _pending(mkt: str, desk: paper.PaperDesk) -> None:
    rows = paper.pending(mkt)
    if not rows:
        return
    st.markdown("**Pending paper orders** — drafted elsewhere; nothing happens until you click.")
    for r in rows:
        a, b, c = st.columns([5, 1, 1])
        if r.get("symbol"):
            a.write(f"#{r['id']} · {r.get('source')} · {(r.get('side') or '').upper()} {r.get('qty')} "
                    f"{r.get('symbol')} {r.get('kind')} {r.get('price') or ''} stop {r.get('stop') or '—'}")
        else:
            a.write(f"#{r['id']} · {r.get('source')} · {r.get('kind', '')} · {r.get('note', '')}")
        if b.button("Accept", key=f"pd_acc_{r['id']}"):
            o = paper.accept(r["id"], desk)
            if o is None:
                st.info("Accepted for tracking. Multi-leg strategies are not filled by the bar model.")
            else:
                (st.error if o.status == "BLOCKED" else st.success)(
                    f"Paper order #{o.id}: {o.status} {o.reason}")
        if c.button("Reject", key=f"pd_rej_{r['id']}"):
            paper.reject(r["id"], "rejected on the Paper Desk")
            st.rerun()


def _orders_positions(mkt: str, desk: paper.PaperDesk) -> None:
    work = desk.open_orders()
    if work:
        st.markdown("**Working paper orders**")
        st.dataframe(pd.DataFrame([{"#": o.id, "Contract": o.symbol, "Side": o.side, "Qty": o.qty,
                                    "Type": o.kind, "Price": o.price, "Stop": o.stop,
                                    "Status": o.status, "Filled": o.filled_qty,
                                    "Unplanned": "⚑" if o.unplanned else ""} for o in work]),
                     hide_index=True, width="stretch")
        for o in work:
            if st.button(f"Cancel #{o.id}", key=f"pd_cxl_{o.id}"):
                desk.cancel(o.id)
                st.rerun()
    st.markdown("**Positions**")
    if not desk.positions:
        st.caption("No open paper positions.")
    for p in desk.positions:
        cols = st.columns([4, 1.2, 1.3, 1.6, 1.4])
        cols[0].write(f"#{p.id} {p.side.upper()} {p.qty} {p.symbol} @ {p.entry:,.2f} · stop "
                      f"{p.stop if p.stop is not None else '—'} · P&L {sizing.money(p.open_pnl(), mkt, 2)}"
                      + (" · closing at next bar" if p.closing else "")
                      + (f" · funding {sizing.money(p.funding, mkt, 2)}" if p.funding else ""))
        new_stop = cols[1].number_input("New stop", value=float(p.stop or p.entry), key=f"pd_ns_{p.id}",
                                        format="%.2f", label_visibility="collapsed")
        reason = cols[2].text_input("Reason", key=f"pd_nr_{p.id}", placeholder="reason (required)",
                                    label_visibility="collapsed")
        if cols[3].button("Move stop", key=f"pd_mv_{p.id}"):
            try:
                desk.move_stop(p.id, new_stop, reason)
                st.rerun()
            except ValueError as exc:
                st.warning(str(exc))
        if cols[4].button("Close at next bar", key=f"pd_close_{p.id}", disabled=p.closing):
            desk.close_at_next_bar(p.id)
            st.rerun()
        if p.symbol.endswith("-PERP"):
            a, b = st.columns(2)
            desk.funding_rate[p.symbol] = a.number_input(
                "Funding per 8 h (%)", -1.0, 1.0, desk.funding_rate.get(p.symbol, 0.0001) * 100, 0.001,
                format="%.4f", key=f"pd_fr_{p.id}") / 100
            if b.button("Send to Crypto Monitor", key=f"pd_cm_{p.id}"):
                store().add("notes", {"kind": "paper_perp", "symbol": p.symbol, "side": p.side,
                                      "qty": p.qty, "entry": p.entry, "market": mkt},
                            tag="send-to-crypto-monitor")
                st.success("Sent. Crypto Monitor and Alerts › From Crypto Monitor can use it.")
    if desk.trades:
        st.markdown("**Closed this session**")
        st.dataframe(pd.DataFrame([{"Contract": t["symbol"], "Side": t["side"], "Qty": t["qty"],
                                    "Entry": t["entry"], "Exit": t["exit"], "Exit reason": t["exit_reason"],
                                    "Slippage": t["slippage"], "Charges": t["costs_total"],
                                    "Net": t["net"], "R": t["r"], "Tag": t["mode"]} for t in desk.trades]),
                     hide_index=True, width="stretch")
    if desk.blocked:
        with st.expander(f"BLOCKED paper orders ({len(desk.blocked)})"):
            st.dataframe(pd.DataFrame(desk.blocked), hide_index=True, width="stretch")


# ---------------------------------------------------------------- drift check
def _compare(mkt: str, desk: paper.PaperDesk) -> None:
    if st.button("Compare with backtest", key="pd_cmp"):
        st.session_state["pd_cmp_open"] = not st.session_state.get("pd_cmp_open", False)
    if not st.session_state.get("pd_cmp_open"):
        return
    st.markdown("**Compare with backtest** — same rule, same bars, same fills.")
    c = st.columns([3, 1, 1])
    rule = c[0].text_input("Rule (read-back text)", "Buy at the next open on the first close above the "
                           "20-day average; sell at the next open when the close is below the 20-day average",
                           key="pd_rule")
    start = c[1].date_input("From", date.today().replace(day=1), key="pd_cmp_from")
    end = c[2].date_input("To", date.today(), key="pd_cmp_to")
    sym = st.selectbox("Contract", paper.default_symbols(mkt), key="pd_cmp_sym")
    inst = paper.instrument(sym, mkt)
    if st.button("Run shadow backtest", key="pd_shadow", type="primary"):
        bars = paper.session_bars(inst.data_symbol, mkt, end, "1d")
        bars = bars.filter(bars["date"] >= start)
        st.caption(f"{bars.height} bars recorded for the period · source: synthetic/REPLAY")
        try:
            res = paper.run_shadow(rule, bars, costs=inst.profile or "IN-futures")
            journal = [r for r in store().all("journal", tag="PAPER") + store().all("journal", tag="REPLAY")
                       if r.get("symbol") == sym and str(start) <= str(r.get("date", "")) <= str(end)]
            one_r = desk.limits()["one_r"] or None
            sh = paper.shadow_trades(res, one_r)
            rep = paper.drift_report(paper.paper_rows_for_drift(journal, {s["signal"] for s in sh}), sh)
            st.session_state["pd_drift"] = rep
        except drift.ShadowUnavailable as exc:
            st.info(str(exc))
    rep = st.session_state.get("pd_drift")
    if rep:
        c = st.columns(4)
        c[0].metric("Shadow backtest", f"{rep.shadow_r:+.2f}R")
        c[1].metric("Paper", f"{rep.paper_r:+.2f}R")
        c[2].metric("Gap · costs", f"{rep.cost_gap_r:.2f}R")
        c[3].metric("Gap · rule breaks", f"{rep.break_gap_r:.2f}R")
        if rep.breaks:
            st.dataframe(pd.DataFrame([{"Signal": r.signal, "Break": r.kind, "Shadow R": r.shadow_r,
                                        "Paper R": r.paper_r, "Gap R": round(r.break_r, 2),
                                        "Trade": r.trade_id, "Note": r.note} for r in rep.breaks]),
                         hide_index=True, width="stretch")
        ui.ai_block(rep, key="pd_drift_ai", section=SECTION, sensitive=True)


def render() -> None:
    ui.page_header("Paper Desk", SECTION)
    ui.paper_only_note()
    mkt = ui.market()
    desk = _desk(mkt)
    _session_strip(mkt, desk)
    _guardrail_strip(mkt, desk)
    left, right = st.columns([1.1, 1])
    with left:
        _ticket(mkt, desk)
    with right:
        _pending(mkt, desk)
        _orders_positions(mkt, desk)
    _compare(mkt, desk)
