"""The paper-only guarantee, checked in code.

PlugAI-Trade contains no code that can place a real order. ``scan`` looks for
order-placement calls of common broker SDKs; the test-suite runs it on the whole
package and the Plugin check runs it on every plugin before it may be enabled.
"""

from __future__ import annotations

import re
from pathlib import Path

PATTERNS = [
    r"\.place_order\s*\(", r"\.placeorder\s*\(", r"\.submit_order\s*\(", r"\.create_order\s*\(",
    r"\.modify_order\s*\(", r"\.place_gtt\s*\(", r"orders?/regular", r"/v2/orders\b",
    r"\bplaceOrder\b", r"\bsubmitOrder\b", r"create_market_(buy|sell)_order",
]
_RX = re.compile("|".join(PATTERNS), re.I)
_SELF = {"paper_guard.py"}


def scan_text(text: str) -> list[str]:
    return [m.group(0) for m in _RX.finditer(text)]


def scan_path(root: Path) -> list[tuple[str, int, str]]:
    hits = []
    for f in root.rglob("*.py"):
        if f.name in _SELF or "tests" in f.parts:
            continue
        for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
            if _RX.search(line):
                hits.append((str(f), i, line.strip()[:120]))
    return hits


def scan_package() -> str:
    hits = scan_path(Path(__file__).parent)
    return "none found ✓" if not hits else f"FOUND {len(hits)} suspicious line(s)"
