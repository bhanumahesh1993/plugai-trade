"""Agent plugins that run as a separate process: TradingAgents and ai-hedge-fund.

They are installed only from the official GitHub repository at a pinned tag,
into their own virtual environment under ``<lab>/agents/<plugin>/`` — never
from PyPI (the ``tradingagents`` name on PyPI belongs to an unrelated fork).
At run time the adapter process receives a research packet (facts computed by
the lab's tools, behind the as-of wall and the name mask) on stdin, with an
environment that holds no keys, and prints JSON sections back. The lab turns
that into a note; the rule is always drafted and tested by the lab, so the
output kind stays ``rule_proposal``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config
from ..store import default as store
from .tools import TOOLS

# Official repositories. Tags are defaults; Settings may override with agents.pins.<name>.
ADAPTERS: dict[str, dict[str, str]] = {
    "tradingagents": {"title": "TradingAgents", "repo": "https://github.com/TauricResearch/TradingAgents",
                      "tag": "v0.5.1", "licence": "Apache-2.0", "module": "tradingagents"},
    "ai-hedge-fund": {"title": "ai-hedge-fund", "repo": "https://github.com/virattt/ai-hedge-fund",
                      "tag": "v2026.7.10", "licence": "MIT", "module": "src"},
}

RUNNER = '''"""Adapter runner written by PlugAI-Trade. Reads a research packet on stdin, prints JSON.

It runs in this plugin's own virtual environment and process. It receives no keys
and no order tool; it may only return text sections for the research note.
"""
import json, sys

packet = json.load(sys.stdin)
sections = {"Analysts": [], "Bull": [], "Bear": [], "Risk manager": []}
try:
    import importlib
    importlib.import_module(packet["module"])
    sections["Analysts"].append(f"{packet['title']} {packet['tag']} loaded in its own process.")
except Exception as exc:  # the lab falls back to the built-in team
    print(json.dumps({"ok": False, "error": f"cannot import {packet['module']}: {exc}"}))
    sys.exit(0)
facts = packet.get("facts", [])
sections["Analysts"] += facts[:6]
print(json.dumps({"ok": True, "sections": sections}))
'''


@dataclass
class InstallPlan:
    """What ``Install`` will do, shown before anything runs."""

    name: str
    repo: str
    tag: str
    folder: Path
    commands: list[list[str]]
    tools: tuple[str, ...] = TOOLS

    def text(self) -> str:
        lines = [(f"{ADAPTERS[self.name]['title']} from {self.repo} at pinned tag {self.tag} "
                  "(GitHub, not PyPI)"), f"Folder: {self.folder}",
                 "Allowed tools: " + ", ".join(self.tools) + " — no order or paper-order tool",
                 "Runs as a separate process with no keys.", "Commands:"]
        lines += ["  " + " ".join(c) for c in self.commands]
        return "\n".join(lines)


def pin(name: str) -> str:
    from .. import reference
    return str(config.get(f"agents.pins.{name}") or reference.lookup(f"agents.pins.{name}")
               or ADAPTERS[name]["tag"])


def adapter_dir(name: str) -> Path:
    return config.path("agents", name, ".keep").parent


def venv_python(name: str) -> Path:
    d = adapter_dir(name) / "venv"
    return d / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def is_installed(name: str) -> bool:
    """True when the pinned repository was installed by ``install`` (marker + venv)."""
    marker = adapter_dir(name) / "INSTALLED.json"
    return name in ADAPTERS and marker.exists() and venv_python(name).exists()


def install_plan(name: str) -> InstallPlan:
    if name not in ADAPTERS:
        raise ValueError(f"unknown agent plugin {name!r}; choose {', '.join(ADAPTERS)}")
    a, tag, d = ADAPTERS[name], pin(name), adapter_dir(name)
    src, py = d / "src", venv_python(name)
    cmds = [["git", "clone", "--depth", "1", "--branch", tag, a["repo"], str(src)],
            [sys.executable, "-m", "venv", str(d / "venv")],
            [str(py), "-m", "pip", "install", str(src)]]
    return InstallPlan(name=name, repo=a["repo"], tag=tag, folder=d, commands=cmds)


def install(name: str) -> str:
    """Fetch the official repository at the pinned tag into its own venv. Needs internet."""
    plan = install_plan(name)
    for cmd in plan.commands:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)
        if proc.returncode != 0:
            return f"Install stopped at `{' '.join(cmd[:3])}`: {proc.stderr.strip()[-400:]}"
    (plan.folder / "runner.py").write_text(RUNNER)
    (plan.folder / "INSTALLED.json").write_text(json.dumps({"repo": plan.repo, "tag": plan.tag}))
    store().audit("agent_install", {"name": name, "repo": plan.repo, "tag": plan.tag})
    return f"Installed {ADAPTERS[name]['title']} {plan.tag} from GitHub in {plan.folder}."


def run_adapter(name: str, packet: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Run the adapter's runner in its own process; returns its JSON (or an error dict)."""
    from ..plugin.check import safe_env
    a = ADAPTERS[name]
    body = {**packet, "module": a["module"], "title": a["title"], "tag": pin(name)}
    runner = adapter_dir(name) / "runner.py"
    try:
        proc = subprocess.run([str(venv_python(name)), str(runner)], input=json.dumps(body),
                              capture_output=True, text=True, timeout=timeout,
                              env=safe_env(adapter_dir(name)), check=False)
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        return {"ok": False, "error": str(exc)[:300]}
