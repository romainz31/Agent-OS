"""
Routeur déterministe du Manager Agent-OS V2.3.1.

Le LLM ne décide pas seul si une demande est :
- une conversation ;
- une tâche ;
- une mission.

Python effectue d'abord un routage stable.

Correction V2.3.1 :
- les demandes de conception technique ;
- architecture ;
- design logiciel ;
- structure applicative ;
sont explicitement routées vers le Developer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class RouteDecision:
    """
    Résultat du routage déterministe.
    """

    action: str
    worker: Optional[str] = None
    reason: str = ""


class ManagerRouter:
    """
    Routeur principal du Manager.

    Il détermine :
    - conversation ;
    - tâche ;
    - mission ;
    - worker spécialisé.
    """

    MISSION_MARKERS = (
        "d'abord",
        "ensuite",
        "puis",
        "enfin",
        "après ça",
        "première étape",
        "deuxième étape",
        "troisième étape",
        "plusieurs étapes",
        "étape 1",
        "étape 2",
        "étape 3",
    )

    RESEARCH_KEYWORDS = (
        "recherche",
        "rechercher",
        "cherche",
        "chercher",
        "documentation",
        "documente",
        "documenter",
        "source",
        "sources",
        "web",
        "internet",
        "compare",
        "comparer",
        "comparaison",
        "étude",
        "étudier",
        "renseigne",
        "renseigner",
        "trouve-moi",
        "trouve moi",
        "bonnes pratiques",
    )

    DEVELOPER_KEYWORDS = (
        "python",
        "code",
        "coder",
        "développe",
        "développer",
        "développement",
        "programme",
        "programmer",
        "programmation",
        "script",
        "fonction",
        "classe",
        "module",
        "api",
        "refactor",
        "refactoriser",
        "implémente",
        "implémenter",
        "architecture",
        "architecture python",
        "architecture logicielle",
        "architecture technique",
        "conçois",
        "concevoir",
        "conception",
        "design logiciel",
        "design technique",
        "structure du projet",
        "structure applicative",
        "organise le code",
        "organiser le code",
        "crée le fichier",
        "créé le fichier",
        "modifie le code",
        "modifier le code",
        "corrige le code",
        "corriger le code",
    )

    TESTER_KEYWORDS = (
        "teste",
        "tester",
        "tests",
        "vérifie",
        "vérifier",
        "validation",
        "valider",
        "bug",
        "bugs",
        "erreur",
        "erreurs",
        "reproduire le bug",
        "reproduis le bug",
        "contrôle le fonctionnement",
        "cherche les problèmes",
        "problèmes techniques",
    )

    DEMO_KEYWORDS = (
        "démo",
        "demo",
        "démonstration",
    )

    WORK_VERBS = (
        "fais",
        "faire",
        "crée",
        "créer",
        "conçois",
        "concevoir",
        "prépare",
        "préparer",
        "analyse",
        "analyser",
        "rédige",
        "rédiger",
        "génère",
        "générer",
        "produis",
        "produire",
        "calcule",
        "calculer",
        "organise",
        "organiser",
        "planifie",
        "planifier",
    )

    CONVERSATION_PREFIXES = (
        "bonjour",
        "salut",
        "bonsoir",
        "coucou",
        "merci",
        "ça va",
        "ca va",
        "comment vas-tu",
        "comment vas tu",
        "tu vas bien",
    )

    def route(
        self,
        message: str,
        available_workers: Iterable[str],
    ) -> RouteDecision:
        """
        Route un message.
        """

        text = " ".join(
            message.lower().strip().split()
        )

        available = set(
            available_workers
        )

        if not text:
            return RouteDecision(
                action="conversation",
                reason="message vide",
            )

        # ========================================================
        # MISSION
        # ========================================================

        if self._is_mission(
            text
        ):

            worker = (
                self._infer_first_mission_worker(
                    text,
                    available,
                )
            )

            return RouteDecision(
                action="create_mission",
                worker=worker,
                reason=(
                    "plusieurs étapes détectées"
                ),
            )

        # ========================================================
        # WORKER SPÉCIALISÉ
        # ========================================================

        worker = (
            self._infer_worker(
                text,
                available,
            )
        )

        if worker:

            return RouteDecision(
                action="create_task",
                worker=worker,
                reason=(
                    "worker spécialisé détecté : "
                    f"{worker}"
                ),
            )

        # ========================================================
        # TRAVAIL GÉNÉRAL
        # ========================================================

        if self._looks_like_work(
            text
        ):

            fallback = None

            if (
                "ai_worker"
                in available
            ):
                fallback = (
                    "ai_worker"
                )

            return RouteDecision(
                action="create_task",
                worker=fallback,
                reason=(
                    "demande de travail "
                    "générale détectée"
                ),
            )

        # ========================================================
        # CONVERSATION
        # ========================================================

        return RouteDecision(
            action="conversation",
            reason=(
                "conversation détectée"
            ),
        )

    def _is_mission(
        self,
        text: str,
    ) -> bool:
        """
        Détecte une demande multi-étapes.
        """

        marker_count = sum(
            1
            for marker
            in self.MISSION_MARKERS
            if marker in text
        )

        if (
            marker_count >= 2
        ):
            return True

        chained_patterns = (
            "recherche puis",
            "recherche d'abord",
            "analyse puis",
            "analyse d'abord",
            "développe puis",
            "crée puis",
            "conçois puis",
            "conçois d'abord",
            "ensuite teste",
            "ensuite vérifie",
            "puis teste",
            "puis vérifie",
        )

        return any(
            pattern in text
            for pattern
            in chained_patterns
        )

    def _infer_worker(
        self,
        text: str,
        available: set[str],
    ) -> Optional[str]:
        """
        Détermine le worker le plus pertinent.
        """

        scores = {
            "tester": self._score(
                text,
                self.TESTER_KEYWORDS,
            ),
            "developer": self._score(
                text,
                self.DEVELOPER_KEYWORDS,
            ),
            "researcher": self._score(
                text,
                self.RESEARCH_KEYWORDS,
            ),
            "demo": self._score(
                text,
                self.DEMO_KEYWORDS,
            ),
        }

        priority = (
            "tester",
            "developer",
            "researcher",
            "demo",
        )

        best_worker = None
        best_score = 0

        for worker in priority:

            if (
                worker
                not in available
            ):
                continue

            score = (
                scores[worker]
            )

            if (
                score
                > best_score
            ):

                best_worker = (
                    worker
                )

                best_score = (
                    score
                )

        return best_worker

    def _infer_first_mission_worker(
        self,
        text: str,
        available: set[str],
    ) -> Optional[str]:
        """
        Détermine le worker
        de la première étape.
        """

        first_part = (
            text
        )

        separators = (
            " ensuite ",
            " puis ",
            " enfin ",
            " après ça ",
            " après ",
        )

        indexes = []

        for separator in (
            separators
        ):

            index = (
                text.find(
                    separator
                )
            )

            if (
                index != -1
            ):
                indexes.append(
                    index
                )

        if indexes:

            first_part = (
                text[
                    :min(indexes)
                ]
            )

        return (
            self._infer_worker(
                first_part,
                available,
            )
        )

    def _looks_like_work(
        self,
        text: str,
    ) -> bool:
        """
        Détecte une demande générale
        de travail.
        """

        if any(
            text.startswith(
                prefix
            )
            for prefix
            in self.CONVERSATION_PREFIXES
        ):

            return False

        return any(
            verb in text
            for verb
            in self.WORK_VERBS
        )

    @staticmethod
    def _score(
        text: str,
        keywords: tuple[
            str,
            ...
        ],
    ) -> int:
        """
        Score simple par mots-clés.
        """

        return sum(
            1
            for keyword
            in keywords
            if keyword in text
        )