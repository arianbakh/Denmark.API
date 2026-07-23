"""Render translated report text into English PDFs (for the in-app viewer).

CPU-only (no GPU). Reads parquet/smiley_translate, writes data/pdfs_en/<shard>/<id>.pdf,
mirroring the report's line structure. A small header marks it as an UNOFFICIAL machine
translation so it is never mistaken for the official document.

Run:  python -m denmarkapi.smiley.render_pdf [--limit N]
"""
from __future__ import annotations
import argparse
import re
import sys

import duckdb
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from .. import config


def _breakable(line: str, maxtok: int = 55) -> str:
    # fpdf can't wrap a single token wider than the page; insert soft breaks in long runs.
    return re.sub(r"\S{%d,}" % (maxtok + 1),
                  lambda m: " ".join(m.group(0)[i:i + maxtok]
                                     for i in range(0, len(m.group(0)), maxtok)),
                  line)

OUT_DIR = config.DATA / "pdfs_en"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
TRANSLATE_GLOB = f"{config.PARQUET / 'smiley_translate'}/*.parquet"


def _shard_path(report_id: str):
    d = OUT_DIR / report_id[-3:].rjust(3, "0")
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{report_id}.pdf"


def render(report_id: str, text_en: str) -> str:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT)
    pdf.set_font("DejaVu", size=8)
    pdf.set_text_color(140, 140, 140)
    pdf.multi_cell(0, 4, "Unofficial machine translation (gpt-oss-20b). "
                         "Source: Fødevarestyrelsen / findsmiley.dk",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", size=10)
    for line in text_en.split("\n"):
        pdf.multi_cell(0, 5, _breakable(line) if line.strip() else " ",
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    out = _shard_path(report_id)
    pdf.output(str(out))
    return str(out)


def run(limit: int | None) -> None:
    con = duckdb.connect()
    rows = con.sql(f"SELECT report_id, text_en FROM read_parquet('{TRANSLATE_GLOB}')").fetchall()
    if limit:
        rows = rows[:limit]
    n = 0
    for rid, en in rows:
        if en:
            render(str(rid), en)
            n += 1
    print(f"rendered {n} English PDFs -> {OUT_DIR}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    run(args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
