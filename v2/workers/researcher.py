"""
Researcher Agent-OS V2.3.

Worker spécialisé dans :
- recherche Web réelle ;
- lecture de sources ;
- analyse ;
- synthèse ;
- restitution de sources vérifiables.
"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
)

from v2.brain.llm import (
    LLM,
    LLMError,
)

from v2.permissions.permissions import (
    PermissionEngine,
)

from v2.tools.web_search import (
    WebResearchTool,
    WebToolError,
    WebToolPermissionError,
)

from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class ResearcherWorker(
    Worker
):

    name = (
        "researcher"
    )

    description = (
        "Agent spécialisé dans la recherche "
        "Web réelle, l'analyse, la comparaison "
        "et la synthèse d'informations avec "
        "sources."
    )

    def __init__(
        self,
        llm: LLM | None = None,
        permissions: (
            PermissionEngine
            | None
        ) = None,
        web_tool: (
            WebResearchTool
            | None
        ) = None,
    ) -> None:

        self.llm = (
            llm
            or LLM()
        )

        self.permissions = (
            permissions
            or PermissionEngine()
        )

        self.web_tool = (
            web_tool
            or WebResearchTool(
                permissions=(
                    self.permissions
                )
            )
        )

    # ========================================================
    # QUERY
    # ========================================================

    @staticmethod
    def _build_search_query(
        title: str,
        description: str,
    ) -> str:

        query = (
            description.strip()
            or title.strip()
        )

        lower = (
            query.lower()
        )

        prefixes = (
            "recherche d'abord ",
            "recherche d’abord ",
            "recherche ",
            "cherche ",
            "trouve ",
        )

        for prefix in prefixes:

            if (
                lower.startswith(
                    prefix
                )
            ):

                query = (
                    query[
                        len(prefix):
                    ]
                    .strip()
                )

                break

        return query

    # ========================================================
    # EXECUTION
    # ========================================================

    def execute(
        self,
        task: Dict[
            str,
            Any,
        ],
    ) -> WorkerResult:

        title = str(
            task.get(
                "title",
                "",
            )
        ).strip()

        description = str(
            task.get(
                "description",
                "",
            )
        ).strip()

        dependency_context = (
            task.get(
                "dependency_context"
            )
            or (
                task.get(
                    "metadata",
                    {}
                ).get(
                    "dependency_context"
                )
                if isinstance(
                    task.get(
                        "metadata"
                    ),
                    dict,
                )
                else None
            )
            or ""
        )

        query = (
            self._build_search_query(
                title=title,
                description=description,
            )
        )

        if not query:

            return WorkerResult(
                success=False,
                message=(
                    "Le Researcher n'a pas "
                    "reçu de sujet de recherche."
                ),
                error=(
                    "empty_search_query"
                ),
            )

        # ====================================================
        # REAL WEB SEARCH
        # ====================================================

        try:

            research = (
                self.web_tool.research(
                    query=query,
                    max_results=6,
                    max_pages=3,
                )
            )

        except (
            WebToolPermissionError
        ) as exc:

            return WorkerResult(
                success=False,
                message=(
                    "La recherche Web "
                    "a été refusée par "
                    "le Permission Engine."
                ),
                error=str(
                    exc
                ),
            )

        except WebToolError as exc:

            return WorkerResult(
                success=False,
                message=(
                    "La recherche Web "
                    "a échoué."
                ),
                error=str(
                    exc
                ),
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Erreur inattendue "
                    "pendant la recherche Web."
                ),
                error=str(
                    exc
                ),
            )

        if not research.sources:

            return WorkerResult(
                success=False,
                message=(
                    "Aucune source Web "
                    "n'a été trouvée."
                ),
                error=(
                    "no_web_sources"
                ),
            )

        web_context = (
            research.build_context(
                max_chars_per_source=5000
            )
        )

        # ====================================================
        # LLM SYNTHESIS
        # ====================================================

        prompt = f"""
Tu es le Researcher d'une équipe multi-agents.

Le Manager t'a confié une recherche.

============================================================
TÂCHE
============================================================

TITRE :
{title}

DESCRIPTION :
{description}

REQUÊTE WEB UTILISÉE :
{query}

============================================================
CONTEXTE D'UNE ÉTAPE PRÉCÉDENTE
============================================================

{dependency_context or "(aucun)"}

============================================================
SOURCES WEB RÉELLEMENT OBTENUES
============================================================

{web_context}

============================================================
TRAVAIL DEMANDÉ
============================================================

Analyse exclusivement les informations présentes
dans les sources fournies.

Tu dois produire un rapport utile au Manager
et directement exploitable par les autres agents.

Structure recommandée :

1. Synthèse
2. Informations importantes
3. Bonnes pratiques / recommandations
4. Avantages
5. Inconvénients ou limites
6. Incertitudes ou points à vérifier
7. Sources

RÈGLES IMPORTANTES :

- N'invente aucune source.
- N'affirme pas avoir consulté autre chose
  que les sources fournies.
- Lorsque tu relies une affirmation à une source,
  utilise [S1], [S2], etc.
- Dans la section Sources,
  indique le titre et l'URL.
- Si les sources se contredisent,
  signale-le.
- Si une page n'a pas pu être récupérée,
  utilise seulement son extrait de moteur
  de recherche et reste prudent.
- Ne parle pas comme un assistant conversationnel.
- Tu rends un rapport professionnel au Manager.
"""

        try:

            result = (
                self.llm.simple_chat(
                    prompt=prompt,
                    system_prompt=(
                        "Tu es un agent Researcher "
                        "rigoureux. Tu analyses "
                        "uniquement des sources Web "
                        "réellement fournies et tu "
                        "cites [S1], [S2], etc."
                    ),
                )
            )

        except LLMError as exc:

            return WorkerResult(
                success=False,
                message=(
                    "La recherche Web a réussi, "
                    "mais le Researcher n'a pas "
                    "pu contacter le modèle."
                ),
                error=str(
                    exc
                ),
                data={
                    "query": (
                        query
                    ),
                    "sources": [
                        source.to_dict()
                        for source
                        in research.sources
                    ],
                },
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Erreur du Researcher "
                    "pendant la synthèse."
                ),
                error=str(
                    exc
                ),
            )

        if not result.strip():

            return WorkerResult(
                success=False,
                message=(
                    "Le Researcher n'a retourné "
                    "aucune synthèse."
                ),
                error=(
                    "empty_research_result"
                ),
            )

        return WorkerResult(
            success=True,
            message=(
                result.strip()
            ),
            data={
                "worker": (
                    self.name
                ),
                "type": (
                    "web_research"
                ),
                "task_id": (
                    task.get(
                        "id"
                    )
                ),
                "model": (
                    self.llm.model
                ),
                "query": (
                    query
                ),
                "source_count": (
                    len(
                        research.sources
                    )
                ),
                "fetched_source_count": (
                    len(
                        [
                            source
                            for source
                            in research.sources
                            if source.fetched
                        ]
                    )
                ),
                "sources": [
                    source.to_dict()
                    for source
                    in research.sources
                ],
            },
        )