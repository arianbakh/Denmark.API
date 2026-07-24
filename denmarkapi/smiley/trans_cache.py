"""Persistent line-level translation cache, shared across ALL reports.

Smiley reports are overwhelmingly boilerplate: the same sentences recur across tens of
thousands of inspections. translate.py already dedupes whole identical reports; this caches
individual LINES, so a report that is 90% standard phrasing only pays the LLM for the 10% that
is genuinely new. After warm-up most pages need no LLM call at all.

Its own SQLite file (not state.db) so that a hot, write-heavy cache never contends with the
harvest/extract/analyze writers on the state DB.
"""
from __future__ import annotations
import re
import sqlite3
import threading
import time

from .. import config

CACHE_DB = config.DATA / "trans_cache.db"
_conn: sqlite3.Connection | None = None
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS lines (
    k          TEXT PRIMARY KEY,   -- normalised source line
    da         TEXT NOT NULL,
    en         TEXT NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
"""

_WS = re.compile(r"\s+")


def key(line: str) -> str:
    """Whitespace-insensitive, case-sensitive. Lines carrying per-report data (names, dates)
    simply never hit; the boilerplate does."""
    return _WS.sub(" ", line).strip()


def _c() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.ensure_dirs()
        _conn = sqlite3.connect(CACHE_DB, timeout=30, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute("PRAGMA busy_timeout=30000")
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def get_many(ks: list[str]) -> dict[str, str]:
    if not ks:
        return {}
    uniq = list({k for k in ks})
    out: dict[str, str] = {}
    with _lock:
        c = _c()
        for i in range(0, len(uniq), 400):           # keep the SQL variable count sane
            chunk = uniq[i:i + 400]
            q = f"SELECT k, en FROM lines WHERE k IN ({','.join('?' * len(chunk))})"
            for row in c.execute(q, chunk).fetchall():
                out[row[0]] = row[1]
    return out


def put_many(pairs: list[tuple[str, str, str]]) -> None:
    """pairs = [(key, danish, english)]"""
    if not pairs:
        return
    now = time.time()
    with _lock:
        c = _c()
        c.executemany(
            "INSERT INTO lines(k,da,en,hits,created_at) VALUES (?,?,?,0,?) "
            "ON CONFLICT(k) DO UPDATE SET hits=lines.hits+1",
            [(k, da, en, now) for k, da, en in pairs])
        c.commit()


def stats() -> dict:
    with _lock:
        c = _c()
        n, h = c.execute("SELECT COUNT(*), COALESCE(SUM(hits),0) FROM lines").fetchone()
    return {"lines": n, "reuses": h}
