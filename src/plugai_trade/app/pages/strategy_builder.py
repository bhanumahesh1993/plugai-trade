"""Strategy › Strategy Builder (Chapter 11).

Describe your idea → rule cards (ENTRY, EXIT, FILL, SIZE · COST; amber "assumed"
fields) → Read back in English → Chart check (entries/exits and the warning
chip) → Backtest. The drafted cards are applied only when you click Accept;
every backtest of a new variant adds one to the Trials counter.
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd
import polars as pl
import streamlit as st

from plugai_trade import backtest
from plugai_trade.app import strategy_ui as sui
from plugai_trade.app import ui
from plugai_trade.backtest import Condition, Operand, Spec, SpecError

SECTION = "Strategy"
KINDS = {"Close": "close", "Simple average": "sma", "Exponential average": "ema",
         "Prior N-day high": "high_n", "Prior N-day low": "low_n", "RSI": "rsi",
         "Close N sessions ago": "close_ago", "Number": "value"}
OPS = {"is above": "above", "is below": "below", "first moves above": "cross_above",
       "first moves below": "cross_below"}
CHECKS = {"Every session": "daily", "Weekly (Fridays)": "weekly", "Monthly": "monthly"}
SIZES = {"All capital, whole units": "all_capital", "Volatility target": "vol_target"}


def _key(name: str) -> str:
    return f"sb{st.session_state.get('sb_ver', 0)}_{name}"


def _assumed() -> set[str]:
    return set(st.session_state.setdefault("sb_assumed", []))


def _clear(*flags: str) -> None:
    st.session_state["sb_assumed"] = sorted(_assumed() - set(flags))


def _label(text: str, *flags: str) -> str:
    return f"{text} :orange-badge[assumed]" if _assumed() & set(flags) else text


def _pick(label: str, options: dict[str, Any], value: Any, key: str, flags: tuple[str, ...] = ()
          ) -> Any:
    names = list(options)
    idx = next((i for i, k in enumerate(names) if options[k] == value), 0)
    choice = st.selectbox(_label(label, *flags), names, index=idx, key=_key(key),
                          on_change=_clear, args=flags)
    return options[choice]


# ------------------------------------------------------------------ cards
def _operand(op: Operand, key: str, flags: tuple[str, ...]) -> Operand:
    kind = _pick("Measure", KINDS, op.kind, f"{key}_kind", flags)
    if kind == "value":
        v = st.number_input("Number", value=float(op.value if op.value is not None else 50.0),
                            key=_key(f"{key}_val"))
        return Operand("value", value=v)
    if kind == "close":
        return Operand("close")
    n = st.number_input("Length (sessions)", min_value=1, max_value=2000,
                        value=int(op.n or 20), step=1, key=_key(f"{key}_n"))
    return Operand(kind, int(n))


def _condition(c: Condition, key: str, side: str) -> Condition:
    left = _operand(c.left, f"{key}_l", (f"{side}.basis",))
    op = _pick("Comparison", OPS, c.op, f"{key}_op")
    right = _operand(c.right, f"{key}_r", (f"{side}.average", f"{side}.rsi_length"))
    return Condition(op, left, right)


def _card_header(title: str, tag: str = "") -> None:
    st.markdown(f"**{title}** {tag}")


def _edit_cards(spec: Spec) -> Spec:
    """The four editable cards. Changing an amber field clears its "assumed" mark."""
    new = Spec.from_dict(spec)
    mkt = ui.market()
    tag = ":violet-badge[PROPOSED]" if spec.origin == "agent" else ""
    c1, c2, c3, c4 = st.columns(4)
    with c1.container(border=True):
        _card_header("ENTRY" if spec.mode != "hold_while" else "ENTRY · hold while", tag)
        new.entry = [_condition(c, f"en{i}", "entry") for i, c in enumerate(spec.entry[:1])]
        new.entry += spec.entry[1:]
        for c in spec.entry[1:]:
            st.caption(f"and {c.english(short=True)}")
    with c2.container(border=True):
        _card_header("EXIT", tag)
        if spec.mode == "hold_while":
            st.caption("When the ENTRY condition stops being true.")
        else:
            new.exit = [_condition(c, f"ex{i}", "exit") for i, c in enumerate(spec.exit[:1])]
            new.exit += spec.exit[1:]
            for c in spec.exit[1:]:
                st.caption(f"or {c.english(short=True)}")
            ts = st.number_input("Time stop (sessions, 0 = none)", min_value=0, max_value=2000,
                                 value=int(spec.time_stop or 0), key=_key("ts"))
            new.time_stop = int(ts) or None
            if not new.exit and not new.time_stop and not new.stop_loss_pct:
                st.warning("EXIT is empty: add a time stop or describe an exit.")
    with c3.container(border=True):
        _card_header("FILL")
        st.selectbox(_label("Fill", "fill"), ["Next session's open"], key=_key("fill"),
                     disabled=True, help="Cannot be set earlier: a signal is known only after "
                                         "its bar has closed.")
        new.check = _pick("Check", CHECKS, spec.check, "check", ("check",))
        for n in spec.notes:
            st.caption(n)
    with c4.container(border=True):
        _card_header("SIZE · COST")
        new.size.method = _pick("Size", SIZES, spec.size.method, "size", ("size.method",))
        if new.size.method == "vol_target":
            new.size.target_vol = st.number_input(
                _label("Target volatility % a year", "size.target_vol"), 1.0, 100.0,
                float(spec.size.target_vol * 100), key=_key("tv"), on_change=_clear,
                args=("size.target_vol",)) / 100
            new.size.buffer = st.number_input(_label("Buffer %", "size.buffer"), 0.0, 50.0,
                                              float(spec.size.buffer * 100), key=_key("buf"),
                                              on_change=_clear, args=("size.buffer",)) / 100
        profiles = sui.PROFILES[mkt]
        cur = spec.cost.profile if spec.cost.profile in profiles else profiles[0]
        new.cost.profile = _pick("Cost profile", {p: p for p in profiles}, cur, "prof",
                                 ("cost.profile",))
        default_slip = backtest.spec.DEFAULT_SLIPPAGE_PCT[mkt]
        new.cost.slippage_pct = st.number_input(
            _label("Slippage % a side", "cost.slippage"), 0.0, 2.0,
            float(spec.cost.slippage_pct if spec.cost.slippage_pct is not None else default_slip),
            step=0.01, format="%.2f", key=_key("slip"), on_change=_clear,
            args=("cost.slippage",))
    new.market = mkt
    new.assumed = sorted(_assumed())
    return new


# ------------------------------------------------------------------ describe → draft → accept
def _incoming() -> None:
    """A proposal sent from Automate › Agents (Send to Strategy Builder) arrives as a draft."""
    prop = st.session_state.pop("strategy_builder_spec", None)
    if prop is None:
        saved = [p for p in ui.lab_store().all("proposals", tag="PROPOSED") if p.get("spec")]
        if saved:
            with st.expander(f"Agent proposals waiting ({len(saved)})"):
                for p in saved[:10]:
                    label = f"#{p['id']} · {p.get('subject', p.get('symbol', ''))} · {p['created'][:10]}"
                    if st.button(f"Load {label}", key=f"sb_load_prop_{p['id']}"):
                        prop = p["spec"]
        if prop is None:
            return
    try:
        spec = prop if isinstance(prop, Spec) else Spec.from_dict(prop)
        spec.origin = "agent"
        st.session_state["sb_draft"] = spec.validate().to_dict()
    except SpecError as exc:
        st.error(f"The proposal could not be turned into rule cards: {exc}")


def _describe() -> None:
    idea = st.text_input("Describe your idea", key="sb_idea",
                         placeholder="Buy when the price is above the 50-day average; get out "
                                     "when it falls below the 20-day average")
    if idea and idea != st.session_state.get("sb_last_idea"):
        st.session_state["sb_last_idea"] = idea
        try:
            st.session_state["sb_draft"] = backtest.rules(idea).to_dict()
            st.session_state.pop("sb_error", None)
        except SpecError as exc:
            st.session_state["sb_error"] = str(exc)
            st.session_state.pop("sb_draft", None)
    if st.session_state.get("sb_error"):
        st.error(st.session_state["sb_error"])
    draft = st.session_state.get("sb_draft")
    if not draft:
        return
    spec = Spec.from_dict(draft)
    tag = " · PROPOSED" if spec.origin == "agent" else ""
    with st.container(border=True):
        st.markdown(f"**Draft rule cards{tag}** — nothing is applied until you click Accept.")
        for card in spec.cards():
            st.markdown(f"- **{card['title']}**: " + "; ".join(
                f"{t} :orange-badge[assumed]" if flag else t for t, flag in card["lines"]))
        if st.button("Accept", key="sb_accept", type="primary"):
            st.session_state["sb_spec"] = draft
            st.session_state["sb_assumed"] = list(spec.assumed)
            st.session_state["sb_ver"] = st.session_state.get("sb_ver", 0) + 1
            st.session_state.pop("sb_draft", None)
            for k in ("sb_readback", "sb_chart", "sb_result"):
                st.session_state.pop(k, None)
            st.rerun()


# ------------------------------------------------------------------ chart check
def _chart_check(spec: Spec, bars: pl.DataFrame, profile: str) -> None:
    cc = backtest.chart_check(spec, bars, costs=profile)
    df = bars.select("date", "close").to_pandas()
    lines = ["close"]
    for c in spec.entry + spec.exit:
        for o in c.operands():
            if o.kind in ("sma", "ema") and f"{o.kind}_{o.n}" not in df:
                s = pd.Series(df["close"])
                df[f"{o.kind}_{o.n}"] = (s.rolling(o.n).mean() if o.kind == "sma"
                                         else s.ewm(span=o.n, adjust=False).mean())
                lines.append(f"{o.kind}_{o.n}")
    years = sorted({d.year for d in df["date"]})
    lo, hi = st.select_slider("Years", options=years, value=(years[0], years[-1]),
                              key="sb_years") if len(years) > 1 else (years[0], years[0])
    df["date"] = pd.to_datetime(df["date"])
    view = df[(df["date"].dt.year >= lo) & (df["date"].dt.year <= hi)]
    long = view.melt("date", lines, var_name="series", value_name="price")
    base = alt.Chart(long).mark_line().encode(
        x=alt.X("date:T", title=None), y=alt.Y("price:Q", scale=alt.Scale(zero=False), title=None),
        color=alt.Color("series:N", legend=alt.Legend(orient="bottom", title=None)))
    px = dict(zip(df["date"].dt.date, df["close"]))
    marks = pd.DataFrame(
        [{"date": pd.Timestamp(d), "price": px.get(d), "kind": "buy"} for d in cc["buys"]]
        + [{"date": pd.Timestamp(d), "price": px.get(d), "kind": "sell"} for d in cc["sells"]])
    layers = [base]
    if not marks.empty:
        marks = marks[(marks["date"].dt.year >= lo) & (marks["date"].dt.year <= hi)]
        layers.append(alt.Chart(marks).mark_point(filled=True, size=70).encode(
            x="date:T", y="price:Q",
            shape=alt.Shape("kind:N", scale=alt.Scale(domain=["buy", "sell"],
                                                      range=["triangle-up", "triangle-down"])),
            color=alt.Color("kind:N", scale=alt.Scale(domain=["buy", "sell"],
                                                      range=["#0F766E", "#D97706"]), legend=None),
            tooltip=["date:T", "kind:N"]))
    st.altair_chart(ui.hypothetical_chart(alt.layer(*layers).properties(height=300)),
                    width="stretch")
    if cc["chip"]:
        st.warning(cc["chip"])
    else:
        st.success(f"No clusters of exits and re-entries · {cc['round_trips']} round trips.")
    st.caption("Markers sit on the fill session (the open after the signal). Chart check does "
               "not add a trial.")


# ------------------------------------------------------------------ page
def render() -> None:
    ui.page_header("Strategy Builder", SECTION,
                   "Describe your idea → rule cards → Read back in English → Chart check → Backtest")
    mkt = ui.market()
    _incoming()
    c1, c2, c3 = st.columns([1.2, 1, 1.4])
    symbol = c1.selectbox("Instrument", sui.INSTRUMENTS[mkt], key=f"sb_sym_{mkt}")
    years = c2.number_input("Years", 1, 15, 5, key="sb_years_n")
    with c3:
        synthetic = sui.data_choice("sb_data")
    _describe()
    raw = st.session_state.get("sb_spec")
    if not raw:
        st.info("Type your idea and press Enter. The lab drafts the rule cards; you Accept them, "
                "fill anything marked assumed, then read them back.")
        return
    spec = _edit_cards(Spec.from_dict(raw))
    try:
        spec.validate()
    except SpecError as exc:
        st.error(str(exc))
        return
    st.session_state["sb_spec"] = spec.to_dict()
    profile = spec.cost.profile or sui.PROFILES[mkt][0]
    n = backtest.trials.count(spec.family_key())
    b1, b2, b3, b4 = st.columns([1.3, 1, 1, 1])
    if b1.button("Read back in English", key="sb_rb"):
        st.session_state["sb_readback"] = True
    if b2.button("Chart check", key="sb_cc"):
        st.session_state["sb_chart"] = True
    go = b3.button("Backtest", key="sb_bt", type="primary")
    b4.markdown(f"**Trials: {n}**")
    if st.session_state.get("sb_readback"):
        st.info(spec.read_back())
        ui.ai_block(spec, "sb_ai", SECTION, question="Explain these rules to a new trader in "
                                                     "three plain sentences.")
    bars = sui.load_bars(symbol, mkt, int(years), synthetic)
    if st.session_state.get("sb_chart"):
        _chart_check(spec, bars, profile)
    if go:
        res = backtest.run(spec, bars, costs=profile, symbol=symbol)
        res.save(tag="strategy_builder")
        st.session_state["bt_result"] = res
        st.session_state["sb_result"] = res
        st.rerun()
    res = st.session_state.get("sb_result")
    if res is not None and res.spec.digest() == spec.digest():
        st.success(f"Backtest done · Trials: {res.trial_count()} · open Strategy › Backtest "
                   "Report for costs, walk-forward and the Report Card.")
        sui.summary_tiles(res)
        sui.equity_chart(res, height=220)
