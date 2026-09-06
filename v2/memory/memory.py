"""
Mémoire Agent-OS V2.

La mémoire est séparée en plusieurs catégories :

- conversation
- personal
- emotional
- tasks
- knowledge
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.config import MEMORY_DIR


class MemoryStore:
    """
    Gestionnaire central de mémoire.

    Chaque catégorie possède son propre fichier JSON.
    """

    CATEGORIES = {
        "conversation",
        "personal",
        "emotional",
        "tasks",
        "knowledge",
    }

    def __init__(
        self,
        directory: Path = MEMORY_DIR,
    ):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    # ========================================================
    # UTILITAIRES
    # ========================================================

    def _path(self, category: str) -> Path:
        self._validate_category(category)

        return self.directory / f"{category}.json"

    def _validate_category(self, category: str) -> None:
        if category not in self.CATEGORIES:
            raise ValueError(
                f"Catégorie mémoire inconnue : {category}"
            )

    def _load(self, category: str) -> list[dict[str, Any]]:
        path = self._path(category)

        if not path.exists():
            return []

        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)

        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(data, list):
            return []

        return data

    def _save(
        self,
        category: str,
        entries: list[dict[str, Any]],
    ) -> None:
        path = self._path(category)

        temporary_path = path.with_suffix(".tmp")

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

        temporary_path.replace(path)

    # ========================================================
    # AJOUT
    # ========================================================

    def add(
        self,
        category: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Ajoute une entrée mémoire.
        """

        if not content or not content.strip():
            raise ValueError("Impossible d'enregistrer une mémoire vide.")

        entry = {
            "id": str(uuid.uuid4()),
            "content": content.strip(),
            "metadata": metadata or {},
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        entries = self._load(category)

        entries.append(entry)

        self._save(category, entries)

        return entry

    # ========================================================
    # LECTURE
    # ========================================================

    def get(
        self,
        category: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Retourne les dernières mémoires.
        """

        entries = self._load(category)

        if limit <= 0:
            return []

        return entries[-limit:]

    def search(
        self,
        category: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Recherche textuelle simple.

        Une recherche vectorielle pourra remplacer ceci plus tard
        sans modifier le reste de l'architecture.
        """

        query = query.lower().strip()

        if not query:
            return []

        entries = self._load(category)

        results = []

        for entry in reversed(entries):

            content = str(
                entry.get("content", "")
            ).lower()

            if query in content:
                results.append(entry)

            if len(results) >= limit:
                break

        return results

    # ========================================================
    # SUPPRESSION
    # ========================================================

    def delete(
        self,
        category: str,
        entry_id: str,
    ) -> bool:
        """
        Supprime une mémoire précise.
        """

        entries = self._load(category)

        original_count = len(entries)

        entries = [
            entry
            for entry in entries
            if entry.get("id") != entry_id
        ]

        if len(entries) == original_count:
            return False

        self._save(category, entries)

        return True

    def clear(self, category: str) -> None:
        """
        Efface complètement une catégorie.
        """

        self._save(category, [])

    # ========================================================
    # CONTEXTE MANAGER
    # ========================================================

    def build_manager_context(
        self,
        conversation_limit: int = 12,
        personal_limit: int = 20,
        emotional_limit: int = 10,
        task_limit: int = 10,
    ) -> str:
        """
        Construit le contexte mémoire injecté dans le prompt du Manager.
        """

        sections = []

        personal = self.get(
            "personal",
            personal_limit,
        )

        if personal:
            sections.append(
                "=== MÉMOIRE PERSONNELLE ===\n"
                + "\n".join(
                    f"- {entry['content']}"
                    for entry in personal
                )
            )

        emotional = self.get(
            "emotional",
            emotional_limit,
        )

        if emotional:
            sections.append(
                "=== CONTEXTE ÉMOTIONNEL ===\n"
                + "\n".join(
                    f"- {entry['content']}"
                    for entry in emotional
                )
            )

        tasks = self.get(
            "tasks",
            task_limit,
        )

        if tasks:
            sections.append(
                "=== CONTEXTE DES TÂCHES ===\n"
                + "\n".join(
                    f"- {entry['content']}"
                    for entry in tasks
                )
            )

        conversation = self.get(
            "conversation",
            conversation_limit,
        )

        if conversation:
            sections.append(
                "=== CONVERSATION RÉCENTE ===\n"
                + "\n".join(
                    f"- {entry['content']}"
                    for entry in conversation
                )
            )

        if not sections:
            return "(aucune mémoire pertinente)"

        return "\n\n".join(sections)