"""The Plugin check: manifest, tests, and the mechanical red-flag scans.

    plugai-trade plugin test gap_report

    Manifest ............ ok (report · IN, US · network: none)
    Tests (pytest) ...... 1 passed in 0.16 s
    Order code .......... none ✓
    Keys in code ........ none ✓
    Packages ............ polars, plugai_trade ✓
    Look-ahead scan ..... no negative shift ✓
    Plugin check passed: ready to enable.

Licence and network lines appear only when they fail (both are summarised on
the Manifest line when they pass). The tests never run when the scans find
order code, keys or undeclared internet access: a plugin that fails is never run.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..store import default as store
from ..store import now
from . import scan

MARKETS = {"IN", "US", "CRYPTO"}
REQUIRED = ("name", "kind", "markets", "entry", "network", "licence")
_SUMMARY = re.compile(r"((?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed)(?:, )?)+)"
                      r"(?: in ([0-9.]+)s)?")
_SAFE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "TEMP", "TMP",
             "PLUGAI_TRADE_HOME", "PLUGAI_TRADE_OFFLINE")


@dataclass
class CheckItem:
    """One line of the Plugin check."""

    name: str
    ok: bool
    value: str
    hits: list[scan.Hit] = field(default_factory=list)
    always_shown: bool = True

    def line(self) -> str:
        return f"{self.name} {'.' * max(2, 20 - len(self.name))} {self.value}"


@dataclass
class CheckReport:
    """The result of :func:`check`: ``.passed`` and ``.text()`` in the book's format."""

    name: str
    items: list[CheckItem]
    kind: str = ""
    markets: list[str] = field(default_factory=list)
    network: list[str] = field(default_factory=list)
    licence: str = ""

    @property
    def passed(self) -> bool:
        return all(i.ok for i in self.items)

    @property
    def red_flags(self) -> int:
        return sum(not i.ok for i in self.items)

    def item(self, name: str) -> CheckItem:
        return next(i for i in self.items if i.name == name)

    def text(self, details: bool = True) -> str:
        lines = []
        for i in self.items:
            if i.always_shown or not i.ok:
                lines.append(i.line())
                if details and not i.ok:
                    lines += [f"    {h}" for h in i.hits[:5]]
        if self.passed:
            lines.append("Plugin check passed: ready to enable.")
        else:
            n = self.red_flags
            lines.append(f"Plugin check failed: {n} red flag{'s' if n != 1 else ''}. "
                         "Blocked: fix them, then run the check again.")
        return "\n".join(lines)

    def facts(self) -> list[str]:
        return [i.line() for i in self.items] + [self.text(details=False).splitlines()[-1]]

    def __str__(self) -> str:
        return self.text()


def safe_env(pythonpath: Path) -> dict[str, str]:
    """Environment for a plugin process: no keys, no tokens, offline flags kept."""
    env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ}
    env.update(PYTHONPATH=str(pythonpath), PYTHONDONTWRITEBYTECODE="1", PLUGAI_TRADE_PLUGIN="1")
    return env


def _manifest(root: Path) -> tuple[CheckItem, dict]:
    f = root / "plugin.toml"
    if not f.exists():
        return CheckItem("Manifest", False, "missing plugin.toml ✗"), {}
    try:
        m = tomllib.loads(f.read_text())
    except tomllib.TOMLDecodeError as exc:
        return CheckItem("Manifest", False, f"cannot read plugin.toml ({exc}) ✗"), {}
    problems = [f"no {k}" for k in REQUIRED if k not in m]
    if m.get("name") and m["name"] != root.name:
        problems.append(f"name {m['name']!r} differs from folder {root.name!r}")
    if m.get("kind") not in ("report", "strategy", "screen"):
        problems.append("kind must be report, strategy or screen")
    if not set(m.get("markets") or []) <= MARKETS or not m.get("markets"):
        problems.append("markets must list IN, US or CRYPTO")
    if not isinstance(m.get("network", []), list):
        problems.append("network must be a list of web addresses ([] for none)")
    entry = str(m.get("entry", ""))
    file, _, func = entry.partition(":")
    code = root / file
    if not (file and func and code.exists()):
        problems.append(f"entry {entry!r} not found")
    elif not re.search(rf"^def {re.escape(func)}\s*\(", code.read_text(), re.MULTILINE):
        problems.append(f"function {func} not defined in {file}")
    if problems:
        return CheckItem("Manifest", False, "; ".join(problems) + " ✗"), m
    net = ", ".join(m["network"]) or "none"
    return CheckItem("Manifest", True, f"ok ({m['kind']} · {', '.join(m['markets'])} · "
                                       f"network: {net})"), m


def _pytest(root: Path) -> CheckItem:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir",
             str(root), "-o", "addopts=", "tests"],
            cwd=root, env=safe_env(root.parent), capture_output=True, text=True, timeout=180,
            check=False)
    except subprocess.TimeoutExpired:
        return CheckItem("Tests (pytest)", False, "timed out after 180 s ✗")
    out = proc.stdout + proc.stderr
    if proc.returncode == 5:
        return CheckItem("Tests (pytest)", False, "no tests found ✗")
    summary = None
    for line in reversed(out.splitlines()):
        m = _SUMMARY.search(line)
        if m:
            summary = m.group(1).rstrip(", ") + (f" in {float(m.group(2)):.2f} s" if m.group(2) else "")
            break
    summary = summary or f"pytest exited with code {proc.returncode}"
    fails = [scan.Hit("tests", 0, ln.strip()[:100], "pytest") for ln in out.splitlines()
             if ln.startswith(("FAILED", "ERROR", "E "))]
    ok = proc.returncode == 0
    return CheckItem("Tests (pytest)", ok, summary if ok else f"{summary} ✗", fails)


def _flag(name: str, hits: list[scan.Hit], ok_text: str, always: bool = True) -> CheckItem:
    if not hits:
        return CheckItem(name, True, ok_text, always_shown=always)
    first = hits[0]
    return CheckItem(name, False, f"FOUND {len(hits)} · {first.file}:{first.line} {first.why} ✗",
                     hits, always_shown=always)


def check(name: str | Path, record: bool = True) -> CheckReport:
    """Run the Plugin check on a plugin folder (name under ``<lab>/plugins`` or a path)."""
    from . import folder
    root = folder(name)
    if not root.is_dir():
        item = CheckItem("Manifest", False, f"no plugin folder {root} ✗")
        return CheckReport(name=str(name), items=[item])
    man_item, m = _manifest(root)
    declared = [str(x) for x in m.get("network", [])] if isinstance(m.get("network"), list) else []
    order = scan.order_code(root)
    keys = scan.keys_in_code(root)
    used, pkg_hits = scan.packages(root, root.name)
    net = scan.network(root, declared)
    look = scan.look_ahead(root)
    skipped = scan.skipped_tests(root)
    licence = str(m.get("licence", ""))
    lic_ok = licence in scan.PERMISSIVE_LICENCES
    if order or keys or net:
        tests = CheckItem("Tests (pytest)", False, "not run: blocked by the scans below ✗")
    elif skipped:
        tests = _flag("Tests (pytest)", skipped, "")
    else:
        tests = _pytest(root)
    pk_text = f"{', '.join(used) or 'none'} ✓"
    pkg = (CheckItem("Packages", True, pk_text) if not pkg_hits else
           CheckItem("Packages", False, f"{', '.join(sorted({h.text for h in pkg_hits}))} "
                                        f"not on the allow-list ✗", pkg_hits))
    items = [
        man_item, tests,
        _flag("Order code", order, "none ✓"),
        _flag("Keys in code", keys, "none ✓"),
        pkg,
        CheckItem("Licence", lic_ok, f"{licence} ✓" if lic_ok else
                  f"{licence or 'none'} ✗ (use a separate process over HTTP or MCP for "
                  "GPL/AGPL tools)", always_shown=False),
        _flag("Network", net, f"{', '.join(declared) or 'none declared'} ✓", always=False),
        _flag("Look-ahead scan", look, "no negative shift ✓"),
    ]
    rep = CheckReport(name=root.name, items=items, kind=str(m.get("kind", "")),
                      markets=list(m.get("markets", [])), network=declared, licence=licence)
    if record:
        _record(rep)
    return rep


def _record(rep: CheckReport) -> None:
    prev = store().all("plugins", tag=rep.name, limit=1)
    enabled = bool(prev and prev[0].get("enabled")) and rep.passed
    store().add("plugins", {"name": rep.name, "kind": rep.kind, "markets": rep.markets,
                            "network": rep.network, "licence": rep.licence,
                            "passed": rep.passed, "red_flags": rep.red_flags,
                            "enabled": enabled, "checked": now(),
                            "report": rep.text(details=False)}, tag=rep.name)
    store().audit("plugin_check", {"name": rep.name, "passed": rep.passed,
                                   "red_flags": rep.red_flags})
