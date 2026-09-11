from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any


def _json_from_text(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("\x60\x60\x60"):
        text = re.sub(r"^\x60{3}(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*\x60{3}$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


class LocalSemanticAI:
    """Small Ollama client used only for semantic interpretation.

    The model never writes SQLite. It proposes a JSON plan; Python validates
    that plan and the store remains the source of truth.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = dict(config or {})
        enabled = config.get("semantic_ai_enabled", True)
        self.enabled = bool(enabled) and os.getenv("AGENT_OS_SEMANTIC_AI", "1") != "0"
        self.base_url = str(
            config.get("ollama_base_url")
            or os.getenv("AGENT_OS_OLLAMA_URL")
            or "http://host.docker.internal:11434"
        ).rstrip("/")
        self.model = str(
            config.get("semantic_model")
            or os.getenv("AGENT_OS_SEMANTIC_MODEL")
            or "qwen2.5:7b"
        )
        try:
            self.timeout = max(1.0, min(120.0, float(
                config.get("semantic_timeout_seconds", 12)
            )))
        except (TypeError, ValueError):
            self.timeout = 12.0
        self._failed_until = 0.0

    def _request(self, prompt: str, *, json_mode: bool) -> str | None:
        if not self.enabled or time.monotonic() < self._failed_until:
            return None
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        if json_mode:
            payload["format"] = "json"
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return str(body.get("response") or "")
        except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            # A local model is an optional accelerator. Do not make memory
            # capture unavailable just because Ollama is stopped.
            self._failed_until = time.monotonic() + 30.0
            return None

    async def generate_json(self, prompt: str) -> Any:
        response = await asyncio.to_thread(self._request, prompt, json_mode=True)
        return _json_from_text(response or "")

    async def generate_text(self, prompt: str) -> str | None:
        return await asyncio.to_thread(self._request, prompt, json_mode=False)
