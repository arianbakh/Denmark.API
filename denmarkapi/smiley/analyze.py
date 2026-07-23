"""LLM extraction stage: turn deterministic-extracted reports into STRUCTURED FINDINGS
using local gpt-oss-20b. Resolves the mention-vs-finding problem, classifies enforcement,
detects resolution, and produces English text for the app.

Cost control: only reports that actually have remarks are sent to the LLM (all-clear reports
are recorded deterministically as no_remarks). Concurrency lets vLLM batch server-side.
Resumable via state (pipeline 'smiley_analyze'); output in parquet/smiley_analyze.

Run:  python -m denmarkapi.smiley.analyze [--limit N] [--concurrency K]
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from .. import config, state
from ..llm import client

ANALYZE_PIPE = "smiley_analyze"
OUT_DIR = config.PARQUET / "smiley_analyze"
EXTRACT_GLOB = f"{config.PARQUET / 'smiley_extract'}/*.parquet"

CATEGORIES = ["hygiene", "pest", "labeling", "temperature", "self_control",
              "approval", "traceability", "maintenance", "other"]
ENFORCE = ["none", "guidance", "injunction", "order", "ban", "fine", "police"]

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["overall", "summary_en", "findings"],
    "properties": {
        "overall": {"type": "string", "enum": ["no_remarks", "minor", "remarks", "serious"]},
        "summary_en": {"type": "string"},
        "findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["category", "description_en", "is_actual_finding",
                         "pest_type", "enforcement", "resolved"],
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "description_en": {"type": "string"},
                "is_actual_finding": {"type": "boolean"},
                "pest_type": {"type": ["string", "null"]},
                "enforcement": {"type": "string", "enum": ENFORCE},
                "resolved": {"type": "boolean"},
            }}},
    }}

SYSTEM = (
    "You analyze Danish food-inspection (smiley) reports. Extract the actual inspection findings. "
    "CRITICAL: distinguish a real finding (a problem observed at THIS visit) from: advice/guidance "
    "('vejledt'), a clean check ('ingen anmærkninger', 'ingen spor af skadedyr'), a self-check, or "
    "a reference to a PRIOR/already-resolved case ('fulgt op på ...', 'bragt i orden'). Set "
    "is_actual_finding accordingly, and resolved=true when the text says the matter was fixed. "
    "Map enforcement: indskærpelse->injunction, påbud->order, forbud->ban, bøde/bødeforlæg->fine, "
    "politianmeldelse->police, else guidance/none. For pests set category=pest and pest_type "
    "(rats/mice/cockroaches/insects/birds). Write concise English. Output must match the schema."
)


def _select(limit: int | None) -> list[tuple]:
    con = duckdb.connect()
    done = set()
    with state.connect() as c:
        done = {r["key"] for r in c.execute(
            "SELECT key FROM items WHERE pipeline=? AND status='done'", (ANALYZE_PIPE,)).fetchall()}
    # Reports with remarks: any enforcement/pest flag, or a 'konstateret' finding marker.
    rows = con.sql(f"""
        SELECT report_id, navnelbnr, text FROM read_parquet('{EXTRACT_GLOB}')
        WHERE doc_type='report' AND (
            has_pest OR has_indskaerpelse OR has_paabud OR has_forbud OR has_gebyr
            OR has_politianmeldelse OR has_boede OR text ILIKE '%konstateret%')
    """).fetchall()
    todo = [(r[0], r[1], r[2]) for r in rows if r[0] not in done]
    return todo[:limit] if limit else todo


def _severity(findings: list) -> str:
    # Derived from the findings themselves (the model's own 'overall' is unreliable).
    actual = [f for f in findings if f.get("is_actual_finding") and not f.get("resolved")]
    if not actual:
        return "no_remarks"
    enf = _max_enforcement(actual)
    if enf in ("fine", "police", "ban"):
        return "serious"
    if enf in ("injunction", "order"):
        return "remarks"
    return "minor"


def analyze_one(report_id: str, navnelbnr, text: str) -> dict:
    out = client.chat(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": text[:6000]}],
        schema=SCHEMA, max_tokens=3000, reasoning_effort="low")
    findings = out.get("findings", [])
    actual = [f for f in findings if f.get("is_actual_finding") and not f.get("resolved")]
    return {
        "report_id": report_id, "navnelbnr": navnelbnr,
        "severity": _severity(findings),            # authoritative (derived)
        "overall_llm": out.get("overall"),          # model's own label (for reference)
        "summary_en": out.get("summary_en"),
        "n_findings": len(findings),
        "n_actual_findings": len(actual),
        "actual_pest": any(f.get("category") == "pest" and f.get("is_actual_finding")
                           and not f.get("resolved") for f in findings),
        "max_enforcement": _max_enforcement(actual),
        "findings": json.dumps(findings, ensure_ascii=False),
    }


def _max_enforcement(findings: list) -> str:
    order = {e: i for i, e in enumerate(ENFORCE)}
    best = "none"
    for f in findings:
        e = f.get("enforcement", "none")
        if order.get(e, 0) > order.get(best, 0):
            best = e
    return best


def _write_part(records: list[dict], n: int) -> None:
    import os
    import pyarrow as pa
    import pyarrow.parquet as pq
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), OUT_DIR / f"part-{os.getpid()}-{n:05d}.parquet")


def run(limit: int | None, concurrency: int, batch: int = 500) -> None:
    config.ensure_dirs()
    if not client.is_up():
        print("ERROR: vLLM not reachable at", client.BASE, file=sys.stderr)
        return
    todo = _select(limit)
    print(f"reports to analyze: {len(todo)}   concurrency={concurrency}")
    if not todo:
        return
    t0 = time.time()
    ok = err = 0
    buf: list[dict] = []
    part = len(list(OUT_DIR.glob("part-*.parquet"))) if OUT_DIR.exists() else 0

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
                        (ANALYZE_PIPE, rec["report_id"], "done", time.time()))
            part += 1
            buf = []

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(analyze_one, rid, nav, txt): rid for rid, nav, txt in todo}
            for fut in as_completed(futs):
                try:
                    buf.append(fut.result())
                    ok += 1
                except Exception as e:
                    err += 1
                    if err <= 3:
                        print("  err:", str(e)[:120])
                if len(buf) >= batch:
                    flush()
                if ok and ok % 200 == 0:
                    print(f"  analyzed {ok}/{len(todo)}  ({ok/(time.time()-t0):.1f}/s, {err} err)")
        flush()
    print(f"\nDONE: analyzed={ok} errors={err} in {time.time()-t0:.0f}s -> {OUT_DIR}")


def _running(pat: str) -> bool:
    import subprocess
    try:
        return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--watch", action="store_true",
                    help="keep analyzing until harvest+extract finish and nothing remains")
    args = ap.parse_args()
    if not args.watch:
        run(args.limit, args.concurrency)
        return 0
    while True:
        run(args.limit, args.concurrency)
        if not _running("[s]miley.harvest") and not _running("[s]miley.extract"):
            if not _select(None):
                print("all upstream done and nothing left to analyze; exiting watch.")
                return 0
        time.sleep(20)


if __name__ == "__main__":
    sys.exit(main())
