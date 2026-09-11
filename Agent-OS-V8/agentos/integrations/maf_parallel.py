from __future__ import annotations

import asyncio
import os
from typing import Any


class MAFParallel:
    def __init__(self, enabled: bool = True, ollama_host: str = "", ollama_model: str = "") -> None:
        self.enabled = enabled
        self.ollama_host = ollama_host
        self.ollama_model = ollama_model
        self._error = ""

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            from agent_framework import Agent  # noqa: F401
            from agent_framework.ollama import OllamaChatClient  # noqa: F401
            from agent_framework.orchestrations import ConcurrentBuilder  # noqa: F401
            return True
        except Exception as exc:
            self._error = str(exc)
            return False

    def status(self) -> dict:
        ok = self.available()
        return {
            "enabled": self.enabled,
            "installed": ok,
            "ok": ok,
            "pattern": "ConcurrentBuilder",
            **({"error": self._error} if self._error and not ok else {}),
        }

    async def _run_async(self, prompt: str, roles: list[tuple[str, str]]) -> list[dict[str, str]]:
        from agent_framework import Agent, AgentResponse
        from agent_framework.ollama import OllamaChatClient
        from agent_framework.orchestrations import ConcurrentBuilder

        if self.ollama_host:
            os.environ["OLLAMA_HOST"] = self.ollama_host
        if self.ollama_model:
            os.environ["OLLAMA_MODEL"] = self.ollama_model

        client = OllamaChatClient()
        participants = [Agent(client=client, name=name, instructions=instructions) for name, instructions in roles]
        workflow = ConcurrentBuilder(participants=participants).build()
        events = await workflow.run(prompt)
        outputs = events.get_outputs()
        result: list[dict[str, str]] = []
        for output in outputs or []:
            if not isinstance(output, AgentResponse):
                continue
            for msg in output.messages:
                result.append({"agent": msg.author_name or "assistant", "text": msg.text or ""})
        return result

    def run(self, prompt: str, roles: list[tuple[str, str]] | None = None) -> list[dict[str, str]]:
        if not self.available():
            raise RuntimeError("Microsoft Agent Framework n'est pas disponible.")
        roles = roles or [
            ("researcher", "Analyse les faits, contraintes et informations manquantes."),
            ("builder", "Propose une solution concrète et techniquement simple."),
            ("reviewer", "Cherche les erreurs, risques et incohérences de la solution."),
        ]
        try:
            return asyncio.run(self._run_async(prompt, roles))
        except RuntimeError as exc:
            if "asyncio.run() cannot be called" not in str(exc):
                raise
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._run_async(prompt, roles))
            finally:
                loop.close()
