"""API keys live in the operating-system keychain — never in files or chats.

macOS Keychain, Windows Credential Manager or Linux Secret Service, through the
``keyring`` library. Only the last four characters are ever displayed.
Exchange keys with trade or withdraw permission are refused: the lab only reads.
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError

from . import config

SERVICE = "plugai-trade"

KNOWN = (
    "alpaca_key_id", "alpaca_secret", "upstox_analytics_token", "fyers_app_id", "fyers_token",
    "angel_api_key", "angel_jwt", "breeze_api_key", "kite_api_key", "dhan_token", "groww_token",
    "fred_api_key", "finnhub_api_key", "tiingo_api_key", "massive_api_key",
    "openai_api_key", "anthropic_api_key", "gemini_api_key", "groq_api_key",
    "openrouter_api_key", "deepseek_api_key", "telegram_bot_token", "smtp_password", "exchange_key",
)

FORBIDDEN_PERMISSIONS = ("trade", "withdraw", "transfer", "order")


class KeyRefused(ValueError):
    pass


def _index() -> set[str]:
    return set(config.get("keys_index", []) or [])


def _save_index(names: set[str]) -> None:
    config.set_value("keys_index", sorted(names))


def set_key(name: str, value: str, permissions: list[str] | None = None) -> None:
    """Store a key. ``permissions`` (if known) must be read-only."""
    perms = [p.lower() for p in (permissions or [])]
    bad = [p for p in perms if any(f in p for f in FORBIDDEN_PERMISSIONS)]
    if bad:
        from .store import default as _store
        _store().audit("key_refused", {"name": name, "permissions": bad})
        raise KeyRefused(
            f"Refused: this key allows {', '.join(bad)}. PlugAI-Trade only needs read-only keys."
        )
    keyring.set_password(SERVICE, name, value)
    idx = _index()
    idx.add(name)
    _save_index(idx)


def get_key(name: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, name)
    except KeyringError:
        return None


def remove_key(name: str) -> None:
    try:
        keyring.delete_password(SERVICE, name)
    except KeyringError:
        pass
    idx = _index()
    idx.discard(name)
    _save_index(idx)


def masked(name: str) -> str:
    v = get_key(name)
    return "not set" if not v else f"••••{v[-4:]}"


def listed() -> list[str]:
    return sorted(_index())


def keychain_ok() -> bool:
    try:
        keyring.get_keyring()
        return True
    except Exception:  # pragma: no cover - platform specific
        return False
