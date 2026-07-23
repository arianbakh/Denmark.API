"""Thin client for the local vLLM (gpt-oss-20b) OpenAI-compatible API.

Localhost only. Supports strict JSON-schema structured output and retries. Callers do their
own concurrency (a thread pool); vLLM batches the concurrent requests server-side.
"""
from __future__ import annotations
import json
import os
import time

import requests

BASE = os.environ.get("VLLM_BASE", "http://localhost:8000/v1")
MODEL = os.environ.get("VLLM_MODEL", "gpt-oss-20b")


class LLMError(Exception):
    pass


def chat(messages: list[dict], *, schema: dict | None = None, temperature: float = 0.0,
         max_tokens: int = 3000, reasoning_effort: str = "low", timeout: int = 180,
         retries: int = 3):
    """Return parsed JSON (if schema given) or the text content. Retries transient errors."""
    body: dict = {"model": MODEL, "messages": messages, "temperature": temperature,
                  "max_tokens": max_tokens}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    if schema is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "extraction", "schema": schema,
                                                   "strict": True}}
    delay = 2.0
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(f"{BASE}/chat/completions", json=body, timeout=timeout)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content) if schema is not None else content
        except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError) as e:
            last = e
            if attempt == retries - 1:
                break
            time.sleep(delay)
            delay *= 2
    raise LLMError(str(last)[:200])


def is_up() -> bool:
    try:
        return requests.get(f"{BASE}/models", timeout=5).status_code == 200
    except Exception:
        return False
