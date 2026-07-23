#!/usr/bin/env python3
"""Dashboard server for the VPS. Serves an HTML page + an ENRICHED status JSON:
the GPU-pushed snapshot (counts/bytes) merged with metrics the VPS computes itself —
report rate, throughput, ETA (from a short snapshot history) — plus RSS-poller stats
(news.db) and which components are running. Basic-Auth protected. Stdlib only.
"""
from __future__ import annotations
import base64
import json
import os
import sqlite3
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = Path("/root/denmarkdash")
NEWS_DB = Path("/root/denmarknews/news.db")
USER = os.environ.get("DASH_USER", "admin")
PASS = os.environ.get("DASH_PASS", "changeme")
PORT = int(os.environ.get("DASH_PORT", "8080"))
_EXPECTED = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()

_hist = deque(maxlen=90)          # (t, reports_done, pdf_bytes)
_hist_lock = threading.Lock()
_last_seen_t = 0.0


def _read_status() -> dict:
    try:
        return json.loads((HOME / "status.json").read_text())
    except Exception:
        return {}


def _record(s: dict):
    global _last_seen_t
    t = s.get("updated_at", 0)
    if not t or t == _last_seen_t:
        return
    _last_seen_t = t
    with _hist_lock:
        _hist.append((t, s.get("reports", {}).get("done", 0), s.get("pdfs", {}).get("bytes", 0)))


def _derived(s: dict) -> dict:
    with _hist_lock:
        h = list(_hist)
    out = {"report_rate_per_s": 0.0, "throughput_mb_per_s": 0.0,
           "eta_seconds": None, "est_total_reports": None}
    if len(h) >= 2:
        (t0, r0, b0), (t1, r1, b1) = h[0], h[-1]
        dt = t1 - t0
        if dt > 0:
            out["report_rate_per_s"] = round((r1 - r0) / dt, 2)
            out["throughput_mb_per_s"] = round((b1 - b0) / dt / 1e6, 2)
    rpt = s.get("reports", {})
    bus = s.get("businesses", {})
    seen = sum(rpt.get(k, 0) for k in ("done", "pending", "failed", "skipped"))
    bdone, btot = bus.get("done", 0), bus.get("total", 0)
    if bdone > 0 and btot:
        est = round(seen / bdone * btot)
        out["est_total_reports"] = est
        rate = out["report_rate_per_s"]
        if rate > 0:
            out["eta_seconds"] = max(int((est - rpt.get("done", 0)) / rate), 0)
    return out


def _rss() -> dict:
    if not NEWS_DB.exists():
        return {}
    try:
        c = sqlite3.connect(f"file:{NEWS_DB}?mode=ro", uri=True, timeout=5)
        total = c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        last = c.execute("SELECT MAX(ran_at) FROM poll_log").fetchone()[0]
        new24 = c.execute("SELECT COUNT(*) FROM articles WHERE fetched_at > ?",
                          (time.time() - 86400,)).fetchone()[0]
        srcs = c.execute("SELECT COUNT(DISTINCT source) FROM articles").fetchone()[0]
        c.close()
        return {"articles": total, "new_24h": new24, "sources": srcs,
                "last_poll_ago_s": int(time.time() - last) if last else None}
    except Exception:
        return {}


def _svc_active(name: str) -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", name]).returncode == 0
    except Exception:
        return False


def _services(s: dict) -> list:
    fresh = s.get("updated_at", 0) and (time.time() - s["updated_at"] < 10)
    return [
        {"name": "harvest (GPU)", "up": bool(s.get("harvest_running") and fresh)},
        {"name": "status push (GPU)", "up": bool(fresh)},
        {"name": "news poller (VPS)", "up": _svc_active("denmarknews.timer")},
        {"name": "dashboard (VPS)", "up": True},
    ]


def build() -> dict:
    s = _read_status()
    _record(s)
    s["derived"] = _derived(s)
    s["rss"] = _rss()
    s["services"] = _services(s)
    s["server_now"] = time.time()
    return s


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self):
        return self.headers.get("Authorization", "") == _EXPECTED

    def do_GET(self):
        if not self._auth_ok():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="DenmarkAPI"')
            self.end_headers()
            return
        if self.path.startswith("/status.json"):
            body = json.dumps(build()).encode()
            self._send(body, "application/json")
        else:
            try:
                self._send((HOME / "index.html").read_bytes(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(b"no index.html", "text/plain")

    def _send(self, data: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
