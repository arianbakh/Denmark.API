"""Loop: recompute status.json and push it to the VPS every INTERVAL seconds.

Runs on the GPU box. Survives GPU downtime — while it's off, the VPS simply serves the last
snapshot (the dashboard shows how stale it is). Autostart via systemd (see README).
"""
from __future__ import annotations
import os
import subprocess
import time

from . import status
from .. import config

def _vps_target() -> str:
    # Prefer explicit DENMARKAPI_VPS; else build from VPS_USER@VPS_IP (systemd EnvironmentFile=secrets.env).
    v = os.environ.get("DENMARKAPI_VPS", "")
    if v:
        return v
    user, ip = os.environ.get("VPS_USER", ""), os.environ.get("VPS_IP", "")
    return f"{user}@{ip}" if user and ip else ""


VPS = _vps_target()
REMOTE_PATH = "/root/denmarkdash/status.json"
INTERVAL = int(os.environ.get("DENMARKAPI_DASH_INTERVAL", "30"))


def push_once() -> None:
    status.write()
    if not VPS:
        print("DENMARKAPI_VPS not set; wrote status.json locally only")
        return
    subprocess.run(
        ["scp", "-q", "-o", "StrictHostKeyChecking=accept-new",
         str(status.STATUS_JSON), f"{VPS}:{REMOTE_PATH}"],
        check=False, timeout=30)


def main() -> int:
    while True:
        try:
            push_once()
        except Exception as e:
            print("push error:", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
