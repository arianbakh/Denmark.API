#!/usr/bin/env python3
"""Minimal dashboard server for the VPS. Serves an HTML page + the pushed status.json,
protected by HTTP Basic Auth. Stdlib only. Autostarts via systemd.

Env: DASH_USER, DASH_PASS (set by the systemd unit). Files in /root/denmarkdash/.
"""
from __future__ import annotations
import base64
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = Path("/root/denmarkdash")
USER = os.environ.get("DASH_USER", "admin")
PASS = os.environ.get("DASH_PASS", "changeme")
PORT = int(os.environ.get("DASH_PORT", "8080"))
_EXPECTED = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self) -> bool:
        return self.headers.get("Authorization", "") == _EXPECTED

    def _deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="DenmarkAPI"')
        self.end_headers()

    def do_GET(self):
        if not self._auth_ok():
            return self._deny()
        if self.path.startswith("/status.json"):
            return self._serve(HOME / "status.json", "application/json")
        return self._serve(HOME / "index.html", "text/html; charset=utf-8")

    def _serve(self, path: Path, ctype: str):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found (no snapshot yet)")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
