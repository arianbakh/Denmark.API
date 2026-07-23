"""Compute a compact status snapshot from state.db (+ PDF dir) and write status.json.

Errors are AGGREGATED (grouped by a short signature) so the dashboard never shows thousands
of individual errors.
"""
from __future__ import annotations
import json
import re
import time
from collections import Counter
from pathlib import Path

from .. import config, state

TOTAL_BUSINESSES = 58616  # from the smiley index; denominator for the progress bar

STATUS_JSON = config.DATA / "status.json"


def _err_signature(msg: str) -> str:
    if not msg:
        return "unknown"
    m = re.search(r"HTTP\s*(\d{3})", msg)
    if m:
        return f"HTTP {m.group(1)}"
    if "not a PDF" in msg:
        return "not a PDF (HTML response)"
    if "timed out" in msg or "timeout" in msg.lower():
        return "timeout"
    if "Connection" in msg or "connection" in msg:
        return "connection error"
    return msg[:40]


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

        cutoff = time.time() - 300
        recent = c.execute(
            "SELECT COUNT(*) n FROM items WHERE pipeline='smiley_report' "
            "AND status='done' AND updated_at > ?", (cutoff,)).fetchone()["n"]

    # PDF disk usage (cheap: sum sizes)
    pdf_count, pdf_bytes = 0, 0
    pdir = config.PDF_DIR
    if pdir.exists():
        for p in pdir.rglob("*.pdf"):
            pdf_count += 1
            try:
                pdf_bytes += p.stat().st_size
            except OSError:
                pass

    bus = pipes.get("smiley_business", {})
    rpt = pipes.get("smiley_report", {})
    return {
        "updated_at": time.time(),
        "businesses": {
            "done": bus.get("done", 0),
            "failed": bus.get("failed", 0),
            "total": TOTAL_BUSINESSES,
        },
        "reports": {
            "done": rpt.get("done", 0),
            "pending": rpt.get("pending", 0),
            "failed": rpt.get("failed", 0),
            "skipped": rpt.get("skipped", 0),
        },
        "pdfs": {"count": pdf_count, "bytes": pdf_bytes},
        "rate": {"pdfs_per_min_5m": round(recent / 5.0, 1)},
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
