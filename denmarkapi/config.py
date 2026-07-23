"""Central paths and constants. Working data on NVMe; raw archive on external SSD."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# NVMe working data (fast, random I/O). See bench/RESULTS.md for why hot data lives here.
DATA = Path(os.environ.get("DENMARKAPI_DATA", ROOT / "data"))
SNAPSHOTS = DATA / "snapshots"          # dated raw index snapshots (xlsx/xml)
PARQUET = DATA / "parquet"              # processed columnar tables
STATE_DB = DATA / "state.db"           # single source of truth for progress/resume

# External USB3 SSD (exFAT): sequential archive + backup only, NOT hot data.
ARCHIVE = Path(os.environ.get("DENMARKAPI_ARCHIVE", "/mnt/ext/denmarkapi"))
PDF_ARCHIVE = ARCHIVE / "smiley_pdfs"  # raw inspection PDFs (bulk, sequential)

# Polite crawler identity (user's uplink is the real bottleneck, but be a good citizen).
# Neutral, non-identifying UA (no personal/company identity). Abuse-avoidance comes from
# request rate + robots.txt, not from announcing who we are. Override per-source if needed.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

# Sources
SMILEY_DATA_PAGE = "https://www.findsmiley.dk/Statistik/Smiley_data/Sider/default.aspx"


def ensure_dirs() -> None:
    for p in (DATA, SNAPSHOTS, PARQUET):
        p.mkdir(parents=True, exist_ok=True)
    # Archive dir best-effort (external may be unmounted on a given boot).
    try:
        PDF_ARCHIVE.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
