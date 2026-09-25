"""The lab's local state: one SQLite file, simple tables of JSON records.

Every screen reads and writes through ``Store``. Records are dicts; each table
is a list of rows with an auto id, a created timestamp and a JSON body. This is
deliberately boring so it is easy to back up, inspect and test.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

from . import config

TABLES = (
    "watchlists", "plans", "rule_cards", "journal", "paper_orders", "paper_positions",
    "alerts", "alert_log", "audit_log", "trials", "backtests", "briefings", "documents",
    "theses", "forecasts", "ipos", "jobs", "job_log", "proposals", "plugins", "reviews",
    "tax_accounts", "notes", "lessons", "cost_log", "workspaces", "pilot_plans",
)

_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(config.path("lab.sqlite"))
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with _lock:
            for t in TABLES:
                self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " created TEXT NOT NULL, tag TEXT DEFAULT '', body TEXT NOT NULL)"
                )
            self._conn.commit()

    def _check(self, table: str) -> None:
        if table not in TABLES:
            raise ValueError(f"unknown table {table!r}")

    def add(self, table: str, body: dict[str, Any], tag: str = "") -> int:
        self._check(table)
        with _lock:
            cur = self._conn.execute(
                f"INSERT INTO {table} (created, tag, body) VALUES (?, ?, ?)",
                (now(), tag, json.dumps(body, default=str)),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update(self, table: str, row_id: int, body: dict[str, Any], tag: str | None = None) -> None:
        self._check(table)
        with _lock:
            if tag is None:
                self._conn.execute(f"UPDATE {table} SET body=? WHERE id=?",
                                   (json.dumps(body, default=str), row_id))
            else:
                self._conn.execute(f"UPDATE {table} SET body=?, tag=? WHERE id=?",
                                   (json.dumps(body, default=str), tag, row_id))
            self._conn.commit()

    def delete(self, table: str, row_id: int) -> None:
        self._check(table)
        with _lock:
            self._conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
            self._conn.commit()

    def all(self, table: str, tag: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        self._check(table)
        q = f"SELECT id, created, tag, body FROM {table}"
        args: tuple = ()
        if tag is not None:
            q += " WHERE tag=?"
            args = (tag,)
        q += " ORDER BY id DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        with _lock:
            rows = self._conn.execute(q, args).fetchall()
        return [{"id": r["id"], "created": r["created"], "tag": r["tag"], **json.loads(r["body"])}
                for r in rows]

    def get(self, table: str, row_id: int) -> dict[str, Any] | None:
        self._check(table)
        with _lock:
            r = self._conn.execute(f"SELECT id, created, tag, body FROM {table} WHERE id=?",
                                   (row_id,)).fetchone()
        return None if r is None else {"id": r["id"], "created": r["created"], "tag": r["tag"],
                                       **json.loads(r["body"])}

    def count(self, table: str, tag: str | None = None) -> int:
        self._check(table)
        with _lock:
            if tag is None:
                return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            return int(self._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE tag=?",
                                          (tag,)).fetchone()[0])

    def add_many(self, table: str, rows: Iterable[dict[str, Any]], tag: str = "") -> int:
        n = 0
        for r in rows:
            self.add(table, r, tag)
            n += 1
        return n

    def audit(self, kind: str, detail: dict[str, Any]) -> None:
        """Append to the audit log (Settings › Security › Audit log)."""
        self.add("audit_log", {"kind": kind, **detail}, tag=kind)


_default: Store | None = None


def default() -> Store:
    global _default
    if _default is None or _default.db_path != str(config.path("lab.sqlite")):
        _default = Store()
    return _default
