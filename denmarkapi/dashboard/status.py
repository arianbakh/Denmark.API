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
    # Refresh every 10s, not 30: the full rglob of ~175k files measures at 0.37s, and with the
    # harvest adding ~1 MB/s a 30s cache left the archive size reading ~30 MB behind reality.
    now = time.time()
    if now - _disk["t"] > 10 or _disk["count"] == 0:
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


def _running(pattern: str) -> bool:
    try:
        return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0
    except Exception:
        return False


_analyze_cache = {"t": 0.0, "stats": {}}


def _duck(query: str, retries: int = 3):
    # A concurrent writer may briefly leave a part mid-write; retry before giving up.
    import duckdb
    for i in range(retries):
        try:
            return duckdb.sql(query).fetchone()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(0.3)


def _analyze_stats(done_count: int) -> dict:
    now = time.time()
    # Refresh the parquet-derived fields at most once/60s; on failure KEEP the last good stats.
    if now - _analyze_cache["t"] > 60 or "actual_pest" not in _analyze_cache["stats"]:
        try:
            g = f"'{config.PARQUET / 'smiley_analyze'}/*.parquet'"
            row = _duck(
                f"SELECT SUM(actual_pest::int) pest, "
                f"COUNT(*) FILTER(WHERE severity='serious') serious, "
                f"COUNT(*) FILTER(WHERE severity='remarks') remarks, "
                f"COUNT(*) FILTER(WHERE max_enforcement IN ('fine','police','ban')) enforced "
                f"FROM read_parquet({g})")
            # Denominator: reports with remarks (the ones that need the LLM).
            ge = f"'{config.PARQUET / 'smiley_extract'}/*.parquet'"
            tot = _duck(
                f"SELECT COUNT(*) FROM read_parquet({ge}) WHERE doc_type='report' AND "
                f"(has_pest OR has_indskaerpelse OR has_paabud OR has_forbud OR has_gebyr "
                f"OR has_politianmeldelse OR has_boede OR text ILIKE '%konstateret%')")
            _analyze_cache["stats"].update(actual_pest=row[0] or 0, serious=row[1] or 0,
                                           remarks=row[2] or 0, enforced=row[3] or 0,
                                           to_analyze=tot[0] or 0)
            _analyze_cache["t"] = now
        except Exception:
            pass
    _analyze_cache["stats"]["analyzed"] = done_count
    return _analyze_cache["stats"]


_extract_cache = {"t": 0.0, "stats": {}}


def _extract_stats(done_count: int) -> dict:
    now = time.time()
    if now - _extract_cache["t"] > 60 or "reports" not in _extract_cache["stats"]:
        try:
            g = f"'{config.PARQUET / 'smiley_extract'}/*.parquet'"
            row = _duck(
                f"SELECT COUNT(*) FILTER(WHERE doc_type='report') reports, "
                f"COUNT(*) FILTER(WHERE doc_type='placard') placards, "
                f"SUM(has_pest::int) pest, SUM(has_indskaerpelse::int) injunctions, "
                f"SUM(has_gebyr::int) fees FROM read_parquet({g})")
            _extract_cache["stats"].update(reports=row[0] or 0, placards=row[1] or 0,
                                           pest=row[2] or 0, injunctions=row[3] or 0,
                                           fees=row[4] or 0)
            _extract_cache["t"] = now
        except Exception:
            pass
    _extract_cache["stats"]["extracted"] = done_count
    return _extract_cache["stats"]


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
        extract_done = c.execute(
            "SELECT COUNT(*) n FROM items WHERE pipeline='smiley_extract' AND status='done'"
        ).fetchone()["n"]
        analyze_done = c.execute(
            "SELECT COUNT(*) n FROM items WHERE pipeline='smiley_analyze' AND status='done'"
        ).fetchone()["n"]
        overlay_rows = c.execute(
            "SELECT status, COUNT(*) n FROM items WHERE pipeline='smiley_overlay' GROUP BY status"
        ).fetchall()
        overlay = {r["status"]: r["n"] for r in overlay_rows}

    _, pdf_bytes = _disk_stats()
    bus = pipes.get("smiley_business", {})
    rpt = pipes.get("smiley_report", {})
    return {
        "updated_at": time.time(),
        "harvest_running": _running("[s]miley.harvest"),
        "extract_running": _running("[s]miley.extract"),
        "analyze_running": _running("[s]miley.analyze"),
        "overlay_running": _running("[s]miley.overlay_pdf"),
        "businesses": {"done": bus.get("done", 0), "failed": bus.get("failed", 0),
                       "total": TOTAL_BUSINESSES},
        "reports": {"done": rpt.get("done", 0), "pending": rpt.get("pending", 0),
                    "failed": rpt.get("failed", 0), "skipped": rpt.get("skipped", 0)},
        "pdfs": {"count": rpt.get("done", 0), "bytes": pdf_bytes},
        "extract": _extract_stats(extract_done),
        "analyze": _analyze_stats(analyze_done),
        "overlay": {"done": overlay.get("done", 0), "skipped": overlay.get("skipped", 0),
                    "to_overlay": _extract_cache["stats"].get("reports", 0),
                    **_cache_stats()},
        "errors": errors,
    }


_cache_cache = {"t": 0.0, "stats": {"cache_lines": 0, "cache_reuses": 0}}


def _cache_stats() -> dict:
    """Line-translation cache size — cheap, but no need to hit it every 2s."""
    now = time.time()
    if now - _cache_cache["t"] > 30:
        try:
            from ..smiley import trans_cache
            s = trans_cache.stats()
            _cache_cache["stats"] = {"cache_lines": s["lines"], "cache_reuses": s["reuses"]}
            _cache_cache["t"] = now
        except Exception:
            pass
    return _cache_cache["stats"]


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
