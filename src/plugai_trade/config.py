"""Paths and user settings.

Everything the lab stores lives under one folder (default ``~/.plugai-trade``,
override with ``PLUGAI_TRADE_HOME``). Settings are a small JSON file so they can
be read, diffed and backed up by hand. Keys never go here — see ``keys.py``.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "market": "IN",  # IN | US — the top-bar switch
    "education_lag_days": 90,  # house rule for named Indian securities (min 30)
    "watchlists": {
        "IN": ["NIFTY", "BANKNIFTY", "SENSEX"],
        "US": ["SPY", "QQQ", "DIA"],
    },
    "ai": {
        "provider": "ollama",  # ollama | openai-compatible | litellm
        "ollama_host": "http://localhost:11434",
        "local_model": "qwen3.5:9b",
        "drafting_model": "",  # empty = local_model
        "journal_model": "",  # journal & portfolio: local only by default
        "cloud_models": [],  # e.g. ["gemini/gemini-flash", "anthropic/claude-haiku"]
        "local_servers": [],  # e.g. ["http://localhost:1234/v1"] (LM Studio)
        "embedding_model": "nomic-embed-text",
        "context_length": 8192,
        "monthly_budget": 5.0,  # USD; cloud calls pause at the cap
        "use_for": {
            "Today": "Cloud allowed",
            "Research": "Cloud allowed",
            "Strategy": "Cloud allowed",
            "Plan & Risk": "Cloud allowed",
            "Paper Trading": "Local only",
            "Derivatives": "Cloud allowed",
            "Portfolio": "Local only",
            "Journal": "Local only",
            "Tax": "Local only",
            "Documents": "Local only",
            "Automate": "Cloud allowed",
        },
    },
    "privacy": {
        "journal_local_only": True,
        "holdings_local_only": True,
        "ask_before_cloud": True,
        "strip_identifiers": True,
        "crash_reports": False,
    },
    "data": {
        "fallback": {
            "IN-eod": ["nse_bhavcopy", "upstox", "fyers", "angel", "breeze", "yfinance", "cache"],
            "IN-intraday": ["upstox", "fyers", "angel", "breeze", "eod_replay"],
            "US-eod": ["alpaca", "yfinance", "tiingo", "cache"],
            "US-intraday": ["alpaca", "finnhub", "yfinance"],
            "FX": ["frankfurter", "yfinance"],
            "crypto": ["ccxt_public"],
        },
        "live_stream": False,
        "edgar_contact": "",
    },
    "paper": {"daily_loss_limit": 0.0, "max_trades_per_day": 0, "cooldown_minutes": 0},
    "workspace": {"template": "", "pinned": []},
}


def home() -> Path:
    p = Path(os.environ.get("PLUGAI_TRADE_HOME", Path.home() / ".plugai-trade"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def path(*parts: str) -> Path:
    """A path inside the lab folder; parent folders are created."""
    p = home().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict[str, Any]:
    f = path("settings.json")
    if not f.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        return _merge(DEFAULTS, json.loads(f.read_text()))
    except json.JSONDecodeError:
        return copy.deepcopy(DEFAULTS)


def save(settings: dict[str, Any]) -> None:
    settings["education_lag_days"] = max(30, int(settings.get("education_lag_days", 90)))
    path("settings.json").write_text(json.dumps(settings, indent=2, sort_keys=True))


def get(dotted: str, default: Any = None) -> Any:
    node: Any = load()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_value(dotted: str, value: Any) -> None:
    s = load()
    node = s
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    save(s)
