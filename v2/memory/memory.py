"""
Mémoire Agent-OS V2.1.

Principe important :

La conversation courante n'est PAS une mémoire longue durée.

La mémoire persistante contient uniquement :
- informations personnelles ;
- contexte émotionnel utile ;
- tâches importantes ;
- connaissances.

La conversation active est conservée par le Manager
uniquement pendant la session.
"""

from __future__ import annotations

import json
import re
import uuid

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path

from typing import Any

from v2.config import MEMORY_DIR


class MemoryStore:
    """
    Gestionnaire de mémoire persistante.
    """

    CATEGORIES = {
        "conversation",
        "personal",
        "emotional",
        "tasks",
        "knowledge",
    }

    LONG_TERM_CATEGORIES = (
        "personal",
        "emotional",
        "tasks",
        "knowledge",
    )

    STOP_WORDS = {
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "de",
        "du",
        "dans",
        "sur",
        "avec",
        "pour",
        "par",
        "et",
        "ou",
        "est",
        "sont",
        "je",
        "tu",
        "il",
        "elle",
        "nous",
        "vous",
        "ils",
        "elles",
        "mon",
        "ma",
        "mes",
        "ton",
        "ta",
        "tes",
        "son",
        "sa",
        "ses",
        "ce",
        "cet",
        "cette",
        "ça",
        "ca",
        "qui",
        "que",
        "quoi",
        "comment",
    }

    def __init__(
        self,
        directory: Path = MEMORY_DIR,
    ):
        self.directory = Path(
            directory
        )

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ========================================================
    # STORAGE
    # ========================================================

    def _path(
        self,
        category: str,
    ) -> Path:

        self._validate_category(
            category
        )

        return (
            self.directory
            / f"{category}.json"
        )

    def _validate_category(
        self,
        category: str,
    ) -> None:

        if category not in self.CATEGORIES:

            raise ValueError(
                "Catégorie mémoire inconnue : "
                f"{category}"
            )

    def _load(
        self,
        category: str,
    ) -> list[dict[str, Any]]:

        path = self._path(
            category
        )

        if not path.exists():
            return []

        try:

            with path.open(
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(
                    file
                )

        except (
            OSError,
            json.JSONDecodeError,
        ):
            return []

        if not isinstance(
            data,
            list,
        ):
            return []

        return data

    def _save(
        self,
        category: str,
        entries: list[dict[str, Any]],
    ) -> None:

        path = self._path(
            category
        )

        temporary_path = (
            path.with_suffix(
                ".tmp"
            )
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                entries,
                file,
                indent=2,
                ensure_ascii=False,
            )

        temporary_path.replace(
            path
        )

    # ========================================================
    # CREATE
    # ========================================================

    def add(
        self,
        category: str,
        content: str,
        metadata: dict[str, Any]
        | None = None,
    ) -> dict[str, Any]:

        self._validate_category(
            category
        )

        content = str(
            content
        ).strip()

        if not content:

            raise ValueError(
                "Impossible d'enregistrer "
                "une mémoire vide."
            )

        entry = {
            "id": str(
                uuid.uuid4()
            ),
            "content": content,
            "metadata": (
                metadata
                or {}
            ),
            "created_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

        entries = self._load(
            category
        )

        entries.append(
            entry
        )

        self._save(
            category,
            entries,
        )

        return entry

    # ========================================================
    # READ
    # ========================================================

    def get(
        self,
        category: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:

        entries = self._load(
            category
        )

        if limit <= 0:
            return []

        return entries[
            -limit:
        ]

    def search(
        self,
        category: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Recherche textuelle avec score simple.
        """

        query_tokens = self._tokens(
            query
        )

        if not query_tokens:
            return []

        entries = self._load(
            category
        )

        scored = []

        for entry in entries:

            content = str(
                entry.get(
                    "content",
                    "",
                )
            )

            content_tokens = (
                self._tokens(
                    content
                )
            )

            score = len(
                query_tokens
                & content_tokens
            )

            if score > 0:

                scored.append(
                    (
                        score,
                        entry,
                    )
                )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return [
            entry
            for _score, entry
            in scored[:limit]
        ]

    # ========================================================
    # DELETE
    # ========================================================

    def delete(
        self,
        category: str,
        entry_id: str,
    ) -> bool:

        entries = self._load(
            category
        )

        original_count = len(
            entries
        )

        entries = [
            entry
            for entry in entries
            if entry.get("id")
            != entry_id
        ]

        if (
            len(entries)
            == original_count
        ):
            return False

        self._save(
            category,
            entries,
        )

        return True

    def clear(
        self,
        category: str,
    ) -> None:

        self._save(
            category,
            [],
        )

    # ========================================================
    # MANAGER CONTEXT
    # ========================================================

    def build_manager_context(
        self,
        query: str = "",
        personal_limit: int = 8,
        emotional_limit: int = 4,
        task_limit: int = 6,
        knowledge_limit: int = 8,
    ) -> str:
        """
        Construit UNIQUEMENT le contexte longue durée.

        La catégorie conversation n'est volontairement
        jamais injectée ici.
        """

        sections = []

        categories = (
            (
                "personal",
                personal_limit,
                "MÉMOIRE PERSONNELLE",
            ),
            (
                "emotional",
                emotional_limit,
                "CONTEXTE ÉMOTIONNEL",
            ),
            (
                "tasks",
                task_limit,
                "TÂCHES / PROJETS",
            ),
            (
                "knowledge",
                knowledge_limit,
                "CONNAISSANCES",
            ),
        )

        for (
            category,
            limit,
            title,
        ) in categories:

            if query.strip():

                entries = self.search(
                    category,
                    query,
                    limit,
                )

            else:

                entries = self.get(
                    category,
                    limit,
                )

            if not entries:
                continue

            content = "\n".join(
                f"- {entry['content']}"
                for entry in entries
            )

            sections.append(
                f"=== {title} ===\n"
                f"{content}"
            )

        if not sections:

            return (
                "(aucune mémoire longue durée "
                "pertinente)"
            )

        return "\n\n".join(
            sections
        )

    # ========================================================
    # TOKENISATION
    # ========================================================

    def _tokens(
        self,
        text: str,
    ) -> set[str]:

        words = re.findall(
            r"[a-zA-ZÀ-ÿ0-9_]+",
            text.lower(),
        )

        return {
            word
            for word in words
            if (
                len(word) >= 3
                and word
                not in self.STOP_WORDS
            )
        }