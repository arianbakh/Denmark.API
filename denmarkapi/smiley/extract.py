"""Extract structured data from harvested smiley PDFs — deterministic, no LLM, no OCR.

Runs NOW (pipelined) on PDFs already downloaded, while the harvest continues. Per report:
  - clean text via pdfplumber (x_tolerance=1.5 recovers spaces some PDFs omit)
  - classify placard vs report
  - split the body into control-point sections
  - flag pest + enforcement keywords (first-pass "rat issue" signal, refined later by the LLM)
Outputs Parquet parts (data/parquet/smiley_extract/part-*.parquet); resumable via state
(pipeline 'smiley_extract'). The unique free-text corpus for LLM translation/extraction is built
in a later step from these outputs.

Run:  python -m denmarkapi.smiley.extract [--limit N] [--workers K]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import pdfplumber

from .. import config, control, state

EXTRACT_PIPE = "smiley_extract"
OUT_DIR = config.PARQUET / "smiley_extract"

# Official control points (kontrolområder) — body sections start with these headers.
CONTROL_POINTS = [
    "Hygiejne", "Virksomhedens egenkontrol", "Godkendelser m.v.",
    "Mærkning og information", "Emballage m.v.", "Særlige mærkningsordninger",
    "Tilsætningsstoffer m.v.", "Import", "Andet", "Offentliggørelse af kontrolrapport",
]
_CP_RE = re.compile(r"(?=(?:%s)\s*:)" % "|".join(re.escape(c) for c in CONTROL_POINTS))

PEST_RE = re.compile(r"\b(rotte\w*|mus|mose\w*|skadedyr\w*|kakerlak\w*|insekt\w*|fluer|gnaver\w*)\b", re.I)
ENFORCE = {
    "indskaerpelse": re.compile(r"indskærp", re.I),
    "paabud": re.compile(r"påbud", re.I),
    "forbud": re.compile(r"forbud", re.I),
    "boede": re.compile(r"\bbøde\b", re.I),
    "gebyr": re.compile(r"gebyr", re.I),
    "politianmeldelse": re.compile(r"politianmeld", re.I),
    "autorisation_frataget": re.compile(r"(autorisation|registrering)\s+\w*\s*(frataget|inddrag)", re.I),
}


def _text(path: str) -> tuple[str, int]:
    with pdfplumber.open(path) as pdf:
        pages = [(p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages]
    return "\n".join(pages), len(pages)


def _sections(body: str) -> dict:
    parts = _CP_RE.split(body)
    out: dict[str, str] = {}
    for seg in parts:
        seg = seg.strip()
        if not seg:
            continue
        for cp in CONTROL_POINTS:
            if seg.startswith(cp):
                out.setdefault(cp, "")
                out[cp] += (" " if out[cp] else "") + seg
                break
    return out


def extract_one(report_id: str, path: str, navnelbnr: str | None) -> dict:
    control.wait_if_paused()
    try:
        text, n_pages = _text(path)
    except Exception as e:
        return {"report_id": report_id, "error": str(e)[:200]}
    doc_type = "placard" if "Scan: gå til" in text or "gå til https://findsmiley" in text else "report"
    sections = _sections(text) if doc_type == "report" else {}
    flags = {k: bool(rx.search(text)) for k, rx in ENFORCE.items()}
    return {
        "report_id": report_id,
        "navnelbnr": navnelbnr,
        "doc_type": doc_type,
        "n_pages": n_pages,
        "n_chars": len(text),
        "control_points": json.dumps(sorted(sections.keys()), ensure_ascii=False),
        "sections": json.dumps(sections, ensure_ascii=False),
        "has_pest": bool(PEST_RE.search(text)),
        **{f"has_{k}": v for k, v in flags.items()},
        "text": text,
        "error": None,
    }


def _todo(conn) -> list[tuple[str, str, str | None]]:
    done = {r["key"] for r in conn.execute(
        "SELECT key FROM items WHERE pipeline=? AND status='done'", (EXTRACT_PIPE,)).fetchall()}
    rows = conn.execute(
        "SELECT key, path, meta FROM items WHERE pipeline='smiley_report' "
        "AND status='done' AND path IS NOT NULL").fetchall()
    out = []
    for r in rows:
        if r["key"] in done:
            continue
        nav = None
        if r["meta"]:
            try:
                nav = json.loads(r["meta"]).get("navnelbnr")
            except Exception:
                pass
        out.append((r["key"], r["path"], nav))
    return out


def _write_part(records: list[dict], part: int) -> None:
    import os
    import pyarrow as pa
    import pyarrow.parquet as pq
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # pid in the name so a second extractor instance can't overwrite our parts.
    # Write to .tmp then rename so a concurrent reader (dashboard) never sees a partial file.
    path = OUT_DIR / f"part-{os.getpid()}-{part:05d}.parquet"
    tmp = str(path) + ".tmp"
    pq.write_table(pa.Table.from_pylist(records), tmp)
    os.replace(tmp, path)


def run(limit: int | None, workers: int, batch: int = 2000) -> None:
    config.ensure_dirs()
    with state.connect(check_same_thread=False) as conn:
        todo = _todo(conn)
        if limit:
            todo = todo[:limit]
        print(f"to extract: {len(todo)} PDFs   workers={workers}")
        if not todo:
            return
        existing = len(list(OUT_DIR.glob("part-*.parquet"))) if OUT_DIR.exists() else 0
        part = existing
        t0 = time.time()
        done_n, placard_n, pest_n, err_n = 0, 0, 0, 0
        buf: list[dict] = []

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
                        (EXTRACT_PIPE, rec["report_id"], "done", time.time()))
            part += 1
            buf = []

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(extract_one, rid, path, nav) for rid, path, nav in todo]
            for fut in futs:
                rec = fut.result()
                if rec.get("error"):
                    err_n += 1
                    continue
                done_n += 1
                placard_n += rec["doc_type"] == "placard"
                pest_n += rec["has_pest"]
                buf.append(rec)
                if len(buf) >= batch:
                    flush()
                    print(f"  extracted {done_n} (placards {placard_n}, pest {pest_n}, "
                          f"{done_n/(time.time()-t0):.0f}/s)")
        flush()
        print(f"\nDONE: extracted={done_n} placards={placard_n} pest_flagged={pest_n} "
              f"errors={err_n} in {time.time()-t0:.0f}s -> {OUT_DIR}")


def _harvest_running() -> bool:
    import subprocess
    try:
        return subprocess.run(["pgrep", "-f", "[s]miley.harvest"],
                              capture_output=True).returncode == 0
    except Exception:
        return False


def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 4))
    ap.add_argument("--watch", action="store_true",
                    help="keep extracting new PDFs until the harvest finishes")
    args = ap.parse_args()
    if not args.watch:
        run(args.limit, args.workers)
        return 0
    # Pipelined companion to the harvest: drain, then poll for more until harvest is done.
    while True:
        run(args.limit, args.workers)
        if not _harvest_running():
            with state.connect() as conn:
                if not _todo(conn):
                    print("harvest finished and nothing left to extract; exiting watch.")
                    return 0
        time.sleep(15)


if __name__ == "__main__":
    sys.exit(main())
