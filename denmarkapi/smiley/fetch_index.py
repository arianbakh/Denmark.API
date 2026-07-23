"""Fetch the smiley bulk index (XLSX + XML) from findsmiley.dk.

The download URLs are versioned CMS media paths that rotate on republish, so we scrape
the links off the page rather than hardcode them. Content-hashed, dated snapshots: if the
file hasn't changed since last run, we record that and don't re-save. Idempotent + resumable.

Run: python -m denmarkapi.smiley.fetch_index
"""
from __future__ import annotations
import datetime as dt
import hashlib
import os
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .. import config, state

SOURCE = "smiley"


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=60, **kw)
    r.raise_for_status()
    return r


def discover_links(page_url: str = config.SMILEY_DATA_PAGE) -> dict[str, str]:
    """Return {'xlsx': url, 'xml': url} scraped from the data page."""
    html = _get(page_url).text
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, list[str]] = {"xlsx": [], "xml": []}
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"])
        low = href.lower()
        if low.endswith(".xlsx") or ".xlsx?" in low:
            found["xlsx"].append(href)
        elif low.endswith(".xml") or ".xml?" in low:
            found["xml"].append(href)

    def pick(cands: list[str]) -> str | None:
        if not cands:
            return None
        # Prefer a smiley-related filename when several candidates exist.
        for c in cands:
            if "smiley" in c.lower():
                return c
        return cands[0]

    return {k: pick(v) for k, v in found.items() if pick(v)}


def _atomic_write(path, data: bytes) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def fetch_one(conn, kind: str, url: str) -> dict:
    data = _get(url).content
    sha = hashlib.sha256(data).hexdigest()
    prev = state.last_snapshot_sha(conn, SOURCE, kind)
    changed = sha != prev
    saved_path = None
    if changed:
        day = dt.date.today().isoformat()
        outdir = config.SNAPSHOTS / SOURCE / day
        outdir.mkdir(parents=True, exist_ok=True)
        name = os.path.basename(urlparse(url).path) or f"smiley.{kind}"
        saved_path = outdir / name
        _atomic_write(saved_path, data)
    state.record_snapshot(conn, SOURCE, kind, url, saved_path, sha, len(data), changed)
    return {"kind": kind, "url": url, "bytes": len(data), "sha256": sha[:12],
            "changed": changed, "path": str(saved_path) if saved_path else None}


def main() -> int:
    config.ensure_dirs()
    print("Discovering smiley index links...")
    links = discover_links()
    if not links:
        print("ERROR: no xlsx/xml links found on the page.", file=sys.stderr)
        return 2
    for k, u in links.items():
        print(f"  {k}: {u}")
    with state.connect() as conn:
        for kind, url in links.items():
            res = fetch_one(conn, kind, url)
            tag = "CHANGED -> saved" if res["changed"] else "unchanged"
            print(f"  [{res['kind']}] {res['bytes']:,} bytes  sha {res['sha256']}  {tag}"
                  + (f"  {res['path']}" if res["path"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
