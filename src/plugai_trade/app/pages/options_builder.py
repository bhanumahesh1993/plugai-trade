"""Derivatives › Options Strategy Builder (Chapters 22–23)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import options
from plugai_trade.app import ui
from plugai_trade.options import chain

_DEFAULT = {"IN": ("NIFTY", 25000.0), "US": ("SPY", 565.0)}
_KINDS = {"Call": "call", "Put": "put", "Shares": "stock"}


@dataclass
class _Bundle:
    """Everything on screen, as citable facts for Explain / Show sources."""

    parts: list[list[str]]

    def facts(self) -> list[str]:
        return [f for part in self.parts for f in part]


# ---------------------------------------------------------------- state
def _state_key(mkt: str) -> str:
    return f"ob_legs_{mkt}"


def _new_strategy(mkt: str, seed_example: bool) -> None:
    sym, strike = _DEFAULT[mkt]
    st.session_state[f"ob_symbol_{mkt}"] = sym
    st.session_state[_state_key(mkt)] = (
        [{"side": "buy", "kind": "call", "strike": strike, "expiry": "weekly", "qty": 1}]
        if seed_example else [])
    st.session_state.pop("ob_preset", None)


def _legs(mkt: str) -> list[dict]:
    if _state_key(mkt) not in st.session_state:
        _new_strategy(mkt, seed_example=True)
    return st.session_state[_state_key(mkt)]


def _build(specs: list[dict], symbol: str, mkt: str, spot: float | None,
           iv: float | None) -> list[options.Leg]:
    return [options.leg(symbol, kind=s["kind"], strike=s["strike"], expiry=s["expiry"],
                        side=s["side"], qty=int(s["qty"]), spot=spot, iv=iv, market=mkt)
            for s in specs]


# ---------------------------------------------------------------- controls
def _add_leg_controls(mkt: str, spot: float) -> None:
    with st.popover("Add leg"):
        strike = st.number_input("Strike", value=float(round(spot)), step=chain_step(spot),
                                 key="ob_new_strike")
        expiry = st.selectbox("Expiry", ["weekly", "monthly"], key="ob_new_expiry")
        qty = st.number_input("Lots / contracts", 1, 100, 1, key="ob_new_qty")
        side = st.session_state.get("ob_new_side", "buy")
        c1, c2 = st.columns(2)
        if c1.button("Buy", type="primary" if side == "buy" else "secondary"):
            st.session_state["ob_new_side"] = side = "buy"
        if c2.button("Sell", type="primary" if side == "sell" else "secondary"):
            st.session_state["ob_new_side"] = side = "sell"
        st.caption(f"Side: **{side.title()}** — now pick Call or Put to add the leg.")
        c3, c4 = st.columns(2)
        for col, label in ((c3, "Call"), (c4, "Put")):
            if col.button(label):
                _legs(mkt).append({"side": side, "kind": _KINDS[label], "strike": strike,
                                   "expiry": expiry, "qty": int(qty)})
                st.rerun()


def chain_step(spot: float) -> float:
    """Strike step for the number input."""
    return float(options.presets.strike_step(spot))


def _presets(mkt: str, symbol: str, spot: float) -> None:
    with st.popover("Income presets"):
        st.caption("Adds the legs with Sell and Buy already set (monthly lesson chain).")
        for name in options.PRESETS:
            if st.button(name, key=f"ob_preset_{name}"):
                legs = options.preset(name, symbol, market=mkt, spot=spot)
                st.session_state[_state_key(mkt)] = [
                    {"side": lg.side, "kind": lg.kind, "strike": lg.strike, "expiry": "monthly",
                     "qty": lg.qty} for lg in legs]
                st.session_state["ob_preset"] = name
                st.rerun()


def _leg_editor(mkt: str, legs: list[options.Leg]) -> None:
    specs = _legs(mkt)
    df = pd.DataFrame([{"Side": s["side"].title(), "Type": {v: k for k, v in _KINDS.items()}[s["kind"]],
                        "Strike": float(s["strike"]), "Expiry": s["expiry"], "Lots": int(s["qty"]),
                        "Premium": lg.premium, "Lot size": lg.lot} for s, lg in zip(specs, legs)])
    edited = st.data_editor(
        df, key=f"ob_editor_{mkt}_{abs(hash(repr(specs))) % 10**8}", num_rows="dynamic", width="stretch", hide_index=True,
        disabled=["Premium", "Lot size"],
        column_config={"Side": st.column_config.SelectboxColumn(options=["Buy", "Sell"]),
                       "Type": st.column_config.SelectboxColumn(options=list(_KINDS)),
                       "Expiry": st.column_config.SelectboxColumn(options=["weekly", "monthly"])})
    new = [{"side": str(r.Side).lower(), "kind": _KINDS.get(str(r.Type), "call"),
            "strike": float(r.Strike), "expiry": str(r.Expiry), "qty": max(int(r.Lots), 1)}
           for r in edited.dropna(subset=["Strike"]).itertuples()
           if r.Side in ("Buy", "Sell") and r.Expiry in ("weekly", "monthly")]
    if new != specs:
        st.session_state[_state_key(mkt)] = new
        st.rerun()


# ---------------------------------------------------------------- panels
def _tiles(view: options.Strategy, single: options.Leg | None) -> list[str]:
    if single is not None:
        st.markdown("**What you're paying for** · per lot")
        tiles = single.tiles().display()
        facts = [f"{k}: {v}" for k, v in tiles.items()]
    else:
        st.markdown("**Position tiles** · whole position")
        tiles = view.summary().tiles()
        facts = view.summary().facts()
    cols = st.columns(min(len(tiles), 5))
    for i, (k, v) in enumerate(tiles.items()):
        cols[i % len(cols)].metric(k, v)
    return facts


def _payoff_chart(view: options.Strategy, mkt: str) -> None:
    arr = view.payoff()
    df = pd.DataFrame({"spot": arr["spot"], "expiry": arr["expiry"], "now": arr["now"]})
    df["profit"] = df["expiry"].clip(lower=0)
    df["loss"] = df["expiry"].clip(upper=0)
    em = view.expected_move()
    band = pd.DataFrame({"lo": [view.spot - em], "hi": [view.spot + em]})
    x = alt.X("spot:Q", title=f"{view.symbol} at expiry", scale=alt.Scale(zero=False))
    layers = [
        alt.Chart(band).mark_rect(opacity=0.12, color="#0284C7").encode(x="lo:Q", x2="hi:Q"),
        alt.Chart(df).mark_area(opacity=0.35, color="#15803D").encode(x=x, y=alt.Y("profit:Q", title=f"P&L ({chain.CURRENCY[mkt]})")),
        alt.Chart(df).mark_area(opacity=0.35, color="#DC2626").encode(x=x, y="loss:Q"),
        alt.Chart(df).mark_line(color="#334155").encode(x=x, y="expiry:Q"),
        alt.Chart(df).mark_line(color="#7C3AED", strokeDash=[5, 3]).encode(x=x, y="now:Q"),
        alt.Chart(pd.DataFrame({"s": [view.spot]})).mark_rule(color="#475569").encode(x="s:Q"),
    ]
    bes = view.breakevens()
    if bes:
        layers.append(alt.Chart(pd.DataFrame({"b": bes})).mark_rule(color="#15803D", strokeDash=[2, 2]).encode(x="b:Q"))
    st.altair_chart(alt.layer(*layers).properties(height=280), width="stretch")
    st.caption(f"Solid: at expiry · dashed: now, with {view.days_left:g} days left · shaded band: "
               f"±1σ expected move (±{chain.fmt_num(em, mkt, 0 if mkt == 'IN' else 2)}). "
               "Black–Scholes on the lesson chain; illustrative.")


def _iv_panel(symbol: str) -> list[str]:
    ivr = options.iv_rank(symbol, window=252)
    st.markdown("**IV panel**")
    c1, c2, c3 = st.columns(3)
    c1.metric("IV", f"{ivr.iv:.1f}%")
    c2.metric("IV rank", f"{ivr.rank:.0f}")
    c3.metric("IV percentile", f"{ivr.percentile:.0f}")
    st.progress(min(max(ivr.rank / 100, 0.0), 1.0), text=f"IV rank gauge: {ivr.rank:.0f} of 100")
    year = pd.DataFrame({"date": ivr.dates, "IV %": ivr.series})
    st.altair_chart(alt.Chart(year).mark_line(color="#0284C7").encode(
        x=alt.X("date:T", title=None), y=alt.Y("IV %:Q", scale=alt.Scale(zero=False)))
        .properties(height=140), width="stretch")
    st.caption(f"Series: {ivr.source}; window {ivr.window} sessions. Rank = (today − low) ÷ "
               "(high − low); percentile = share of earlier sessions below today.")
    events = [f"{d:%d %b %Y}: {e}" for d, e in ivr.events]
    st.markdown("**Events**")
    for e in events:
        st.caption(e)
    st.caption("Check RBI / Fed, budget and heavyweight results dates before expiry in the "
               "Earnings Desk calendar.")
    return ivr.facts()


def _scenarios(strat: options.Strategy, view: options.Strategy, days: float,
               single: options.Leg | None, mkt: str) -> tuple[list[str], tuple[float, float, float] | None]:
    st.markdown("**Scenarios**")
    unit = "points" if mkt == "IN" else "$"
    c1, c2 = st.columns(2)
    gap = c1.number_input(f"Gap ({unit})", value=0.0, step=10.0 if mkt == "IN" else 1.0, key="ob_gap")
    ivc = c2.number_input("IV change (points)", value=0.0, step=1.0, key="ob_ivchg")
    b1, b2, b3 = st.columns(3)
    if b1.button("Gap") or b2.button("IV spike"):
        st.session_state["ob_scn_on"] = True
    if b3.button("Scenarios"):
        st.session_state["ob_table_on"] = not st.session_state.get("ob_table_on", False)
    facts: list[str] = []
    scn_days = min(days, max(strat.days_left - 1, 0.0))
    move = None
    if st.session_state.get("ob_scn_on"):
        if single is not None:
            sc = single.scenario(gap=gap, iv=ivc, days_left=scn_days)
            m1, m2 = st.columns(2)
            m1.metric("Value", chain.fmt_money(sc.price, mkt, 2 if mkt == "US" else 1))
            m2.metric("P&L per lot", chain.fmt_money(sc.pnl, mkt))
            facts = sc.facts()
        else:
            row = strat.stress(gap=gap / strat.spot, iv_to=strat.base_iv + ivc / 100,
                               days=strat.days_left - scn_days, label="Your scenario")
            st.metric("Position P&L", chain.fmt_money(row.pnl, mkt))
            facts = row.facts()
        st.caption(f"Repriced with {scn_days:g} days left (tomorrow's open at the earliest).")
        move = (strat.spot + gap, strat.base_iv + ivc / 100, strat.days_left - scn_days)
    if st.session_state.get("ob_table_on"):
        rows = strat.stress_table()
        _, ml = strat.max_profit_loss()
        tbl = pd.DataFrame([{"Scenario": r.label, "Spot": r.spot, "IV": f"{r.iv * 100:.0f}%",
                             "Days left": r.days_left, "P&L": chain.fmt_money(r.pnl, mkt)} for r in rows])
        st.dataframe(tbl, hide_index=True, width="stretch")
        st.caption("Repriced one day after entry, everything else fixed. Maximum loss at expiry: "
                   + ("unlimited" if ml is None else chain.fmt_money(ml, mkt, 2))
                   + ". Illustrative; not a forecast.")
        facts += [r.facts()[0] for r in rows]
    return facts, move


def _attribution(strat: options.Strategy, move: tuple[float, float, float] | None,
                 mkt: str) -> list[str]:
    st.markdown("**P&L attribution** · direction (delta, gamma), time (theta), volatility (vega)")
    if move is None:
        st.caption("Run a scenario (Gap / IV spike) to split its P&L.")
        return []
    spot, iv, elapsed = move
    att = strat.attribution(spot=spot, iv=iv, days=elapsed)
    parts = att.parts() | {"Actual": att.actual}
    df = pd.DataFrame({"part": list(parts), "value": list(parts.values())})
    st.altair_chart(alt.Chart(df).mark_bar().encode(
        x=alt.X("part:N", sort=None, title=None), y=alt.Y("value:Q", title=chain.CURRENCY[mkt]),
        color=alt.condition("datum.value >= 0", alt.value("#15803D"), alt.value("#DC2626")))
        .properties(height=160), width="stretch")
    return att.facts()


# ---------------------------------------------------------------- save / send
def _save_to_plan(strat: options.Strategy, facts: list[str]) -> None:
    store = ui.lab_store()
    versions = [p for p in store.all("plans", tag="options") if p.get("name") == strat.name]
    exp = st.session_state.get("ob_ai_exp")
    store.add("plans", {"name": strat.name, "version": len(versions) + 1,
                        "screen": "Options Strategy Builder", "strategy": strat.to_dict(),
                        "tiles": facts, "ai_explanation": exp.text if exp else "",
                        "exit_rule": st.session_state.get("ob_exit_rule", "")}, tag="options")
    store.audit("options.save_to_plan", {"name": strat.name, "version": len(versions) + 1})


def _send_to_paper(strat: options.Strategy) -> None:
    store = ui.lab_store()
    store.add("paper_orders", {"source": "Options Strategy Builder", "kind": "options",
                               "strategy": strat.to_dict(), "status": "pending",
                               "note": "PAPER ONLY — review and Accept in Paper Desk"}, tag="pending")
    store.audit("options.send_to_paper", {"name": strat.name})


# ---------------------------------------------------------------- page
def render() -> None:
    ui.page_header("Options Strategy Builder", "Derivatives")
    mkt = ui.market()
    if st.button("New strategy"):
        _new_strategy(mkt, seed_example=False)
    specs = _legs(mkt)
    c1, c2, c3 = st.columns([1.2, 1, 1])
    symbol = c1.text_input("Underlying", key=f"ob_symbol_{mkt}").strip().upper() or _DEFAULT[mkt][0]
    default_spot = chain.default_spot(symbol, mkt)
    spot = c2.number_input("Spot", value=float(default_spot), step=chain_step(default_spot),
                           key=f"ob_spot_{mkt}_{symbol}")
    iv_in = c3.number_input("IV % (blank = chain)", value=None, min_value=1.0, max_value=200.0,
                            key=f"ob_iv_{mkt}")
    st.session_state["data_status"] = "Lesson chain (synthetic) · offline"
    b1, b2 = st.columns(2)
    with b1:
        _add_leg_controls(mkt, spot)
    with b2:
        _presets(mkt, symbol, spot)
    if not specs:
        st.info("New strategy: click Add leg → Buy / Sell → Call / Put, or pick an Income preset.")
        return
    try:
        legs = _build(specs, symbol, mkt, spot, iv_in / 100 if iv_in else None)
        strat = options.strategy(legs, name=st.session_state.get("ob_preset", ""))
    except (ValueError, KeyError) as exc:
        st.error(f"Could not price this strategy: {exc}")
        return
    _leg_editor(mkt, legs)
    st.caption(f"{legs[0].lot_note} · {legs[0].chain_label} · rate {legs[0].rate * 100:.2f}%")
    days_max = int(math.ceil(strat.days_left))
    days = st.slider("Days left", 0, max(days_max, 1), days_max, key=f"ob_days_{mkt}")
    view = strat.at(days)
    opts = [lg for lg in view.legs if lg.kind != "stock"]
    single = opts[0] if len(view.legs) == 1 and opts else None

    left, right = st.columns([1.6, 1])
    with left:
        facts = _tiles(view, single)
        _payoff_chart(view, mkt)
    with right:
        iv_facts = _iv_panel(symbol)
    scn_facts, move = _scenarios(strat, view, days, single, mkt)
    att_facts = _attribution(strat, move, mkt)

    leg_lines = single.facts()[:5] if single is not None else view.facts()[: len(view.legs) + 1]
    bundle = _Bundle([facts, iv_facts, scn_facts, att_facts, leg_lines])
    ui.ai_block(bundle, key="ob_ai", section="Derivatives",
                question="Narrate these tiles and scenarios in plain words, citing each number. "
                         "Do not say whether to trade.")
    st.text_input("Exit rule (time and price, in words)", key="ob_exit_rule")
    s1, s2 = st.columns(2)
    if s1.button("Save to plan"):
        _save_to_plan(strat, facts)
        st.success("Saved to plans (tag: options). Earlier versions are kept as history.")
    if s2.button("Send to Paper Desk"):
        _send_to_paper(strat)
        st.success("Sent to Paper Desk as a pending paper order — nothing fills until you Accept.")
    ui.paper_only_note()
    ui.dated_note("Margin figures are estimates; your broker's calculator is the real figure.")
