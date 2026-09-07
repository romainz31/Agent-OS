from __future__ import annotations

import re
from datetime import datetime, timezone

from agentos.config import DATA_DIR
from agentos.storage import JsonStore


class Memory:
    QUESTION_STARTERS = (
        "quel ",
        "quelle ",
        "quels ",
        "quelles ",
        "qui ",
        "que ",
        "quoi ",
        "où ",
        "ou ",
        "quand ",
        "comment ",
        "combien ",
        "pourquoi ",
        "est-ce ",
        "est ce ",
        "peux-tu ",
        "peux tu ",
        "pourrais-tu ",
        "pourrais tu ",
        "sais-tu ",
        "sais tu ",
        "tu sais ",
        "tu te souviens ",
        "rappelle-moi ",
        "rappelle moi ",
    )

    EXPLICIT_PATTERNS = (
        r"^\s*souviens-toi\s+que\s+",
        r"^\s*souviens toi\s+que\s+",
        r"^\s*retiens\s+que\s+",
        r"^\s*mémorise\s+(?:que\s+)?",
        r"^\s*memorise\s+(?:que\s+)?",
        r"^\s*garde\s+en\s+mémoire\s+(?:que\s+)?",
        r"^\s*garde\s+en\s+memoire\s+(?:que\s+)?",
        r"^\s*à\s+l'avenir\s*[:,]?\s*",
        r"^\s*a\s+l'avenir\s*[:,]?\s*",
    )

    def __init__(self) -> None:
        self.store = JsonStore(
            DATA_DIR / "memory.json",
            {
                "session": [],
                "long_term": [],
                "profile": [],
            },
        )

        loaded = self.store.load()

        if not isinstance(
            loaded,
            dict,
        ):
            loaded = {}

        if not isinstance(
            loaded.get("session"),
            list,
        ):
            loaded["session"] = []

        if not isinstance(
            loaded.get("long_term"),
            list,
        ):
            loaded["long_term"] = []

        if not isinstance(
            loaded.get("profile"),
            list,
        ):
            loaded["profile"] = []

        self.data = loaded

        # Nettoie automatiquement les anciennes
        # mémoires parasites au démarrage.
        self._sanitize_long_term()

        self._save()

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _save(self) -> None:
        self.store.save(
            self.data
        )

    # =========================================================
    # QUESTION DETECTION
    # =========================================================

    @classmethod
    def _looks_like_question(
        cls,
        text: str,
    ) -> bool:
        clean = " ".join(
            text.strip().split()
        )

        if not clean:
            return False

        lower = clean.lower()

        if clean.endswith("?"):
            return True

        return any(
            lower.startswith(
                starter
            )
            for starter
            in cls.QUESTION_STARTERS
        )

    # =========================================================
    # EXPLICIT MEMORY NORMALIZATION
    # =========================================================

    @classmethod
    def _normalize_explicit_memory(
        cls,
        text: str,
    ) -> str:
        clean = " ".join(
            text.strip().split()
        )

        for pattern in (
            cls.EXPLICIT_PATTERNS
        ):
            cleaned = re.sub(
                pattern,
                "",
                clean,
                count=1,
                flags=re.IGNORECASE,
            ).strip()

            if cleaned != clean:
                return cleaned

        return clean

    # =========================================================
    # LONG TERM SELF HEAL
    # =========================================================

    def _sanitize_long_term(
        self,
    ) -> None:
        cleaned_items = []
        seen = set()

        for item in (
            self.data["long_term"]
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            content = str(
                item.get(
                    "content",
                    "",
                )
            ).strip()

            if not content:
                continue

            # Une question ne doit jamais
            # devenir un souvenir.
            if self._looks_like_question(
                content
            ):
                continue

            kind = str(
                item.get(
                    "kind",
                    "memory",
                )
            )

            # Les anciennes mémoires explicites
            # sont converties en vrais faits.
            if kind == "explicit":
                content = (
                    self._normalize_explicit_memory(
                        content
                    )
                )

            if not content:
                continue

            key = content.lower()

            if key in seen:
                continue

            seen.add(
                key
            )

            cleaned_items.append(
                {
                    "kind": kind,
                    "content": content,
                    "at": item.get(
                        "at",
                        self._now(),
                    ),
                }
            )

        self.data[
            "long_term"
        ] = cleaned_items[-100:]

    # =========================================================
    # SESSION
    # =========================================================

    def add_session(
        self,
        role: str,
        content: str,
    ) -> None:
        content = (
            content.strip()
        )

        if not content:
            return

        self.data[
            "session"
        ].append(
            {
                "role": role,
                "content": content,
                "at": self._now(),
            }
        )

        self.data[
            "session"
        ] = (
            self.data[
                "session"
            ][-40:]
        )

        self._save()

    # =========================================================
    # LONG TERM
    # =========================================================

    def remember(
        self,
        text: str,
        *,
        kind: str = "memory",
    ) -> None:
        text = " ".join(
            text.strip().split()
        )

        if not text:
            return

        if self._looks_like_question(
            text
        ):
            return

        existing = [
            str(
                item.get(
                    "content",
                    "",
                )
            ).lower()
            for item
            in self.data[
                "long_term"
            ]
            if isinstance(
                item,
                dict,
            )
        ]

        if (
            text.lower()
            in existing
        ):
            return

        self.data[
            "long_term"
        ].append(
            {
                "kind": kind,
                "content": text,
                "at": self._now(),
            }
        )

        self.data[
            "long_term"
        ] = (
            self.data[
                "long_term"
            ][-100:]
        )

        self._save()

    # =========================================================
    # PROFILE
    # =========================================================

    def remember_profile(
        self,
        *,
        key: str,
        value: str,
        source: str,
    ) -> None:
        key = key.strip()
        value = value.strip()

        if (
            not key
            or not value
        ):
            return

        remaining = []

        for item in (
            self.data[
                "profile"
            ]
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            if (
                item.get("key")
                == key
            ):
                continue

            remaining.append(
                item
            )

        remaining.append(
            {
                "key": key,
                "value": value,
                "source": source,
                "at": self._now(),
            }
        )

        self.data[
            "profile"
        ] = remaining[-50:]

        self._save()

    # =========================================================
    # EXPLICIT MEMORY
    # =========================================================

    def _explicit_memory(
        self,
        text: str,
    ) -> bool:
        if self._looks_like_question(
            text
        ):
            return False

        clean = " ".join(
            text.strip().split()
        )

        for pattern in (
            self.EXPLICIT_PATTERNS
        ):
            if re.search(
                pattern,
                clean,
                flags=re.IGNORECASE,
            ):
                fact = (
                    self._normalize_explicit_memory(
                        clean
                    )
                )

                if fact:
                    self.remember(
                        fact,
                        kind="explicit",
                    )

                return True

        return False

    # =========================================================
    # AUTOMATIC PROFILE EXTRACTION
    # =========================================================

    def _extract_profile(
        self,
        text: str,
    ) -> None:
        clean = " ".join(
            text.strip().split()
        )

        if (
            not clean
            or self._looks_like_question(
                clean
            )
        ):
            return

        # -----------------------------------------------------
        # NAME
        # -----------------------------------------------------

        match = re.search(
            (
                r"^(?:je m'appelle|"
                r"je m’appelle|"
                r"mon prénom est|"
                r"mon prenom est)\s+"
                r"([A-Za-zÀ-ÿ'-]{2,40})\b"
            ),
            clean,
            flags=re.IGNORECASE,
        )

        if match:
            self.remember_profile(
                key="first_name",
                value=(
                    match.group(1)
                ),
                source=clean,
            )

        # -----------------------------------------------------
        # LOCATION
        # -----------------------------------------------------

        match = re.search(
            (
                r"^(?:j'habite|"
                r"j’habite|"
                r"je vis)\s+"
                r"(?:à|a)\s+"
                r"([^,.!?]{2,80})"
            ),
            clean,
            flags=re.IGNORECASE,
        )

        if match:
            self.remember_profile(
                key="location",
                value=(
                    match.group(1)
                    .strip()
                ),
                source=clean,
            )

        # -----------------------------------------------------
        # PREFERENCES
        # -----------------------------------------------------

        if re.search(
            r"^je préfère\s+.{2,120}$",
            clean,
            flags=re.IGNORECASE,
        ):
            self.remember(
                clean,
                kind="preference",
            )

        if re.search(
            r"^je prefere\s+.{2,120}$",
            clean,
            flags=re.IGNORECASE,
        ):
            self.remember(
                clean,
                kind="preference",
            )

        if re.search(
            r"^j'aime\s+.{2,120}$",
            clean,
            flags=re.IGNORECASE,
        ):
            self.remember(
                clean,
                kind="preference",
            )

    # =========================================================
    # AUTOMATIC MEMORY
    # =========================================================

    def maybe_remember(
        self,
        text: str,
    ) -> None:
        # Important :
        # on ne mémorise jamais automatiquement
        # une question.
        if self._looks_like_question(
            text
        ):
            return

        self._explicit_memory(
            text
        )

        self._extract_profile(
            text
        )

    # =========================================================
    # SESSION CONTEXT
    # =========================================================

    def session_context(
        self,
        limit: int = 12,
    ) -> str:
        lines = []

        for item in (
            self.data[
                "session"
            ][-limit:]
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            role = str(
                item.get(
                    "role",
                    "?",
                )
            )

            content = str(
                item.get(
                    "content",
                    "",
                )
            )

            lines.append(
                f"{role}: {content}"
            )

        return (
            "\n".join(lines)
            or "(vide)"
        )

    # =========================================================
    # PROFILE CONTEXT
    # =========================================================

    def profile_context(
        self,
    ) -> str:
        lines = []

        labels = {
            "first_name": (
                "Prénom"
            ),
            "location": (
                "Lieu de vie"
            ),
        }

        for item in (
            self.data[
                "profile"
            ]
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            key = str(
                item.get(
                    "key",
                    "",
                )
            )

            value = str(
                item.get(
                    "value",
                    "",
                )
            )

            if not value:
                continue

            label = labels.get(
                key,
                key,
            )

            lines.append(
                f"- {label} : {value}"
            )

        return (
            "\n".join(lines)
            or "(vide)"
        )

    # =========================================================
    # LONG TERM CONTEXT
    # =========================================================

    def long_term_context(
        self,
        limit: int = 20,
    ) -> str:
        lines = []

        for item in (
            self.data[
                "long_term"
            ][-limit:]
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            content = str(
                item.get(
                    "content",
                    "",
                )
            )

            if content:
                lines.append(
                    f"- {content}"
                )

        return (
            "\n".join(lines)
            or "(vide)"
        )

    # =========================================================
    # FULL CONTEXT
    # =========================================================

    def context(
        self,
    ) -> str:
        return (
            "PROFIL UTILISATEUR:\n"
            + self.profile_context()
            + "\n\n"
            + "MÉMOIRE LONGUE DURÉE:\n"
            + self.long_term_context()
            + "\n\n"
            + "CONVERSATION RÉCENTE:\n"
            + self.session_context()
        )

    def format(
        self,
    ) -> str:
        return self.context()