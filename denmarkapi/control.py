"""Global pause switch for the GPU pipelines.

The dashboard (on the VPS) writes a paused flag; the push loop mirrors it to the local
data/control.json; pipelines call wait_if_paused() so a click halts new work within seconds.
"""
from __future__ import annotations
import json
import time

from . import config

CONTROL_FILE = config.DATA / "control.json"


def is_paused() -> bool:
    try:
        return bool(json.loads(CONTROL_FILE.read_text()).get("paused"))
    except Exception:
        return False


def set_paused(paused: bool) -> None:
    config.ensure_dirs()
    CONTROL_FILE.write_text(json.dumps({"paused": bool(paused)}))


def wait_if_paused(poll: float = 3.0) -> None:
    while is_paused():
        time.sleep(poll)
