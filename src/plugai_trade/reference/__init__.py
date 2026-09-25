"""Dated reference tables (Derivatives › Contract Table, costs, tax).

Values come from ``tables.yaml`` — or a newer copy in the lab folder written by
``plugai-trade update``. Nothing else in the package hard-codes a rate or a lot.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from .. import config


@lru_cache(maxsize=1)
def tables() -> dict[str, Any]:
    local = config.path("reference", "tables.yaml")
    if local.exists():
        return yaml.safe_load(local.read_text(encoding="utf-8"))
    return yaml.safe_load(resources.files(__package__).joinpath("tables.yaml").read_text(encoding="utf-8"))


def reload() -> dict[str, Any]:
    tables.cache_clear()
    return tables()


def lookup(dotted: str, default: Any = None) -> Any:
    node: Any = tables()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def lot_size(symbol: str) -> int | None:
    row = lookup(f"india.contracts.{symbol.upper()}") or {}
    return row.get("lot")


def multiplier(symbol: str) -> int:
    row = lookup(f"us.contracts.{symbol.upper()}") or {}
    return int(row.get("multiplier", 100))


def as_of() -> str:
    return str(tables().get("as_of", ""))
