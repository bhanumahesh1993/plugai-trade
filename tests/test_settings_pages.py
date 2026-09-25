"""Settings › AI Models, Privacy, Security and Workspace, driven like a reader (offline)."""

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import ai, config, privacy, rulecard, scheduler, security, workspace


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)
    monkeypatch.setattr(ai, "_ollama_chat", lambda *a, **k: (_ for _ in ()).throw(
        ConnectionError("offline test")))


def page(module: str) -> AppTest:
    return AppTest.from_string(f"from plugai_trade.app.pages import {module} as m\nm.render()\n",
                               default_timeout=60).run()


def click(at: AppTest, label: str, key: str | None = None) -> AppTest:
    next(b for b in at.button if b.label == label and (key is None or b.key == key)).click()
    return at.run()


# ---------------------------------------------------------------- privacy
def test_strip_identifiers():
    t = ("PAN ABCPE1234F, SSN 123-45-6789, Aadhaar 2345 6789 0123, Account No: 004512345678, "
         "client code: ZX9921, me@x.com. NIFTY 24,788.50 qty 65 at 25000")
    out = privacy.strip_identifiers(t)
    for secret in ("ABCPE1234F", "123-45-6789", "2345 6789 0123", "004512345678", "ZX9921",
                   "me@x.com"):
        assert secret not in out
    assert "24,788.50" in out and "qty 65" in out and "25000" in out
    assert set(privacy.found_identifiers(t)) >= {"PAN", "SSN", "AADHAAR", "ACCOUNT", "EMAIL"}


def test_privacy_defaults_and_lag():
    assert privacy.defaults_on() and privacy.education_lag() == 90
    assert privacy.set_education_lag(10) == 30
    privacy.set_toggle("crash_reports", True)
    assert not privacy.defaults_on()
    assert privacy.cloud_payload("SSN 123-45-6789") == "SSN [SSN REMOVED]"


def test_privacy_page():
    at = page("privacy")
    assert not at.exception
    labels = [t.label for t in at.toggle]
    assert "Ask before sending to cloud" in labels
    assert [t.value for t in at.toggle] == [True, True, True, True, False]
    at.number_input(key="pv_lag").set_value(120).run()
    assert privacy.education_lag() == 120


# ---------------------------------------------------------------- AI models
def test_ai_models_page_routes_and_budget():
    at = page("ai_models")
    assert not at.exception
    labels = {b.label for b in at.button}
    assert {"Test model", "Pull model", "Add local server", "Add cloud model"} <= labels
    assert at.radio(key="aim_use_Tax").value == "Local only"
    assert at.radio(key="aim_use_Documents").value == "Local only"
    assert at.radio(key="aim_use_Journal").disabled        # Privacy keeps it local
    at.radio(key="aim_use_Research").set_value("Local only").run()
    assert config.get("ai.use_for.Research") == "Local only"
    at.number_input(key="aim_budget").set_value(4.0).run()
    assert config.get("ai.monthly_budget") == 4.0
    at = click(at, "Test model")
    assert any("Ollama not found" in w.value for w in at.warning)
    at = click(at, "Add local server")
    assert "http://localhost:1234/v1" in config.get("ai.local_servers")
    at = click(at, "Pull model", key="aim_pull")
    assert any("Pull model did not finish" in e.value for e in at.error)


# ---------------------------------------------------------------- security
def test_security_checklist_and_registers():
    items = security.checklist(date(2026, 9, 25))
    auto = [i for i in items if not i.manual]
    assert all(i.ok for i in auto), [(i.text, i.detail) for i in auto if not i.ok]
    assert sum(i.manual for i in items) == 4
    security.tick("2fa", True)
    assert next(i for i in security.checklist() if i.key == "2fa").ok
    assert not security.checklist(date(2027, 3, 1))[4].ok     # stale tables → update available
    urls = {r.url for m in security.REGISTERS for k in security.REG_TYPES
            for r in security.registers(m, k)}
    assert any("sebi.gov.in" in u for u in urls) and any("brokercheck.finra.org" in u for u in urls)
    assert any("nfa.futures.org" in u for u in urls) and any("adviserinfo.sec.gov" in u for u in urls)


def test_check_a_pitch_offline():
    pc = security.check_pitch("Our AI bot pays 3% a day, fixed! Seats closing tonight. "
                              "Deposit USDT to our wallet. Call 9876543210.")
    kinds = {f.kind for f in pc.flags}
    assert {"returns", "urgency", "custody", "technology"} <= kinds
    assert pc.compound and round(pc.compound[0][1]) == 1619
    assert "9876543210" not in pc.prompt and "UNTRUSTED" in pc.prompt
    assert pc.where == "Fallback"


def test_audit_log_cloud_filter_and_export():
    from plugai_trade.store import default as store
    store().audit("ai_call", {"section": "Research", "model": "gemini/x", "where": "Cloud",
                              "usd": 0.01})
    store().audit("ai_call", {"section": "Journal", "model": "local", "where": "Local"})
    assert len(security.audit_rows("Cloud")) == 1
    csv = security.export_log("Cloud")
    assert csv.splitlines()[0] == "time,kind,category,detail" and "gemini/x" in csv


def test_security_page():
    at = page("security")
    assert not at.exception
    assert any("Security checklist" in m.value for m in at.markdown)
    at.text_area(key="sec_pitch").input("Guaranteed 2% a day with our AI robot. Limited seats.")
    at = click(at, "Check a pitch")
    assert not at.exception
    assert any("Calculator test" in w.value for w in at.warning)
    at = click(at, "Export log")
    assert not at.exception


# ---------------------------------------------------------------- workspace
def test_workspace_preview_and_accept_per_group():
    pv = workspace.preview("Swing", "IN")
    assert pv.group("Scheduler jobs")[0] == "Daily Briefing · IN · Mon–Fri 08:40 IST"
    assert {j.job for j in pv.jobs} == {"Daily Briefing", "Weekly Review", "Backup",
                                        "Monthly update check"}
    workspace.accept(pv, "Pinned screens")
    assert workspace.pinned()[0] == "Screener"
    assert scheduler.jobs() == []                          # other groups untouched
    workspace.accept(pv, "Scheduler jobs")
    workspace.accept(pv, "Scheduler jobs")                 # idempotent
    assert len(scheduler.jobs()) == 4
    workspace.accept(pv, "Rule Card lines")
    suggested = [r for r in rulecard.current().rules if r["status"] == "suggested"]
    assert len(suggested) == 3
    us = workspace.preview("Mixed", "Both", {"US": "08:50"})
    assert "Daily Briefing · US · Mon–Fri 08:50 ET" in us.group("Scheduler jobs")


def test_export_has_no_keys_or_journal():
    config.set_value("keys_index", ["gemini_api_key"])
    import json
    out = workspace.export()
    body = json.loads(out)
    assert "keys_index" not in out and "gemini_api_key" not in out
    assert set(body) == {"plugai_trade", "exported", "settings", "pinned", "rhythm", "jobs",
                         "rule_card_lines", "note"}


def test_workspace_page_flow():
    at = page("workspace")
    at = click(at, "Apply template")
    at = click(at, "Preview changes")
    assert len([b for b in at.button if b.label == "Accept"]) == 4
    at = click(at, "Accept", key="ws_accept_Pinned screens")
    assert not at.exception and workspace.pinned()
    at = click(at, "Export workspace")
    assert not at.exception
