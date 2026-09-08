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
    """
    Agent-OS V4.7.3 — Intent router.

    Objectif du correctif :
    - ne plus prendre une habitude ("je teste le code le soir") pour une tâche ;
    - ne plus prendre une préférence ("quand tu modifies du code...") pour une
      demande de développement ;
    - continuer à détecter les vraies demandes explicites :
      "Teste ce fichier", "Peux-tu modifier app.py ?", etc.
    """

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
    # ACTION PATTERNS
    # =========================================================

    TEST_RE = re.compile(
        r"\b(?:"
        r"teste|tester|testes|"
        r"vérifie|verifie|vérifier|verifier|vérifies|verifies|"
        r"compile|compiler|compiles"
        r")\b",
        flags=re.IGNORECASE,
    )

    RESEARCH_RE = re.compile(
        r"\b(?:"
        r"recherche|rechercher|recherches|"
        r"cherche|chercher|cherches|"
        r"renseigne-toi|renseigne toi|"
        r"documente-toi|documente toi|"
        r"trouve des sources"
        r")\b",
        flags=re.IGNORECASE,
    )

    DEV_RE = re.compile(
        r"\b(?:"
        r"crée|cree|créer|creer|crées|crees|"
        r"modifie|modifier|modifies|"
        r"corrige|corriger|corriges|"
        r"ajoute|ajouter|ajoutes|"
        r"supprime|supprimer|supprimes|"
        r"remplace|remplacer|remplaces|"
        r"écris|ecris|écrire|ecrire|"
        r"développe|developpe|développer|developper|développes|developpes"
        r")\b",
        flags=re.IGNORECASE,
    )

    WORK_RE = re.compile(
        r"\b(?:"
        r"analyse|analyser|analyses|"
        r"planifie|planifier|planifies|"
        r"conçois|concois|concevoir|"
        r"prépare|prepare|préparer|preparer|prépares|prepares|"
        r"propose-moi|propose moi"
        r")\b",
        flags=re.IGNORECASE,
    )

    REQUEST_PREFIXES = (
        "peux-tu ",
        "peux tu ",
        "pourrais-tu ",
        "pourrais tu ",
        "tu peux ",
        "est-ce que tu peux ",
        "est ce que tu peux ",
        "je veux que tu ",
        "j'aimerais que tu ",
        "j’aimerais que tu ",
        "je voudrais que tu ",
        "merci de ",
        "il faut que tu ",
    )

    PERSONAL_START_RE = re.compile(
        r"^(?:"
        r"d'habitude|d’habitude|habituellement|"
        r"en général,?\s+je|en general,?\s+je|"
        r"j'aime|j’aime|j'adore|j’adore|"
        r"je déteste|je deteste|"
        r"mon\s+.{1,80}\s+(?:préféré|prefere)\s+est|"
        r"(?:ma|mon)\s+(?:copine|compagnon|compagne|femme|mari|"
        r"frère|frere|sœur|soeur|mère|mere|père|pere|ami|amie)"
        r"\s+s['’]?appelle"
        r")\b",
        flags=re.IGNORECASE,
    )

    FORGET_RE = re.compile(
        r"^(?:"
        r"oublie\b|ne retiens plus\b|efface\b|supprime de ta mémoire\b|"
        r"supprime de ta memoire\b|"
        r"(?:peux-tu|peux tu|pourrais-tu|pourrais tu) oublier\b|"
        r"je veux que tu oublies\b|j['’]?aimerais que tu oublies\b"
        r")",
        flags=re.IGNORECASE,
    )

    COMMUNICATION_PREFERENCE_MARKERS = (
        "droit au but",
        "réponse directe",
        "reponse directe",
        "réponses directes",
        "reponses directes",
        "sans blabla",
        "sans bla bla",
        "étape par étape",
        "etape par etape",
        "fichier complet",
        "fichiers complets",
        "code complet",
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

    @classmethod
    def _explicit_file(
        cls,
        text: str,
    ) -> bool:

        return bool(
            cls.FILE_RE.search(
                text.replace(
                    "\\",
                    "/",
                )
            )
        )

    @classmethod
    def _looks_personal_statement(
        cls,
        text: str,
    ) -> bool:
        """
        Barrière anti-faux-positifs.

        Une phrase qui décrit une préférence, une habitude, un goût ou une
        relation reste une conversation, même si elle contient le mot
        "teste" ou "modifies".
        """

        if cls.FORGET_RE.search(text):
            return True

        candidate = re.sub(
            r"^(?:finalement|en fait|désormais|desormais|maintenant|corrige\s*:)\s*[:,]?\s*",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        # « Corrige ma copine s'appelle ... » décrit une correction de
        # mémoire personnelle. « Corrige ce fichier » reste, lui, une tâche.
        relation_correction = re.sub(
            r"^corrige\s+",
            "",
            candidate,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        if (
            relation_correction != candidate
            and cls.PERSONAL_START_RE.search(relation_correction)
        ):
            return True

        if cls.PERSONAL_START_RE.search(candidate):
            return True

        if candidate.startswith(
            (
                "je préfère ",
                "je prefere ",
            )
        ):
            if any(
                marker in candidate
                for marker in cls.COMMUNICATION_PREFERENCE_MARKERS
            ):
                # Avec un chemin de fichier précis, la phrase peut être une
                # vraie demande de modification. Sans cible précise, c'est une
                # préférence de communication.
                return not cls._explicit_file(candidate)

            # "Je préfère X" est par défaut une information personnelle,
            # pas une mission.
            return True

        return False

    @classmethod
    def _action_is_requested(
        cls,
        text: str,
        pattern: re.Pattern[str],
    ) -> bool:
        match = pattern.search(text)

        if match is None:
            return False

        prefix = text[:match.start()].strip()

        # Impératif / infinitif au début :
        # "Teste...", "Modifier...", "Analyse..."
        if not prefix:
            return True

        # "stp teste...", "svp modifie..."
        if prefix in {
            "stp",
            "svp",
            "s'il te plaît",
            "s'il te plait",
        }:
            return True

        # Formulations explicites de demande.
        return any(
            prefix.startswith(marker.strip())
            or text.startswith(marker)
            for marker in cls.REQUEST_PREFIXES
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
        # PERSONAL / RELATIONAL STATEMENTS
        # =====================================================

        if self._looks_personal_statement(
            text
        ):

            return Route(
                "conversation",
                None,
                "information personnelle ou préférence",
            )

        # =====================================================
        # TEST
        # =====================================================

        if self._action_is_requested(
            text,
            self.TEST_RE,
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

        if self._action_is_requested(
            text,
            self.RESEARCH_RE,
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

        if self._action_is_requested(
            text,
            self.DEV_RE,
        ):

            return Route(
                "task",
                "developer",
                (
                    "demande explicite "
                    "de développement"
                ),
            )

        explicit_file = self._explicit_file(
            text
        )

        if (
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

        if self._action_is_requested(
            text,
            self.WORK_RE,
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
