"""
Tester Agent-OS V2.

Worker spécialisé dans la vérification,
la critique et la validation technique.

Cette première version réalise une validation
intellectuelle. L'exécution réelle de tests
sera ajoutée avec les outils sécurisés.
"""

from __future__ import annotations

from typing import Any, Dict

from v2.brain.llm import LLM, LLMError
from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class TesterWorker(Worker):

    name = "tester"

    description = (
        "Agent spécialisé dans les tests, "
        "la vérification, la détection de bugs "
        "et la validation de solutions."
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

        metadata = task.get(
            "metadata",
            {},
        )

        prompt = f"""
Tu es le Tester d'une équipe d'agents IA.

Le Manager te demande de vérifier une solution.

============================================================
TÂCHE
============================================================

TITRE :
{title}

DESCRIPTION :
{description}

============================================================
CONTEXTE / RÉSULTAT À TESTER
============================================================

{metadata}

============================================================
OBJECTIF
============================================================

Analyse ce qui doit être vérifié.

Cherche notamment :

- erreurs logiques
- bugs potentiels
- cas limites
- incohérences
- problèmes d'architecture
- problèmes de sécurité
- éléments manquants

Donne une conclusion claire :

VALIDÉ
ou
NON VALIDÉ

avec les corrections nécessaires.

IMPORTANT :

Tu ne disposes actuellement d'aucun outil
permettant d'exécuter réellement du code.

Ne prétends jamais avoir exécuté un test
que tu n'as pas réellement pu exécuter.

Tu rends un rapport au Manager.
"""

        try:

            result = self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Tu es un agent Tester "
                    "rigoureux spécialisé "
                    "dans la validation technique."
                ),
            )

        except LLMError as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Le Tester n'a pas pu "
                    "contacter le modèle."
                ),
                error=str(exc),
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Erreur du Tester."
                ),
                error=str(exc),
            )

        if not result.strip():

            return WorkerResult(
                success=False,
                message=(
                    "Le Tester n'a retourné "
                    "aucun résultat."
                ),
                error="empty_tester_result",
            )

        return WorkerResult(
            success=True,
            message=result.strip(),
            data={
                "worker": self.name,
                "type": "testing",
                "task_id": task.get("id"),
                "model": self.llm.model,
            },
        )