"""Paper Trading › Alerts — price, indicator and event alerts, labelled SIMULATED.

New alert → From plan / From Crypto Monitor proposes alerts; nothing is active
until Accept. Channels: Desktop, Email, Telegram (BotFather token in the OS
keychain). Quiet hours hold all but break-through alerts; the alert log keeps
every firing, test, hold and expiry.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from plugai_trade import alerts, config, keys, plans
from plugai_trade.app import ui
from plugai_trade.store import default as store

SECTION = "Paper Trading"


def _proposals() -> list[alerts.Alert]:
    return st.session_state.setdefault("al_props", [])


def _new_alert(mkt: str) -> None:
    st.markdown("**New alert**")
    src = st.segmented_control("Start from", ["From plan", "From Crypto Monitor", "Blank"],
                               default="From plan", key="al_src") or "From plan"
    if src == "From plan":
        opts = {f"#{p.id} {p.name} ({p.symbol})": p for p in plans.all_plans(mkt)}
        if not opts:
            st.caption("No saved plans for this market yet (Plan & Risk › Trade Plan).")
            return
        picked = st.multiselect("Plans", list(opts), default=list(opts)[:1], key="al_plans")
        if st.button("Propose alerts", key="al_prop_plan"):
            st.session_state["al_props"] = [a for k in picked for a in alerts.from_plan(opts[k], mkt)]
    elif src == "From Crypto Monitor":
        positions = [p for p in store().all("paper_positions", tag="open") if str(p.get("symbol", "")).endswith("-PERP")]
        positions += [n for n in store().all("notes", tag="send-to-crypto-monitor")]
        if not positions:
            st.caption("No paper perpetual positions yet (Paper Desk › Send to Crypto Monitor).")
            return
        labels = {f"{p['symbol']} {p.get('side', 'long')} @ {p.get('entry')}": p for p in positions}
        pick = st.selectbox("Paper position", list(labels), key="al_cm_pos")
        lev = st.number_input("Leverage", 1.0, 125.0, 5.0, 1.0, key="al_cm_lev")
        if st.button("Propose alerts", key="al_prop_cm"):
            st.session_state["al_props"] = alerts.from_crypto_monitor(
                {**labels[pick], "leverage": lev, "market": mkt})
    else:
        c = st.columns(4)
        sym = c[0].text_input("Symbol", "NIFTY FUT" if mkt == "IN" else "SPY", key="al_b_sym")
        kind = c[1].selectbox("Type", ["price", "indicator", "event"], key="al_b_kind")
        cond = c[2].selectbox("Condition", ["touch above", "touch below", "close above", "close below"],
                              key="al_b_cond")
        lvl = c[3].number_input("Level", value=0.0, key="al_b_lvl", format="%.2f")
        ind = st.selectbox("Indicator (for indicator alerts)", ["sma_20", "sma_50", "ema_20", "rsi_14"],
                           key="al_b_ind") if kind == "indicator" else None
        if st.button("Propose alert", key="al_prop_blank"):
            st.session_state["al_props"] = [alerts.Alert(
                f"{sym} {cond} {ind or lvl}", sym.strip().upper(), mkt, kind,
                "new item" if kind == "event" else cond, lvl or None, indicator=ind)]


def _saved_proposals() -> None:
    """Alerts other screens proposed (e.g. Crypto Monitor › Send to Alerts): Accept or discard."""
    saved = alerts.load_all("proposed")
    if not saved:
        return
    st.markdown("**Proposed by other screens** — inactive until Accept.")
    for a in saved:
        c = st.columns([5, 1, 1])
        c[0].write(f"#{a.id} {a.name} · {a.describe()}")
        if c[1].button("Accept", key=f"al_sacc_{a.id}"):
            alerts.accept(a)
            st.rerun()
        if c[2].button("Discard", key=f"al_sdis_{a.id}"):
            store().delete("alerts", a.id)
            st.rerun()


def _review() -> None:
    props = _proposals()
    if not props:
        return
    st.markdown("**Proposed alerts** — check bar size and condition; nothing is active until Accept.")
    for i, a in enumerate(props):
        with st.container(border=True):
            st.write(f"**{a.name}** · {a.describe()}")
            c = st.columns(4)
            a.bar_size = c[0].selectbox("Bar size", list(alerts.BAR_SIZES),
                                        index=list(alerts.BAR_SIZES).index(a.bar_size), key=f"al_bs_{i}")
            if a.level is not None and a.kind in ("price", "loss_limit", "funding"):
                a.level = c[1].number_input("Level", value=float(a.level), key=f"al_lv_{i}", format="%.4f")
            a.expires = c[2].text_input("Expiry (date)", a.expires, key=f"al_ex_{i}",
                                        placeholder="none")
            a.channels = c[3].multiselect("Channels", list(alerts.CHANNELS), default=a.channels,
                                          key=f"al_ch_{i}")
            d = st.columns(3)
            a.breakthrough = d[0].checkbox("May break through quiet hours", a.breakthrough, key=f"al_bt_{i}")
            a.ai_note = d[1].checkbox("AI note (one sentence of context)", a.ai_note, key=f"al_ai_{i}")
            if a.order_draft:
                a.attach_paper_order = d[2].checkbox("Attach paper order", a.attach_paper_order,
                                                     key=f"al_po_{i}",
                                                     help="Creates a *pending* paper order; it still waits for your Accept")
    c1, c2 = st.columns(2)
    if c1.button("Accept", type="primary", key="al_accept"):
        for a in props:
            alerts.accept(a)
        st.session_state["al_props"] = []
        st.success(f"{len(props)} alert(s) active.")
    if c2.button("Discard proposals", key="al_discard"):
        st.session_state["al_props"] = []
        st.rerun()


def _channels() -> None:
    with st.expander("Channels · quiet hours"):
        c = st.columns(3)
        qh = c[0].text_input("Quiet hours", config.get("alerts.quiet_hours", ""), key="al_qh",
                             placeholder="23:00-06:00")
        chat = c[1].text_input("Telegram chat id", config.get("alerts.telegram_chat_id", ""), key="al_tg")
        c[2].caption(f"Telegram bot token: {keys.masked('telegram_bot_token')} (Settings › Keys)")
        email = config.get("alerts.email", {}) or {}
        e = st.columns(3)
        to = e[0].text_input("Email address", email.get("to", ""), key="al_em_to")
        host = e[1].text_input("SMTP server", email.get("smtp_host", ""), key="al_em_host")
        port = e[2].number_input("SMTP port", 1, 65535, int(email.get("smtp_port", 587)), key="al_em_port")
        tok = st.text_input("Paste BotFather token (stored in the OS keychain)", type="password", key="al_tok")
        if st.button("Save channels", key="al_save_ch"):
            config.set_value("alerts.quiet_hours", qh.strip())
            config.set_value("alerts.telegram_chat_id", chat.strip())
            config.set_value("alerts.email", {"to": to.strip(), "smtp_host": host.strip(),
                                              "smtp_port": int(port)})
            if tok.strip():
                keys.set_key("telegram_bot_token", tok.strip())
            st.success("Saved. Send `/start` to your bot, then click Send test on an alert.")
        st.caption("Channels: Desktop (this lab) · Email · Telegram. Messages start with SIMULATED.")


def _active() -> None:
    rows = alerts.load_all()
    live = [a for a in rows if a.status in ("active", "fired", "expired", "paused")]
    if not live:
        st.caption("No alerts yet.")
        return
    st.markdown("**Alerts**")
    for a in live:
        c = st.columns([5, 1, 1])
        c[0].write(f"#{a.id} [{a.status.upper()}] {a.name} · {a.describe()}"
                   + (f" · expires {a.expires}" if a.expires else "")
                   + (" · paper order attached" if a.attach_paper_order else ""))
        if c[1].button("Send test", key=f"al_test_{a.id}"):
            msg, ok = alerts.send_test(a)
            st.info(f"{msg}\n\nDelivered: {', '.join(ok) or 'none (see alert log)'}")
        if a.status == "active" and c[2].button("Pause", key=f"al_pause_{a.id}"):
            a.status = "paused"
            alerts.save(a)
            st.rerun()


def _log() -> None:
    with st.expander("Alert log", expanded=False):
        rows = alerts.alert_log()
        if rows:
            st.dataframe(pd.DataFrame([{"When": r.get("at"), "Event": r.get("event"), "Alert": r.get("name"),
                                        "Bar": r.get("bar", ""), "Delivered": ", ".join(r.get("delivered") or []),
                                        "Message": r.get("message")} for r in rows]),
                         hide_index=True, width="stretch")
        else:
            st.caption("Every firing, test, hold and expiry appears here.")


def render() -> None:
    ui.page_header("Alerts", SECTION, "Rules checked in code on completed bars. Every message says SIMULATED.")
    ui.paper_only_note()
    mkt = ui.market()
    if st.button("New alert", key="al_new", type="primary"):
        st.session_state["al_open"] = True
    if st.session_state.get("al_open"):
        _new_alert(mkt)
    _review()
    _saved_proposals()
    _active()
    _channels()
    _log()
