"""Harvest smiley inspection PDFs — two pipelined, resumable stages.

Stage 1: business page (findsmiley.dk/<navnelbnr>) -> report IDs
         (links like /Sider/KontrolRapport.aspx?Virk<REPORTID>)
Stage 2: report ID -> PDF (KontrolRapport.aspx?Virk<id> returns application/pdf directly)

Pipelined: as soon as a business is scraped, its PDFs start downloading while other business
pages are still being scraped (stage 2 consumes stage 1's output via the shared SQLite queue).
Resumable: businesses/reports already 'done' in state are skipped, so a `poweroff` mid-run is safe.

Run:  python -m denmarkapi.smiley.harvest --limit 25      # sample
      python -m denmarkapi.smiley.harvest                 # full
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .. import config, control, state
from .urls import BUSINESS_URL, REPORT_URL, pdf_path   # single source of truth for locations

BUS_PIPE = "smiley_business"   # key = navnelbnr
RPT_PIPE = "smiley_report"     # key = report_id, meta = {"navnelbnr": ...}

REPORT_RE = re.compile(r"KontrolRapport\.aspx\?Virk(\d+)", re.I)

_local = threading.local()
_db_lock = threading.Lock()   # serialize writes to the single SQLite connection


class RateLimiter:
    """Global cap on request rate across all worker threads (be a good citizen).

    The rate is re-read from a provider (the dashboard slider via control.json) on every
    request, so dragging the slider re-paces a running harvest without a restart.
    """
    def __init__(self, rate_per_sec: float, provider=None):
        self.provider = provider
        self.rate = rate_per_sec
        self.min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self.lock = threading.Lock()
        self.next_at = 0.0

    def _set_rate(self, rate_per_sec: float):
        self.rate = rate_per_sec
        self.min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0

    def wait(self):
        """Blocks while the rate is 0 — that is how the dashboard pauses the harvest."""
        while True:
            with self.lock:
                if self.provider:
                    r = self.provider()
                    if r != self.rate:
                        self._set_rate(r)
                if self.rate > 0:
                    now = time.monotonic()
                    sleep = max(0.0, self.next_at - now)
                    self.next_at = max(now, self.next_at) + self.min_interval
                    break
                if not self.provider:      # fixed rate of 0 given on the CLI: no limit
                    return
            time.sleep(1.0)                # paused: slider at the bottom
        if sleep:
            time.sleep(sleep)


class CircuitBreaker:
    """Trip when the server throttles us (5xx/429/timeouts) → ABORT instead of hammering.
    Only server-side throttle signals count as failures; a normal 'not a PDF' skip does not."""
    def __init__(self, window: int = 40, trip_ratio: float = 0.5, min_samples: int = 20):
        self.window = deque(maxlen=window)
        self.lock = threading.Lock()
        self.tripped = threading.Event()
        self.trip_ratio = trip_ratio
        self.min_samples = min_samples

    def record(self, ok: bool):
        with self.lock:
            self.window.append(1 if ok else 0)
            if len(self.window) >= self.min_samples:
                fails = self.window.count(0)
                if fails / len(self.window) >= self.trip_ratio:
                    self.tripped.set()

    def open(self) -> bool:
        return self.tripped.is_set()


_rl = RateLimiter(0)          # configured in run()
_cb = CircuitBreaker()


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = config.USER_AGENT
        _local.session = s
    return s


def _shard_path(report_id: str):
    p = pdf_path(report_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def scrape_business(navnelbnr: str) -> list[str]:
    control.wait_if_paused()
    if _cb.open():
        raise Transient("circuit breaker open (server throttling)")
    _rl.wait()
    try:
        r = _session().get(BUSINESS_URL.format(navnelbnr=navnelbnr), timeout=45,
                           allow_redirects=True)
    except requests.RequestException as e:
        _cb.record(False)
        raise Transient(str(e)[:120])
    if r.status_code == 429 or 500 <= r.status_code < 600:
        _cb.record(False)
        raise Transient(f"HTTP {r.status_code}")
    r.raise_for_status()
    _cb.record(True)
    return sorted(set(REPORT_RE.findall(r.text)))


class Transient(Exception):
    """Retryable (5xx / 429 / network). Goes to 'failed' and is retried on resume."""


class Terminal(Exception):
    """Permanent (non-PDF / 404 / other 4xx). Goes to 'skipped' — never retried."""


def _download_once(report_id: str) -> tuple[str, int]:
    control.wait_if_paused()
    if _cb.open():
        raise Transient("circuit breaker open (server throttling)")
    _rl.wait()
    path = _shard_path(report_id)
    try:
        r = _session().get(REPORT_URL.format(report_id=report_id), timeout=60,
                           allow_redirects=True)
    except requests.RequestException as e:
        _cb.record(False)
        raise Transient(str(e)[:120])
    if r.status_code == 429 or 500 <= r.status_code < 600:
        _cb.record(False)
        raise Transient(f"HTTP {r.status_code}")
    _cb.record(True)   # server responded healthily (even a 4xx/non-PDF is not throttling)
    if 400 <= r.status_code < 500:
        raise Terminal(f"HTTP {r.status_code}")
    ct = r.headers.get("Content-Type", "")
    if "application/pdf" not in ct and not r.content.startswith(b"%PDF"):
        raise Terminal(f"not a PDF (content-type={ct[:40]!r})")
    tmp = str(path) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(r.content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return str(path), len(r.content)


def download_pdf(report_id: str) -> tuple[str, int]:
    """Retry transient failures with exponential backoff; terminal errors propagate."""
    delay = 1.0
    for attempt in range(3):
        try:
            return _download_once(report_id)
        except (Transient, requests.RequestException) as e:
            if attempt == 2 or _cb.open():   # stop retrying once throttling is detected
                raise Transient(str(e)[:200])
            time.sleep(delay)
            delay *= 2


def _load_businesses(limit: int | None) -> list[str]:
    import duckdb
    pq = str(config.PARQUET / "smiley_status.parquet")
    q = f"SELECT navnelbnr FROM read_parquet('{pq}') WHERE navnelbnr IS NOT NULL"
    if limit:
        q += f" LIMIT {int(limit)}"
    return [str(row[0]) for row in duckdb.sql(q).fetchall()]


def _done_keys(conn, pipeline) -> set[str]:
    return {r["key"] for r in conn.execute(
        "SELECT key FROM items WHERE pipeline=? AND status='done'", (pipeline,)).fetchall()}


def run(limit: int | None, stage1_workers: int, stage2_workers: int,
        rate_per_sec: float | None = None) -> None:
    """rate_per_sec=None -> follow the dashboard slider live (control.json harvest_rate)."""
    global _rl, _cb
    if rate_per_sec is None:
        _rl = RateLimiter(control.harvest_rate(), provider=control.harvest_rate)
        print(f"rate: following dashboard slider (now {control.harvest_rate()} req/s)")
    else:
        _rl = RateLimiter(rate_per_sec)
        print(f"rate: fixed at {rate_per_sec} req/s (--rate given; slider ignored)")
    _cb = CircuitBreaker()
    config.ensure_dirs()
    # check_same_thread=False: worker threads write via _db_lock (serialized).
    with state.connect(check_same_thread=False) as conn:
        businesses = _load_businesses(limit)
        done_bus = _done_keys(conn, BUS_PIPE)
        done_rpt = _done_keys(conn, RPT_PIPE)
        todo_bus = [b for b in businesses if b not in done_bus]
        print(f"businesses: {len(businesses)} total, {len(todo_bus)} to scrape "
              f"({len(done_bus)} already done)")

        counters = {"bus_ok": 0, "bus_err": 0, "pdf_ok": 0, "pdf_err": 0, "reports": 0}
        t0 = time.time()

        def do_download(report_id: str):
            if report_id in done_rpt:
                return
            try:
                path, nbytes = download_pdf(report_id)
                sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
                with _db_lock:
                    state.upsert_item(conn, RPT_PIPE, report_id, status="done",
                                      sha256=sha, path=path, bump_attempt=True)
                    conn.commit()
                counters["pdf_ok"] += 1
            except Terminal as e:                 # permanent -> skip, never retry
                with _db_lock:
                    state.upsert_item(conn, RPT_PIPE, report_id, status="skipped",
                                      error=str(e)[:300], bump_attempt=True)
                    conn.commit()
                counters["pdf_err"] += 1
            except Exception as e:                # transient (retries exhausted) -> retry on resume
                with _db_lock:
                    state.upsert_item(conn, RPT_PIPE, report_id, status="failed",
                                      error=str(e)[:300], bump_attempt=True)
                    conn.commit()
                counters["pdf_err"] += 1

        # Pipelined: stage-2 pool downloads PDFs as stage-1 discovers them.
        with ThreadPoolExecutor(max_workers=stage2_workers) as dl_pool, \
             ThreadPoolExecutor(max_workers=stage1_workers) as scrape_pool:
            # Resume: drain any reports left pending/failed by a previous run.
            resume = [r["key"] for r in state.pending_items(conn, RPT_PIPE)]
            if resume:
                print(f"resuming {len(resume)} pending/failed report downloads")
                for rid in resume:
                    dl_pool.submit(do_download, rid)
            fut_to_bus = {scrape_pool.submit(scrape_business, b): b for b in todo_bus}
            for fut in as_completed(fut_to_bus):
                if _cb.open():
                    print("\n!! CIRCUIT BREAKER TRIPPED — server is throttling us "
                          "(5xx/429/timeouts). Aborting harvest; retry later / from another IP.",
                          file=sys.stderr)
                    break
                b = fut_to_bus[fut]
                try:
                    report_ids = fut.result()
                    with _db_lock:
                        for rid in report_ids:
                            state.upsert_item(conn, RPT_PIPE, rid, status="pending",
                                              meta=json.dumps({"navnelbnr": b}))
                        state.upsert_item(conn, BUS_PIPE, b, status="done",
                                          meta=json.dumps({"n_reports": len(report_ids)}),
                                          bump_attempt=True)
                        conn.commit()
                    counters["bus_ok"] += 1
                    counters["reports"] += len(report_ids)
                    for rid in report_ids:            # hand off to stage 2 immediately
                        dl_pool.submit(do_download, rid)
                except Exception as e:
                    with _db_lock:
                        state.upsert_item(conn, BUS_PIPE, b, status="failed",
                                          error=str(e)[:300], bump_attempt=True)
                        conn.commit()
                    counters["bus_err"] += 1
                if counters["bus_ok"] % 50 == 0 and counters["bus_ok"]:
                    print(f"  scraped {counters['bus_ok']} businesses, "
                          f"{counters['reports']} reports found, "
                          f"{counters['pdf_ok']} PDFs downloaded...")

        dt = time.time() - t0
        print(f"\nDONE in {dt:.0f}s: businesses ok={counters['bus_ok']} err={counters['bus_err']}; "
              f"reports found={counters['reports']}; "
              f"PDFs ok={counters['pdf_ok']} err={counters['pdf_err']}")
        print("state:", state.progress(conn, RPT_PIPE))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max businesses (sample runs)")
    ap.add_argument("--stage1-workers", type=int, default=4)
    ap.add_argument("--stage2-workers", type=int, default=8)
    ap.add_argument("--rate", type=float, default=None,
                    help="fixed max total requests/sec across all workers; "
                         "omit to follow the dashboard slider (control.json harvest_rate)")
    args = ap.parse_args()
    run(args.limit, args.stage1_workers, args.stage2_workers, rate_per_sec=args.rate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
