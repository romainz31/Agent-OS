from __future__ import annotations
import requests
from agentos.config import OLLAMA_HOST, OLLAMA_MODEL

class LLMError(RuntimeError):
    pass

class LLM:
    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL, timeout: int = 180) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, user: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
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
