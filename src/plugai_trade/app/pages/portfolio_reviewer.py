"""Portfolio › Portfolio Reviewer (Chapters 15 and 16).

Import holdings (CAS PDF read locally, broker CSV, generic CSV), then Holdings /
Overlap / Costs / Concentration / Allocation / ETF check / Income / SIP planner /
Thesis tracker. Every number is computed in ``plugai_trade.portfolio``; the AI
only explains, always on the local model (holdings are private).
"""

from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import portfolio as pf
from plugai_trade import reference
from plugai_trade.app import ui
from plugai_trade.portfolio import allocation, etf, funds, holdings, income, sip, thesis
from plugai_trade.store import default as store

AMBER = "background-color: #FEF3C7; color: #92400E"
SECTION = "Portfolio"
TABS = ["Holdings", "Overlap", "Costs", "Concentration", "Allocation", "ETF check", "Income",
        "SIP planner", "Thesis tracker"]


def _cur(market: str) -> str:
    return "₹" if market == "IN" else "$"


def _explain(obj, key: str) -> None:
    """Explain / Show sources / Second opinion — local model only (sensitive)."""
    ui.ai_block(obj, key, section=SECTION, sensitive=True)


# ------------------------------------------------------------------ import
def _holdings(market: str) -> list[holdings.Holding]:
    key = f"pr_holdings_{market}"
    if key not in st.session_state:
        st.session_state[key] = holdings.match(holdings.sample_holdings(market),
                                               funds.catalogue(market))
        st.session_state[f"{key}_label"] = "Sample portfolio (synthetic, lesson 15)"
    return st.session_state[key]


def _import_panel(market: str) -> None:
    with st.expander("Import holdings", expanded=False):
        st.caption("The file is read on your computer and never sent to an AI model.")
        up = st.file_uploader("CAS PDF, broker holdings CSV or generic CSV",
                              type=["pdf", "csv"], key="pr_upload")
        c1, c2 = st.columns(2)
        pwd = c1.text_input("CAS password", type="password", key="pr_pwd",
                            help="Often your PAN in capitals. Used only to open the file locally.")
        account = c2.text_input("Account type (US: 401(k), IRA, Brokerage)", key="pr_account")
        b1, b2 = st.columns(2)
        if b1.button("Import holdings", type="primary", key="pr_import"):
            if up is None:
                st.warning("Choose a file first.")
            else:
                _do_import(up, pwd, account, market)
        if b2.button("Load sample portfolio", key="pr_sample"):
            st.session_state.pop(f"pr_holdings_{market}", None)
            st.rerun()
    st.caption(f"Showing: {st.session_state.get(f'pr_holdings_{market}_label', '')}")


def _do_import(up, pwd: str, account: str, market: str) -> None:
    try:
        if up.name.lower().endswith(".pdf"):
            rows = holdings.read_cas_pdf(up.getvalue(), pwd)
        else:
            rows = holdings.parse_holdings_csv(up.getvalue().decode("utf-8", "ignore"), account)
    except Exception as exc:  # show the importer's message, keep the old table
        st.error(str(exc))
        return
    if not rows:
        st.warning("No holdings found in that file. Try the generic CSV template: "
                   "name, units, price, value, asset_class, account.")
        return
    key = f"pr_holdings_{market}"
    st.session_state[key] = holdings.match(rows, funds.catalogue(market))
    st.session_state[f"{key}_label"] = f"Imported: {up.name}"
    store().audit("holdings_import", {"file": up.name, "rows": len(rows), "market": market})
    st.success(f"Imported {len(rows)} holdings locally.")


# ------------------------------------------------------------------ Holdings
def _holdings_tab(market: str, rows: list[holdings.Holding], cat: dict) -> None:
    cur = _cur(market)
    df = pd.DataFrame([{"Name": h.name, "Units": h.units, "Price / NAV": h.price, "Value": h.value,
                        "Asset class": h.asset_class, "Account": h.account, "Plan": h.plan,
                        "Matched to": cat[h.match].name if h.match else "UNMATCHED"} for h in rows])
    st.dataframe(df.style.apply(lambda r: [AMBER if r["Matched to"] == "UNMATCHED" else ""] * len(r),
                                axis=1), hide_index=True, width="stretch")
    c1, c2, c3 = st.columns(3)
    c1.metric("Holdings", len(rows))
    c2.metric("Total value", pf.money(sum(h.value for h in rows), cur))
    c3.metric("Unmatched", sum(1 for h in rows if not h.matched))
    for i, h in enumerate(rows):
        if not h.matched:
            pick = st.selectbox(f"Match '{h.name}' by hand", ["—"] + list(cat),
                                format_func=lambda k: k if k == "—" else cat[k].name,
                                key=f"pr_match_{market}_{i}")
            if pick != "—":
                h.match, h.asset_class = pick, cat[pick].asset_class
                st.rerun()


# ------------------------------------------------------------------ Overlap
def _fund_list(market: str, rows: list[holdings.Holding], cat: dict) -> list[funds.Fund]:
    extra = st.session_state.get(f"pr_fundfiles_{market}", {})
    ids = list(dict.fromkeys(h.match for h in rows if h.match))
    fl = [cat[i] for i in ids if len(cat[i].holdings) > 1]
    return fl + list(extra.values())


def _overlap_tab(market: str, rows: list[holdings.Holding], cat: dict) -> None:
    st.caption("Overlap = share of money in the same companies (sum of the smaller weight). "
               "Uses each fund's latest published portfolio; the bundled funds are synthetic.")
    with st.expander("Add fund holdings file (AMFI monthly portfolio / fund-house CSV)"):
        f = st.file_uploader("Holdings CSV: company, weight (% to NAV), sector", type=["csv"],
                             key="pr_fundfile")
        nm = st.text_input("Fund name", key="pr_fundfile_name")
        if st.button("Add fund", key="pr_fundfile_add") and f and nm:
            try:
                fund = funds.parse_holdings_csv(f.getvalue().decode("utf-8", "ignore"),
                                                f"F{len(st.session_state.get(f'pr_fundfiles_{market}', {})) + 1}",
                                                nm, market=market)
                st.session_state.setdefault(f"pr_fundfiles_{market}", {})[fund.fund_id] = fund
                st.success(f"Added {nm}: {len(fund.holdings)} companies.")
            except ValueError as exc:
                st.error(str(exc))
    fl = _fund_list(market, rows, cat)
    if len(fl) < 2:
        st.info("Overlap needs at least two funds with look-through holdings.")
        return
    cells = []
    for a in fl:
        for b in fl:
            top = ", ".join(f"{c} {w:.1f}%" for c, w in funds.shared(a.holdings, b.holdings, 5))
            cells.append({"row": a.name, "col": b.fund_id, "overlap": round(funds.overlap(a.holdings, b.holdings)),
                          "shared": top})
    cdf = pd.DataFrame(cells)
    base = alt.Chart(cdf).encode(x=alt.X("col:N", title=None, sort=[f.fund_id for f in fl]),
                                 y=alt.Y("row:N", title=None, sort=[f.name for f in fl]))
    heat = base.mark_rect().encode(color=alt.Color("overlap:Q", scale=alt.Scale(scheme="purples"),
                                                   legend=None),
                                   tooltip=["row", "col", "overlap", "shared"])
    text = base.mark_text().encode(text="overlap:Q", color=alt.condition(
        "datum.overlap > 60", alt.value("white"), alt.value("#1E1B4B")))
    st.altair_chart((heat + text).properties(height=48 * len(fl) + 20), width="stretch")
    mat = funds.overlap_matrix(fl)
    _explain(_OverlapFacts(fl), f"pr_overlap_{market}")
    st.download_button("Export CSV", mat.write_csv(), "overlap.csv", key="pr_overlap_csv")


class _OverlapFacts:
    def __init__(self, fl: list[funds.Fund]):
        self.fl = fl

    def facts(self) -> list[str]:
        out = [f"Funds: {', '.join(f.name for f in self.fl)}"]
        for a, b in funds.pairs_of(self.fl):
            out.append(f"Overlap {a.name} ↔ {b.name}: {funds.overlap(a.holdings, b.holdings):.0f}%")
        return out


# ------------------------------------------------------------------ Costs
def _costs_tab(market: str, rows: list[holdings.Holding], cat: dict) -> None:
    cur = _cur(market)
    pos = [(cat[h.match], h.value, h.plan or ("Regular" if market == "IN" else "—"))
           for h in rows if h.match]
    audit = funds.cost_audit(pos, cur)
    st.dataframe(audit.frame().to_pandas(), hide_index=True, width="stretch")
    c1, c2, c3 = st.columns(3)
    c1.metric("Weighted expense now", f"{audit.weighted_ter:.2f}%", pf.money(audit.annual, cur) + " a year",
              delta_color="off")
    if market == "IN":
        c2.metric("Direct-plan equivalent", f"{audit.weighted_direct_ter:.2f}%",
                  pf.money(audit.direct_annual, cur) + " a year", delta_color="off")
        c3.metric("Annual difference", pf.money(audit.annual - audit.direct_annual, cur))
        st.caption("Switching to direct plans can trigger capital-gains tax and exit loads. "
                   "New SIP money can switch at once; old units are a tax judgment for you or your CA.")
    st.markdown("**What an expense-ratio gap does over time** (illustrative assumption, held constant)")
    d = (1_000_000, 15, 10.0, 0.6, 1.6) if market == "IN" else (50_000, 25, 8.0, 0.05, 0.75)
    k = st.columns(5)
    amt = k[0].number_input("Amount", value=float(d[0]), step=1000.0, key=f"pr_fg_amt_{market}")
    yrs = k[1].number_input("Years", value=d[1], step=1, key=f"pr_fg_y_{market}")
    gross = k[2].number_input("Assumed return % (before fees)", value=d[2], key=f"pr_fg_r_{market}")
    lo = k[3].number_input("Cheaper fee %", value=d[3], key=f"pr_fg_lo_{market}")
    hi = k[4].number_input("Dearer fee %", value=d[4], key=f"pr_fg_hi_{market}")
    a, b = funds.fee_gap(amt, int(yrs), gross / 100, lo / 100, hi / 100)
    st.write(f"Cheaper fund: **{pf.money(a, cur)}** · Dearer fund: **{pf.money(b, cur)}** · "
             f"Difference: **{pf.money(a - b, cur)}** — HYPOTHETICAL")
    _explain(audit, f"pr_costs_{market}")


# ------------------------------------------------------------------ Concentration
def _concentration_tab(market: str, rows: list[holdings.Holding], cat: dict) -> None:
    pos = [(cat[h.match], h.value) for h in rows if h.match and len(cat[h.match].holdings) > 1]
    if not pos:
        st.info("No look-through holdings yet.")
        return
    lt = funds.look_through(pos)
    c1, c2, c3 = st.columns(3)
    c1.metric("Companies (look-through)", lt.companies)
    c2.metric("Largest single company", f"{lt.top(1)[0][1]:.1%}")
    c3.metric("Top 10", f"{lt.top10_share:.1%}")
    left, right = st.columns(2)
    left.dataframe(pd.DataFrame([{"Company": c, "Share": f"{s:.2%}"} for c, s in lt.top(10)]),
                   hide_index=True, width="stretch")
    sec = pd.DataFrame([{"Sector": s, "Share %": round(v / lt.total * 100, 1)}
                        for s, v in sorted(lt.sectors.items(), key=lambda kv: -kv[1])])
    right.altair_chart(alt.Chart(sec).mark_bar(color="#7C3AED").encode(
        x="Share %:Q", y=alt.Y("Sector:N", sort="-x", title=None)).properties(height=260),
        width="stretch")
    _explain(lt, f"pr_conc_{market}")


# ------------------------------------------------------------------ Allocation
def _sleeves(rows: list[holdings.Holding]) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in rows:
        out[h.asset_class] = out.get(h.asset_class, 0.0) + h.value
    return out


def _default_target(market: str, sleeves: list[str]) -> dict[str, float]:
    """The book's examples (60/30/10 IN, 60/20/20 US) when the sleeves match, else equal."""
    book = ({"Equity": 60.0, "Debt": 30.0, "Gold": 10.0} if market == "IN"
            else {"US stocks": 60.0, "Intl": 20.0, "Bonds": 20.0})
    if set(sleeves) == set(book):
        return book
    even = round(100 / len(sleeves), 1)
    out = {s: even for s in sleeves}
    out[sleeves[-1]] = round(100 - even * (len(sleeves) - 1), 1)
    return out


def _allocation_tab(market: str, rows: list[holdings.Holding]) -> None:
    cur = _cur(market)
    values = _sleeves(rows)
    tkey = f"pr_target_{market}"
    if tkey not in st.session_state:
        st.session_state[tkey] = (_default_target(market, list(values)), 5.0)
    if st.button("Set target", key=f"pr_set_target_{market}"):
        st.session_state[f"{tkey}_edit"] = True
    if st.session_state.get(f"{tkey}_edit"):
        with st.form(f"pr_target_form_{market}"):
            tgt = {s: st.number_input(f"{s} target %", 0.0, 100.0, float(st.session_state[tkey][0].get(s, 0.0)),
                                      key=f"pr_t_{market}_{s}") for s in values}
            band = st.number_input("Band (± points)", 0.5, 25.0, float(st.session_state[tkey][1]),
                                   key=f"pr_band_{market}")
            if st.form_submit_button("Save target"):
                st.session_state[tkey] = (tgt, band)
                st.session_state[f"{tkey}_edit"] = False
                store().add("plans", {"kind": "allocation_target", "market": market,
                                      "target": tgt, "band": band}, tag="allocation")
                st.rerun()
    tgt, band = st.session_state[tkey]
    total_t = sum(tgt.values())
    if abs(total_t - 100) > 0.05:
        st.warning(f"Target adds up to {total_t:.1f}%, not 100%. Click Set target.")
        return
    monthly = st.number_input(f"Monthly new money ({cur})", 0.0, value=0.0, step=1000.0,
                              key=f"pr_newmoney_{market}")
    alloc = allocation.drift(values, {k: v / 100 for k, v in tgt.items()}, band / 100, monthly, cur)
    df = pd.DataFrame(alloc.rows())
    chart = pd.DataFrame([{"Sleeve": r["Sleeve"], "kind": k, "pct": r[k],
                           "out": r["Status"] != "inside"} for r in alloc.rows()
                          for k in ("Target %", "Now %")])
    st.altair_chart(alt.Chart(chart).mark_bar().encode(
        x=alt.X("kind:N", title=None), y=alt.Y("pct:Q", title="%"), column=alt.Column("Sleeve:N"),
        color=alt.condition("datum.out && datum.kind == 'Now %'", alt.value("#F59E0B"),
                            alt.value("#7C3AED"))).properties(width=90, height=200))
    st.dataframe(df.style.apply(lambda r: [AMBER if r["Status"] != "inside" else ""] * len(r), axis=1),
                 hide_index=True, width="stretch")
    if st.button("Rebalance checklist", key=f"pr_rebal_{market}"):
        st.session_state[f"pr_rebal_show_{market}"] = True
    if st.session_state.get(f"pr_rebal_show_{market}"):
        _rebalance(alloc, cur)
    _explain(alloc, f"pr_alloc_{market}")


def _rebalance(alloc: allocation.Allocation, cur: str) -> None:
    st.markdown("**Rebalance checklist**")
    for i, item in enumerate(allocation.CHECKLIST, 1):
        st.markdown(f"{i}. {item}")
    out = [r for r in alloc.rows() if r["Status"] != "inside"]
    if out:
        st.write("Sleeves outside their bands:")
        st.dataframe(pd.DataFrame(out)[["Sleeve", "Drift (pts)", "To target", "Months of new money"]],
                     hide_index=True)
    else:
        st.write("No sleeve is outside its band.")
    with st.expander("Lots for a sale (estimate, Draft for your CA / CPA)"):
        lots = st.data_editor(pd.DataFrame({"bought": [date(2024, 4, 1)], "units": [100.0],
                                            "cost": [50.0]}), num_rows="dynamic", key="pr_lots")
        c1, c2 = st.columns(2)
        units = c1.number_input("Units to sell", 0.0, value=50.0, key="pr_sell_units")
        price = c2.number_input("Price / NAV", 0.0, value=60.0, key="pr_sell_price")
        lot_objs = [allocation.Lot(pd.Timestamp(r.bought).date(), float(r.units), float(r.cost))
                    for r in lots.dropna().itertuples()]
        if lot_objs:
            st.dataframe(pd.DataFrame(allocation.sale_lots(lot_objs, units, price)), hide_index=True)
    st.caption("The lab places no orders; you act in your own broker or fund account.")


# ------------------------------------------------------------------ ETF check
def _etf_tab(market: str) -> None:
    cur = _cur(market)
    key = f"pr_etfs_{market}"
    if key not in st.session_state:
        st.session_state[key] = etf.sample_etfs(market)
    c1, c2 = st.columns([3, 1])
    name = c1.text_input("ETF name or ticker", key=f"pr_etf_name_{market}")
    if c2.button("Add ETF", key=f"pr_etf_add_{market}") and name:
        stand_in = etf.stand_in(name, st.session_state[key][0])
        st.session_state[key] = [*st.session_state[key][-1:], stand_in]
        st.info("No free NAV / iNAV source is connected for this fund, so a synthetic stand-in is "
                "shown. Connect AMFI NAV / NSE bhavcopy (IN) or yfinance (US) in Data Sources.")
    pair = st.session_state[key][-2:]
    checks = [e.check() for e in pair]
    for col, chk in zip(st.columns(len(checks)), checks, strict=True):
        col.markdown(f"**{chk.name}**")
        for label, val in chk.tiles().items():
            col.metric(label, val)
    st.markdown("**Cost of the gap**")
    d = (500_000.0, 10, 12.40) if market == "IN" else (50_000.0, 10, 10.0)
    k = st.columns(3)
    amount = k[0].number_input(f"Investment ({cur})", value=d[0], step=10_000.0, key=f"pr_etf_amt_{market}")
    years = k[1].number_input("Horizon (years)", value=d[1], key=f"pr_etf_yrs_{market}")
    idx_r = k[2].number_input("Index total return % a year (assumed)", value=d[2], key=f"pr_etf_idx_{market}")
    ra = idx_r / 100 + (checks[0].td[1] or 0.0)
    rb = idx_r / 100 + (checks[1].td[1] or 0.0)
    a, b, gap = etf.cost_of_gap(amount, int(years), ra, rb)
    st.write(f"{checks[0].name}: **{pf.money(a, cur)}** · {checks[1].name}: **{pf.money(b, cur)}** · "
             f"Cost of the gap: **{pf.money(gap, cur)}** (HYPOTHETICAL, returns held constant)")
    _premium_chart(pair[-1], market, cur)
    _explain(_EtfFacts(checks, gap, cur), f"pr_etf_{market}")
    if st.button("Save to thesis", key=f"pr_etf_save_{market}"):
        store().add("theses", {"kind": "etf_comparison", "market": market,
                               "funds": [c.name for c in checks],
                               "tiles": [c.tiles() for c in checks], "cost_of_gap": gap,
                               "amount": amount, "years": years}, tag="etf")
        st.success("Saved to the Thesis tracker; next month's review can check whether the gap held.")


class _EtfFacts:
    def __init__(self, checks: list[etf.EtfCheck], gap: float, cur: str):
        self.checks, self.gap, self.cur = checks, gap, cur

    def facts(self) -> list[str]:
        out = [f for c in self.checks for f in c.facts()]
        return out + [f"Cost of the gap: {pf.money(self.gap, self.cur)}"]


def _premium_chart(e: etf.SyntheticEtf, market: str, cur: str) -> None:
    st.markdown("**Premium today** (market price vs iNAV, 5-minute points)")
    thr = st.number_input("Flag above (%)", 0.1, 5.0, etf.PREMIUM_THRESHOLD * 100, 0.1,
                          key=f"pr_prem_thr_{market}")
    times = etf.session_times(len(e.intraday_premium))
    df = pd.DataFrame({"time": times, "premium %": [round(p * 100, 2) for p in e.intraday_premium]})
    df["flag"] = df["premium %"] > thr
    line = alt.Chart(df).mark_line(color="#7C3AED").encode(x=alt.X("time:O", title=None,
                                                                   axis=alt.Axis(labelOverlap=True)),
                                                           y=alt.Y("premium %:Q"))
    pts = alt.Chart(df[df["flag"]]).mark_point(color="#F59E0B", filled=True).encode(x="time:O", y="premium %:Q")
    rule = alt.Chart(pd.DataFrame({"y": [thr]})).mark_rule(strokeDash=[4, 3], color="#F59E0B").encode(y="y:Q")
    st.altair_chart((line + pts + rule).properties(height=220), width="stretch")
    inav = 100.90
    now = float(e.intraday_premium[-1])
    peak = float(max(e.intraday_premium))
    if peak * 100 > thr:
        st.warning(f"Premium reached {peak:.2%} today, above your {thr:.1f}% threshold. "
                   f"Reference limit price = iNAV {cur}{inav:,.2f} (synthetic). Nothing is placed.")
    st.caption(f"Latest premium {now:+.2%}. Buying {pf.money(200_000 if market == 'IN' else 20_000, cur)} "
               f"at the peak premium pays about "
               f"{pf.money(etf.premium_cost(200_000 if market == 'IN' else 20_000, inav * (1 + peak), inav), cur)} "
               "above fair value.")


# ------------------------------------------------------------------ Income
def _income_tab(market: str) -> None:
    cur = _cur(market)
    held = income.sample_income(market)
    st.caption("Last 12 months of dividends (synthetic sample until a free dividend source is "
               "connected). Payout and cash cover are computed in code.")
    hp = market == "US" and st.checkbox("Holding-period check", key="pr_hp_check")
    df = pd.DataFrame([h.row(hp) for h in held])
    st.dataframe(df.style.apply(lambda r: [AMBER if str(r["Safety"]).startswith("⚠") else ""] * len(r),
                                axis=1), hide_index=True, width="stretch")
    st.markdown("**Yield vs price** (synthetic dividend payer; dashed = yield up only because price fell)")
    ser = pd.DataFrame(income.yield_trap_series())
    price = alt.Chart(ser).mark_line(color="#334155").encode(x=alt.X("month:Q"), y=alt.Y("price:Q", title=f"Price {cur}"))
    yl = alt.Chart(ser).mark_line(color="#7C3AED", strokeDash=[4, 3]).encode(
        x="month:Q", y=alt.Y("yield_pct:Q", title="Trailing yield %"))
    st.altair_chart(alt.vconcat(price.properties(height=140), yl.properties(height=140)),
                    width="stretch")
    st.markdown("**Tax profile**")
    if market == "IN":
        c1, c2 = st.columns(2)
        slab = c1.number_input("Your slab rate %", 0.0, 45.0, 30.0, key="pr_slab")
        cess_default = (pf.cess_rate() or 0.04) * 100
        cess = c2.number_input("Cess %", 0.0, 10.0, cess_default, key="pr_cess")
        if pf.cess_rate() is None:
            c2.caption("Cess is not in the dated table yet; confirm the rate (Appendix A).")
        summ = income.summarise(held, "IN", slab=slab / 100, cess=cess / 100)
    else:
        c1, c2, c3 = st.columns(3)
        bracket = c1.number_input("Your bracket %", 0.0, 40.0, 22.0, key="pr_bracket")
        qualified = c2.checkbox("Expect qualified dividends", True, key="pr_qual")
        rates = list(reference.lookup("us.tax.long_term", [0.0, 0.15, 0.20]))
        qrate = c3.selectbox("Qualified rate", rates, index=1, format_func=lambda r: f"{r:.0%}",
                             key="pr_qrate")
        niit = st.checkbox("Add NIIT (3.8%, top brackets)", key="pr_niit")
        summ = income.summarise(held, "US", bracket=bracket / 100, qualified=qualified,
                                qualified_rate=qrate, niit=niit, check_holding_period=hp)
    t1, t2 = st.columns(2)
    t1.metric("Gross income (12m)", pf.money(summ.gross, cur))
    t2.metric("After-tax income", pf.money(summ.net, cur), summ.profile, delta_color="off")
    _explain(summ, f"pr_income_{market}")


# ------------------------------------------------------------------ SIP planner
def _sip_tab(market: str) -> None:
    cur = _cur(market)
    goal_mode = st.toggle("Goal mode", key=f"pr_sip_goal_{market}")
    c = st.columns(3)
    monthly = c[0].number_input(f"Monthly amount ({cur})", 0.0, value=10_000.0 if market == "IN" else 500.0,
                                step=500.0, key=f"pr_sip_m_{market}")
    years = int(c[1].number_input("Years", 1, 50, 20 if market == "IN" else 25, key=f"pr_sip_y_{market}"))
    c[2].date_input("Start date", date.today(), key=f"pr_sip_start_{market}")
    goal = None
    if goal_mode:
        goal = st.number_input(f"Target amount ({cur}, at today's prices if Inflation > 0)", 0.0,
                               value=5_000_000.0 if market == "IN" else 300_000.0, step=10_000.0,
                               key=f"pr_sip_goal_amt_{market}")
    st.caption("Assumed return — **illustrative**, not forecasts; real returns vary and can be "
               "negative for years.")
    r = st.columns(3)
    rets = tuple(r[i].number_input(f"Assumed return {i + 1} (%)", -20.0, 30.0, d,
                                   key=f"pr_sip_r{i}_{market}") / 100
                 for i, d in enumerate((6.0, 8.0, 10.0)))
    o = st.columns(4)
    inflation = o[0].number_input("Inflation %", 0.0, 20.0, 0.0, key=f"pr_sip_inf_{market}") / 100
    step = o[1].number_input("Step-up % a year", 0.0, 50.0, 0.0, key=f"pr_sip_step_{market}") / 100
    p_start = int(o[2].number_input("Pause from month", 0, 600, 0, key=f"pr_sip_ps_{market}"))
    p_len = int(o[3].number_input("Pause (months)", 0, 120, 0, key=f"pr_sip_pl_{market}"))
    pause = (p_start, p_len) if p_start and p_len else None
    plan = sip.SipPlan(monthly, years, rets, step, inflation, pause, goal, cur)
    months = list(range(1, years * 12 + 1))
    chart = pd.DataFrame({"month": months,
                          **{f"{x:.0%} assumed": sip.path(monthly, years, x, step, pause) for x in rets},
                          "invested": pd.Series(sip.schedule(monthly, years, step, pause)).cumsum()})
    ui.line_chart(chart, "month", [c for c in chart.columns if c != "month"],
                  title=f"{cur}{monthly:,.0f} a month · value under each assumption", hypothetical=True)
    st.dataframe(pd.DataFrame(plan.table()), hide_index=True, width="stretch")
    _explain(plan, f"pr_sip_{market}")
    if st.button("Save plan", key=f"pr_sip_save_{market}"):
        store().add("plans", {**plan.to_record(), "market": market, "saved": date.today().isoformat()},
                    tag="sip")
        st.success("Saved with today's date. Next year's review compares what happened with what you assumed.")


# ------------------------------------------------------------------ Thesis tracker
def _thesis_tab(market: str, rows: list[holdings.Holding]) -> None:
    saved = thesis.load_all()
    if not saved:
        thesis.save(thesis.sample_thesis())
        saved = thesis.load_all()
    if st.button("Add thesis", key="pr_add_thesis"):
        st.session_state["pr_thesis_new"] = True
    if st.session_state.get("pr_thesis_new"):
        _new_thesis(rows)
    ids = {tid: t for tid, t in saved}
    tid = st.selectbox("Thesis", list(ids), format_func=lambda i: ids[i].holding, key="pr_thesis_pick")
    t = ids[tid]
    st.markdown(f"**{t.holding}** — Why I own it: {t.why}")
    if st.button("Check thesis", key="pr_check_thesis", type="primary"):
        st.session_state["pr_thesis_checked"] = tid
    if st.session_state.get("pr_thesis_checked") == tid:
        df = pd.DataFrame(t.check())
        st.dataframe(df.style.apply(lambda r: [AMBER if r["Status"] == "⚠ review" else ""] * len(r), axis=1),
                     hide_index=True, width="stretch")
        if t.tripped:
            st.warning(f"{t.tripped} condition tripped — a prompt to look, not a sale.")
    with st.expander("Add figures (or Accept them from the Document Desk)"):
        c = st.columns(4)
        q = c[0].text_input("Quarter", "2026-Q3", key="pr_fig_q")
        m = c[1].selectbox("Metric", [x.metric for x in t.conditions], key="pr_fig_m")
        v = c[2].number_input("Value", value=0.0, key="pr_fig_v")
        s = c[3].text_input("Source (page / table)", key="pr_fig_s")
        if st.button("Add figure", key="pr_fig_add"):
            t.figures.append({"quarter": q, "metric": m, "value": v, "source": s})
            thesis.save(t, tid)
            st.rerun()
    _explain(t, f"pr_thesis_{tid}")
    note = st.text_area("Your decision (for the journal)", key="pr_thesis_note")
    if st.button("Add note to journal", key="pr_thesis_journal") and note.strip():
        thesis.add_note_to_journal(note.strip(), t.holding)
        st.success("Added to your journal. The lab places no orders.")


def _new_thesis(rows: list[holdings.Holding]) -> None:
    with st.form("pr_thesis_form"):
        names = [h.name for h in rows] or ["(type a holding)"]
        holding = st.selectbox("Holding", names)
        why = st.text_area("Why I own it")
        conds = st.data_editor(pd.DataFrame({"metric": ["revenue_growth_pct"], "comparison": [">="],
                                             "threshold": [10.0]}), num_rows="dynamic",
                               column_config={"comparison": st.column_config.SelectboxColumn(
                                   options=list(thesis.OPS))}, key="pr_thesis_conds")
        if st.form_submit_button("Save thesis"):
            cs = [thesis.Condition(str(r.metric), str(r.comparison), float(r.threshold))
                  for r in conds.dropna().itertuples()]
            thesis.save(thesis.Thesis(holding, why, cs))
            st.session_state["pr_thesis_new"] = False
            st.rerun()


# ------------------------------------------------------------------ page
def render() -> None:
    """Portfolio Reviewer."""
    ui.page_header("Portfolio Reviewer", "Portfolio",
                   "Holdings stay on this computer · AI uses the local model only")
    market = ui.market()
    _import_panel(market)
    rows = _holdings(market)
    cat = funds.catalogue(market)
    cat.update(st.session_state.get(f"pr_fundfiles_{market}", {}))
    tabs = st.tabs(TABS)
    with tabs[0]:
        _holdings_tab(market, rows, cat)
    with tabs[1]:
        _overlap_tab(market, rows, cat)
    with tabs[2]:
        _costs_tab(market, rows, cat)
    with tabs[3]:
        _concentration_tab(market, rows, cat)
    with tabs[4]:
        _allocation_tab(market, rows)
    with tabs[5]:
        _etf_tab(market)
    with tabs[6]:
        _income_tab(market)
    with tabs[7]:
        _sip_tab(market)
    with tabs[8]:
        _thesis_tab(market, rows)
    ui.paper_only_note()
