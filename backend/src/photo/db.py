"""SQLite storage with forward-only migrations tracked in ``PRAGMA user_version``.

SQLite in WAL mode is the right tool for a single-machine app: zero setup, crash-safe,
and every query here takes well under a millisecond.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MIGRATIONS: Sequence[str] = (
    # 1 — initial schema
    """
    CREATE TABLE jobs (
        id           TEXT PRIMARY KEY,
        kind         TEXT NOT NULL,
        status       TEXT NOT NULL,
        params       TEXT NOT NULL,
        model        TEXT NOT NULL,
        variant      TEXT NOT NULL,
        seed         INTEGER NOT NULL,
        progress     REAL NOT NULL DEFAULT 0,
        error        TEXT,
        created_at   REAL NOT NULL,
        started_at   REAL,
        finished_at  REAL
    );
    CREATE INDEX jobs_status_created ON jobs(status, created_at);

    CREATE TABLE images (
        id          TEXT PRIMARY KEY,
        job_id      TEXT NOT NULL REFERENCES jobs(id),
        path        TEXT NOT NULL,
        thumb_path  TEXT NOT NULL,
        width       INTEGER NOT NULL,
        height      INTEGER NOT NULL,
        seed        INTEGER NOT NULL,
        model       TEXT NOT NULL,
        params      TEXT NOT NULL,
        favorite    INTEGER NOT NULL DEFAULT 0,
        created_at  REAL NOT NULL,
        deleted_at  REAL
    );
    CREATE INDEX images_created ON images(created_at DESC) WHERE deleted_at IS NULL;
    CREATE INDEX images_job ON images(job_id);
    """,
    # 2 — machine-readable error codes so the UI can explain failures in any language
    """
    ALTER TABLE jobs ADD COLUMN error_code TEXT;
    """,
)


class Database:
    """Thread-safe wrapper around one connection (SQLite serialises writes anyway)."""

    def __init__(self, path: Path | str) -> None:
        self.path = path
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None, timeout=10
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        try:
            self.migrate()
        except BaseException:
            self._conn.close()
            raise

    def migrate(self) -> None:
        with self._lock:
            current: int = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current > len(MIGRATIONS):
                raise RuntimeError(
                    f"database {self.path} is from a newer version of Photo "
                    f"(schema {current}, this build knows {len(MIGRATIONS)})"
                )
            for version in range(current, len(MIGRATIONS)):
                with self.transaction() as tx:
                    tx.executescript_safe(MIGRATIONS[version])
                    tx.execute(f"PRAGMA user_version = {version + 1}")

    @contextmanager
    def transaction(self) -> Iterator[_Tx]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield _Tx(self._conn)
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    def one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    def all(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class _Tx:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        return self._conn.execute(sql, params).rowcount

    def executescript_safe(self, script: str) -> None:
        # executescript() would COMMIT our transaction; run statements one by one instead.
        for stmt in script.split(";"):
            if stmt.strip():
                self._conn.execute(stmt)
