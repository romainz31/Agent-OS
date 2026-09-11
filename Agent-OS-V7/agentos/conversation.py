from __future__ import annotations

import re
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore


class ConversationTracker:
    """Fil conversationnel persistant de Paul.

    La mémoire relationnelle répond à « ce que Paul sait sur l'utilisateur ».
    Ce composant répond à un autre besoin : « de quoi sommes-nous en train de
    parler et qu'est-ce qui vient d'être dit ? ».

    Le fil actif survit aux redémarrages. Après une longue inactivité, il est
    archivé automatiquement et un nouveau fil est créé. Un oubli explicite peut
    aussi purger des valeurs du fil afin qu'une donnée oubliée ne soit pas
    réintroduite par le contexte conversationnel.
    """

    SCHEMA_VERSION = "1"
    MAX_MESSAGES = 80
    MAX_HISTORY = 24
    BOOTSTRAP_LIMIT = 24
    IDLE_ROTATION_HOURS = 12.0

    TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "Agent-OS / développement",
            (
                "agent-os", "agent os", "manager", "mission", "missions",
                "workspace/", "python", "code", "developer", "tester",
                "researcher", "planner", "v4.8", "v48", "paul",
            ),
        ),
        (
            "Aquariophilie",
            (
                "aquarium", "aquariophilie", "poisson", "rasbora", "tetra",
                "tétra", "crevette", "neocaridina", "neritina",
            ),
        ),
        (
            "Home Assistant / domotique",
            (
                "home assistant", "domotique", "zigbee", "zha", "mqtt",
                "frigate", "mushroom", "capteur",
            ),
        ),
        (
            "Travail / maintenance",
            (
                "maintenance", "frigoriste", "froid", "clim", "leclerc",
                "danfoss", "compresseur",
            ),
        ),
        (
            "Maison / jardin",
            (
                "maison", "jardin", "potager", "terrasse", "volet",
                "arrosage", "panneau solaire",
            ),
        ),
    )

    FOLLOW_UP_PREFIXES = (
        "oui", "non", "ok", "d'accord", "daccord", "du coup", "donc",
        "et ", "mais ", "pourquoi", "comment ca", "comment ça", "ca ",
        "ça ", "celui", "celle", "ceux", "elles", "ils", "lui ",
    )

    TRANSIENT_STATE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "rest_energy",
            (
                r"\bcreve(?:e)?\b", r"\bfatigue(?:e)?\b",
                r"\bfatigu(?:e|ee|er)\b", r"\bbesoin de repos\b",
                r"\bme reposer\b", r"\bvais me reposer\b",
                r"\brepose(?:e)?\b", r"\bplus besoin de repos\b",
                r"\bmanque d energie\b", r"\bplein d energie\b",
                r"\bj ai de l energie\b",
            ),
        ),
        (
            "stress",
            (
                r"\bstresse(?:e)?\b", r"\bstress\b",
                r"\banxieux\b", r"\banxieuse\b",
                r"\btendu(?:e)?\b",
            ),
        ),
        (
            "motivation",
            (
                r"\bmotive(?:e)?\b", r"\bmotivation\b",
                r"\bpas envie de bosser\b", r"\benvie de bosser\b",
            ),
        ),
        (
            "mood",
            (
                r"\bca va mieux\b", r"\bca va mal\b",
                r"\bmoral\b", r"\bhumeur\b",
            ),
        ),
    )

    RESUME_PATTERNS = (
        r"^on en etait ou$",
        r"^on en etais ou$",
        r"^ou en etait on$",
        r"^ou en etions nous$",
        r"^de quoi on parlait$",
        r"^de quoi parlait on$",
        r"^on parlait de quoi$",
        r"^rappelle moi ou on en etait$",
        r"^reprends la conversation$",
    )

    def __init__(
        self,
        *,
        idle_rotation_hours: float | None = None,
    ) -> None:
        self.store = JsonStore(
            DATA_DIR / "conversations.json",
            {
                "schema_version": self.SCHEMA_VERSION,
                "current": None,
                "history": [],
            },
        )
        self.lock = threading.RLock()
        self.idle_rotation_hours = float(
            idle_rotation_hours
            if idle_rotation_hours is not None
            else self.IDLE_ROTATION_HOURS
        )

        loaded = self.store.load()
        self.data = (
            loaded
            if isinstance(loaded, dict)
            else {}
        )
        self.data.setdefault("schema_version", self.SCHEMA_VERSION)
        self.data.setdefault("current", None)
        self.data.setdefault("history", [])
        if not isinstance(self.data.get("history"), list):
            self.data["history"] = []
        self._normalize_current()
        self._save()

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _now_iso(cls) -> str:
        return cls._now().isoformat()

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _ascii(text: str) -> str:
        value = unicodedata.normalize(
            "NFKD",
            str(text or ""),
        )
        return "".join(
            char
            for char in value
            if not unicodedata.combining(char)
        ).lower()

    @staticmethod
    def _clean(text: Any) -> str:
        return " ".join(str(text or "").strip().split())

    @classmethod
    def sanitize_assistant_context(cls, text: str) -> str:
        """Retire du contexte les relances génériques produites par Paul.

        On conserve la réponse brute dans l'historique, mais on n'injecte plus
        au LLM des phrases de clôture comme « n'hésite pas » ou des rappels
        génériques de bien-être. Cela évite que le modèle imite ses propres
        tics de réponse au tour suivant.
        """
        clean = str(text or "").strip()
        if not clean:
            return ""

        parts = re.split(r"(?<=[.!?])\s+|\n+", clean)
        blocked = (
            "n hesite pas",
            "si tu as besoin",
            "si tu as d autres questions",
            "si tu veux approfondir",
            "si tu veux en savoir plus",
            "fais moi savoir",
            "ton bien etre",
            "ton confort",
            "ton bien-etre",
            "ton bien être",
            "reviens quand tu es pret",
            "reviens quand tu seras pret",
        )

        kept: list[str] = []
        for part in parts:
            part = cls._clean(part)
            if not part:
                continue
            normalized = cls._normalized_words(part)
            if any(marker in normalized for marker in blocked):
                continue
            kept.append(part)

        return " ".join(kept).strip()

    @classmethod
    def _new_thread_data(
        cls,
        *,
        topic: str = "Conversation générale",
    ) -> dict[str, Any]:
        now = cls._now_iso()
        return {
            "id": "conversation_" + uuid.uuid4().hex[:10],
            "topic": topic,
            "summary": "",
            "started_at": now,
            "updated_at": now,
            "messages": [],
        }

    def _normalize_current(self) -> None:
        current = self.data.get("current")
        if not isinstance(current, dict):
            self.data["current"] = self._new_thread_data()
            return
        current.setdefault("id", "conversation_" + uuid.uuid4().hex[:10])
        current.setdefault("topic", "Conversation générale")
        current.setdefault("summary", "")
        current.setdefault("started_at", self._now_iso())
        current.setdefault("updated_at", current["started_at"])
        current.setdefault("messages", [])
        if not isinstance(current.get("messages"), list):
            current["messages"] = []
        current["messages"] = [
            item
            for item in current["messages"][-self.MAX_MESSAGES:]
            if isinstance(item, dict)
        ]

    def _save(self) -> None:
        self.data["schema_version"] = self.SCHEMA_VERSION
        self.data["history"] = [
            item
            for item in self.data.get("history", [])[-self.MAX_HISTORY:]
            if isinstance(item, dict)
        ]
        self.store.save(self.data)

    def _current(self) -> dict[str, Any]:
        self._normalize_current()
        return self.data["current"]

    def _archive_current(self) -> None:
        current = self._current()
        if not current.get("messages"):
            return
        archived = dict(current)
        archived["ended_at"] = self._now_iso()
        self.data.setdefault("history", []).append(archived)
        self.data["history"] = self.data["history"][-self.MAX_HISTORY:]

    def _rotate_if_idle(self) -> None:
        current = self._current()
        if not current.get("messages"):
            return
        updated = self._parse_dt(current.get("updated_at"))
        if updated is None:
            return
        age = (
            self._now() - updated.astimezone(timezone.utc)
        ).total_seconds() / 3600.0
        if age < self.idle_rotation_hours:
            return
        self._archive_current()
        self.data["current"] = self._new_thread_data()
        self._save()

    @classmethod
    def _normalized_words(cls, text: str) -> str:
        normalized = cls._ascii(cls._clean(text))
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return " ".join(normalized.split())

    @classmethod
    def transient_state_kind(cls, message: str) -> str | None:
        normalized = cls._normalized_words(message)
        if not normalized:
            return None
        for kind, patterns in cls.TRANSIENT_STATE_PATTERNS:
            for pattern in patterns:
                if re.search(pattern, normalized):
                    return kind
        return None

    @classmethod
    def is_resume_query(cls, message: str) -> bool:
        normalized = cls._normalized_words(message)
        if not normalized:
            return False
        return any(
            re.fullmatch(pattern, normalized) is not None
            for pattern in cls.RESUME_PATTERNS
        )

    @classmethod
    def _explicit_discussion_topic(cls, message: str) -> str | None:
        clean = cls._clean(message).strip(" ?!.,;:")
        normalized = cls._ascii(clean)
        patterns = (
            r"^(?:on\s+)?parl(?:ait|ais|e|ons)\s+(?:de|du|des|d')\s*(.+)$",
            r"^(?:on\s+)?discut(?:ait|ais|e|ons)\s+(?:de|du|des|d')\s*(.+)$",
            r"^(?:a propos de|au sujet de)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            # On récupère la même portion dans la chaîne originale autant que
            # possible ; à défaut, la version normalisée reste lisible.
            raw_match = re.search(
                r"(?:de|du|des|d['’])\s+(.+)$",
                clean,
                flags=re.IGNORECASE,
            )
            topic = (raw_match.group(1) if raw_match else match.group(1)).strip(" ?!.,;:")
            if topic:
                return topic[:72] + ("…" if len(topic) > 72 else "")
        return None

    @staticmethod
    def _message_kind(item: dict[str, Any]) -> str:
        return str(item.get("kind", "")).strip().lower()

    @classmethod
    def _is_substantive_item(cls, item: dict[str, Any]) -> bool:
        if not isinstance(item, dict) or item.get("role") != "user":
            return False
        if cls._message_kind(item) == "transient_state":
            return False
        content = cls._clean(item.get("content", ""))
        if not content or cls.is_resume_query(content):
            return False
        normalized = cls._normalized_words(content)
        if normalized in {
            "conversation status", "conversation history",
            "nouvelle conversation", "manager status",
            "manager decisions",
        }:
            return False
        return True

    # =========================================================
    # TOPIC / SUMMARY
    # =========================================================

    def infer_topic(self, message: str) -> str | None:
        clean = self._clean(message)
        if not clean:
            return None

        # Un état temporaire ne devient jamais le sujet du fil.
        if self.transient_state_kind(clean) is not None:
            return None

        if self.is_resume_query(clean):
            return None

        explicit = self._explicit_discussion_topic(clean)
        if explicit:
            return explicit

        normalized = self._ascii(clean)

        for topic, markers in self.TOPICS:
            if any(self._ascii(marker) in normalized for marker in markers):
                return topic

        if any(normalized.startswith(self._ascii(prefix)) for prefix in self.FOLLOW_UP_PREFIXES):
            return None

        words = re.findall(r"[a-zA-ZÀ-ÿ0-9_-]+", clean)
        if len(words) <= 4:
            return None

        return clean[:72] + ("…" if len(clean) > 72 else "")

    def _rebuild_summary(self, thread: dict[str, Any]) -> None:
        user_turns = []
        for item in thread.get("messages", []):
            if not self._is_substantive_item(item):
                continue
            content = self._clean(item.get("content", ""))
            if len(content) > 140:
                content = content[:137].rstrip() + "..."
            user_turns.append(content)

        recent = user_turns[-6:]
        thread["summary"] = (
            " → ".join(recent)
            if recent
            else ""
        )

    # =========================================================
    # PERSISTENT THREAD
    # =========================================================

    def bootstrap_from_session(
        self,
        items: list[dict[str, Any]] | None,
    ) -> bool:
        """Initialise le premier fil depuis l'ancienne session V4.7.

        Cette migration n'a lieu que si le nouveau tracker est vide.
        """
        with self.lock:
            current = self._current()
            if current.get("messages"):
                return False

            selected: list[dict[str, Any]] = []
            for item in list(items or [])[-self.BOOTSTRAP_LIMIT:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "")).strip().lower()
                if role not in {"user", "assistant"}:
                    continue
                content = self._clean(item.get("content", ""))
                if not content:
                    continue
                selected.append({
                    "role": role,
                    "content": content,
                    "at": str(item.get("at") or self._now_iso()),
                })

            if not selected:
                return False

            current["messages"] = selected[-self.MAX_MESSAGES:]
            current["started_at"] = str(
                selected[0].get("at") or self._now_iso()
            )
            current["updated_at"] = str(
                selected[-1].get("at") or self._now_iso()
            )

            for item in reversed(selected):
                if item.get("role") == "user":
                    topic = self.infer_topic(str(item.get("content", "")))
                    if topic:
                        current["topic"] = topic
                        break

            self._rebuild_summary(current)
            self._save()
            return True

    def add_exchange(
        self,
        user_message: str,
        assistant_message: str,
    ) -> None:
        user_message = self._clean(user_message)
        assistant_message = self._clean(assistant_message)
        if not user_message and not assistant_message:
            return

        with self.lock:
            self._rotate_if_idle()
            current = self._current()
            now = self._now_iso()
            state_kind = self.transient_state_kind(user_message)

            common_meta: dict[str, Any] = {}
            if state_kind is not None:
                common_meta = {
                    "kind": "transient_state",
                    "state_kind": state_kind,
                }

            if user_message:
                current["messages"].append({
                    "role": "user",
                    "content": user_message,
                    "at": now,
                    **common_meta,
                })

            if assistant_message:
                current["messages"].append({
                    "role": "assistant",
                    "content": assistant_message,
                    "at": self._now_iso(),
                    **common_meta,
                })

            current["messages"] = current["messages"][-self.MAX_MESSAGES:]
            current["updated_at"] = self._now_iso()

            # Les états temporaires mettent à jour le contexte humain mais ne
            # remplacent jamais le sujet substantiel de la discussion.
            if state_kind is None:
                topic = self.infer_topic(user_message)
                if topic:
                    current["topic"] = topic

            self._rebuild_summary(current)
            self._save()

    def new_thread(
        self,
        *,
        topic: str = "Conversation générale",
    ) -> dict[str, Any]:
        with self.lock:
            self._archive_current()
            self.data["current"] = self._new_thread_data(topic=topic)
            self._save()
            return dict(self.data["current"])

    def forget_values(
        self,
        values: list[str] | tuple[str, ...] | set[str],
    ) -> int:
        normalized_values = [
            self._ascii(value)
            for value in values
            if len(self._clean(value)) >= 2
        ]
        if not normalized_values:
            return 0

        removed = 0
        with self.lock:
            threads = [self._current()] + [
                item
                for item in self.data.get("history", [])
                if isinstance(item, dict)
            ]

            for thread in threads:
                topic = self._clean(thread.get("topic", ""))
                normalized_topic = self._ascii(topic)
                if topic and any(
                    value and value in normalized_topic
                    for value in normalized_values
                ):
                    thread["topic"] = "Conversation générale"

                kept = []
                for item in thread.get("messages", []):
                    if not isinstance(item, dict):
                        continue
                    content = self._clean(item.get("content", ""))
                    normalized = self._ascii(content)
                    if content and any(
                        value and value in normalized
                        for value in normalized_values
                    ):
                        removed += 1
                        continue
                    kept.append(item)
                thread["messages"] = kept[-self.MAX_MESSAGES:]
                self._rebuild_summary(thread)

            self._save()

        return removed

    # =========================================================
    # CONTEXT / COMMANDS
    # =========================================================

    def _latest_substantive_user_message(
        self,
        thread: dict[str, Any],
    ) -> str | None:
        for item in reversed(thread.get("messages", [])):
            if self._is_substantive_item(item):
                content = self._clean(item.get("content", ""))
                if content:
                    return content
        return None

    def resume_response(self) -> str:
        with self.lock:
            self._rotate_if_idle()
            current = self._current()
            topic = self._clean(current.get("topic", ""))
            last = self._latest_substantive_user_message(current)

        if topic and topic != "Conversation générale":
            if topic.startswith(("l'", "L'", "le ", "Le ", "la ", "La ", "les ", "Les ")):
                return f"On parlait de {topic}."
            return f"On en était à : {topic}."

        if last:
            return "On en était là : " + last

        return "Je n'ai pas assez de contexte actif pour reprendre précisément le sujet."


    # =========================================================
    # USER-SOURCE CONTEXT V6.2.2
    # =========================================================

    def user_context_for(
        self,
        query: str = "",
        *,
        limit: int = 10,
    ) -> str:
        """Contexte composé uniquement des déclarations de l'utilisateur.

        Ce flux sert aux questions de mémoire personnelle. Les anciennes
        réponses de Paul restent dans le fil conversationnel normal mais ne
        peuvent plus devenir des preuves sur la vie de l'utilisateur.
        """
        with self.lock:
            self._rotate_if_idle()
            current = self._current()
            query_state = self.transient_state_kind(query)

            source = [
                item
                for item in current.get("messages", [])
                if (
                    isinstance(item, dict)
                    and str(item.get("role", "")).strip().lower() == "user"
                )
            ]

            if query_state is None:
                source = [
                    item
                    for item in source
                    if self._message_kind(item) != "transient_state"
                ]
            else:
                source = [
                    item
                    for item in source
                    if (
                        self._message_kind(item) != "transient_state"
                        or str(item.get("state_kind", "")) == query_state
                    )
                ]

            messages = source[-max(1, int(limit)):]

            if not messages:
                return "(aucune déclaration utilisateur dans le fil actif)"

            lines = [
                "SOURCE UTILISATEUR UNIQUEMENT",
                "Les lignes ci-dessous sont des déclarations de l'utilisateur, "
                "pas des affirmations de Paul.",
                "Déclarations récentes :",
            ]

            for item in messages:
                content = self._clean(item.get("content", ""))
                if content:
                    lines.append(f"user: {content}")

            return "\n".join(lines)

    def context_for(
        self,
        query: str = "",
        *,
        limit: int = 10,
    ) -> str:
        with self.lock:
            self._rotate_if_idle()
            current = self._current()
            query_state = self.transient_state_kind(query)

            source = [
                item
                for item in current.get("messages", [])
                if isinstance(item, dict)
            ]

            # Fatigue, repos, stress, motivation et humeur ne sont injectés
            # que lorsque la question actuelle porte elle-même sur cet état.
            # Cela empêche un ancien « repose-toi » de contaminer un autre sujet.
            if query_state is None:
                source = [
                    item
                    for item in source
                    if self._message_kind(item) != "transient_state"
                ]
            else:
                source = [
                    item
                    for item in source
                    if (
                        self._message_kind(item) != "transient_state"
                        or str(item.get("state_kind", "")) == query_state
                    )
                ]

            messages = source[-max(1, int(limit)):]

            if not messages:
                return "(aucun échange dans le fil actif)"

            lines = [
                f"Sujet courant : {current.get('topic') or 'Conversation générale'}",
            ]
            summary = self._clean(current.get("summary", ""))
            if summary:
                lines.append("Résumé du fil : " + summary)
            lines.append("Derniers échanges :")
            for item in messages:
                role = str(item.get("role", "?"))
                content = self._clean(item.get("content", ""))
                if role == "assistant":
                    content = self.sanitize_assistant_context(content)
                if content:
                    lines.append(f"{role}: {content}")
            return "\n".join(lines)

    @staticmethod
    def _display_dt(value: Any) -> str:
        parsed = ConversationTracker._parse_dt(value)
        if parsed is None:
            return "inconnue"
        return parsed.astimezone().strftime("%d/%m/%Y %H:%M")

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self._rotate_if_idle()
            current = self._current()
            return {
                "id": current.get("id"),
                "topic": current.get("topic"),
                "summary": current.get("summary"),
                "started_at": current.get("started_at"),
                "updated_at": current.get("updated_at"),
                "messages": len(current.get("messages", [])),
                "archived_threads": len(self.data.get("history", [])),
            }

    def status_summary(self) -> str:
        snapshot = self.snapshot()
        return "\n".join([
            "FIL DE CONVERSATION",
            f"Sujet : {snapshot.get('topic') or 'Conversation générale'}",
            f"Messages conservés : {snapshot.get('messages', 0)}",
            f"Début : {self._display_dt(snapshot.get('started_at'))}",
            f"Dernière activité : {self._display_dt(snapshot.get('updated_at'))}",
            f"Fils archivés : {snapshot.get('archived_threads', 0)}",
        ])

    def history_summary(self, limit: int = 8) -> str:
        with self.lock:
            items = [
                item
                for item in self.data.get("history", [])[-max(1, int(limit)):]
                if isinstance(item, dict)
            ]
        if not items:
            return "Aucun ancien fil de conversation archivé."

        lines = ["ANCIENS FILS DE CONVERSATION"]
        for item in reversed(items):
            lines.append(
                "- "
                + self._display_dt(item.get("updated_at"))
                + " | "
                + str(item.get("topic") or "Conversation générale")
                + " | "
                + str(len(item.get("messages", [])))
                + " message(s)"
            )
        return "\n".join(lines)
