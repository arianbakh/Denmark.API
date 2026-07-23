#!/usr/bin/env python3
"""Danish news RSS poller — runs on the always-on VPS to accumulate a topic archive
for the citizenship-test current-affairs vertical (see docs/news-sources.md).

Stores only title/summary/link as topic SIGNAL (no full-text republish). Dedupes by
entry id. Idempotent: safe to run on any schedule; re-runs add only new items.
"""
from __future__ import annotations
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

import feedparser

HOME = Path("/root/denmarknews")
DB = HOME / "news.db"

# Candidate feeds. The poller logs how many entries each returns, so dead URLs are obvious.
FEEDS = {
    # DR (public broadcaster) — verified working
    "dr_senestenyt":       "https://www.dr.dk/nyheder/service/feeds/senestenyt",
    "dr_indland":          "https://www.dr.dk/nyheder/service/feeds/indland",
    "dr_udland":           "https://www.dr.dk/nyheder/service/feeds/udland",
    "dr_politik":          "https://www.dr.dk/nyheder/service/feeds/politik",
    "dr_penge":            "https://www.dr.dk/nyheder/service/feeds/penge",
    # Broadsheet + business — verified working (diversity of outlets = importance signal)
    "politiken_seneste":   "https://politiken.dk/rss/senestenyt.rss",
    "borsen":              "https://borsen.dk/rss",
    # TODO: TV2 has no clean public RSS (404/redirect to HTML). Revisit / add regional TV2.
}

# Polite, identifiable UA so the outlet can contact us if needed (avoids abuse flags).
USER_AGENT = "GatherMind-DenmarkAPI-newsbot/0.1 (+https://github.com/arianbakh/Denmark.API)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id         TEXT PRIMARY KEY,   -- sha256(source|entry-id)
    source     TEXT NOT NULL,
    entry_id   TEXT,
    title      TEXT,
    summary    TEXT,
    link       TEXT,
    published  TEXT,
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_articles_fetched ON articles(fetched_at);
CREATE TABLE IF NOT EXISTS poll_log (
    ran_at REAL NOT NULL, source TEXT, entries INTEGER, new INTEGER, error TEXT
);
-- Per-feed HTTP validators for conditional GET (etag / last-modified).
CREATE TABLE IF NOT EXISTS feed_state (
    source TEXT PRIMARY KEY, etag TEXT, modified TEXT
);
"""


def conn() -> sqlite3.Connection:
    HOME.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def poll_feed(c, source, url) -> tuple[int, int, str | None]:
    try:
        row = c.execute("SELECT etag, modified FROM feed_state WHERE source=?", (source,)).fetchone()
        etag, modified = (row[0], row[1]) if row else (None, None)
        d = feedparser.parse(url, agent=USER_AGENT, etag=etag, modified=modified)
        # 304 Not Modified -> nothing new, no body transferred.
        if getattr(d, "status", None) == 304:
            return 0, 0, None
        # Persist new validators for next time.
        new_etag = getattr(d, "etag", None)
        new_mod = getattr(d, "modified", None)
        if new_etag or new_mod:
            c.execute("INSERT INTO feed_state(source,etag,modified) VALUES (?,?,?) "
                      "ON CONFLICT(source) DO UPDATE SET etag=excluded.etag, modified=excluded.modified",
                      (source, new_etag, new_mod))
        if getattr(d, "bozo", 0) and not d.entries:
            return 0, 0, f"parse error: {getattr(d, 'bozo_exception', '')}"
        new = 0
        for e in d.entries:
            entry_id = e.get("id") or e.get("link") or e.get("title", "")
            uid = hashlib.sha256(f"{source}|{entry_id}".encode()).hexdigest()
            try:
                c.execute(
                    "INSERT INTO articles(id,source,entry_id,title,summary,link,published,fetched_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (uid, source, entry_id, e.get("title"), e.get("summary"),
                     e.get("link"), e.get("published", e.get("updated")), time.time()),
                )
                new += 1
            except sqlite3.IntegrityError:
                pass  # already have it
        return len(d.entries), new, None
    except Exception as ex:  # network etc. — never crash the whole run
        return 0, 0, str(ex)


def main() -> int:
    c = conn()
    total_new = 0
    for source, url in FEEDS.items():
        entries, new, err = poll_feed(c, source, url)
        c.execute("INSERT INTO poll_log(ran_at,source,entries,new,error) VALUES (?,?,?,?,?)",
                  (time.time(), source, entries, new, err))
        total_new += new
        status = err if err else f"{entries} entries, {new} new"
        print(f"  {source:16} {status}")
    c.commit()
    total = c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"Run complete: +{total_new} new, {total} total archived.")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
