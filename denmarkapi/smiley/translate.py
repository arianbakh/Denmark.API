"""Plain English text of each report — for search and the app UI, not for display as a page.

Companion to overlay_pdf.py, which produces the layout-preserving English PDF. This one produces
the same English as searchable TEXT in parquet/smiley_translate (report_id, navnelbnr, text_en).

It pays the LLM almost nothing, because it reuses the OVERLAY'S CACHE.

The first version asked the model to translate each report's whole text in one go, keyed on that
whole text — so it shared nothing with the overlay and every report was translated twice, once
for the PDF and once for the text. The overlay's unit is the PARAGRAPH, cached in
data/trans_cache.db, so the way to share is to ask for exactly the same paragraphs: read the same
PDF, group its lines with the same code (overlay_pdf._lines / _paragraphs), and look the blocks
up by the same key. Measured on reports the overlay had already done: 100% cache hit, zero LLM
calls. Only reports the overlay has NOT reached yet cost anything, and those results land in the
same cache, so whichever stage sees a paragraph first pays for it and the other gets it free.

Consequences worth knowing:
  * run this AFTER (or behind) the overlay and it is nearly free; run it first and it does the
    work the overlay would have done anyway.
  * it needs the PDF on disk, not just the extract parquet — the parquet's text comes from a
    different extractor (pdfplumber) and would not produce matching cache keys.
  * concurrency follows the OVERLAY slider, since it is the same workload against the same vLLM.

Run:  python -m denmarkapi.smiley.translate [--limit N] [--concurrency K] [--watch]
"""
from __future__ import annotations
import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz

from .. import config, control, state
from ..llm import client
from . import overlay_pdf as ov
from . import trans_cache
from .urls import pdf_path

PIPE = "smiley_translate"
OUT_DIR = config.PARQUET / "smiley_translate"
EXTRACT_GLOB = f"{config.PARQUET / 'smiley_extract'}/*.parquet"
MAX_POOL = 64
MAX_ATTEMPTS = 3


def translate_report(report_id: str, navnelbnr) -> dict:
    """English text for one report, assembled from the shared paragraph cache."""
    control.wait_if_paused()
    doc = fitz.open(pdf_path(report_id))
    pages: list[str] = []
    try:
        for page in doc:
            lines = ov._lines(page)
            if not lines:
                continue
            groups = ov._paragraphs(lines, page.rect.width)
            texts = [" ".join(lines[i][0].strip() for i in g) for g in groups]
            ctx = "\n".join(t for t, _, _, _, _, _ in lines)
            ens = ov._translate(texts, ctx)          # cache-first; only misses hit the LLM
            pages.append("\n".join(e.strip() for e in ens if e.strip()))
    finally:
        doc.close()
    return {"report_id": str(report_id), "navnelbnr": navnelbnr,
            "text_en": "\n\n".join(p for p in pages if p)}


def _select(limit: int | None) -> list[tuple]:
    import duckdb
    with state.connect() as c:
        done = {r["key"] for r in c.execute(
            "SELECT key FROM items WHERE pipeline=? AND status IN ('done','skipped')",
            (PIPE,)).fetchall()}
    rows = duckdb.sql(
        f"SELECT report_id, navnelbnr FROM read_parquet('{EXTRACT_GLOB}') "
        f"WHERE doc_type='report'").fetchall()
    todo = [(str(r[0]), r[1]) for r in rows if str(r[0]) not in done]
    return todo[:limit] if limit else todo


def _write_part(records: list[dict], n: int) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"part-{os.getpid()}-{n:05d}.parquet"
    tmp = str(path) + ".tmp"
    pq.write_table(pa.Table.from_pylist(records), tmp)   # tmp+rename: readers see whole files
    os.replace(tmp, path)


def run(limit: int | None, concurrency: int | None, batch: int = 200) -> dict:
    config.ensure_dirs()
    if not client.is_up():
        print("ERROR: vLLM not reachable at", client.BASE, file=sys.stderr)
        return {}
    if concurrency is not None:
        ov._gate._get_limit = lambda: concurrency
    todo = _select(limit)
    print(f"reports to translate: {len(todo)}   concurrency="
          + (f"overlay slider ({control.overlay_concurrency()})" if concurrency is None
             else str(concurrency)))
    if not todo:
        return {}
    before = dict(ov.STATS)                 # so we can report OUR llm calls, not the overlay's
    t0 = time.time()
    ok = err = skip = 0
    buf: list[dict] = []
    part = len(list(OUT_DIR.glob("part-*.parquet"))) if OUT_DIR.exists() else 0
    lock = threading.Lock()

    def one(rid: str, nav):
        if not pdf_path(rid).exists():
            return rid, None, "original PDF not on disk"
        try:
            return rid, translate_report(rid, nav), None
        except Exception as e:
            return rid, None, f"{type(e).__name__}: {str(e)[:200]}"

    with state.connect(check_same_thread=False) as conn:
        def flush():
            nonlocal part, buf
            if not buf:
                return
            _write_part(buf, part)
            with conn:
                for rec in buf:
                    conn.execute(
                        "INSERT INTO items(pipeline,key,status,updated_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(pipeline,key) DO UPDATE SET status='done', "
                        "updated_at=excluded.updated_at",
                        (PIPE, rec["report_id"], "done", time.time()))
            part += 1
            buf = []

        with ThreadPoolExecutor(max_workers=MAX_POOL) as pool:
            futs = [pool.submit(one, rid, nav) for rid, nav in todo]
            for fut in as_completed(futs):
                rid, rec, problem = fut.result()
                with lock:
                    if problem:
                        tried = conn.execute(
                            "SELECT attempts FROM items WHERE pipeline=? AND key=?",
                            (PIPE, rid)).fetchone()
                        done_trying = (tried["attempts"] if tried else 0) + 1 >= MAX_ATTEMPTS
                        state.upsert_item(conn, PIPE, rid,
                                          status="skipped" if done_trying else "failed",
                                          error=problem, bump_attempt=True)
                        conn.commit()
                        skip += 1
                        err += 0 if done_trying else 1
                    else:
                        buf.append(rec)
                        ok += 1
                        if len(buf) >= batch:
                            flush()
                if ok and ok % 200 == 0:
                    print(f"  translated {ok}/{len(todo)}  ({ok/(time.time()-t0):.2f}/s, "
                          f"{err} err, {skip} skipped)")
        flush()

    dt = time.time() - t0
    calls = ov.STATS["llm_calls"] - before["llm_calls"]
    blocks = ov.STATS["lines"] - before["lines"]
    hits = ov.STATS["cache_hits"] - before["cache_hits"]
    print(f"\nDONE: {ok} translated, {err} errors, {skip} skipped in {dt:.0f}s "
          f"({ok/dt if dt else 0:.2f}/s)")
    print(f"  blocks {blocks}, of which {hits} from the shared cache "
          f"({100*hits/max(1,blocks):.1f}%) — {calls} LLM calls")
    return {"ok": ok, "err": err, "skipped": skip, "seconds": round(dt, 1),
            "blocks": blocks, "cache_hits": hits, "llm_calls": calls}


def _running(pat: str) -> bool:
    import subprocess
    try:
        return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=None,
                    help="fixed in-flight LLM requests; omit to follow the overlay slider")
    ap.add_argument("--watch", action="store_true",
                    help="keep going until harvest+extract finish and nothing remains")
    args = ap.parse_args()
    run(args.limit, args.concurrency)
    if not args.watch:
        return 0
    while True:
        run(args.limit, args.concurrency)
        if not _running("[s]miley.harvest") and not _running("[s]miley.extract"):
            if not _select(None):
                print("all upstream done and nothing left to translate; exiting watch.")
                return 0
        time.sleep(20)


if __name__ == "__main__":
    sys.exit(main())
