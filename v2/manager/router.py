"""
Routeur déterministe du Manager Agent-OS V2.3.1.

Python décide d'abord si une demande est :
- une conversation ;
- une tâche ;
- une mission.

Il sélectionne également le worker spécialisé.
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
        "cree",
        "creer",
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
        "modifie",
        "modifier",
        "corrige",
        "corriger",
        "ajoute",
        "ajouter",
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

    FILE_ACTIONS = (
        "crée",
        "créer",
        "cree",
        "creer",
        "modifie",
        "modifier",
        "corrige",
        "corriger",
        "ajoute",
        "ajouter",
        "supprime",
        "supprimer",
        "écris",
        "écrire",
    )

    FILE_MARKERS = (
        "fichier",
        ".py",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".toml",
        ".ini",
        ".env",
        "v2/",
        "v2\\",
        "agents/",
        "agents\\",
        "docs/",
        "docs\\",
    )

    def route(
        self,
        message: str,
        available_workers: Iterable[str],
    ) -> RouteDecision:

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

        # ====================================================
        # MISSION
        # ====================================================

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

        # ====================================================
        # FICHIER / CODE
        # ====================================================

        if (
            "developer" in available
            and self._looks_like_file_task(
                text
            )
        ):

            return RouteDecision(
                action="create_task",
                worker="developer",
                reason=(
                    "action sur fichier "
                    "ou code détectée"
                ),
            )

        # ====================================================
        # WORKER SPÉCIALISÉ
        # ====================================================

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

        # ====================================================
        # TRAVAIL GÉNÉRAL
        # ====================================================

        if self._looks_like_work(
            text
        ):

            fallback = None

            if (
                "ai_worker"
                in available
            ):
                fallback = "ai_worker"

            return RouteDecision(
                action="create_task",
                worker=fallback,
                reason=(
                    "demande de travail "
                    "générale détectée"
                ),
            )

        # ====================================================
        # CONVERSATION
        # ====================================================

        return RouteDecision(
            action="conversation",
            reason="conversation détectée",
        )

    def _is_mission(
        self,
        text: str,
    ) -> bool:

        marker_count = sum(
            1
            for marker
            in self.MISSION_MARKERS
            if marker in text
        )

        if marker_count >= 2:
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

    def _looks_like_file_task(
        self,
        text: str,
    ) -> bool:
        """
        Détecte une action technique portant
        explicitement sur un fichier.
        """

        has_action = any(
            action in text
            for action
            in self.FILE_ACTIONS
        )

        if not has_action:
            return False

        return any(
            marker in text
            for marker
            in self.FILE_MARKERS
        )

    def _infer_worker(
        self,
        text: str,
        available: set[str],
    ) -> Optional[str]:

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

            if worker not in available:
                continue

            score = scores[
                worker
            ]

            if score > best_score:

                best_worker = worker
                best_score = score

        return best_worker

    def _infer_first_mission_worker(
        self,
        text: str,
        available: set[str],
    ) -> Optional[str]:

        first_part = text

        separators = (
            " ensuite ",
            " puis ",
            " enfin ",
            " après ça ",
            " après ",
        )

        indexes = []

        for separator in separators:

            index = text.find(
                separator
            )

            if index != -1:
                indexes.append(
                    index
                )

        if indexes:

            first_part = text[
                :min(indexes)
            ]

        if self._looks_like_file_task(
            first_part
        ):

            if (
                "developer"
                in available
            ):
                return "developer"

        return self._infer_worker(
            first_part,
            available,
        )

    def _looks_like_work(
        self,
        text: str,
    ) -> bool:

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
        keywords: tuple[str, ...],
    ) -> int:

        return sum(
            1
            for keyword
            in keywords
            if keyword in text
        )