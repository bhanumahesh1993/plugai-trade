"""Every Python block printed in the book must run as printed (offline, synthetic data)."""
import json
import textwrap
import warnings
from pathlib import Path

import pytest

SNIPS = json.loads((Path(__file__).parent / "book_snippets.json").read_text(encoding="utf-8"))
PY = [(i, s) for i, s in enumerate(SNIPS) if s["lang"] == "python"]

# [16] is the book's deliberately broken example (key in code, order request) — it must NOT run.
# [17] is a plugin test file; [15] a plugin module — both are covered by test_plugin.py.
SKIP = {16: "deliberately broken example", 15: "plugin module (test_plugin.py)",
        17: "plugin test file (test_plugin.py)"}
# Snippets that continue an earlier one share its namespace.
CHAIN = {21: 20}


def _code(i):
    return textwrap.dedent(SNIPS[i]["code"]).strip("\n` \t")


@pytest.mark.parametrize("i,snip", PY, ids=[f"{s['file']}[{i}]" for i, s in PY])
def test_snippet_runs(i, snip, capsys):
    if i in SKIP:
        pytest.skip(SKIP[i])
    ns: dict = {}
    warnings.simplefilter("ignore")
    if i in CHAIN:
        exec(compile(_code(CHAIN[i]), f"snippet{CHAIN[i]}", "exec"), ns)
    exec(compile(_code(i), f"snippet{i}", "exec"), ns)
