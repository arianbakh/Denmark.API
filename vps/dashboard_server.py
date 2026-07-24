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
CONTROL = HOME / "control.json"
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
        _hist.append((t, s.get("reports", {}).get("done", 0), s.get("pdfs", {}).get("bytes", 0),
                      s.get("extract", {}).get("extracted", 0),
                      s.get("analyze", {}).get("analyzed", 0),
                      s.get("overlay", {}).get("done", 0)))


def _derived(s: dict) -> dict:
    with _hist_lock:
        h = list(_hist)
    out = {"report_rate_per_s": 0.0, "throughput_mb_per_s": 0.0,
           "eta_seconds": None, "est_total_reports": None,
           "extract_rate_per_s": 0.0, "extract_eta_seconds": None,
           "analyze_rate_per_s": 0.0, "analyze_eta_seconds": None,
           "overlay_rate_per_s": 0.0, "overlay_eta_seconds": None}
    if len(h) >= 2:
        (t0, r0, b0, e0, a0, o0), (t1, r1, b1, e1, a1, o1) = h[0], h[-1]
        dt = t1 - t0
        if dt > 0:
            out["report_rate_per_s"] = round((r1 - r0) / dt, 2)
            out["throughput_mb_per_s"] = round((b1 - b0) / dt / 1e6, 2)
            out["extract_rate_per_s"] = round((e1 - e0) / dt, 1)
            out["analyze_rate_per_s"] = round((a1 - a0) / dt, 1)
            out["overlay_rate_per_s"] = round((o1 - o0) / dt, 2)

    def secs(remaining, rate):
        return max(int(remaining / rate), 0) if rate > 0 and remaining > 0 else None

    # ONE model of how much work will exist in total, so the stage ETAs are consistent with
    # each other. Previously each stage measured itself against the work known SO FAR, so
    # extract and analyze both claimed to finish before harvest — which cannot happen, since
    # they consume what harvest produces. Two rules fix that:
    #   * the harvest's remaining work is pending+failed. The old form (est_total - done)
    #     also counted 'skipped' ids, which are resolved and will never be downloaded.
    #   * every downstream stage projects its FINAL total from the final report count, and
    #     can never be reported as finishing before its own source does.
    rpt, bus = s.get("reports", {}), s.get("businesses", {})
    ext, ana, ov = s.get("extract", {}), s.get("analyze", {}), s.get("overlay", {})
    done, pending, failed = rpt.get("done", 0), rpt.get("pending", 0), rpt.get("failed", 0)
    bdone, bfailed, btot = bus.get("done", 0), bus.get("failed", 0), bus.get("total", 0)

    # Business pages not yet scraped will still contribute reports we cannot see yet.
    seen = done + pending + failed + rpt.get("skipped", 0)
    per_business = seen / bdone if bdone else 0
    unscraped = max(0, btot - bdone) + bfailed
    final_reports = done + pending + failed + round(per_business * unscraped)
    out["est_total_reports"] = final_reports
    out["eta_seconds"] = secs(pending + failed + unscraped * (1 + per_business),
                              out["report_rate_per_s"])
    harvest_eta = out["eta_seconds"] or 0

    extracted = ext.get("extracted", 0)
    out["extract_total"] = final_reports
    out["extract_eta_seconds"] = secs(final_reports - extracted, out["extract_rate_per_s"])
    if out["extract_eta_seconds"] is not None:
        out["extract_eta_seconds"] = max(out["extract_eta_seconds"], harvest_eta)
    elif final_reports > extracted:
        out["extract_eta_seconds"] = harvest_eta or None

    # Share of reports that carry remarks, measured on what we have, applied to the final count.
    remarks_share = (ana.get("to_analyze", 0) / extracted) if extracted else 0
    ana_total = round(remarks_share * final_reports)
    out["analyze_total"] = ana_total
    out["analyze_eta_seconds"] = secs(ana_total - ana.get("analyzed", 0),
                                      out["analyze_rate_per_s"])
    if out["analyze_eta_seconds"] is not None:
        out["analyze_eta_seconds"] = max(out["analyze_eta_seconds"], harvest_eta)

    # Overlay covers reports but not placards; scale by the share seen so far.
    report_share = (ov.get("to_overlay", 0) / extracted) if extracted else 1.0
    ov_total = round(report_share * final_reports)
    out["overlay_total"] = ov_total
    out["overlay_eta_seconds"] = secs(ov_total - ov.get("done", 0) - ov.get("skipped", 0),
                                      out["overlay_rate_per_s"])
    if out["overlay_eta_seconds"] is not None:
        out["overlay_eta_seconds"] = max(out["overlay_eta_seconds"], harvest_eta)
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
        oldest = c.execute("SELECT MIN(fetched_at) FROM articles").fetchone()[0]
        c.close()
        # Archive age explains the "new_24h == articles" case: until the archive itself is
        # older than 24h, every row in it is by definition new in the last 24h.
        return {"articles": total, "new_24h": new24, "sources": srcs,
                "archive_age_s": int(time.time() - oldest) if oldest else None,
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
        {"name": "extract (GPU)", "up": bool(s.get("extract_running") and fresh)},
        {"name": "LLM analyze (GPU)", "up": bool(s.get("analyze_running") and fresh)},
        {"name": "EN overlay (GPU)", "up": bool(s.get("overlay_running") and fresh)},
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
    s["control"] = _control()
    s["paused"] = s["control"]["paused"]
    s["server_now"] = time.time()
    return s


# Live knobs mirrored to the GPU box by push.py. Ranges are enforced here (the UI sliders
# are only a convenience) so a stray POST can never make us hammer findsmiley.
# 0 is a legal value for every knob and means "pause that stage" — see denmarkapi/control.py.
DEFAULTS = {"paused": False, "harvest_rate": 2.6, "analyze_concurrency": 32,
            "overlay_concurrency": 8}
LIMITS = {"harvest_rate": (0.0, 10.0, float), "analyze_concurrency": (0, 128, int),
          "overlay_concurrency": (0, 64, int)}


def _control() -> dict:
    try:
        c = json.loads(CONTROL.read_text())
        if not isinstance(c, dict):
            c = {}
    except Exception:
        c = {}
    return {**DEFAULTS, **c}


def _write_control(d: dict) -> None:
    tmp = CONTROL.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d))
    os.replace(tmp, CONTROL)


def _set_paused(paused: bool) -> None:
    _write_control({**_control(), "paused": bool(paused)})


def _set_values(q: dict) -> dict:
    """Clamp and store any known knob present in the query string."""
    c = _control()
    for key, (lo, hi, cast) in LIMITS.items():
        if key in q:
            try:
                c[key] = min(hi, max(lo, cast(float(q[key][0]))))
            except (TypeError, ValueError):
                pass
    _write_control(c)
    return c


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

    def do_POST(self):
        if not self._auth_ok():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="DenmarkAPI"')
            self.end_headers()
            return
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        action = q.get("action", [""])[0]
        if self.path.startswith("/control") and action in ("pause", "resume"):
            _set_paused(action == "pause")
            self._send(json.dumps(_control()).encode(), "application/json")
        elif self.path.startswith("/control") and action == "set":
            self._send(json.dumps(_set_values(q)).encode(), "application/json")
        else:
            self.send_response(400)
            self.end_headers()

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
