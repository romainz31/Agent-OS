from __future__ import annotations

import re

from dataclasses import (
    dataclass,
)


@dataclass(
    frozen=True
)
class Route:

    kind: str
    worker: str | None
    reason: str


class Router:

    # =========================================================
    # FILE
    # =========================================================

    FILE_RE = re.compile(
        r"(?:(?:workspace/)?"
        r"(?:[A-Za-z0-9_.-]+/)*"
        r"[A-Za-z0-9_.-]+\."
        r"[A-Za-z0-9_-]+)"
    )

    # =========================================================
    # ACTION VERBS
    # =========================================================

    DEV_ACTIONS = (
        "crée",
        "cree",
        "créer",
        "creer",
        "modifie",
        "modifier",
        "corrige",
        "corriger",
        "ajoute",
        "ajouter",
        "supprime",
        "supprimer",
        "remplace",
        "remplacer",
        "écris",
        "ecris",
        "écrire",
        "ecrire",
        "développe",
        "developpe",
    )

    TEST_ACTIONS = (
        "teste",
        "tester",
        "vérifie",
        "verifie",
        "vérifier",
        "verifier",
        "compile",
        "compiler",
    )

    RESEARCH_ACTIONS = (
        "recherche",
        "rechercher",
        "cherche sur internet",
        "cherche sur le web",
        "renseigne-toi",
        "renseigne toi",
        "documente-toi",
        "documente toi",
        "trouve des sources",
    )

    WORK_ACTIONS = (
        "analyse",
        "analyser",
        "planifie",
        "planifier",
        "conçois",
        "concois",
        "concevoir",
        "prépare",
        "prepare",
        "préparer",
        "propose-moi",
        "propose moi",
    )

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _normalize(
        message: str,
    ) -> str:

        return " ".join(
            message
            .lower()
            .strip()
            .split()
        )

    @staticmethod
    def _contains_action(
        text: str,
        actions: tuple[str, ...],
    ) -> bool:

        return any(
            action in text
            for action
            in actions
        )

    # =========================================================
    # ROUTE
    # =========================================================

    def route(
        self,
        message: str,
    ) -> Route:

        text = self._normalize(
            message
        )

        if not text:

            return Route(
                "conversation",
                None,
                "message vide",
            )

        # =====================================================
        # TEST
        # =====================================================

        if self._contains_action(
            text,
            self.TEST_ACTIONS,
        ):

            return Route(
                "task",
                "tester",
                (
                    "demande explicite "
                    "de vérification"
                ),
            )

        # =====================================================
        # RESEARCH
        # =====================================================

        if self._contains_action(
            text,
            self.RESEARCH_ACTIONS,
        ):

            return Route(
                "task",
                "researcher",
                (
                    "demande explicite "
                    "de recherche"
                ),
            )

        # =====================================================
        # DEVELOPMENT
        # =====================================================

        dev_action = (
            self._contains_action(
                text,
                self.DEV_ACTIONS,
            )
        )

        explicit_file = bool(
            self.FILE_RE.search(
                text.replace(
                    "\\",
                    "/",
                )
            )
        )

        if (
            dev_action
            or (
                explicit_file
                and any(
                    marker in text
                    for marker
                    in (
                        "fais",
                        "change",
                        "mets",
                        "répare",
                        "repare",
                    )
                )
            )
        ):

            return Route(
                "task",
                "developer",
                (
                    "demande explicite "
                    "de développement"
                ),
            )

        # =====================================================
        # INTELLECTUAL WORK
        # =====================================================

        if self._contains_action(
            text,
            self.WORK_ACTIONS,
        ):

            return Route(
                "task",
                "ai_worker",
                (
                    "demande explicite "
                    "de travail intellectuel"
                ),
            )

        # =====================================================
        # DEFAULT
        # =====================================================

        return Route(
            "conversation",
            None,
            "conversation normale",
        )