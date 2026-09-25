"""Encrypted backups of the lab folder (`plugai-trade backup --to / --restore`).

The archive holds settings, the SQLite store, reference tables and your
documents library — never keys (those stay in the OS keychain) and never the
re-downloadable market-data cache. It is encrypted with a passphrase you type.
"""

from __future__ import annotations

import base64
import getpass
import io
import os
import zipfile
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import config

SKIP_DIRS = {"cache"}
MAGIC = b"PLUGAIBK1"


def _key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def _passphrase(confirm: bool) -> str:
    p = os.environ.get("PLUGAI_TRADE_BACKUP_PASSPHRASE") or getpass.getpass("Backup passphrase: ")
    if confirm and not os.environ.get("PLUGAI_TRADE_BACKUP_PASSPHRASE"):
        if getpass.getpass("Repeat passphrase: ") != p:
            raise SystemExit("Passphrases do not match.")
    return p


def create(folder: Path, passphrase: str | None = None) -> str:
    root = config.home()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in root.rglob("*"):
            if f.is_file() and not (set(f.relative_to(root).parts) & SKIP_DIRS):
                z.write(f, f.relative_to(root))
    salt = os.urandom(16)
    token = Fernet(_key(passphrase or _passphrase(True), salt)).encrypt(buf.getvalue())
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"plugai-trade-backup-{datetime.now():%Y%m%d-%H%M}.plugai"
    out.write_bytes(MAGIC + salt + token)
    return f"Encrypted backup written: {out} (keys are not included)"


def restore(file: Path, passphrase: str | None = None) -> str:
    raw = file.read_bytes()
    if not raw.startswith(MAGIC):
        return "Not a PlugAI-Trade backup file."
    salt, token = raw[len(MAGIC):len(MAGIC) + 16], raw[len(MAGIC) + 16:]
    data = Fernet(_key(passphrase or _passphrase(False), salt)).decrypt(token)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(config.home())
    return f"Restored into {config.home()}. Re-enter keys in Settings › Keys."
