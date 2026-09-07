from __future__ import annotations

import re

from datetime import (
    datetime,
    timezone,
)

from agentos.config import (
    DATA_DIR,
)

from agentos.storage import (
    JsonStore,
)


class Memory:

    def __init__(
        self,
    ) -> None:

        self.store = JsonStore(
            DATA_DIR / "memory.json",
            {
                "session": [],
                "long_term": [],
                "profile": [],
            },
        )

        loaded = (
            self.store.load()
        )

        # =====================================================
        # SELF HEAL
        # =====================================================

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

        self.store.save(
            self.data
        )

    # =========================================================
    # TIME
    # =========================================================

    @staticmethod
    def _now() -> str:

        return datetime.now(
            timezone.utc
        ).isoformat()

    # =========================================================
    # SAVE
    # =========================================================

    def _save(
        self,
    ) -> None:

        self.store.save(
            self.data
        )

    # =========================================================
    # SESSION
    # =========================================================

    def add_session(
        self,
        role: str,
        content: str,
    ) -> None:

        content = content.strip()

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

        # On garde davantage de contexte
        # qu'en V3.3.
        self.data[
            "session"
        ] = self.data[
            "session"
        ][-40:]

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

        text = text.strip()

        if not text:

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

        if text.lower() in existing:

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
        ] = self.data[
            "long_term"
        ][-100:]

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

        # Une clé de profil remplace
        # son ancienne valeur.
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

        markers = (
            "souviens-toi",
            "souviens toi",
            "retiens que",
            "mémorise",
            "memorise",
            "garde en mémoire",
            "garde en memoire",
            "à l'avenir",
            "a l'avenir",
        )

        lower = (
            text.lower()
        )

        if any(
            marker in lower
            for marker
            in markers
        ):

            self.remember(
                text,
                kind="explicit",
            )

            return True

        return False

    # =========================================================
    # SIMPLE PROFILE EXTRACTION
    # =========================================================

    def _extract_profile(
        self,
        text: str,
    ) -> None:

        clean = " ".join(
            text.strip().split()
        )

        # -----------------------------------------------------
        # NAME
        # -----------------------------------------------------

        match = re.search(
            (
                r"\b(?:je m'appelle|"
                r"je m’appelle|"
                r"mon prénom est|"
                r"mon prenom est)\s+"
                r"([A-Za-zÀ-ÿ'-]{2,40})"
            ),
            clean,
            flags=re.IGNORECASE,
        )

        if match:

            self.remember_profile(
                key="first_name",
                value=match.group(1),
                source=clean,
            )

        # -----------------------------------------------------
        # LOCATION
        # -----------------------------------------------------

        match = re.search(
            (
                r"\b(?:j'habite|"
                r"j’habite|"
                r"je vis)\s+(?:à|a)\s+"
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
        # PREFERENCE
        # -----------------------------------------------------

        match = re.search(
            (
                r"\b(?:je préfère|"
                r"je prefere)\s+"
                r"(.{2,120})"
            ),
            clean,
            flags=re.IGNORECASE,
        )

        if match:

            self.remember(
                clean,
                kind="preference",
            )

        # -----------------------------------------------------
        # LIKES
        # -----------------------------------------------------

        match = re.search(
            r"\bj'aime\s+(.{2,120})",
            clean,
            flags=re.IGNORECASE,
        )

        if match:

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
            "first_name": "Prénom",
            "location": "Lieu de vie",
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

            label = (
                labels.get(
                    key,
                    key,
                )
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

    # =========================================================
    # DISPLAY
    # =========================================================

    def format(
        self,
    ) -> str:

        return self.context()