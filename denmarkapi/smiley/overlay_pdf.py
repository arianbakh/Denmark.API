"""Layout-preserving English PDFs: overlay English onto a COPY of the original report.

Keeps the real template (letterhead, smiley image, tables, positions). Only text blocks that
contain letters are translated + replaced; numbers/dates/grid cells are left untouched. No
source/model disclosure. One LLM call per report (all blocks batched).

Run:  python -m denmarkapi.smiley.overlay_pdf --report 6759175
      python -m denmarkapi.smiley.overlay_pdf --limit 20     # from translate parquet's ids
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
    "Translate each Danish text block to English. Return EXACTLY the same number of items in the "
    "same order (one English string per input string). Keep business names, addresses, "
    "CVR/P-numbers, dates and standalone numbers unchanged. Translate labels and headers "
    "(e.g. 'Kontrolrapport'->'Inspection report'). Do not merge, split, add or drop items."
)


def _blocks(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        if "lines" not in b:
            continue
        text = " ".join("".join(s["text"] for s in l["spans"]) for l in b["lines"]).strip()
        if not text or not _ALPHA.search(text):
            continue  # leave numbers / grid cells / blanks untouched
        size = max((s["size"] for l in b["lines"] for s in l["spans"]), default=9)
        out.append((text, fitz.Rect(b["bbox"]), size))
    return out


def _translate(texts: list[str]) -> list[str]:
    out = client.chat(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": json.dumps({"lines": texts}, ensure_ascii=False)}],
        schema=LINES_SCHEMA, max_tokens=4096, reasoning_effort="low")
    en = out.get("lines", [])
    if len(en) != len(texts):                 # keep alignment even if the model miscounts
        en = (list(en) + texts)[:len(texts)]
    return en


def _insert(page, rect: fitz.Rect, text: str, size: float):
    # Give a little rightward room; shrink to fit the original block box.
    r = fitz.Rect(rect.x0, rect.y0 - 1, min(rect.x1 + 40, page.rect.width - 8), rect.y1 + 6)
    fs = size
    while fs >= 4:
        page.insert_font(fontname="dejavu", fontfile=FONT)
        rc = page.insert_textbox(r, text, fontname="dejavu", fontfile=FONT, fontsize=fs,
                                 align=fitz.TEXT_ALIGN_LEFT)
        if rc >= 0:
            return
        fs -= 0.5
    # last resort: draw at smallest size regardless of overflow
    page.insert_textbox(r, text, fontname="dejavu", fontfile=FONT, fontsize=4,
                        align=fitz.TEXT_ALIGN_LEFT)


def overlay(report_id: str, original_path: str) -> str:
    doc = fitz.open(original_path)
    for page in doc:
        blocks = _blocks(page)
        if not blocks:
            continue
        ens = _translate([t for t, _, _ in blocks])
        for _, rect, _ in blocks:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)  # keep the smiley/logo
        for (_, rect, size), en in zip(blocks, ens):
            _insert(page, rect, en, size)
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
    ids = []
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
