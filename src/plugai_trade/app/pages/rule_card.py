"""Plan & Risk › Rule Card — Written rules / Checklist / Go / no-go / Monthly audit.

New version saves a dated copy; Sync limits pushes the numbers to the Position
Sizer caps and the Paper Desk's daily loss limit and guardrails.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from plugai_trade import rulecard, sizing
from plugai_trade.app import ui
from plugai_trade.store import default as store

SECTION = "Plan & Risk"


def _card() -> rulecard.RuleCard:
    if "rc_card" not in st.session_state:
        st.session_state["rc_card"] = rulecard.current()
    return st.session_state["rc_card"]


def _numbers(card: rulecard.RuleCard) -> None:
    st.markdown("**Size & risk · Limits**")
    c = st.columns(4)
    card.account["IN"] = c[0].number_input("Account (IN, ₹)", 0.0, 1e11, card.account.get("IN", 0.0),
                                           10_000.0, key="rc_acc_in")
    card.account["US"] = c[1].number_input("Account (US, $)", 0.0, 1e10, card.account.get("US", 0.0),
                                           1_000.0, key="rc_acc_us")
    card.risk_pct = c[2].number_input("1R (% of account)", 0.0, 10.0, card.risk_pct * 100, 0.05,
                                      key="rc_risk") / 100
    card.position_cap_pct = c[3].number_input("Largest position (% of account)", 0.0, 500.0,
                                              card.position_cap_pct * 100, 1.0, key="rc_cap") / 100
    c = st.columns(4)
    card.open_risk_cap_r = c[0].number_input("Open risk cap (R)", 0.0, 50.0, card.open_risk_cap_r, 0.5, key="rc_open")
    card.group_cap_r = c[1].number_input("One correlated group (R)", 0.0, 50.0, card.group_cap_r, 0.5, key="rc_grp")
    card.daily_limit_r = c[2].number_input("Daily loss limit (R)", 0.0, 50.0, card.daily_limit_r, 0.5, key="rc_day")
    card.weekly_limit_r = c[3].number_input("Weekly loss limit (R)", 0.0, 100.0, card.weekly_limit_r, 0.5, key="rc_wk")
    rows = []
    for m in ("IN", "US"):
        lim = card.money_limits(m)
        rows.append({"Market": m, "1R": sizing.money(lim["one_r"], m),
                     "Daily limit": sizing.money(lim["daily"], m),
                     "Weekly limit": sizing.money(lim["weekly"], m),
                     "Largest position": sizing.money(lim["position_cap"], m)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _guardrails(card: rulecard.RuleCard) -> None:
    with st.expander("Intraday guardrails", expanded=False):
        c = st.columns(4)
        card.max_trades_day = int(c[0].number_input("Max trades a day", 0, 100, card.max_trades_day, 1, key="rc_max"))
        card.cooldown_min = int(c[1].number_input("Cooldown after a loss (min)", 0, 480, card.cooldown_min, 5, key="rc_cool"))
        card.window["IN"] = c[2].text_input("Trading window IST", card.window.get("IN", ""), key="rc_win_in")
        card.window["US"] = c[3].text_input("Trading window ET", card.window.get("US", ""), key="rc_win_us")
        c = st.columns(2)
        card.event_lockout_min = int(c[0].number_input("Event lockout (min before and after)", 0, 600,
                                                       card.event_lockout_min, 5, key="rc_lock"))
        types = rulecard.EVENT_TYPES["IN"] + rulecard.EVENT_TYPES["US"]
        card.event_types = c[1].multiselect("Event types to lock out", sorted(set(types)),
                                            default=[t for t in card.event_types if t in types], key="rc_types")
        st.caption("Add dated events (dates come from your calendar; one per line, "
                   "`YYYY-MM-DDTHH:MM name`).")
        txt = "\n".join(f"{e['when']} {e['name']}" for e in card.events)
        new = st.text_area("Events", txt, key="rc_events", height=80)
        card.events = [{"when": ln.split(" ", 1)[0], "name": (ln.split(" ", 1) + [""])[1] or "event"}
                       for ln in new.splitlines() if ln.strip()]


def _written(card: rulecard.RuleCard) -> None:
    _numbers(card)
    _guardrails(card)
    st.markdown("**Your written rules**")
    for i, r in enumerate(card.rules):
        a, b, c = st.columns([1.2, 6, 1.4])
        a.caption(r["group"])
        b.markdown(r["text"] if r["status"] == "accepted" else f"_{r['text']}_ · suggestion")
        if r["status"] == "suggested" and c.button("Accept", key=f"rc_acc_{i}"):
            r["status"] = "accepted"
            st.rerun()
        if r["status"] == "accepted" and c.button("Delete", key=f"rc_del_{i}"):
            card.rules.pop(i)
            st.rerun()
    c1, c2 = st.columns([3, 1])
    group = c2.selectbox("Group", list(rulecard.TEMPLATE_RULES), index=2, key="rc_grp_new")
    pasted = c1.text_area("Paste rule lines (one per line) — they arrive as suggestions", key="rc_paste",
                          height=80)
    if st.button("Add as suggestions", key="rc_add"):
        rulecard.suggest_rules(card, pasted.splitlines(), group)
        st.rerun()
    c1, c2 = st.columns(2)
    note = c1.text_input("What changed (dated in the history)", key="rc_note")
    if c1.button("New version", type="primary", key="rc_newver"):
        rulecard.new_version(card, note)
        st.success(f"Saved Rule Card version {card.version}.")
    if c2.button("Sync limits", key="rc_sync"):
        vals = rulecard.sync_limits(card)
        mk = ui.market()
        st.success(f"Position Sizer caps and the Paper Desk daily loss limit now match version "
                   f"{card.version}: daily limit {sizing.money(vals['paper.daily_loss_limit_by_market'][mk], mk)}, "
                   f"max {card.max_trades_day} trades a day, cooldown {card.cooldown_min} min.")
    adh = rulecard.adherence([r for r in store().all("journal")
                              if r.get("tag") in ("PAPER", "REPLAY", "PILOT")])
    if adh["score"] is not None:
        st.metric("Adherence score", f"{adh['score']:.1%}",
                  help=f"{adh['followed']} of {adh['decisions']} decisions; broken rows "
                       f"{adh['broken_rows'][:20]}")
    with st.expander("Version history"):
        hist = rulecard.history()
        st.dataframe(pd.DataFrame([{"version": h.get("version"), "written": h.get("written"),
                                    "note": h.get("note")} for h in hist]) if hist else pd.DataFrame(),
                     hide_index=True, width="stretch")


def _checklist(card: rulecard.RuleCard) -> None:
    st.markdown("**Pre-market checklist**")
    st.caption("Ticked items appear in the Daily Briefing's Questions for you.")
    for i, item in enumerate(card.checklist):
        item["ticked"] = st.checkbox(item["text"], item.get("ticked", True), key=f"rc_chk_{i}")
    new = st.text_input("Add a checklist item", key="rc_chk_new")
    if st.button("Add item", key="rc_chk_add") and new.strip():
        card.checklist.append({"text": new.strip(), "ticked": True})
        st.rerun()
    st.caption("Click New version on the Written rules tab to save checklist changes.")


def _gonogo(card: rulecard.RuleCard) -> None:
    c1, c2, c3 = st.columns(3)
    account = c1.segmented_control("Account", ["Paper", "Pilot"], default="Paper", key="rc_acct") or "Paper"
    start = c2.date_input("From", date.today() - timedelta(days=60), key="rc_from")
    end = c3.date_input("To", date.today(), key="rc_to")
    if st.button("Run check", type="primary", key="rc_run"):
        st.session_state["rc_gng"] = rulecard.go_no_go(account=account, marks=card.pass_marks,
                                                       start=str(start), end=str(end))
    g = st.session_state.get("rc_gng")
    if g:
        st.dataframe(pd.DataFrame([{"Measure": m.name, "Pass mark": m.pass_mark, "Value": m.value,
                                    "": "PASS" if m.passed else "NOT YET",
                                    "Rows": ", ".join(str(x) for x in m.rows[:10])}
                                   for m in g.measures]), hide_index=True, width="stretch")
        (st.success if g.verdict.startswith("GO") else st.warning)(f"Verdict: {g.verdict}")
        st.caption("Process measures only. Profit is deliberately not on this list.")
        ui.ai_block(g, key="rc_gng_ai", section=SECTION, sensitive=True)
    with st.expander("Save pilot plan", expanded=bool(g and g.verdict.startswith("GO"))):
        mk = ui.market()
        c = st.columns(3)
        budget = c[0].number_input("Pilot budget", 0.0, 1e9, 3 * card.one_r(mk), 100.0, key="rc_pb")
        tpd = int(c[1].number_input("Trades a day", 1, 20, 1, 1, key="rc_tpd"))
        review = c[2].date_input("Review date", date.today() + timedelta(weeks=6), key="rc_rev")
        size = st.text_input("Pilot size (from the Position Sizer › Use in plan)", key="rc_psize")
        stops = st.text_area("Stop conditions (one per line)",
                             "Pilot budget used up → stop\nDaily loss limit hit → stop for the day\n"
                             "A stop moved away from entry → back to paper", key="rc_stops")
        if st.button("Save pilot plan", key="rc_savepilot"):
            try:
                pid = rulecard.save_pilot_plan(mk, budget, tpd, str(review),
                                               [s for s in stops.splitlines() if s.strip()], size)
                st.success(f"Pilot plan saved (#{pid}). Real trades imported during the pilot are "
                           "tagged PILOT in Journal › Trades. The lab sends nothing to your broker.")
            except ValueError as exc:
                st.warning(str(exc))


def _audit() -> None:
    if st.button("Start audit", type="primary", key="rc_audit"):
        st.session_state["rc_audit_data"] = rulecard.start_audit()
    a = st.session_state.get("rc_audit_data")
    if not a:
        st.caption("First weekend of the month, about 45 minutes. Start with `plugai-trade update` "
                   "and `plugai-trade doctor`.")
        return
    st.caption(f"Monthly audit · {a['month']}")
    for i, it in enumerate(a["items"]):
        it["done"] = st.checkbox(f"**{it['item']}** — {it['hint']}", it["done"], key=f"rc_aud_{i}")
    if st.button("Save audit", key="rc_audit_save"):
        rulecard.save_audit(a)
        st.success("Audit saved to your reviews.")


def render() -> None:
    ui.page_header("Rule Card", SECTION, "Short, specific, checkable rules — read every morning.")
    card = _card()
    st.caption(f"Version {card.version}" + (f" · written {card.written[:10]}" if card.written else " · template"))
    t1, t2, t3, t4 = st.tabs(["Written rules", "Checklist", "Go / no-go", "Monthly audit"])
    with t1:
        _written(card)
    with t2:
        _checklist(card)
    with t3:
        _gonogo(card)
    with t4:
        _audit()
