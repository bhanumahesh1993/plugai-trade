"""Plugins (Chapter 27): template, Plugin check in the book's format, scans, run in a process."""

import json
import re
import textwrap
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from plugai_trade import plugin


def _snippet(i: int) -> str:
    snips = json.loads((Path(__file__).parent / "book_snippets.json").read_text())
    return textwrap.dedent(snips[i]["code"])


def _gap_report() -> Path:
    """Snippets [15] + [17]: the gap report and its hand-checked test."""
    plugin.new("gap_report", "report")
    root = plugin.folder("gap_report")
    (root / "plugin.py").write_text(_snippet(15))
    (root / "tests" / "test_plugin.py").write_text(_snippet(17))
    return root


def test_new_creates_the_book_layout():
    msg = plugin.new("gap_report", "report")
    root = plugin.folder("gap_report")
    assert "gap_report" in msg
    for f in ("plugin.toml", "plugin.py", "tests/test_plugin.py", "AGENTS.md"):
        assert (root / f).exists(), f
    man = plugin.manifest("gap_report")
    assert man == {"name": "gap_report", "kind": "report", "markets": ["IN", "US"],
                   "entry": "plugin.py:gap_report", "network": [], "licence": "Apache-2.0"}
    assert "Never write code that places" in (root / "AGENTS.md").read_text()
    assert "already exists" in plugin.new("gap_report", "report")
    with pytest.raises(ValueError):
        plugin.new("Bad Name!", "report")


@pytest.mark.parametrize("kind", ["report", "strategy", "screen"])
def test_every_template_passes_its_own_check(kind):
    plugin.new(f"t_{kind}", kind)
    rep = plugin.check(f"t_{kind}")
    assert rep.passed, rep.text()
    if kind == "strategy":
        assert "scramble" in (plugin.folder(f"t_{kind}") / "tests" / "test_plugin.py").read_text()


def test_book_gap_report_passes_in_the_book_format():
    _gap_report()
    rep = plugin.check("gap_report")
    assert rep.passed, rep.text()
    expected = _snippet(19).strip().splitlines()
    got = rep.text().splitlines()
    assert len(got) == len(expected)
    for g, e in zip(got, expected):
        if e.startswith("Tests (pytest)"):
            assert re.fullmatch(r"Tests \(pytest\) \.{6} 1 passed in \d+\.\d\d s", g), g
        else:
            assert g == e


def test_book_test_catches_todays_close():
    root = _gap_report()
    code = (root / "plugin.py").read_text().replace('pl.col("close").shift(1)', 'pl.col("close")')
    (root / "plugin.py").write_text(code)
    rep = plugin.check("gap_report")
    assert not rep.passed and not rep.item("Tests (pytest)").ok
    assert "1 failed" in rep.item("Tests (pytest)").value


def test_negative_shift_fails_the_look_ahead_scan():
    root = _gap_report()
    code = (root / "plugin.py").read_text().replace(".shift(1)", ".shift(-1)")
    (root / "plugin.py").write_text(code)
    rep = plugin.check("gap_report")
    assert not rep.item("Look-ahead scan").ok and not rep.passed


def test_leaky_draft_is_blocked_on_sight():
    """Snippet [16]: key in code, today's close, an order request — never run."""
    plugin.new("gapdown_test", "strategy")
    (plugin.folder("gapdown_test") / "plugin.py").write_text(_snippet(16))
    rep = plugin.check("gapdown_test")
    assert not rep.passed
    for name in ("Order code", "Keys in code", "Look-ahead scan", "Packages", "Network"):
        assert not rep.item(name).ok, name
    assert rep.item("Tests (pytest)").value.startswith("not run")
    text = rep.text()
    assert "Plugin check failed" in text and "Network" in text
    assert plugin.enable("gapdown_test").endswith("run the Plugin check until it passes.")


def test_gpl_licence_and_skipped_tests_fail():
    root = _gap_report()
    man = (root / "plugin.toml").read_text().replace("Apache-2.0", "AGPL-3.0")
    (root / "plugin.toml").write_text(man)
    rep = plugin.check("gap_report")
    assert not rep.item("Licence").ok and "Licence" in rep.text()
    root2 = _gap_report()
    t = root2 / "tests" / "test_plugin.py"
    t.write_text("import pytest\n" + t.read_text().replace(
        "def test_gap", "@pytest.mark.skip\ndef test_gap"))
    (root2 / "plugin.toml").write_text(man.replace("AGPL-3.0", "Apache-2.0"))
    assert not plugin.check("gap_report").item("Tests (pytest)").ok


def test_window_signals_cannot_see_the_future():
    def peeker(bars):  # a leaky strategy: tomorrow's close
        return (pl.col("close").shift(-1) > pl.col("close")).cast(pl.Int8).alias("s")

    def leaky(bars):
        return bars.select(peeker(bars))["s"]

    bars = plugin.sample_bars(80)
    sig = plugin.window_signals(leaky, bars)
    assert sig["signal"].sum() == 0   # the last row of every window has no tomorrow


def test_run_in_own_process_and_enable():
    _gap_report()
    with pytest.raises(PermissionError):
        plugin.run("gap_report", "NIFTY", "IN")
    assert plugin.check("gap_report").passed
    res = plugin.run("gap_report", "NIFTY", "IN", start="2024-06-01", end="2026-05-29")
    assert res.table.columns == ["date", "prev_close", "open", "gap_pct", "filled"]
    assert (res.table["gap_pct"].abs() >= 0.5).all()
    assert plugin.enable("gap_report") == "gap_report enabled."
    assert plugin.status("gap_report")["enabled"]


def test_strategy_plugin_backtests_through_the_wall():
    plugin.new("ma_cross", "strategy")
    assert plugin.check("ma_cross").passed
    res = plugin.run("ma_cross", "SPY", "US", start="2024-01-01", end="2025-12-31")
    assert set(res.table["signal"].unique().to_list()) <= {0.0, 1.0}
    assert res.backtest is not None and res.backtest.card().grade


def test_cli_plugin_new_and_test():
    from plugai_trade.cli import app
    r = CliRunner().invoke(app, ["plugin", "new", "gap_report", "--kind", "report"])
    assert r.exit_code == 0 and "gap_report" in r.output
    r = CliRunner().invoke(app, ["plugin", "test", "gap_report"])
    assert r.exit_code == 0 and "Plugin check passed: ready to enable." in r.output


def test_plugins_screen_new_check_enable_run():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string("from plugai_trade.app.pages import plugins as m\nm.render()\n",
                             default_timeout=120)
    at.run()
    assert {"New from template", "Install"} <= {b.label for b in at.button}
    at.button(key="pl_new").click().run()
    for label in ("Open folder", "Run checks", "Enable"):
        assert label in [b.label for b in at.button]
    at.button(key="pl_check").click().run()
    assert any("Plugin check passed: ready to enable." in c.value for c in at.code)
    at.button(key="pl_enable").click().run()
    assert plugin.status("gap_report")["enabled"]
    at.button(key="pl_run").click().run()
    assert not at.exception and len(at.dataframe) == 1
