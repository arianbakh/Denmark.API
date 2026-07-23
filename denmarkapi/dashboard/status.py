"""Compute a compact status snapshot from state.db and write status.json.

Kept CHEAP so it can run every ~2s: counts come from SQL; total PDF bytes from a disk scan
that is cached for 30s (not rescanned every tick). Derived metrics (rate, throughput, ETA) are
computed on the VPS from a short history of these snapshots.
Errors are AGGREGATED so the dashboard never shows thousands of individual errors.
"""
from __future__ import annotations
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from .. import config, state

TOTAL_BUSINESSES = 58616
STATUS_JSON = config.DATA / "status.json"

_disk = {"t": 0.0, "count": 0, "bytes": 0}   # cached disk scan (persists in the push loop process)


def _err_signature(msg: str) -> str:
    if not msg:
        return "unknown"
    m = re.search(r"HTTP\s*(\d{3})", msg)
    if m:
        return f"HTTP {m.group(1)}"
    if "not a PDF" in msg:
        return "invalid id (HTML 'Fejl' page)"
    if "timeout" in msg.lower() or "timed out" in msg:
        return "timeout"
    if "onnection" in msg:
        return "connection error"
    return msg[:40]


def _disk_stats() -> tuple[int, int]:
    now = time.time()
    if now - _disk["t"] > 30 or _disk["count"] == 0:
        c = b = 0
        if config.PDF_DIR.exists():
            for p in config.PDF_DIR.rglob("*.pdf"):
                c += 1
                try:
                    b += p.stat().st_size
                except OSError:
                    pass
        _disk.update(t=now, count=c, bytes=b)
    return _disk["count"], _disk["bytes"]


def _harvest_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-f", "[s]miley.harvest"],
                              capture_output=True).returncode == 0
    except Exception:
        return False


def compute() -> dict:
    with state.connect() as c:
        pipes = {}
        for pipe in ("smiley_business", "smiley_report"):
            rows = c.execute(
                "SELECT status, COUNT(*) n FROM items WHERE pipeline=? GROUP BY status",
                (pipe,)).fetchall()
            pipes[pipe] = {r["status"]: r["n"] for r in rows}
        agg = Counter()
        for r in c.execute(
                "SELECT error, COUNT(*) n FROM items "
                "WHERE status IN ('failed','skipped') AND error IS NOT NULL GROUP BY error"
        ).fetchall():
            agg[_err_signature(r["error"])] += r["n"]
        errors = [{"key": k, "count": v} for k, v in agg.most_common(10)]

    _, pdf_bytes = _disk_stats()
    bus = pipes.get("smiley_business", {})
    rpt = pipes.get("smiley_report", {})
    return {
        "updated_at": time.time(),
        "harvest_running": _harvest_running(),
        "businesses": {"done": bus.get("done", 0), "failed": bus.get("failed", 0),
                       "total": TOTAL_BUSINESSES},
        "reports": {"done": rpt.get("done", 0), "pending": rpt.get("pending", 0),
                    "failed": rpt.get("failed", 0), "skipped": rpt.get("skipped", 0)},
        "pdfs": {"count": rpt.get("done", 0), "bytes": pdf_bytes},
        "errors": errors,
    }


def write(path: Path = STATUS_JSON) -> dict:
    s = compute()
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    Path(tmp).replace(path)
    return s


if __name__ == "__main__":
    import pprint
    pprint.pp(write())
