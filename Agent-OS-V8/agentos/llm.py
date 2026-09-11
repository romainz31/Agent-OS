from __future__ import annotations

import requests

from agentos.config import OLLAMA_HOST, OLLAMA_MODEL


class LLMError(RuntimeError):
    pass


class OllamaLLM:
    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL, timeout: int = 180) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def health(self) -> dict:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=3)
            response.raise_for_status()
            models = [m.get("name", "") for m in response.json().get("models", [])]
            return {"ok": True, "model": self.model, "installed": self.model in models, "models": models[:20]}
        except Exception as exc:
            return {"ok": False, "model": self.model, "error": str(exc)}

    def chat(self, messages: list[dict[str, str]]) -> str:
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return str(response.json()["message"]["content"]).strip()
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise LLMError(f"Ollama inaccessible ou réponse invalide : {exc}") from exc

    def ask(self, user: str, system: str = "") -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        return self.chat(messages)
