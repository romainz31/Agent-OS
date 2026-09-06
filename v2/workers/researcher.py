"""
Researcher Agent-OS V2.

Worker spécialisé dans la recherche,
l'analyse et la synthèse d'informations.
"""

from __future__ import annotations

from typing import Any, Dict

from v2.brain.llm import LLM, LLMError
from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class ResearcherWorker(Worker):

    name = "researcher"

    description = (
        "Agent spécialisé dans la recherche, "
        "l'analyse, la comparaison et la synthèse "
        "d'informations."
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

        prompt = f"""
Tu es le Researcher d'une équipe d'agents IA.

Le Manager te confie une tâche de recherche.

============================================================
TÂCHE
============================================================

TITRE :
{title}

DESCRIPTION :
{description}

============================================================
OBJECTIF
============================================================

Produis une analyse utile au Manager.

Identifie :

- les informations importantes
- les faits principaux
- les avantages
- les inconvénients
- les points d'attention
- les éventuelles incertitudes

Lorsque tu ne disposes pas d'une source ou
d'un outil permettant de vérifier une information,
ne prétends pas l'avoir vérifiée.

Ton résultat doit être directement exploitable
par un autre agent.

Ne parle pas comme un assistant conversationnel.
Tu rends un rapport au Manager.
"""

        try:

            result = self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Tu es un agent Researcher "
                    "rigoureux travaillant pour "
                    "un Manager multi-agents."
                ),
            )

        except LLMError as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Le Researcher n'a pas pu "
                    "contacter le modèle."
                ),
                error=str(exc),
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Erreur du Researcher."
                ),
                error=str(exc),
            )

        if not result.strip():

            return WorkerResult(
                success=False,
                message=(
                    "Le Researcher n'a retourné "
                    "aucun résultat."
                ),
                error="empty_research_result",
            )

        return WorkerResult(
            success=True,
            message=result.strip(),
            data={
                "worker": self.name,
                "type": "research",
                "task_id": task.get("id"),
                "model": self.llm.model,
            },
        )