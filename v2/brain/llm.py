"""
Interface LLM de Agent-OS V2.

Pour l'instant :
    Ollama

Plus tard :
    OpenAI
    modèles locaux supplémentaires
    autres fournisseurs
"""

from typing import Optional

import requests

from v2.config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
)


class LLMError(Exception):
    """Erreur liée au fournisseur LLM."""


class LLM:
    """
    Interface minimale avec Ollama.

    Le reste de l'application ne doit pas connaître
    les détails HTTP d'Ollama.
    """

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: int = 120,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        """
        Envoie une conversation au modèle.
        """

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                *messages,
            ],
            "stream": False,
        }

        url = f"{self.host}/api/chat"

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
            )

        except requests.RequestException as exc:
            raise LLMError(
                f"Impossible de contacter Ollama : {exc}"
            ) from exc

        if response.status_code != 200:
            raise LLMError(
                f"Ollama a retourné HTTP {response.status_code}: "
                f"{response.text}"
            )

        try:
            data = response.json()

        except ValueError as exc:
            raise LLMError(
                "Ollama a retourné une réponse JSON invalide."
            ) from exc

        message = data.get("message")

        if not isinstance(message, dict):
            raise LLMError(
                "Réponse Ollama invalide : champ 'message' absent."
            )

        content = message.get("content")

        if not isinstance(content, str):
            raise LLMError(
                "Réponse Ollama invalide : contenu absent."
            )

        return content.strip()

    def simple_chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Version pratique pour une requête simple.
        """

        if system_prompt is None:
            system_prompt = "Tu es un assistant utile et précis."

        return self.chat(
            system_prompt=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )