"""SQLite-backed state store — the single source of truth for progress and resume.

Design goals (the GPU box may be `poweroff`'d mid-run):
- Every unit of work is a row with a status; pipelines are idempotent and re-entrant.
- WAL mode so a read-only dashboard can query while a pipeline writes.
- Atomic file writes happen elsewhere; this only records committed facts.
"""
from __future__ import annotations
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    source     TEXT NOT NULL,     -- e.g. 'smiley'
    kind       TEXT NOT NULL,     -- e.g. 'xlsx' | 'xml'
    fetched_at REAL NOT NULL,
    url        TEXT,
    path       TEXT,              -- where the snapshot was saved (NULL if unchanged)
    sha256     TEXT NOT NULL,
    bytes      INTEGER NOT NULL,
    changed    INTEGER NOT NULL   -- 1 if content differs from previous snapshot
);
CREATE INDEX IF NOT EXISTS ix_snap_src ON snapshots(source, kind, fetched_at);

-- Generic work queue: one row per unit (a PDF, a report, a CVR record, ...).
CREATE TABLE IF NOT EXISTS items (
    pipeline   TEXT NOT NULL,     -- e.g. 'smiley_pdf'
    key        TEXT NOT NULL,     -- stable id (report id / url)
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending|done|failed|skipped
    sha256     TEXT,
    path       TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    error      TEXT,
    meta       TEXT,              -- JSON blob for pipeline-specific fields
    updated_at REAL NOT NULL,
    PRIMARY KEY (pipeline, key)
);
CREATE INDEX IF NOT EXISTS ix_items_status ON items(pipeline, status);

-- Coarse run log, for the dashboard timeline.
CREATE TABLE IF NOT EXISTS runs (
    pipeline    TEXT NOT NULL,
    started_at  REAL NOT NULL,
    finished_at REAL,
    ok          INTEGER,
    note        TEXT
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    conn = sqlite3.connect(config.STATE_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_snapshot(conn, source, kind, url, path, sha256, nbytes, changed) -> None:
    conn.execute(
        "INSERT INTO snapshots(source,kind,fetched_at,url,path,sha256,bytes,changed) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (source, kind, time.time(), url, str(path) if path else None, sha256, nbytes,
         1 if changed else 0),
    )


def last_snapshot_sha(conn, source, kind) -> Optional[str]:
    row = conn.execute(
        "SELECT sha256 FROM snapshots WHERE source=? AND kind=? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (source, kind),
    ).fetchone()
    return row["sha256"] if row else None


# --- generic item helpers (used by later pipelines: PDFs, CVR, ...) ---

def upsert_item(conn, pipeline, key, *, status="pending", sha256=None, path=None,
                error=None, meta=None, bump_attempt=False) -> None:
    now = time.time()
    conn.execute(
        """INSERT INTO items(pipeline,key,status,sha256,path,attempts,error,meta,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(pipeline,key) DO UPDATE SET
             status=excluded.status,
             sha256=COALESCE(excluded.sha256, items.sha256),
             path=COALESCE(excluded.path, items.path),
             attempts=items.attempts + ?,
             error=excluded.error,
             meta=COALESCE(excluded.meta, items.meta),
             updated_at=excluded.updated_at""",
        (pipeline, key, status, sha256, str(path) if path else None,
         1 if bump_attempt else 0, error, meta, now, 1 if bump_attempt else 0),
    )


def pending_items(conn, pipeline, limit=None):
    q = "SELECT * FROM items WHERE pipeline=? AND status IN ('pending','failed')"
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q, (pipeline,)).fetchall()


def progress(conn, pipeline) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM items WHERE pipeline=? GROUP BY status",
        (pipeline,),
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}
