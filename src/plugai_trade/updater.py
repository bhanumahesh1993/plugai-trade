"""`plugai-trade update` — refresh the dated reference tables and say what changed.

Downloads the latest ``tables.yaml`` published in the repository, compares it
row by row with the copy in use, prints every changed value (with its source),
and flags saved plans that used an old value. Offline: explains and exits.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx
import yaml

from . import REPO_URL, config, reference
from .store import default as store

RAW = REPO_URL.replace("github.com", "raw.githubusercontent.com") + \
    "/main/src/plugai_trade/reference/tables.yaml"


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix] = node
    return out


def diff(old: dict, new: dict) -> list[tuple[str, Any, Any]]:
    a, b = _flatten(old), _flatten(new)
    return [(k, a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


def run(echo: Callable[[str], None] = print, url: str = RAW) -> list[tuple[str, Any, Any]]:
    current = reference.tables()
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True)
        r.raise_for_status()
        latest = yaml.safe_load(r.text)
    except Exception as exc:
        echo(f"Could not reach {url} ({exc}). Your tables are as of {reference.as_of()}.")
        return []
    changes = diff(current, latest)
    if not changes:
        echo(f"Reference tables are current (as of {reference.as_of()}).")
        return []
    config.path("reference", "tables.yaml").write_text(yaml.safe_dump(latest, sort_keys=False))
    reference.reload()
    echo(f"Updated reference tables: {len(changes)} change(s), now as of {reference.as_of()}")
    for key, old, new in changes:
        echo(f"  {key}: {old} → {new}")
    changed_keys = {k.split('.')[-1] for k, *_ in changes}
    stale = [p for p in store().all("plans")
             if any(str(k) in str(p.get("inputs", {})) for k in changed_keys)]
    for p in stale:
        echo(f"  ! Saved plan #{p['id']} used a value that changed — review it.")
    store().audit("update", {"changes": len(changes)})
    return changes
