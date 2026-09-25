"""Strategy › Pairs Lab (Chapter 26).

Pair finder (correlation and Engle–Granger side by side) → Check link (AI note,
kept only on Accept) → Spread z-score on a frozen formation window → Half-life
→ sizing panel → Send to Backtest Report / Send to Paper Desk (linked paper legs).
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import pairs, reference
from plugai_trade.app import ui
from plugai_trade.store import default as store

AMBER = "background-color: #FEF3C7; color: #92400E"


def _universe() -> list[str]:
    lists = {"Lesson 26 sample (SYN-A…SYN-D)": list(pairs.SAMPLE_UNIVERSE)}
    for w in store().all("watchlists"):
        syms = w.get("symbols") or []
        if syms:
            lists[f"Watchlist · {w.get('name', w['id'])}"] = list(syms)
    choice = st.selectbox("Universe", list(lists) + ["Type symbols"], key="pl_universe")
    if choice == "Type symbols":
        text = st.text_input("Symbols (comma-separated)", "SYN-A, SYN-B, SYN-C, SYN-D", key="pl_syms")
        return [s.strip().upper() for s in text.split(",") if s.strip()]
    return lists[choice]


def _finder(market: str, formation: int) -> None:
    st.markdown("#### Pair finder")
    syms = _universe()
    if st.button("Find pairs", key="pl_find", type="primary"):
        st.session_state["pl_candidates"] = pairs.find_pairs(syms, market, formation)
    cands = st.session_state.get("pl_candidates")
    if cands is None:
        st.session_state["pl_candidates"] = cands = pairs.find_pairs(pairs.SAMPLE_UNIVERSE[:4], market, formation)
    if not cands:
        st.info("No pairs could be tested (need at least two symbols with data).")
        return
    df = pd.DataFrame([{"Pair": f"{c.a} / {c.b}", "Correlation": round(c.correlation, 2),
                        "Cointegration t": round(c.adf_t, 2), "5% critical": round(c.critical_5, 2),
                        "Test": "passes" if c.passes else "FAILS",
                        "Half-life": round(c.half_life, 1), "Hedge ratio": round(c.beta, 3)}
                       for c in cands])
    st.dataframe(df.style.apply(lambda r: [AMBER if r["Test"] == "FAILS" and r["Correlation"] >= 0.8
                                           else ""] * len(r), axis=1), hide_index=True, width="stretch")
    st.caption("Amber: high correlation but no leash — correlation is not cointegration.")
    labels = [f"{c.a} / {c.b}" for c in cands]
    st.session_state["pl_pair"] = st.selectbox("Candidate", labels, key="pl_pick")
    _check_link(*st.session_state["pl_pair"].split(" / "), market)


def _check_link(a: str, b: str, market: str) -> None:
    desc = st.text_area("Your two-line description of each business (optional)", key="pl_desc")
    if st.button("Check link", key="pl_link"):
        out = pairs.check_link(a, b, desc, "NSE" if market == "IN" else "NYSE")
        st.session_state["pl_link_note"] = (a, b, out.text, pairs.link_rating(out.text), out.where)
    note = st.session_state.get("pl_link_note")
    if note and note[:2] == (a, b):
        st.info(note[2])
        st.caption(f"Link rating: **{note[3] or 'not rated'}** · {note[4]} · nothing is kept until Accept")
        if st.button("Accept", key="pl_link_accept", disabled=note[3] is None):
            store().add("notes", {"screen": "Pairs Lab", "pair": f"{a}/{b}", "rating": note[3],
                                  "text": note[2]}, tag="pair_link")
            st.success(f"Link note kept: {note[3]}.")


def _spread(market: str, formation: int) -> tuple[pairs.PairFit, pairs.PairRule] | None:
    st.markdown("#### Spread z-score")
    a, b = st.session_state.get("pl_pair", "SYN-A / SYN-B").split(" / ")
    try:
        fit = pairs.fit_symbols(a, b, market, formation)
    except Exception as exc:
        st.error(f"Could not load {a} / {b}: {exc}")
        return None
    c = st.columns(4)
    entry = c[0].number_input("Entry |z|", 0.5, 5.0, 2.0, 0.1, key="pl_entry")
    exit_ = c[1].number_input("Exit |z|", 0.0, 3.0, 0.5, 0.1, key="pl_exit")
    stop = c[2].number_input("Stop |z|", 1.0, 10.0, 3.5, 0.1, key="pl_stop")
    default_ts = max(1, round(3 * fit.half_life)) if fit.half_life < 1e6 else 60
    tstop = int(c[3].number_input("Time stop (sessions)", 1, 500, default_ts, key="pl_tstop",
                                  help="Three half-lives is the book's rule of thumb."))
    rule = pairs.PairRule(entry, exit_, stop, tstop)
    t = st.columns(4)
    t[0].metric("Hedge ratio", f"{fit.beta:.3f}")
    t[1].metric("Half-life", f"{fit.half_life:.1f} sessions")
    t[2].metric("Cointegration t", f"{fit.adf_t:.2f}", f"5% critical {fit.critical_5:.2f}",
                delta_color="off")
    t[3].metric("Spread width (sd)", f"{fit.sd:.2%}")
    if not fit.cointegrated:
        st.warning("This pair fails the cointegration test on the formation window.")
    st.text_input("Known event dates for both companies (results, meetings)", key="pl_events")
    trades, suspended = pairs.run_rule(fit.z, fit.spread, fit.formation, rule)
    _z_chart(fit, rule, trades)
    if trades:
        st.dataframe(pd.DataFrame([{"#": x.number, "Side": "long A / short B" if x.side > 0 else "short A / long B",
                                    "Entry session": x.entry_session, "Entry z": round(x.entry_z, 2),
                                    "Exit session": x.exit_session, "Exit z": round(x.exit_z, 2),
                                    "Exit": x.exit_type, "Sessions": x.sessions,
                                    "Spread P&L (log)": round(x.spread_pnl, 4)} for x in trades]),
                     hide_index=True, width="stretch")
    if suspended:
        st.warning(f"Stopped at session {suspended}: pair suspended. Only a new formation window "
                   "after the event is an honest restart.")
    st.session_state["pl_run"] = (trades, suspended)
    ui.ai_block(fit, "pl_fit", section="Strategy")
    return fit, rule


def _z_chart(fit: pairs.PairFit, rule: pairs.PairRule, trades: list[pairs.PairTrade]) -> None:
    df = pd.DataFrame({"session": range(1, len(fit.z) + 1), "z": fit.z})
    line = alt.Chart(df).mark_line(color="#7C3AED", strokeWidth=1).encode(
        x=alt.X("session:Q", title="Session"), y=alt.Y("z:Q", title="z-score"))
    levels = pd.DataFrame({"y": [rule.entry, -rule.entry, rule.exit, -rule.exit, rule.stop, -rule.stop],
                           "kind": ["entry"] * 2 + ["exit"] * 2 + ["stop"] * 2})
    rules = alt.Chart(levels).mark_rule(strokeDash=[4, 3]).encode(
        y="y:Q", color=alt.Color("kind:N", scale=alt.Scale(domain=["entry", "exit", "stop"],
                                                            range=["#7C3AED", "#94A3B8", "#F59E0B"])))
    form = alt.Chart(pd.DataFrame({"x": [fit.formation]})).mark_rule(color="#0F172A").encode(x="x:Q")
    layers = [line, rules, form]
    if trades:
        tdf = pd.DataFrame([{"session": x.exit_session, "z": x.exit_z, "exit": x.exit_type} for x in trades])
        layers.append(alt.Chart(tdf).mark_point(filled=True, size=50).encode(
            x="session:Q", y="z:Q", shape="exit:N", tooltip=["session", "z", "exit"]))
    st.altair_chart(ui.hypothetical_chart(alt.layer(*layers).properties(
        height=260, title=f"Formation = sessions 1–{fit.formation} (frozen) · trading after")),
        width="stretch")


def _sizing(market: str, fit: pairs.PairFit) -> tuple[float, float]:
    st.markdown("#### Sizing")
    if market == "IN":
        c = st.columns(4)
        pa = c[0].number_input("Price A (₹)", 0.0, value=1630.0, key="pl_pa")
        pb = c[1].number_input("Price B (₹)", 0.0, value=885.0, key="pl_pb")
        la = int(c[2].number_input("Lot A", 1, value=reference.lot_size(fit.a) or 1000, key="pl_la"))
        lb = int(c[3].number_input("Lot B", 1, value=reference.lot_size(fit.b) or 2000, key="pl_lb"))
        s = pairs.size_lots(pa, pb, la, lb, fit.beta)
        m = st.columns(3)
        m[0].metric("Long A", f"1 lot = ₹{s.value_a:,.0f}")
        m[1].metric("Short B (rounded)", f"{s.lots_b} lot = ₹{s.value_b:,.0f}",
                    f"target {s.target_lots_b:.2f} lots", delta_color="off")
        m[2].metric("Hedge-ratio error", f"{s.error:+.1%}", f"achieved {s.achieved:.3f}", delta_color="off")
        near = pairs.lots_within(pa, pb, la, lb, fit.beta)
        if near:
            st.caption(f"Lot mismatch: to get within 5% of target you need {near.lots_a} lots A and "
                       f"{near.lots_b} lots B — about ₹{(near.value_a + near.value_b) / 1e7:.1f} crore gross. "
                       "Overnight shorts need stock futures (whole lots) or SLB; margin on both legs.")
        ui.ai_block(s, "pl_size_in", section="Strategy")
        return float(s.lots_a * la), float(s.lots_b * lb)
    c = st.columns(5)
    cap = c[0].number_input("Capital for the long leg ($)", 0.0, value=10_000.0, key="pl_cap")
    pa = c[1].number_input("Price A ($)", 0.0, value=81.66, key="pl_pa_us")
    pb = c[2].number_input("Price B ($)", 0.0, value=44.26, key="pl_pb_us")
    fee = c[3].number_input("Borrow fee (% a year)", 0.0, 100.0, 3.0, key="pl_fee")
    days = int(c[4].number_input("Days held (estimate)", 1, 365, 16, key="pl_days"))
    s = pairs.size_shares(cap, pa, pb, fit.beta, fee / 100, days)
    m = st.columns(4)
    m[0].metric("Long A", f"{s.shares_a} sh = ${s.value_a:,.2f}")
    m[1].metric("Short B", f"{s.shares_b} sh = ${s.value_b:,.2f}")
    m[2].metric("Hedge-ratio error", f"{s.error:+.1%}", f"achieved {s.achieved:.3f}", delta_color="off")
    m[3].metric("Borrow fee", f"${s.borrow_fee:,.2f}")
    ui.ai_block(s, "pl_size_us", section="Strategy")
    return float(s.shares_a), float(s.shares_b)


def _handoffs(fit: pairs.PairFit, rule: pairs.PairRule, qty: tuple[float, float]) -> None:
    trades, suspended = st.session_state.get("pl_run", ([], None))
    c = st.columns(2)
    if c[0].button("Send to Backtest Report", key="pl_send_bt"):
        bid = pairs.send_to_backtest(fit, rule, trades, suspended)
        st.success(f"Sent as backtest #{bid}. The Trials counter counts every pair you tested.")
    side = 1 if fit.z[-1] < 0 else -1
    ok = fit.cointegrated and not suspended
    if c[1].button("Send to Paper Desk", key="pl_send_paper", disabled=not ok):
        ids = pairs.send_to_paper_desk(fit, side, qty[0], qty[1], rule,
                                       st.session_state.get("pl_events", ""), ui.market())
        st.success(f"Two linked pending paper orders (#{ids[0]}, #{ids[1]}) with the hedge ratio, "
                   "three exits and event dates. Nothing fills until you click Accept.")
    if not ok:
        c[1].caption("Send to Paper Desk needs a pair that passes the test and is not suspended.")


def render() -> None:
    """Pairs Lab."""
    ui.page_header("Pairs Lab", "Strategy", "Hedge ratio · z-score · half-life, fitted on a frozen window")
    market = ui.market()
    formation = int(st.number_input("Formation window (sessions)", 60, 1000, 250, 10, key="pl_formation"))
    _finder(market, formation)
    got = _spread(market, formation)
    if got:
        fit, rule = got
        qty = _sizing(market, fit)
        _handoffs(fit, rule, qty)
    ui.paper_only_note()
