"""Agents (Chapter 30): as-of wall, masking, budget, rule proposals, snippet [24]."""

import json
import textwrap
import tomllib
import warnings
from datetime import date
from pathlib import Path

import pytest

from plugai_trade import agents, ai
from plugai_trade.store import default as store

backtest = pytest.importorskip("plugai_trade.backtest",
                               reason="backtest package not importable yet (another agent builds it)")


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)
    monkeypatch.setattr(ai, "_ollama_chat", lambda *a, **k: (_ for _ in ()).throw(OSError()))


def _builtin(**kw):
    kw.setdefault("as_of", "2026-05-29")
    return agents.load("builtin", model="local", **kw)


def test_proposal_is_a_rule_never_an_order():
    prop = _builtin().propose("NIFTY", market="IN")
    assert prop.kind == "rule_proposal"
    for section in ("BULL CASE", "BEAR CASE", "RISK", "PROPOSAL · NOT AN ORDER"):
        assert section in prop.note
    spec = backtest.Spec.from_dict(prop.rules).validate()
    assert spec.origin == "agent"
    assert not any(w in prop.note.lower() for w in ("place_order", "you should buy", "sell now"))
    tools = {t.get("tool") for t in prop.transcript if t["kind"] == "tool"}
    assert tools == {"get_bars", "get_news", "get_filings", "run_backtest"}
    assert prop.trials_added == 1


def test_as_of_wall_and_masked_names():
    team = _builtin(as_of="2024-03-15", mask_names=True)
    prop = team.propose("NIFTY", market="IN")
    bars_chip = next(t for t in prop.transcript if t.get("tool") == "get_bars")
    assert bars_chip["args"] == {"subject": "Index A", "until": "t-0"}
    assert "NIFTY" not in prop.note and "Index A" in prop.note
    for ev in prop.transcript:
        assert "NIFTY" not in json.dumps(ev.get("data", []))
        assert "2024-03-1" not in json.dumps(ev.get("data", []))
    tools = agents.Tools("NIFTY", "IN", date(2024, 3, 15), True, lambda e: None)
    assert tools.bars()["date"].max() <= date(2024, 3, 15)


def test_budget_stops_and_never_overruns():
    prop = _builtin(budget={"max_steps": 5, "max_cost": 0.5}).propose("SPY", market="US")
    assert prop.steps == 5 and prop.stopped.startswith("step limit")
    assert prop.rules is None and "Run stopped" in prop.note
    b = agents.Budget(max_steps=10, max_cost=0.10)
    b.take("one")
    b.spend(0.06)
    with pytest.raises(agents.BudgetExceeded, match="cost cap"):
        b.take("two")     # 0.06 + worst step 0.06 would pass 0.10


def test_model_text_is_filtered_and_used(monkeypatch):
    calls = []

    def fake(prompt, section="Research", system=ai.SYSTEM, schema=None, sensitive=False):
        calls.append(prompt)
        assert "NIFTY" not in prompt       # masked before the model sees it
        if schema:
            return ai.Explanation(text=json.dumps({
                "text": "Enter on a close above the 100-day average; exit below the 50-day",
                "entry": [{"op": "above", "left": {"kind": "close"},
                           "right": {"kind": "sma", "n": 100}}],
                "exit": [{"op": "below", "left": {"kind": "close"},
                          "right": {"kind": "sma", "n": 50}}]}), cost_usd=0.01)
        text, _ = ai.output_filter("- trend is up\n- you should buy now")
        return ai.Explanation(text=text, cost_usd=0.01)

    monkeypatch.setattr(ai, "complete", fake)
    prop = _builtin().propose("NIFTY", market="IN")
    assert prop.rules["entry"][0]["right"]["n"] == 100
    assert "you should buy" not in prop.note
    assert prop.cost == pytest.approx(0.07) and len(calls) == 7


def test_uninstalled_plugin_falls_back_with_warning():
    with pytest.warns(UserWarning, match="not installed.*pinned tag"):
        team = agents.load("tradingagents", as_of="2026-05-29")
    assert team.name == "builtin" and team.requested == "tradingagents"
    plan = agents.install_plan("tradingagents")
    assert "github.com/TauricResearch/TradingAgents" in plan.repo
    assert plan.commands[0][:2] == ["git", "clone"] and "--branch" in plan.commands[0]
    assert "pypi" not in " ".join(" ".join(c) for c in plan.commands).lower()
    assert "run_backtest" in plan.text() and "no order" in plan.text()
    with pytest.raises(ValueError):
        agents.load("nonsense")


def test_config_file_matches_the_book():
    p = agents.write_config("tradingagents", as_of="2026-05-29")
    assert p.name == "tradingagents.toml" and p.parent.name == "agents"
    cfg = tomllib.loads(p.read_text(encoding="utf-8"))
    snips = json.loads((Path(__file__).parent / "book_snippets.json").read_text(encoding="utf-8"))
    assert cfg == tomllib.loads(snips[23]["code"])
    assert p.read_text(encoding="utf-8").splitlines()[2] == snips[23]["code"].splitlines()[2]


def test_send_to_builder_and_reject():
    prop = _builtin().propose("NIFTY", market="IN")
    rid = agents.propose_to_builder(prop)
    row = store().get("proposals", rid)
    assert row["tag"] == "PROPOSED" and row["status"] == "PROPOSED" and row["spec"] == prop.rules
    agents.reject(prop, "one-year result; revisit with a longer sample")
    assert store().count("proposals", tag="REJECTED") == 1
    assert "one-year result" in store().all("notes", tag="journal")[0]["text"]


def test_book_snippet_24_runs_offline(capsys):
    snips = json.loads((Path(__file__).parent / "book_snippets.json").read_text(encoding="utf-8"))
    code = textwrap.dedent(snips[24]["code"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        exec(compile(code, "snippet-24", "exec"), {})  # noqa: S102 - book snippet
    out = capsys.readouterr().out
    assert "BULL CASE" in out and "BEAR CASE" in out and "RISK" in out
    assert "REPORT CARD" in out and "Grade:" in out


def test_agents_screen_run_send_reject():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(
        "from plugai_trade import ai\nai.ollama_ok = lambda timeout=1.5: False\n"
        "ai._ollama_chat = lambda *a, **k: (_ for _ in ()).throw(OSError())\n"
        "from plugai_trade.app.pages import agents as m\nm.render()\n", default_timeout=120)
    at.run()
    assert {"Run", "Stop"} <= {b.label for b in at.button}
    at.button(key="ag_run").click().run()
    assert not at.exception
    assert any("PROPOSAL · NOT AN ORDER" in md.value for md in at.markdown)
    assert agents.config_path("builtin").exists()
    at.button(key="ag_send").click().run()
    assert store().count("proposals", tag="PROPOSED") == 1
    at.text_input(key="ag_reason").input("one-year result").run()
    at.button(key="ag_reject").click().run()
    assert store().count("proposals", tag="REJECTED") == 1
