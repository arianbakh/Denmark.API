"""Canonical findsmiley URLs and local paths for a report.

Nothing about a report's location needs storing: the report id IS the PDF's filename, and
findsmiley's URL is a pure function of that id. So an API layer can hand out both the local
file and the "view the original" link with no extra column, index or lookup.

Verified 2026-07-24 against a live fetch of report 7219723: the URL below returns HTTP 200,
application/pdf, and the document is identical to our archived copy — same text, same embedded
images, differing only in the 71 bytes of generation timestamp, because findsmiley renders the
PDF fresh on every request rather than serving a stored file.

That last point matters for two decisions:
  * byte hashes / ETags cannot be used to tell "has this report changed?" — compare extracted
    text instead (see extract.py), since the bytes differ on every fetch;
  * hot-linking the original instead of serving our own copy sends one request to a public
    authority per page view. Their site returned 503 site-wide on 2026-07-23 under load, and
    the English PDFs have to be served by us regardless — see docs note in CLAUDE.md.
"""
from __future__ import annotations
from pathlib import Path

from .. import config

REPORT_URL = "https://www.findsmiley.dk/Sider/KontrolRapport.aspx?Virk{report_id}"
BUSINESS_URL = "https://www.findsmiley.dk/{navnelbnr}"

# Reuse and attribution terms for anything we republish (Open Public Data License).
ATTRIBUTION = "Source: Fødevarestyrelsen (findsmiley.dk)"


def report_url(report_id: str | int) -> str:
    """The original Danish PDF on findsmiley — derived, never stored."""
    return REPORT_URL.format(report_id=report_id)


def business_url(navnelbnr: str | int) -> str:
    """The business's page on findsmiley (its report history)."""
    return BUSINESS_URL.format(navnelbnr=navnelbnr)


def shard(report_id: str | int) -> str:
    """Directory shard: the id's last 3 digits, so no directory holds too many files."""
    return str(report_id)[-3:].rjust(3, "0")


def pdf_path(report_id: str | int) -> Path:
    """Local archived Danish PDF."""
    return config.PDF_DIR / shard(report_id) / f"{report_id}.pdf"


def en_pdf_path(report_id: str | int) -> Path:
    """Local generated English PDF."""
    return config.DATA / "pdfs_en" / shard(report_id) / f"{report_id}.pdf"


def report_id_from_path(path: str | Path) -> str:
    """Inverse of pdf_path/en_pdf_path — the filename stem is the report id."""
    return Path(path).stem


def links(report_id: str | int) -> dict:
    """Everything an API needs for one report, computed from the id alone."""
    da, en = pdf_path(report_id), en_pdf_path(report_id)
    return {
        "report_id": str(report_id),
        "original_url": report_url(report_id),
        "attribution": ATTRIBUTION,
        "pdf_da": str(da) if da.exists() else None,
        "pdf_en": str(en) if en.exists() else None,
    }
