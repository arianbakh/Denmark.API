"""Layout-preserving English PDFs: overlay English onto a COPY of the original report.

The report is a single background image (letterhead, green tables, smiley faces) with vector
TEXT on top. So we: redact each text LINE (no fill — the background image shows through),
then reinsert the English at the same position, in the same colour, sized to fit. Numbers /
dates / grid cells (no letters) are left untouched. No source/model disclosure.

Two things the first version lacked, both of which decide whether this can run over ~150k
reports rather than a handful:
  * the template's OWN labels are baked into the background raster and stayed Danish —
    template.py patches those from a per-variant spec built once (see its docstring);
  * every page paid the LLM for text it had already translated a thousand times over —
    trans_cache.py caches per LINE across all reports, so a page whose lines are all known
    costs zero LLM calls. Misses are still translated with the whole page as context.

Resumable via state (pipeline 'smiley_overlay'), --watch, and gated by the dashboard's
overlay concurrency slider so it can share the GPU with analyze.

Run:  python -m denmarkapi.smiley.overlay_pdf --report 6759175
      python -m denmarkapi.smiley.overlay_pdf --limit 100
      python -m denmarkapi.smiley.overlay_pdf --watch
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz

from .. import config, control, state
from ..llm import client
from . import template, trans_cache

OVERLAY_PIPE = "smiley_overlay"
OUT_DIR = config.DATA / "pdfs_en"
EXTRACT_GLOB = f"{config.PARQUET / 'smiley_extract'}/*.parquet"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_ALPHA = re.compile(r"[A-Za-zÆØÅæøå]")
MAX_POOL = 64

# Ids, not positions: a model that merges or drops one line would otherwise shift every later
# line onto the wrong place on the page, silently and invisibly.
LINES_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "en"],
        "properties": {"id": {"type": "integer"}, "en": {"type": "string"}}}}},
}
SYSTEM = (
    "You are translating a Danish food-inspection report line by line. You get the full page as "
    "context, and a JSON array of the lines that still need translating, each with an 'id' (a "
    "line may be a sentence fragment continued on the next line). Translate each line in the "
    "context of the whole page, and return one item per input id, echoing the SAME id with its "
    "English text. Do not merge, split, add, drop or renumber items. Keep business names, "
    "addresses, CVR/P-numbers, dates and standalone numbers unchanged.\n"
    # The form's own labels are translated separately from a fixed dictionary (template.py).
    # Without this glossary the free text drifts — the same report ends up saying both
    # "inspection report" and "control report" — which reads as a translation error.
    "Use EXACTLY these terms, which match the printed form:\n"
    "kontrolrapport = inspection report; kontrol/kontrolbesøg = inspection; "
    "tilsynsførende = inspector; indskærpelse = injunction; påbud = order; forbud = prohibition; "
    "bødeforlæg = fine; politianmeldelse = police report; egenkontrol = own-check system; "
    "anmærkning = remark; ingen anmærkninger = no remarks; virksomhed = business; "
    "Fødevarestyrelsen = Danish Veterinary and Food Administration; "
    "mærkning = labelling; skadedyr = pests; varemodtagelse = receipt of goods; "
    "opbevaring = storage; nedkøling = cooling; sporbarhed = traceability; "
    "bragt i orden = brought into order."
)

_stats_lock = threading.Lock()
STATS = {"llm_calls": 0, "lines": 0, "cache_hits": 0, "pages": 0,
         "labels": 0, "unknown_variant_pages": 0, "retried_lines": 0, "untranslated_lines": 0}


def _bump(**kw):
    with _stats_lock:
        for k, v in kw.items():
            STATS[k] += v


class DynamicGate:
    """In-flight LLM requests, capped by a live value from control.json (dashboard slider)."""
    def __init__(self, get_limit):
        self._get_limit = get_limit
        self._cv = threading.Condition()
        self._in_flight = 0

    def __enter__(self):
        with self._cv:
            while self._in_flight >= self._get_limit():
                self._cv.wait(1.0)
            self._in_flight += 1
        return self

    def __exit__(self, *exc):
        with self._cv:
            self._in_flight -= 1
            self._cv.notify()
        return False


_gate = DynamicGate(control.overlay_concurrency)


def _int_color(c: int):
    return ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)


def _lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            spans = l.get("spans", [])
            text = "".join(s["text"] for s in spans)
            if not text.strip() or not _ALPHA.search(text):
                continue  # leave numbers / grid / blanks untouched
            size = max(s["size"] for s in spans)
            color = _int_color(spans[0].get("color", 0))
            bold = any("bold" in (s.get("font", "") or "").lower() for s in spans)
            out.append((text, fitz.Rect(l["bbox"]), size, color, bold))
    return out


def _translate(texts: list[str], page_context: str) -> list[str]:
    """Cache-first. Only genuinely new lines reach the LLM, with the page as context."""
    keys = [trans_cache.key(t) for t in texts]
    cached = trans_cache.get_many(keys)
    miss_idx = [i for i, k in enumerate(keys) if k not in cached]
    # De-duplicate within the page too: the same line twice costs one slot, not two.
    seen: dict[str, int] = {}
    todo: list[int] = []
    for i in miss_idx:
        if keys[i] not in seen:
            seen[keys[i]] = i
            todo.append(i)
    _bump(lines=len(texts), cache_hits=len(texts) - len(todo))

    fresh: dict[str, str] = {}
    if todo:
        got = _call(texts, todo, page_context)
        # Ids the model didn't return would silently stay Danish on the page. That happens
        # often enough on long pages to matter, so ask again for just the stragglers.
        missing = [i for i in todo if i not in got]
        if missing:
            _bump(retried_lines=len(missing))
            got.update(_call(texts, missing, page_context))
            still = [i for i in missing if i not in got]
            if still:
                _bump(untranslated_lines=len(still))
        for i in todo:
            if i in got:
                fresh[keys[i]] = got[i]
        trans_cache.put_many([(keys[i], texts[i], fresh[keys[i]])
                              for i in todo if keys[i] in fresh])

    return [cached.get(k, fresh.get(k, t)) for k, t in zip(keys, texts)]


def _call(texts: list[str], ids: list[int], page_context: str) -> dict[int, str]:
    """One id-keyed translation request. Returns {id: english} for whatever came back."""
    with _gate:
        out = client.chat(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": json.dumps(
                 {"page_context": page_context,
                  "lines_to_translate": [{"id": i, "da": texts[i]} for i in ids]},
                 ensure_ascii=False)}],
            schema=LINES_SCHEMA, max_tokens=4096, reasoning_effort="low")
    _bump(llm_calls=1)
    return {it["id"]: it["en"] for it in out.get("items", [])
            if isinstance(it, dict) and isinstance(it.get("id"), int) and it["id"] in set(ids)}


def _insert_fitted(page, rect, text, fontsize, color, bold=False):
    """Draw text in rect, shrinking the font until it fits. rect may extend past the original."""
    name, path = ("dejavu-b", FONT_BOLD) if bold and os.path.exists(FONT_BOLD) else ("dejavu", FONT)
    r = fitz.Rect(rect.x0, rect.y0 - 0.5, min(rect.x1, page.rect.width - 4), rect.y1 + 1.5)
    fs = min(fontsize, 11.0)
    while fs >= 4:
        if page.insert_textbox(r, text, fontname=name, fontfile=path, fontsize=fs,
                               color=color, align=fitz.TEXT_ALIGN_LEFT) >= 0:
            return
        fs -= 0.5
    page.insert_textbox(r, text, fontname=name, fontfile=path, fontsize=4, color=color)


def _tpl_insert(page, rect, text, height, color, bold):
    _insert_fitted(page, rect, text, height * 0.80, color, bold)


def overlay(report_id: str, original_path: str) -> str:
    doc = fitz.open(original_path)
    for page in doc:
        lines = _lines(page)
        ens = []
        if lines:
            ctx = "\n".join(t for t, _, _, _, _ in lines)
            ens = _translate([t for t, _, _, _, _ in lines], ctx)
            for _, rect, _, _, _ in lines:
                page.add_redact_annot(rect)                   # no fill -> keep background image
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        # Baked-in template labels (must come after apply_redactions, which rewrites the page).
        # Obstacles are collected above, while the page still has its text.
        n_lab, n_unk = template.patch_page(doc, page, _tpl_insert,
                                           [rect for _, rect, _, _, _ in lines])
        _bump(pages=1, labels=n_lab, unknown_variant_pages=n_unk)
        for (_, rect, size, color, bold), en in zip(lines, ens):
            grow = fitz.Rect(rect.x0, rect.y0, min(rect.x1 + 55, page.rect.width - 6), rect.y1)
            _insert_fitted(page, grow, en, size, color, bold)
    shard = OUT_DIR / report_id[-3:].rjust(3, "0")
    shard.mkdir(parents=True, exist_ok=True)
    out = shard / f"{report_id}.pdf"
    tmp = str(out) + ".tmp"
    try:
        # Without this each PDF embeds the whole DejaVu face (~750 KB) — 1.2 MB per report
        # against a 415 KB original. Subsetting to the glyphs actually used cuts that ~60%.
        doc.subset_fonts()
    except Exception:
        pass
    doc.save(tmp, garbage=4, deflate=True)       # tmp+rename: a reader never sees a partial PDF
    doc.close()
    os.replace(tmp, out)
    return str(out)


def _original(report_id: str) -> str | None:
    p = config.PDF_DIR / report_id[-3:].rjust(3, "0") / f"{report_id}.pdf"
    return str(p) if p.exists() else None


def _select(limit: int | None) -> list[str]:
    """Reports with a downloaded PDF that have not been overlaid yet."""
    import duckdb
    with state.connect() as c:
        done = {r["key"] for r in c.execute(
            "SELECT key FROM items WHERE pipeline=? AND status='done'",
            (OVERLAY_PIPE,)).fetchall()}
    try:
        rows = duckdb.sql(
            f"SELECT report_id FROM read_parquet('{EXTRACT_GLOB}') WHERE doc_type='report'"
        ).fetchall()
        ids = [str(r[0]) for r in rows]
    except Exception:                            # extract hasn't produced parquet yet
        with state.connect() as c:
            ids = [r["key"] for r in c.execute(
                "SELECT key FROM items WHERE pipeline='smiley_report' AND status='done'"
            ).fetchall()]
    todo = [i for i in ids if i not in done]
    return todo[:limit] if limit else todo


def run(limit: int | None, concurrency: int | None) -> dict:
    config.ensure_dirs()
    if not client.is_up():
        print("ERROR: vLLM not reachable at", client.BASE, file=sys.stderr)
        return {}
    if not template.known_variants():
        print("WARNING: no template specs in", template.SPEC_DIR,
              "- baked labels will stay Danish. Run: python -m denmarkapi.smiley.template --build",
              file=sys.stderr)
    _gate._get_limit = (control.overlay_concurrency if concurrency is None
                        else (lambda: concurrency))
    todo = _select(limit)
    print(f"reports to overlay: {len(todo)}   concurrency="
          + (f"slider ({control.overlay_concurrency()})" if concurrency is None
             else str(concurrency)))
    if not todo:
        return {}
    t0 = time.time()
    ok = err = skip = 0
    db_lock = threading.Lock()

    def one(rid: str):
        control.wait_if_paused()
        orig = _original(rid)
        if not orig:
            return rid, None, "original PDF not on disk"
        return rid, overlay(rid, orig), None

    with state.connect(check_same_thread=False) as conn:
        with ThreadPoolExecutor(max_workers=MAX_POOL) as pool:
            futs = [pool.submit(one, rid) for rid in todo]
            for fut in as_completed(futs):
                try:
                    rid, path, problem = fut.result()
                    with db_lock:
                        if problem:
                            state.upsert_item(conn, OVERLAY_PIPE, rid, status="skipped",
                                              error=problem, bump_attempt=True)
                            skip += 1
                        else:
                            state.upsert_item(conn, OVERLAY_PIPE, rid, status="done",
                                              path=path, bump_attempt=True)
                            ok += 1
                        conn.commit()
                except Exception as e:
                    err += 1
                    if err <= 3:
                        print("  err:", str(e)[:160])
                if ok and ok % 50 == 0:
                    print(f"  overlaid {ok}/{len(todo)}  ({ok/(time.time()-t0):.2f}/s, "
                          f"{err} err, {skip} skipped)")

    dt = time.time() - t0
    cache = trans_cache.stats()
    summary = {"ok": ok, "err": err, "skipped": skip, "seconds": round(dt, 1),
               "reports_per_s": round(ok / dt, 3) if dt else 0, **STATS, "cache": cache}
    print(f"\nDONE: {ok} overlaid, {err} errors, {skip} skipped in {dt:.0f}s "
          f"({ok/dt if dt else 0:.2f}/s)")
    print(f"  LLM calls {STATS['llm_calls']} for {STATS['pages']} pages; "
          f"lines {STATS['lines']} of which {STATS['cache_hits']} served from cache "
          f"({100*STATS['cache_hits']/max(1,STATS['lines']):.1f}%)")
    print(f"  template labels patched {STATS['labels']}; "
          f"unknown-variant pages {STATS['unknown_variant_pages']}")
    print(f"  lines needing a retry {STATS['retried_lines']} "
          f"({100*STATS['retried_lines']/max(1,STATS['lines']):.2f}%); "
          f"still Danish after retry {STATS['untranslated_lines']} "
          f"({100*STATS['untranslated_lines']/max(1,STATS['lines']):.3f}%)")
    print(f"  cache now {cache['lines']} lines, {cache['reuses']} reuses")
    return summary


def _running(pat: str) -> bool:
    import subprocess
    try:
        return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=str, default=None, help="overlay a single report id")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=None,
                    help="fixed max in-flight LLM requests; omit to follow the dashboard slider")
    ap.add_argument("--watch", action="store_true",
                    help="keep overlaying until harvest+extract finish and nothing remains")
    ap.add_argument("--json", type=str, default=None, help="write the run summary to this file")
    args = ap.parse_args()

    if args.report:
        orig = _original(args.report)
        if not orig:
            print("original PDF not on disk:", args.report, file=sys.stderr)
            return 1
        print(overlay(args.report, orig))
        return 0

    summary = run(args.limit, args.concurrency)
    if args.json:
        from pathlib import Path
        Path(args.json).write_text(json.dumps(summary, indent=2))
    if not args.watch:
        return 0
    while True:
        run(args.limit, args.concurrency)
        if not _running("[s]miley.harvest") and not _running("[s]miley.extract"):
            if not _select(None):
                print("all upstream done and nothing left to overlay; exiting watch.")
                return 0
        time.sleep(20)


if __name__ == "__main__":
    sys.exit(main())
