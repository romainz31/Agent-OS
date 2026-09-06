"""
LLM Worker Agent-OS V2.

Worker générique capable d'exécuter une tâche
en utilisant le LLM configuré dans Agent-OS.

Ce worker constitue la première base de nos
agents spécialisés futurs.
"""

from __future__ import annotations

from typing import Any, Dict

from v2.brain.llm import LLM, LLMError
from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class LLMWorker(Worker):
    """
    Worker générique utilisant Ollama.

    Il reçoit une tâche structurée et demande
    au LLM de produire un résultat.
    """

    name = "ai_worker"

    description = (
        "Worker généraliste utilisant le LLM "
        "pour analyser et exécuter des tâches "
        "intellectuelles."
    )

    def __init__(
        self,
        llm: LLM | None = None,
    ) -> None:

        self.llm = llm or LLM()

    def execute(
        self,
        task: Dict[str, Any],
    ) -> WorkerResult:
        """
        Exécute une tâche avec le LLM.
        """

        task_id = str(
            task.get(
                "id",
                "unknown",
            )
        )

        title = str(
            task.get(
                "title",
                "",
            )
        )

        description = str(
            task.get(
                "description",
                "",
            )
        )

        priority = str(
            task.get(
                "priority",
                "normal",
            )
        )

        deadline = task.get(
            "deadline"
        )

        metadata = task.get(
            "metadata",
            {},
        )

        prompt = f"""
Tu es un worker autonome d'Agent-OS.

Tu as reçu une tâche du Manager.

Tu dois travailler uniquement sur cette tâche.

============================================================
TÂCHE
============================================================

ID :
{task_id}

TITRE :
{title}

DESCRIPTION :
{description}

PRIORITÉ :
{priority}

ÉCHÉANCE :
{deadline or "aucune"}

MÉTADONNÉES :
{metadata}

============================================================
INSTRUCTIONS
============================================================

Analyse la tâche.

Effectue le travail intellectuel nécessaire.

Donne un résultat concret, utile et exploitable
par le Manager.

Ne prétends pas avoir effectué une action externe
si tu ne disposes pas de l'outil nécessaire.

Si la tâche nécessite une action que tu ne peux
pas réellement effectuer, indique clairement
la limite.

Réponds directement avec le résultat du travail.

Ne parle pas de ton fonctionnement interne.
Ne réponds pas comme un assistant conversationnel.
Tu es un worker qui rend compte à son Manager.
"""

        try:

            result = self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Tu es un worker spécialisé "
                    "dans l'exécution de tâches "
                    "pour un système multi-agents."
                ),
            )

        except LLMError as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Le worker LLM n'a pas pu "
                    "contacter le modèle."
                ),
                error=str(exc),
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Erreur inattendue du "
                    "worker LLM."
                ),
                error=str(exc),
            )

        if not result.strip():

            return WorkerResult(
                success=False,
                message=(
                    "Le worker LLM n'a retourné "
                    "aucun résultat."
                ),
                error="empty_llm_result",
            )

        return WorkerResult(
            success=True,
            message=result.strip(),
            data={
                "worker": self.name,
                "task_id": task_id,
                "model": self.llm.model,
            },
        )