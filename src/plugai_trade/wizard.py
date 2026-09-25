"""The first-run wizard (Chapter 4): five short screens and a ten-second self-test.

1. Check your computer — RAM, free disk, whether Ollama is running (Check again).
2. Local model — a size suggested from RAM (≤ 8 GB: 4B, 16 GB: 9B, ≥ 32 GB: larger);
   Pull model streams Ollama's ``/api/pull`` progress.
3. Cloud key (optional) — Skip for now, or add one in Settings › Keys.
4. Sample data — synthetic NIFTY / BANKNIFTY / SENSEX and SPY / QQQ / DIA.
5. Self-test — six checks; Copy diagnostic if one fails.

Nothing here needs a network: with ``PLUGAI_TRADE_OFFLINE=1`` (the test suite)
Ollama is treated as absent and only the model check fails.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from . import BOOK_EDITION, __version__, config, keys, paper_guard
from .store import default as store

STEPS = ("Check your computer", "Local model", "Cloud key (optional)", "Sample data", "Self-test")
SAMPLE_END = date(2026, 5, 29)  # the book's reference date: lessons match the page
SAMPLE_START = date(2025, 5, 29)
PROBE_KEY = "plugai_selftest_probe"
CLOUD_PROVIDERS = ("Gemini", "Groq", "OpenRouter", "OpenAI", "Anthropic", "DeepSeek")
OLLAMA_DOWNLOAD = "https://ollama.com/download"


@dataclass(frozen=True)
class ModelSize:
    """One row of the RAM → model table (Chapter 4, Chapter 31)."""

    size: str  # small | mid | large | embedding
    label: str
    tag: str  # Ollama model tag
    params_b: float
    download_gb: float
    good_for: str


MODELS: tuple[ModelSize, ...] = (
    ModelSize("small", "a small 4B model", "qwen3.5:4b", 4, 3.4,
              "short summaries, tagging news, explaining one number at a time"),
    ModelSize("mid", "a 9B model (default)", "qwen3.5:9b", 9, 6.6,
              "daily briefings, document Q&A, journal narration"),
    ModelSize("large", "a larger model", "qwen3.5:27b", 27, 17.0,
              "long filings, closer to cloud quality"),
)
EMBEDDING = ModelSize("embedding", "small embedding model", "nomic-embed-text", 0.137, 0.27,
                      "indexing your documents for search (Document Desk)")


# ---------------------------------------------------------------- the machine
def offline() -> bool:
    return os.environ.get("PLUGAI_TRADE_OFFLINE", "").lower() in ("1", "true", "yes")


def ollama_host() -> str:
    """``OLLAMA_HOST`` (Docker) wins over Settings › AI Models."""
    host = os.environ.get("OLLAMA_HOST") or config.get("ai.ollama_host", "http://localhost:11434")
    return host if host.startswith("http") else f"http://{host}"


def ram_gb() -> float | None:
    """Total physical memory in GB, or None when the platform will not say."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (ValueError, OSError, AttributeError):
        pass
    if sys.platform == "win32":  # pragma: no cover - platform specific
        class _Mem(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = _Mem()
        m.dwLength = ctypes.sizeof(_Mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullTotalPhys / 1024**3
    return None


def free_ram_gb() -> float | None:
    """Memory available right now (best effort): Linux MemAvailable, macOS vm_stat."""
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        m = re.search(r"MemAvailable:\s+(\d+) kB", meminfo.read_text())
        return int(m.group(1)) / 1024**2 if m else None
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=2,
                                 check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        page = int(re.search(r"page size of (\d+)", out).group(1)) if "page size" in out else 4096
        pages = sum(int(n) for k, n in re.findall(r"Pages (free|inactive|speculative):\s+(\d+)", out))
        return pages * page / 1024**3 if pages else None
    return None


def disk_free_gb(path: Path | None = None) -> float:
    return shutil.disk_usage(path or config.home()).free / 1024**3


def suggest(ram: float | None) -> ModelSize:
    """≤ 8 GB (up to 12): 4B · 16 GB (up to 30): 9B · 32 GB or more: larger. Unknown → 9B."""
    if ram is None:
        return MODELS[1]
    if ram <= 12:
        return MODELS[0]
    if ram < 30:
        return MODELS[1]
    return MODELS[2]


def ollama_reachable(timeout: float = 1.5) -> bool:
    if offline():
        return False
    try:
        return httpx.get(f"{ollama_host()}/api/tags", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def installed_models() -> list[str]:
    if offline():
        return []
    try:
        r = httpx.get(f"{ollama_host()}/api/tags", timeout=3)
        return [m["name"] for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return []


@dataclass(frozen=True)
class Machine:
    """Screen 1: three facts about your computer."""

    ram_gb: float | None
    free_ram_gb: float | None
    disk_free_gb: float
    ollama: bool

    @property
    def suggestion(self) -> ModelSize:
        return suggest(self.ram_gb)

    def lines(self) -> list[str]:
        ram = f"{self.ram_gb:.0f} GB" if self.ram_gb else "unknown"
        free = f" ({self.free_ram_gb:.1f} GB free now)" if self.free_ram_gb else ""
        return [f"Memory (RAM): {ram}{free}", f"Free disk: {self.disk_free_gb:.0f} GB",
                "Ollama: running" if self.ollama else "Ollama not found"]


def check_machine() -> Machine:
    return Machine(ram_gb(), free_ram_gb(), disk_free_gb(), ollama_reachable())


# ---------------------------------------------------------------- pull a model
@dataclass(frozen=True)
class PullProgress:
    status: str
    completed: int = 0
    total: int = 0

    @property
    def fraction(self) -> float:
        return min(1.0, self.completed / self.total) if self.total else 0.0


def pull_model(tag: str, timeout: float = 30.0) -> Iterator[PullProgress]:
    """Stream Ollama's ``/api/pull``. Pull model again resumes an interrupted download."""
    if offline():
        raise ConnectionError("Offline mode: model downloads are switched off.")
    with httpx.stream("POST", f"{ollama_host()}/api/pull", json={"model": tag, "stream": True},
                      timeout=httpx.Timeout(timeout, read=None)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.strip():
                continue
            msg = json.loads(line)
            if "error" in msg:
                raise RuntimeError(msg["error"])
            yield PullProgress(msg.get("status", ""), int(msg.get("completed") or 0),
                               int(msg.get("total") or 0))


def set_local_model(tag: str) -> None:
    config.set_value("ai.local_model", tag)


# ---------------------------------------------------------------- sample data
@dataclass
class SampleLoad:
    market: str
    rows: dict[str, int] = field(default_factory=dict)
    last_close: dict[str, float] = field(default_factory=dict)

    def facts(self) -> list[str]:
        return [f"{s}: {n} synthetic bars, last close {self.last_close[s]:,.2f}"
                for s, n in self.rows.items()]


def sample_bars(symbol: str, market: str):
    """The book's synthetic sample (fixed dates, so numbers match the page)."""
    from . import data
    return data.get(symbol, market=market, start=SAMPLE_START, end=SAMPLE_END,
                    source="synthetic", use_cache=False)


def load_sample_data(market: str) -> SampleLoad:
    """Screen 4: set the market and load the sample watchlist's synthetic bars."""
    symbols = list(config.get(f"watchlists.{market}") or config.DEFAULTS["watchlists"][market])
    config.set_value(f"watchlists.{market}", symbols)
    config.set_value("market", market)
    out = SampleLoad(market)
    for s in symbols:
        df = sample_bars(s, market)
        out.rows[s] = df.height
        out.last_close[s] = float(df["close"][-1])
    config.set_value("wizard.sample_loaded", sorted({*config.get("wizard.sample_loaded", []),
                                                      market}))
    return out


# ---------------------------------------------------------------- self-test
@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class SelfTest:
    """Screen 5: six checks, each a green tick or a plain-English failure."""

    checks: list[Check]
    seconds: float

    NAMES = ("Sample data loaded", "Average computed", "Model quoted it", "Keychain ready",
             "Paper ledger empty", "No order code")

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def facts(self) -> list[str]:
        return [f"{'✓' if c.passed else '✗'} {c.name}: {c.detail}" for c in self.checks] + [
            f"Self-test took {self.seconds:.1f} s"]


def _fmt(x: float) -> str:
    return f"{x:,.2f}"


def _model_quotes(value: str) -> Check:
    name = SelfTest.NAMES[2]
    if not ollama_reachable():
        return Check(name, False, "No local model answered: Ollama not found. Install it from "
                                  f"{OLLAMA_DOWNLOAD}, then Check again.")
    from . import ai
    out = ai.complete(f"FACTS:\n[1] 20-day average close: {value}\n\nTASK: Describe this one "
                      "number in a single sentence. Quote it exactly as written.",
                      section="Research", sensitive=True)
    if not out.text:
        return Check(name, False, f"The model {out.model} did not answer; is it pulled?")
    ok = value in out.text or value.replace(",", "") in out.text.replace(",", "")
    return Check(name, ok, f"{out.model} quoted {value}" if ok else
                 f"{out.model} did not quote {value} exactly: “{out.text[:120]}”")


def _keychain() -> Check:
    name = SelfTest.NAMES[3]
    if not keys.keychain_ok():
        return Check(name, False, "No keychain available (Linux: install and unlock GNOME "
                                  "Keyring or KWallet, then restart the lab).")
    try:
        keys.set_key(PROBE_KEY, "ok")
        ok = keys.get_key(PROBE_KEY) == "ok"
    except Exception as exc:  # keyring backends raise their own types
        return Check(name, False, f"The keychain refused a test secret: {exc}")
    finally:
        keys.remove_key(PROBE_KEY)
    return Check(name, ok, "stored and removed a test secret" if ok else
                 "the test secret could not be read back")


def self_test(market: str = "IN") -> SelfTest:
    """Run the six checks. Only the model check needs Ollama."""
    from . import indicators
    t0 = time.perf_counter()
    sym = "NIFTY" if market == "IN" else "SPY"
    checks: list[Check] = []
    bars = sample_bars(sym, market)
    checks.append(Check(SelfTest.NAMES[0], bars.height > 0,
                        f"{sym}: {bars.height} synthetic bars to {SAMPLE_END:%d %b %Y}"))
    avg = indicators.sma(bars, 20)["sma_20"][-1] if bars.height >= 20 else None
    checks.append(Check(SelfTest.NAMES[1], avg is not None,
                        f"20-day average {_fmt(avg)} (computed in code)" if avg else "too few bars"))
    checks.append(_model_quotes(_fmt(avg)) if avg else
                  Check(SelfTest.NAMES[2], False, "no number to quote"))
    checks.append(_keychain())
    rows = store().count("paper_orders") + store().count("paper_positions")
    checks.append(Check(SelfTest.NAMES[4], rows == 0 or is_done(),
                        "no paper orders or positions yet" if rows == 0 else
                        f"{rows} paper rows (expected once you have paper-traded)"))
    hits = paper_guard.scan_path(Path(paper_guard.__file__).parent)
    checks.append(Check(SelfTest.NAMES[5], not hits,
                        "none found (paper only)" if not hits else f"{len(hits)} suspicious lines"))
    result = SelfTest(checks, time.perf_counter() - t0)
    config.set_value("wizard.self_test", {"passed": result.passed,
                                          "failed": [c.name for c in result.failed()]})
    return result


def diagnostic(result: SelfTest | None = None) -> str:
    """The short report behind Copy diagnostic. It never contains keys or journal rows."""
    m = check_machine()
    lines = [f"PlugAI-Trade {__version__} ({BOOK_EDITION})",
             (f"Python {sys.version.split()[0]} · {platform.system()} {platform.release()} "
              f"({platform.machine()})"), *m.lines(),
             f"Ollama host: {ollama_host()}",
             f"Local model setting: {config.get('ai.local_model')}",
             f"Keychain: {'ready' if keys.keychain_ok() else 'NOT available'}",
             f"Offline mode: {'on' if offline() else 'off'}"]
    if result is not None:
        lines.append("Self-test:")
        lines += [f"  {f}" for f in result.facts()]
    return "\n".join(lines)


# ---------------------------------------------------------------- wizard state
def is_done() -> bool:
    return bool(config.get("wizard.done", False))


def mark_done(on: bool = True) -> None:
    config.set_value("wizard.done", bool(on))


def step() -> int:
    return int(config.get("wizard.step", 0))


def set_step(n: int) -> int:
    n = max(0, min(len(STEPS) - 1, int(n)))
    config.set_value("wizard.step", n)
    return n


# ---------------------------------------------------------------- fit check (Chapter 31)
KV_GB_PER_1K_AT_9B = 0.05  # scratchpad (KV cache) estimate per 1k tokens of context, 9B model


@dataclass(frozen=True)
class Fit:
    """The Fit check bar: download + context scratchpad + what is already in use."""

    model_gb: float
    context_gb: float
    used_gb: float
    ram_gb: float

    @property
    def total_gb(self) -> float:
        return round(self.model_gb + self.context_gb + self.used_gb, 2)

    @property
    def share(self) -> float:
        return self.total_gb / self.ram_gb if self.ram_gb else 1.0

    @property
    def colour(self) -> str:
        """green ≤ 80% of RAM, amber ≤ 100%, red above."""
        return "green" if self.share <= 0.8 else "amber" if self.share <= 1.0 else "red"

    def facts(self) -> list[str]:
        return [f"Model file {self.model_gb:.1f} GB", f"Context scratchpad {self.context_gb:.2f} GB",
                f"Already in use {self.used_gb:.1f} GB",
                (f"Total {self.total_gb:.1f} GB of {self.ram_gb:.0f} GB RAM ({self.share:.0%}) · "
                 f"{self.colour}")]


def fit_check(model: ModelSize, context_tokens: int, ram: float | None = None,
              used: float | None = None) -> Fit:
    """An estimate, labelled as one: real use varies with the runner and quantisation."""
    ram = ram if ram is not None else (ram_gb() or 16.0)
    if used is None:
        free = free_ram_gb()
        used = max(0.0, ram - free) if free is not None else 0.25 * ram
    ctx = KV_GB_PER_1K_AT_9B * (model.params_b / 9) * context_tokens / 1024
    return Fit(model.download_gb, round(ctx, 2), round(used, 2), ram)


# ---------------------------------------------------------------- Test model (Chapters 2, 31)
TEST_TABLE = {"Day 1 close": "100.00", "Day 2 close": "103.00", "Change": "+3.00 (3.00%)"}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class ModelTest:
    model: str
    ok: bool
    tokens_per_s: float
    prompt_s: float
    detail: str

    def facts(self) -> list[str]:
        return [f"Model {self.model}", f"Speed {self.tokens_per_s:.1f} tokens/s",
                f"Prompt reading time {self.prompt_s:.2f} s", self.detail]


def test_model(tag: str | None = None) -> ModelTest:
    """Ask the model to explain a tiny synthetic table; check it invented no numbers."""
    tag = tag or config.get("ai.local_model")
    if not ollama_reachable():
        return ModelTest(tag, False, 0.0, 0.0, "No local model answered: Ollama not found.")
    table = "\n".join(f"{k}: {v}" for k, v in TEST_TABLE.items())
    prompt = (f"TABLE (synthetic):\n{table}\n\nExplain this table in two sentences. Use only the "
              "numbers in the table; do not calculate anything new.")
    try:
        r = httpx.post(f"{ollama_host()}/api/generate", timeout=180,
                       json={"model": tag, "prompt": prompt, "stream": False,
                             "options": {"num_ctx": int(config.get("ai.context_length", 8192))}})
        r.raise_for_status()
        body = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        return ModelTest(tag, False, 0.0, 0.0, f"The model did not answer: {exc}")
    allowed = {n for v in (*TEST_TABLE.values(), *TEST_TABLE) for n in _NUMBER.findall(v)}
    invented = sorted({n for n in _NUMBER.findall(body.get("response", ""))} - allowed)
    speed = body.get("eval_count", 0) / max(body.get("eval_duration", 0) / 1e9, 1e-9)
    read = body.get("prompt_eval_duration", 0) / 1e9
    return ModelTest(tag, not invented, round(speed, 1), round(read, 2),
                     "No invented numbers ✓" if not invented else
                     f"Numbers not in the table: {', '.join(invented[:5])}")
