"""Layout-preserving English PDFs: overlay English onto a COPY of the original report.

The report is a single background image (letterhead, green tables, smiley faces) with vector
TEXT on top. So we: redact each text LINE (no fill — the background image shows through),
then reinsert the English at the same position, in the same colour, sized to fit. Numbers /
dates / grid cells (no letters) are left untouched. No source/model disclosure.

Run:  python -m denmarkapi.smiley.overlay_pdf --report 6759175
      python -m denmarkapi.smiley.overlay_pdf --limit 20
"""
from __future__ import annotations
import argparse
import json
import re
import sys

import fitz

from .. import config, control
from ..llm import client

OUT_DIR = config.DATA / "pdfs_en"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_ALPHA = re.compile(r"[A-Za-zÆØÅæøå]")

LINES_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["lines"],
    "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
}
SYSTEM = (
    "You are translating a Danish food-inspection report line by line. You get a JSON array of "
    "lines (a line may be a sentence fragment continued on the next line). Return EXACTLY the "
    "same number of English lines in the same order — translate each line in the context of the "
    "whole list, but do not merge, split, add or drop lines. Keep business names, addresses, "
    "CVR/P-numbers, dates and standalone numbers unchanged. Translate labels/headers."
)


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
            out.append((text, fitz.Rect(l["bbox"]), size, color))
    return out


def _translate(texts: list[str]) -> list[str]:
    out = client.chat(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": json.dumps({"lines": texts}, ensure_ascii=False)}],
        schema=LINES_SCHEMA, max_tokens=4096, reasoning_effort="low")
    en = out.get("lines", [])
    if len(en) != len(texts):
        en = (list(en) + texts)[:len(texts)]
    return en


def _insert(page, rect, text, size, color):
    # Single line: keep the baseline; allow a little rightward room; shrink font to fit width.
    r = fitz.Rect(rect.x0, rect.y0 - 0.5, min(rect.x1 + 55, page.rect.width - 6), rect.y1 + 1.5)
    fs = min(size, 11.0)
    while fs >= 4:
        rc = page.insert_textbox(r, text, fontname="dejavu", fontfile=FONT, fontsize=fs,
                                 color=color, align=fitz.TEXT_ALIGN_LEFT)
        if rc >= 0:
            return
        fs -= 0.5
    page.insert_textbox(r, text, fontname="dejavu", fontfile=FONT, fontsize=4, color=color)


def overlay(report_id: str, original_path: str) -> str:
    doc = fitz.open(original_path)
    for page in doc:
        lines = _lines(page)
        if not lines:
            continue
        ens = _translate([t for t, _, _, _ in lines])
        for _, rect, _, _ in lines:
            page.add_redact_annot(rect)                       # no fill -> keep background image
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        for (_, rect, size, color), en in zip(lines, ens):
            _insert(page, rect, en, size, color)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shard = OUT_DIR / report_id[-3:].rjust(3, "0")
    shard.mkdir(parents=True, exist_ok=True)
    out = shard / f"{report_id}.pdf"
    doc.save(str(out), garbage=4, deflate=True)
    doc.close()
    return str(out)


def _original(report_id: str) -> str | None:
    p = config.PDF_DIR / report_id[-3:].rjust(3, "0") / f"{report_id}.pdf"
    return str(p) if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=str, default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    if args.report:
        ids = [args.report]
    else:
        import duckdb
        rows = duckdb.sql(
            f"SELECT report_id FROM read_parquet('{config.PARQUET/'smiley_translate'}/*.parquet')"
        ).fetchall()
        ids = [str(r[0]) for r in rows][:args.limit]
    for rid in ids:
        control.wait_if_paused()
        orig = _original(rid)
        if not orig:
            print(f"  {rid}: original PDF not found, skip")
            continue
        print(f"  {rid} -> {overlay(rid, orig)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
