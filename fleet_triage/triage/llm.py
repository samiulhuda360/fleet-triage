"""OpenAI-compatible chat client with a disk cache, call spacing and retries.

Configuration comes from the environment only: ``AI_API_KEY``, ``AI_BASE_URL`` and ``AI_MODEL``. Without a key
the client still answers from the cache (so committed results replay offline) and otherwise reports that no
model is available, and the triage falls back to its rules path.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-flash-lite-latest"
CACHE_DIR = Path(__file__).resolve().parents[2] / "results" / "llm_cache"
MIN_INTERVAL_S = 2.5

_lock = threading.Lock()
_last_call = [0.0]


@dataclass
class CallMeta:
    cached: bool = False
    live: bool = False
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        cache_dir: Path = CACHE_DIR,
        allow_live: bool = True,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("AI_API_KEY")
        self.base_url = base_url or os.environ.get("AI_BASE_URL") or DEFAULT_BASE_URL
        self.model = model or os.environ.get("AI_MODEL") or DEFAULT_MODEL
        self.cache_dir = cache_dir
        self.allow_live = allow_live and bool(self.api_key)
        self._client = None

    def _key(self, system: str, user: str) -> str:
        return hashlib.sha256(f"{self.model}\n{system}\n{user}".encode()).hexdigest()[:32]

    def complete_json(self, system: str, user: str, max_retries: int = 4) -> tuple[dict | None, CallMeta]:
        key = self._key(system, user)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            rec = json.loads(path.read_text(encoding="utf-8"))
            meta = CallMeta(
                cached=True,
                latency_s=rec.get("latency_s", 0.0),
                prompt_tokens=rec.get("prompt_tokens", 0),
                completion_tokens=rec.get("completion_tokens", 0),
            )
            return _parse_json(rec["content"]), meta
        if not self.allow_live:
            return None, CallMeta(error="no model configured")

        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0, timeout=60)
        err = None
        for attempt in range(max_retries):
            with _lock:
                wait = MIN_INTERVAL_S - (time.monotonic() - _last_call[0])
                if wait > 0:
                    time.sleep(wait)
                _last_call[0] = time.monotonic()
            t0 = time.perf_counter()
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
            except Exception as e:  # rate limits, timeouts, 5xx: back off and retry
                err = f"{type(e).__name__}: {str(e)[:200]}"
                time.sleep(min(30, 3 * 2**attempt))
                continue
            latency = time.perf_counter() - t0
            content = resp.choices[0].message.content or ""
            usage = resp.usage
            rec = {
                "model": self.model,
                "content": content,
                "latency_s": round(latency, 2),
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            }
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
            meta = CallMeta(
                live=True,
                latency_s=rec["latency_s"],
                prompt_tokens=rec["prompt_tokens"],
                completion_tokens=rec["completion_tokens"],
            )
            return _parse_json(content), meta
        return None, CallMeta(error=err)


def _parse_json(content: str) -> dict | None:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return None
        try:
            out = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return out if isinstance(out, dict) else None
