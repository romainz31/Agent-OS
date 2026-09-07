from __future__ import annotations

from datetime import datetime, timezone

from agentos.config import DATA_DIR
from agentos.storage import JsonStore


class Memory:

    def __init__(
        self,
    ) -> None:

        self.store = JsonStore(
            DATA_DIR / "memory.json",
            {
                "session": [],
                "long_term": [],
            },
        )

        loaded = self.store.load()

        # =====================================================
        # SELF-HEAL
        #
        # Si memory.json est vide, ancien, corrompu
        # ou contient [] au lieu d'un dictionnaire,
        # Agent-OS repart sur une structure valide.
        # =====================================================

        if not isinstance(
            loaded,
            dict,
        ):

            loaded = {
                "session": [],
                "long_term": [],
            }

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
    # SESSION MEMORY
    # =========================================================

    def add_session(
        self,
        role: str,
        content: str,
    ) -> None:

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
        ] = self.data[
            "session"
        ][-20:]

        self.store.save(
            self.data
        )

    # =========================================================
    # LONG TERM MEMORY
    # =========================================================

    def remember(
        self,
        text: str,
    ) -> None:

        text = text.strip()

        if not text:

            return

        existing = [
            item.get(
                "content"
            )
            for item
            in self.data[
                "long_term"
            ]
            if isinstance(
                item,
                dict,
            )
        ]

        if text in existing:

            return

        self.data[
            "long_term"
        ].append(
            {
                "content": text,
                "at": self._now(),
            }
        )

        self.store.save(
            self.data
        )

    # =========================================================
    # AUTOMATIC MEMORY
    # =========================================================

    def maybe_remember(
        self,
        text: str,
    ) -> None:

        markers = (
            "souviens-toi",
            "souviens toi",
            "retiens que",
            "mémorise",
            "memorise",
            "je préfère",
            "je prefere",
            "à l'avenir",
            "a l'avenir",
        )

        lower = text.lower()

        if any(
            marker in lower
            for marker
            in markers
        ):

            self.remember(
                text
            )

    # =========================================================
    # CONTEXT
    # =========================================================

    def context(
        self,
    ) -> str:

        long_term = "\n".join(
            (
                "- "
                + str(
                    item.get(
                        "content",
                        "",
                    )
                )
            )
            for item
            in self.data[
                "long_term"
            ][-15:]
            if isinstance(
                item,
                dict,
            )
        )

        if not long_term:

            long_term = "(vide)"

        session = "\n".join(
            (
                str(
                    item.get(
                        "role",
                        "?",
                    )
                )
                + ": "
                + str(
                    item.get(
                        "content",
                        "",
                    )
                )
            )
            for item
            in self.data[
                "session"
            ][-8:]
            if isinstance(
                item,
                dict,
            )
        )

        if not session:

            session = "(vide)"

        return (
            "MÉMOIRE LONGUE DURÉE:\n"
            + long_term
            + "\n\n"
            + "SESSION RÉCENTE:\n"
            + session
        )

    # =========================================================
    # DISPLAY
    # =========================================================

    def format(
        self,
    ) -> str:

        return self.context()