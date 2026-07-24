"""Live control knobs for the GPU pipelines.

The dashboard (on the VPS) writes control.json; the push loop mirrors it to the local
data/control.json; pipelines poll it so a click takes effect within seconds:

  paused              bool   halt all pipelines (wait_if_paused)
  harvest_rate        float  max total findsmiley requests/sec across all harvest workers
  analyze_concurrency int    max in-flight LLM requests in the analyze stage
  overlay_concurrency int    max in-flight LLM requests in the English-PDF overlay stage
                             (shares the one vLLM with analyze — that's why it has its own knob)

Reads are cached for CACHE_TTL and fall back to the last good value, because push.py
overwrites the file underneath us — a torn read must never look like "unset".
"""
from __future__ import annotations
import json
import time

from . import config

CONTROL_FILE = config.DATA / "control.json"

DEFAULTS = {
    "paused": False,
    "harvest_rate": 2.6,        # req/s — see dashboard slider (finishes the backlog overnight)
    "analyze_concurrency": 32,
    "overlay_concurrency": 8,
}

CACHE_TTL = 2.0
_cache: dict = dict(DEFAULTS)
_cache_at = 0.0


def get_all() -> dict:
    """Whole control dict, defaults filled in. Cached; last good value wins on a torn read."""
    global _cache, _cache_at
    now = time.monotonic()
    if now - _cache_at < CACHE_TTL:
        return _cache
    try:
        data = json.loads(CONTROL_FILE.read_text())
        if isinstance(data, dict):
            _cache = {**DEFAULTS, **data}
    except Exception:
        pass                     # keep the previous value (file missing / mid-scp)
    _cache_at = now
    return _cache


def get(key: str, default=None):
    return get_all().get(key, DEFAULTS.get(key) if default is None else default)


def get_float(key: str, lo: float, hi: float) -> float:
    try:
        return min(hi, max(lo, float(get(key))))
    except (TypeError, ValueError):
        return float(DEFAULTS[key])


def get_int(key: str, lo: int, hi: int) -> int:
    try:
        return min(hi, max(lo, int(get(key))))
    except (TypeError, ValueError):
        return int(DEFAULTS[key])


def harvest_rate() -> float:
    return get_float("harvest_rate", 0.2, 20.0)


def analyze_concurrency() -> int:
    return get_int("analyze_concurrency", 1, 128)


def overlay_concurrency() -> int:
    return get_int("overlay_concurrency", 1, 64)


def is_paused() -> bool:
    return bool(get("paused"))


def set_values(**kw) -> None:
    """Merge keys into the local control file (dashboard is the usual writer)."""
    global _cache_at
    config.ensure_dirs()
    try:
        cur = json.loads(CONTROL_FILE.read_text())
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    cur.update(kw)
    tmp = CONTROL_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur))
    tmp.replace(CONTROL_FILE)
    _cache_at = 0.0


def set_paused(paused: bool) -> None:
    set_values(paused=bool(paused))


def wait_if_paused(poll: float = 3.0) -> None:
    while is_paused():
        time.sleep(poll)
