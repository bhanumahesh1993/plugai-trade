"""Shared plumbing for the network data sources.

Every connector goes through :func:`get` so it gets the same timeouts, polite
per-host pacing, retry with backoff on 429/5xx and one switch to stay offline.
Failures raise; the router in ``plugai_trade.data`` catches them and falls back.

Tests replace :data:`TRANSPORT` with an ``httpx.MockTransport``.
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import config, keys

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
TIMEOUT = httpx.Timeout(15.0, connect=6.0)
TRANSPORT: httpx.BaseTransport | None = None  # tests plug a MockTransport in here

_last_call: dict[str, float] = {}


class Offline(RuntimeError):
    """Network sources are switched off (``PLUGAI_TRADE_OFFLINE=1`` or ``data.offline``)."""


class NeedsKey(RuntimeError):
    """The source needs a key or token that is not in the keychain yet."""


class NotFound(RuntimeError):
    """The server answered 404 — usually a holiday or a file not published yet."""


class HTTPError(RuntimeError):
    """Any other HTTP failure. The message never contains the query string (keys live there)."""


def offline() -> bool:
    """True when the lab must not touch the network."""
    env = os.environ.get("PLUGAI_TRADE_OFFLINE", "").lower() in ("1", "true", "yes")
    return env or bool(config.get("data.offline", False))


def _pace(host: str, min_interval: float) -> None:
    wait = _last_call.get(host, 0.0) + min_interval - time.monotonic()
    if wait > 0 and TRANSPORT is None:
        time.sleep(wait)
    _last_call[host] = time.monotonic()


def get(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
        min_interval: float = 0.0, retries: int = 2, method: str = "GET",
        json: Any = None) -> httpx.Response:
    """One polite HTTP request. Raises :class:`NotFound` on 404, :class:`HTTPError` otherwise."""
    if offline():
        raise Offline("offline mode — network sources are switched off")
    host = urlparse(url).netloc
    delay = 2.0
    for attempt in range(retries + 1):
        _pace(host, min_interval)
        try:
            with httpx.Client(transport=TRANSPORT, timeout=TIMEOUT, follow_redirects=True,
                              headers=headers or {}) as client:
                resp = client.request(method, url, params=params, json=json)
        except httpx.RequestError as exc:  # no URL in the message: keys may sit in the query
            raise HTTPError(f"{host}: {type(exc).__name__} (network unreachable?)") from None
        if resp.status_code == 404:
            raise NotFound(f"{host}: not found (404)")
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            if TRANSPORT is None:
                time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code >= 400:
            hint = " — check the key or token" if resp.status_code in (401, 403) else ""
            raise HTTPError(f"{host}{urlparse(url).path}: HTTP {resp.status_code}{hint}")
        return resp
    raise RuntimeError("unreachable")  # pragma: no cover


def raw_path(source: str, *parts: str) -> Path:
    """Where a source keeps its raw downloaded files (never committed to git)."""
    return config.path("raw", source, *parts)


def require_key(name: str, label: str) -> str:
    """The key from the OS keychain, or a clear 'needs key' error."""
    value = keys.get_key(name)
    if not value:
        raise NeedsKey(f"{label} is not set — add it in Settings › Data Sources "
                       "(Save to keychain) or Settings › Keys.")
    return value


def windows(start: date, end: date, days: int) -> list[tuple[date, date]]:
    """Split ``start..end`` into consecutive windows of at most ``days`` days."""
    out, lo = [], start
    while lo <= end:
        hi = min(end, lo + timedelta(days=days - 1))
        out.append((lo, hi))
        lo = hi + timedelta(days=1)
    return out
