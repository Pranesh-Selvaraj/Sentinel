"""SQLite state store.

Sentinel remembers everything it has seen. All persistence goes through this
module; no other code touches SQL directly.

Schema (``PRAGMA user_version = 1``):

    sources    — the monitored sources and their configuration
    snapshots  — append-only observations (a new row per *value change*)
    changes    — detected changes with explanations
    checks     — one row per check attempt (ok/failed), for uptime stats
    updates    — future `sentinel upgrade` audit trail

The per-attempt ``checks`` log is pruned on startup per ``retention_days``
(see :meth:`Database.prune`); snapshots/changes/updates are kept.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Self

from sentinel.diffing import Change
from sentinel.models import Snapshot, Source, StoredChange
from sentinel.util import UTC

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL,
    config          TEXT NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_checked_at TEXT,
    last_status     TEXT,
    last_error      TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    value       TEXT,
    state       TEXT NOT NULL DEFAULT '{}',
    raw         TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_source ON snapshots(source_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    detected_at TEXT NOT NULL,
    kind        TEXT NOT NULL,
    previous    TEXT,
    current     TEXT,
    description TEXT NOT NULL DEFAULT '',
    severity    TEXT NOT NULL DEFAULT 'info',
    data        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_changes_source ON changes(source_id, detected_at DESC);

CREATE TABLE IF NOT EXISTS checks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    checked_at TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_source ON checks(source_id, checked_at DESC);

CREATE TABLE IF NOT EXISTS updates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id         INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    tool              TEXT NOT NULL,
    installed_version TEXT,
    latest_version    TEXT,
    source_url        TEXT,
    performed_at      TEXT NOT NULL,
    status            TEXT NOT NULL
);
"""


class Database:
    """SQLite-backed persistence for Sentinel."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    # -- schema -----------------------------------------------------------
    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- sources ----------------------------------------------------------
    def add_source(self, kind: str, name: str, config: dict, created_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO sources (kind, name, config, created_at) VALUES (?, ?, ?, ?)",
            (kind, name, json.dumps(config, sort_keys=True), created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_source(self, source_id: int) -> Source | None:
        row = self.conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self._row_to_source(row) if row else None

    def list_sources(self, enabled_only: bool = False) -> list[Source]:
        q = "SELECT * FROM sources"
        if enabled_only:
            q += " WHERE enabled = 1"
        q += " ORDER BY id"
        return [self._row_to_source(r) for r in self.conn.execute(q).fetchall()]

    def delete_source(self, source_id: int) -> None:
        self.conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        self.conn.commit()

    def set_check_result(self, source_id: int, ok: bool, error: str | None, checked_at: str) -> None:
        self.conn.execute(
            "UPDATE sources SET last_checked_at = ?, last_status = ?, last_error = ? WHERE id = ?",
            (checked_at, "ok" if ok else "failed", error, source_id),
        )
        self.conn.commit()

    def record_check(self, source_id: int, checked_at: str, ok: bool, error: str | None) -> None:
        self.conn.execute(
            "INSERT INTO checks (source_id, checked_at, ok, error) VALUES (?, ?, ?, ?)",
            (source_id, checked_at, 1 if ok else 0, error),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> Source:
        return Source(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            config=json.loads(row["config"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            last_checked_at=row["last_checked_at"],
            last_status=row["last_status"],
            last_error=row["last_error"],
        )

    # -- snapshots --------------------------------------------------------
    def record_snapshot(
        self, source_id: int, observed_at: str, value: str | None, state: dict, raw: str | None
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO snapshots (source_id, observed_at, value, state, raw) VALUES (?, ?, ?, ?, ?)",
            (source_id, observed_at, value, json.dumps(state, sort_keys=True), raw),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def latest_snapshot(self, source_id: int) -> Snapshot | None:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE source_id = ? ORDER BY observed_at DESC, id DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def list_snapshots(self, source_id: int, limit: int = 100) -> list[Snapshot]:
        rows = self.conn.execute(
            "SELECT * FROM snapshots WHERE source_id = ? ORDER BY observed_at DESC, id DESC LIMIT ?",
            (source_id, limit),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> Snapshot:
        return Snapshot(
            id=row["id"],
            source_id=row["source_id"],
            observed_at=row["observed_at"],
            value=row["value"],
            state=json.loads(row["state"]),
            raw=row["raw"],
        )

    # -- changes ----------------------------------------------------------
    def record_changes(self, source_id: int, detected_at: str, changes: list[Change]) -> None:
        for c in changes:
            self.conn.execute(
                "INSERT INTO changes (source_id, detected_at, kind, previous, current, "
                "description, severity, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source_id,
                    detected_at,
                    c.kind,
                    c.previous,
                    c.current,
                    c.description,
                    c.severity,
                    json.dumps(c.data, sort_keys=True),
                ),
            )
        self.conn.commit()

    def list_changes(self, source_id: int | None = None, limit: int = 50) -> list[StoredChange]:
        # Static fragments only; all values go through `?` placeholders.
        q = (
            "SELECT * FROM changes"  # noqa: S608  # nosec B608 — static SQL, values are `?`-bound
            + (" WHERE source_id = ?" if source_id is not None else "")
            + " ORDER BY detected_at DESC, id DESC LIMIT ?"
        )
        params = (source_id, limit) if source_id is not None else (limit,)
        rows = self.conn.execute(q, params).fetchall()
        return [
            StoredChange(
                source_id=r["source_id"],
                detected_at=r["detected_at"],
                change=Change(
                    kind=r["kind"],
                    previous=r["previous"],
                    current=r["current"],
                    description=r["description"],
                    severity=r["severity"],
                    data=json.loads(r["data"]),
                ),
            )
            for r in rows
        ]

    def latest_change(self, source_id: int) -> StoredChange | None:
        rows = self.list_changes(source_id, limit=1)
        return rows[0] if rows else None

    # -- retention -------------------------------------------------------
    def check_stats(self, source_id: int | None = None, since: str | None = None) -> list[dict]:
        """Aggregate the per-attempt checks log for uptime statistics.

        Returns one dict per source with ``source_id``, ``total`` (attempts)
        and ``ok`` (successful attempts) within the window (*since* is an
        ISO-8601 UTC cutoff; ``None`` means all history).
        """
        clauses: list[str] = []
        params: list = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if since:
            clauses.append("checked_at >= ?")
            params.append(since)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (  # nosec B608 — static fragments, values are `?`-bound
            f"SELECT source_id, COUNT(*) AS total, SUM(ok) AS ok FROM checks{where} "  # noqa: S608
            "GROUP BY source_id ORDER BY source_id"
        )
        rows = self.conn.execute(query, params).fetchall()
        return [{"source_id": r["source_id"], "total": r["total"], "ok": r["ok"] or 0} for r in rows]

    def prune(self, retention_days: int) -> int:
        """Delete per-attempt ``checks`` rows older than *retention_days*.

        The checks table grows one row per check attempt per source — in
        watch mode that is every interval — so it is pruned on startup.
        History (``snapshots``/``changes``) and the ``updates`` audit trail
        are kept: they are small and are the product's core value.
        ``retention_days <= 0`` keeps everything.

        Returns the number of deleted rows.
        """
        if retention_days <= 0:
            return 0
        cutoff = (dt.datetime.now(UTC) - dt.timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self.conn.execute("DELETE FROM checks WHERE checked_at < ?", (cutoff,))
        self.conn.commit()
        return int(cur.rowcount)

    # -- updates (future `sentinel upgrade` audit trail) ------------------
    def record_update(
        self,
        source_id: int | None,
        tool: str,
        installed: str | None,
        latest: str | None,
        source_url: str | None,
        performed_at: str,
        status: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO updates (source_id, tool, installed_version, latest_version, "
            "source_url, performed_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_id, tool, installed, latest, source_url, performed_at, status),
        )
        self.conn.commit()

    def list_updates(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM updates ORDER BY performed_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
