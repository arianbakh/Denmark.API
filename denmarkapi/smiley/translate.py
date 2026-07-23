"""Full English translation of smiley reports — same layout, just English instead of Danish.

For the in-app PDF viewer (English UI). Translates the whole report text preserving structure;
keeps names/addresses/CVR/dates unchanged. Separate from analyze.py (which extracts structured
findings). In-run dedup on normalized text avoids re-translating identical reports. Resumable
via state (pipeline 'smiley_translate'); output in parquet/smiley_translate.

Run:  python -m denmarkapi.smiley.translate [--limit N] [--concurrency K]
"""
from __future__ import annotations
import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from .. import config, control, state
from ..llm import client

PIPE = "smiley_translate"
OUT_DIR = config.PARQUET / "smiley_translate"
EXTRACT_GLOB = f"{config.PARQUET / 'smiley_extract'}/*.parquet"

SYSTEM = (
    "Translate this Danish food-inspection (smiley) report into English. Preserve the EXACT "
    "structure: same line breaks, ordering, sections and layout. Keep business names, addresses, "
    "CVR/P-numbers and dates unchanged. Translate all Danish prose and fixed labels (e.g. "
    "'Kontrolrapport'->'Inspection report', 'side 1 af 2'->'page 1 of 2', control-area headers "
    "like 'Hygiejne: Håndtering af fødevarer'->'Hygiene: Handling of food'). Output ONLY the "
    "translated report text — no preamble, no commentary."
)


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t).lower()


def translate_one(report_id: str, navnelbnr, text_da: str) -> dict:
    control.wait_if_paused()
    en = client.chat(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": text_da[:6000]}],
        schema=None, max_tokens=4000, reasoning_effort="low")
    return {"report_id": report_id, "navnelbnr": navnelbnr, "text_en": en.strip()}


def _select(limit):
    con = duckdb.connect()
    with state.connect() as c:
        done = {r["key"] for r in c.execute(
            "SELECT key FROM items WHERE pipeline=? AND status='done'", (PIPE,)).fetchall()}
    rows = con.sql(
        f"SELECT report_id, navnelbnr, text FROM read_parquet('{EXTRACT_GLOB}') "
        f"WHERE doc_type='report'").fetchall()
    todo = [(r[0], r[1], r[2]) for r in rows if r[0] not in done]
    return todo[:limit] if limit else todo


def _write_part(records, n):
    import os
    import pyarrow as pa
    import pyarrow.parquet as pq
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"part-{os.getpid()}-{n:05d}.parquet"
    tmp = str(path) + ".tmp"
    pq.write_table(pa.Table.from_pylist(records), tmp)
    os.replace(tmp, path)


def run(limit, concurrency, batch=50):
    config.ensure_dirs()
    if not client.is_up():
        print("ERROR: vLLM not reachable at", client.BASE, file=sys.stderr)
        return
    todo = _select(limit)
    print(f"reports to translate: {len(todo)}   concurrency={concurrency}")
    if not todo:
        return
    cache: dict[str, str] = {}       # normalized-text -> English (in-run dedup)
    t0 = time.time()
    ok = err = reused = 0
    buf, part = [], (len(list(OUT_DIR.glob("part-*.parquet"))) if OUT_DIR.exists() else 0)

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
                        "ON CONFLICT(pipeline,key) DO UPDATE SET status='done', updated_at=excluded.updated_at",
                        (PIPE, rec["report_id"], "done", time.time()))
            part += 1
            buf = []

        # Split into cache-hits (reuse) and misses (call the LLM).
        misses = []
        for rid, nav, txt in todo:
            k = _norm(txt)
            if k in cache:
                buf.append({"report_id": rid, "navnelbnr": nav, "text_en": cache[k]})
                reused += 1
            else:
                misses.append((rid, nav, txt, k))

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(translate_one, rid, nav, txt): (rid, nav, txt, k)
                    for rid, nav, txt, k in misses}
            for fut in as_completed(futs):
                _, _, _, k = futs[fut]
                try:
                    rec = fut.result()
                    cache[k] = rec["text_en"]
                    buf.append(rec)
                    ok += 1
                except Exception as e:
                    err += 1
                    if err <= 3:
                        print("  err:", str(e)[:120])
                if len(buf) >= batch:
                    flush()
                if ok and ok % 200 == 0:
                    print(f"  translated {ok} (+{reused} reused)  {ok/(time.time()-t0):.1f}/s  {err} err")
        flush()
    print(f"\nDONE: translated={ok} reused={reused} errors={err} in {time.time()-t0:.0f}s -> {OUT_DIR}")


def _running(pat):
    import subprocess
    try:
        return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--watch", action="store_true")
    args = ap.parse_args()
    if not args.watch:
        run(args.limit, args.concurrency)
        return 0
    while True:
        run(args.limit, args.concurrency)
        if not _running("[s]miley.harvest") and not _running("[s]miley.extract"):
            if not _select(None):
                print("done; exiting watch.")
                return 0
        time.sleep(20)


if __name__ == "__main__":
    sys.exit(main())
