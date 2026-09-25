"""Book snippets [12] (Ch 22) and [13] (Ch 23) run as printed, offline."""

import json
import textwrap
from pathlib import Path

import pytest

SNIPPETS = json.loads((Path(__file__).parent / "book_snippets.json").read_text())


@pytest.mark.parametrize("idx", [12, 13])
def test_snippet_runs(idx, capsys):
    code = textwrap.dedent(SNIPPETS[idx]["code"])
    assert "options" in code
    exec(compile(code, f"snippet_{idx}", "exec"), {})
    out = capsys.readouterr().out
    if idx == 12:
        assert "Breakeven: 25,089" in out and "IV rank 29" in out and "P&L per lot" in out
