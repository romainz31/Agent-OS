"""
Developer Agent-OS V2.

Worker spécialisé dans l'analyse technique,
la conception et la programmation.

IMPORTANT :
Cette première version ne modifie aucun fichier
du système. Elle produit uniquement du travail
intellectuel.

Les outils de fichiers et l'exécution de code
seront ajoutés avec le Permission Engine.
"""

from __future__ import annotations

from typing import Any, Dict

from v2.brain.llm import LLM, LLMError
from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class DeveloperWorker(Worker):

    name = "developer"

    description = (
        "Agent spécialisé dans la programmation, "
        "la conception technique, l'analyse de code "
        "et la résolution de problèmes logiciels."
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
Tu es le Developer d'une équipe d'agents IA.

Le Manager te confie une tâche technique.

============================================================
TÂCHE
============================================================

TITRE :
{title}

DESCRIPTION :
{description}

============================================================
CONTEXTE
============================================================

{metadata}

============================================================
OBJECTIF
============================================================

Analyse le problème et propose une solution
technique concrète.

Tu peux :

- concevoir une architecture
- écrire du code
- corriger du code fourni
- expliquer une erreur
- proposer une stratégie d'implémentation
- identifier les risques techniques

IMPORTANT :

Tu ne disposes actuellement d'aucun outil
permettant de modifier réellement les fichiers.

Ne prétends donc jamais avoir modifié,
créé ou exécuté un fichier.

Si du code est nécessaire, fournis-le clairement.

Ton résultat sera transmis au Manager
et éventuellement au Tester.

Ne réponds pas comme un assistant conversationnel.
Tu rends un rapport technique.
"""

        try:

            result = self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Tu es un agent Developer "
                    "spécialisé en développement logiciel."
                ),
            )

        except LLMError as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Le Developer n'a pas pu "
                    "contacter le modèle."
                ),
                error=str(exc),
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Erreur du Developer."
                ),
                error=str(exc),
            )

        if not result.strip():

            return WorkerResult(
                success=False,
                message=(
                    "Le Developer n'a retourné "
                    "aucun résultat."
                ),
                error="empty_developer_result",
            )

        return WorkerResult(
            success=True,
            message=result.strip(),
            data={
                "worker": self.name,
                "type": "development",
                "task_id": task.get("id"),
                "model": self.llm.model,
            },
        )