"""The mechanical red-flag scans of the Plugin check (Chapter 27, "Red flags").

Each scan returns a list of :class:`Hit` (file, line, text, why). An empty list
means the scan is clean. They are deliberately simple and conservative: one hit
is not always a bug, but it is always a question before the plugin may run.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .. import paper_guard

ALLOWED_PACKAGES = {"polars", "numpy", "pandas", "plugai_trade", "math", "statistics", "datetime",
                    "typing", "dataclasses", "collections", "functools", "itertools", "decimal",
                    "__future__"}
TEST_ONLY_PACKAGES = {"pytest"}
PERMISSIVE_LICENCES = {"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD",
                       "Unlicense", "CC0-1.0"}
NETWORK_MODULES = {"requests", "httpx", "urllib", "urllib3", "http", "socket", "aiohttp",
                   "websocket", "websockets", "ftplib", "smtplib"}

_ORDER_EXTRA = re.compile(
    r"""['"][^'"]*/orders?\b|\b(place|submit|modify|cancel)_?orders?\s*\(|\bkite\.orders?\b""",
    re.IGNORECASE)
_KEY_ASSIGN = re.compile(
    r"""\b\w*(api_?key|key|token|secret|password|passwd|bearer)\w*\s*[:=]\s*['"][^'"\s]{6,}['"]""",
    re.IGNORECASE)
_KEY_SHAPE = re.compile(
    r"""['"](sk-[A-Za-z0-9_-]{10,}|AKIA[0-9A-Z]{12,}|ghp_[A-Za-z0-9]{20,}|xox[bp]-[A-Za-z0-9-]{10,}"""
    r"""|kite_[A-Za-z0-9._-]{6,}|eyJ[A-Za-z0-9_-]{20,})""")
_AUTH_LITERAL = re.compile(r"""['"]Authorization['"]\s*:\s*['"][^'"]+['"]""", re.IGNORECASE)
_KEY_ACCESS = re.compile(r"plugai_trade\.keys|from\s+plugai_trade\s+import\s+[^\n]*\bkeys\b|"
                         r"\bkeyring\b|os\.environ|getenv\(|['\"]\.env['\"]")
_NEG_SHIFT = re.compile(r"shift\(\s*(periods\s*=\s*)?-\s*\d|shift\(\s*-\s*\w")
_LOOKAHEAD = re.compile(r"center\s*=\s*True|lookahead_on|\.bfill\(|backward_fill|"
                        r"fill_null\(\s*strategy\s*=\s*['\"]backward")
_SAME_ROW = re.compile(r"""col\(\s*['"]open['"]\s*\)\s*/\s*(pl\.)?col\(\s*['"]close['"]\s*\)(?!\s*\.shift)""")
_URL = re.compile(r"https?://([A-Za-z0-9.-]+)")
_SKIPPED = re.compile(r"pytest\.mark\.skip|pytest\.skip\(|unittest\.skip|except\s*:\s*pass|"
                      r"except\s+Exception\s*:\s*pass")


@dataclass
class Hit:
    """One red flag: where it is and why it matters."""

    file: str
    line: int
    text: str
    why: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.why} — {self.text}"


def py_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*.py") if "__pycache__" not in p.parts)


def is_test(folder: Path, f: Path) -> bool:
    return "tests" in f.relative_to(folder).parts


def _lines(folder: Path, files: list[Path]) -> list[tuple[str, int, str]]:
    out = []
    for f in files:
        rel = str(f.relative_to(folder))
        for i, line in enumerate(f.read_text(errors="ignore", encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
            out.append((rel, i, code))
    return out


def _grep(folder: Path, files: list[Path], rx: re.Pattern, why: str) -> list[Hit]:
    return [Hit(rel, i, code.strip()[:100], why) for rel, i, code in _lines(folder, files)
            if rx.search(code)]


def order_code(folder: Path) -> list[Hit]:
    """Order-placement calls and order endpoints (paper_guard patterns + ``/orders``)."""
    files = py_files(folder)
    hits = [Hit(rel, i, code.strip()[:100], "order call")
            for rel, i, code in _lines(folder, files) if paper_guard.scan_text(code)]
    seen = {(h.file, h.line) for h in hits}
    hits += [h for h in _grep(folder, files, _ORDER_EXTRA, "order endpoint")
             if (h.file, h.line) not in seen]
    return hits


def keys_in_code(folder: Path) -> list[Hit]:
    """Strings that look like keys, tokens or passwords written into the code."""
    files = py_files(folder)
    hits: dict[tuple[str, int], Hit] = {}
    for rx, why in ((_KEY_ASSIGN, "key or token in quotes"), (_KEY_SHAPE, "key-shaped string"),
                    (_AUTH_LITERAL, "Authorization header written in code"),
                    (_KEY_ACCESS, "reads keys or the environment (plugins never get keys)")):
        for h in _grep(folder, files, rx, why):
            hits.setdefault((h.file, h.line), h)
    return list(hits.values())


def imports(folder: Path, tests: bool) -> dict[str, list[tuple[str, int]]]:
    """Top-level modules imported by the plugin code (``tests=False``) or its tests."""
    out: dict[str, list[tuple[str, int]]] = {}
    for f in py_files(folder):
        if is_test(folder, f) != tests:
            continue
        try:
            tree = ast.parse(f.read_text(errors="ignore", encoding="utf-8"))
        except SyntaxError as exc:
            out.setdefault("<syntax error>", []).append((str(f.relative_to(folder)), exc.lineno or 0))
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for n in names:
                out.setdefault(n.split(".")[0], []).append((str(f.relative_to(folder)), node.lineno))
    return out


def packages(folder: Path, name: str) -> tuple[list[str], list[Hit]]:
    """(packages the plugin code uses, hits for any outside the allow-list)."""
    code = imports(folder, tests=False)
    test = imports(folder, tests=True)
    used = [m for m in code if m not in ("__future__", name)]
    hits = [Hit(f, ln, m, "package not on the allow-list") for m, locs in code.items()
            if m not in ALLOWED_PACKAGES | {name} for f, ln in locs]
    hits += [Hit(f, ln, m, "package not on the allow-list (tests)") for m, locs in test.items()
             if m not in ALLOWED_PACKAGES | TEST_ONLY_PACKAGES | {name} for f, ln in locs]
    order = ["polars", "numpy", "pandas", "plugai_trade"]
    used.sort(key=lambda m: (order.index(m) if m in order else len(order), m))
    return used, hits


def network(folder: Path, declared: list[str]) -> list[Hit]:
    """Web addresses and network modules that the manifest does not declare."""
    files = [f for f in py_files(folder) if not is_test(folder, f)]
    hits = []
    for rel, i, code in _lines(folder, files):
        for host in _URL.findall(code):
            if host not in declared:
                hits.append(Hit(rel, i, code.strip()[:100], f"web address {host} not declared"))
    if not declared:
        for mod, locs in imports(folder, tests=False).items():
            if mod in NETWORK_MODULES:
                hits += [Hit(f, ln, mod, "network module, but manifest says network = []")
                         for f, ln in locs]
    return hits


def look_ahead(folder: Path) -> list[Hit]:
    """Negative shifts and other ways to read a later bar."""
    files = py_files(folder)
    hits = _grep(folder, files, _NEG_SHIFT, "negative shift reads a later bar")
    hits += _grep(folder, files, _LOOKAHEAD, "fills or centres from later bars")
    hits += [h for h in _grep(folder, [f for f in files if not is_test(folder, f)], _SAME_ROW,
                              "today's close beside today's open (not known at the open)")]
    return hits


def skipped_tests(folder: Path) -> list[Hit]:
    """Tests switched off, or errors silenced."""
    return _grep(folder, py_files(folder), _SKIPPED, "check switched off")
