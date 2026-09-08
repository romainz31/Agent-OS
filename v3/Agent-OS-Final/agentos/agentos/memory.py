from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore


class Memory:
    """
    Agent-OS V4.6.2 — Personal / Operational Memory + Emotional Context.

    Les données sont séparées en plusieurs couches :
    - session      : conversation récente ;
    - profile      : identité et faits structurés stables ;
    - long_term    : préférences, habitudes et faits durables ;
    - episodic     : événements PERSONNELS datés ;
    - operational  : historique Agent-OS (missions, erreurs, décisions) ;
    - working      : contexte opérationnel temporaire encore actif ;
    - emotional    : état émotionnel courant + observations récentes.

    Le fichier reste compatible avec les versions V4.5 / V4.5.1 et migre
    automatiquement les anciens événements de mission hors de la mémoire
    personnelle.
    """

    SCHEMA_VERSION = "4.6.2"

    SESSION_LIMIT = 60
    LONG_TERM_LIMIT = 250
    PROFILE_LIMIT = 100
    EPISODIC_LIMIT = 200
    OPERATIONAL_LIMIT = 300
    WORKING_LIMIT = 100
    EMOTIONAL_HISTORY_LIMIT = 120

    QUESTION_STARTERS = (
        "quel ", "quelle ", "quels ", "quelles ", "qui ", "que ",
        "quoi ", "où ", "ou ", "quand ", "comment ", "combien ",
        "pourquoi ", "est-ce ", "est ce ", "peux-tu ", "peux tu ",
        "pourrais-tu ", "pourrais tu ", "sais-tu ", "sais tu ",
        "tu sais ", "tu te souviens ", "rappelle-moi ", "rappelle moi ",
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

    TEMPORAL_MARKERS = (
        "aujourd'hui", "aujourd’hui", "ce matin", "cet après-midi",
        "cet apres-midi", "ce soir", "cette nuit", "hier", "avant-hier",
        "avant hier", "demain", "cette semaine", "ce week-end", "ce weekend",
        "en ce moment", "actuellement",
    )

    # Une amélioration globale ne signifie pas automatiquement que l'énergie
    # est haute, le stress nul, etc. En revanche, elle rend obsolètes les
    # anciens signaux négatifs qui n'ont pas été reconfirmés dans le nouveau
    # message. On les retire donc plutôt que de continuer à les présenter
    # comme l'état actuel de l'utilisateur.
    GLOBAL_IMPROVEMENT_PATTERNS = (
        r"\b(?:finalement\s+)?ca va mieux\b",
        r"\bje vais mieux\b",
        r"\bca va beaucoup mieux\b",
        r"\bje me sens mieux\b",
    )

    NEGATIVE_EMOTIONAL_VALUES = {
        "energy": {"low"},
        "motivation": {"low"},
        "stress": {"high"},
        "frustration": {"high"},
        "mood": {"negative"},
    }

    OPERATIONAL_KINDS = {
        "mission", "mission_created", "mission_completed", "mission_failed",
        "mission_cancelled", "mission_rejected", "mission_paused",
        "mission_resumed", "approval", "approval_required", "repair",
        "task", "task_completed", "task_failed",
    }

    # Groupes simples pour améliorer la récupération sémantique sans dépendre
    # du LLM. Si un terme du groupe est dans la question, les autres termes
    # deviennent des synonymes de recherche.
    TOPIC_GROUPS = (
        {
            "aquariophilie", "aquarium", "aquariums", "poisson", "poissons",
            "rasbora", "brigittae", "crevette", "crevettes", "bac", "bacs",
            "nano", "plante", "plantes", "plante", "plantes",
        },
        {
            "agentos", "agent-os", "agent", "agents", "manager", "mission",
            "missions", "worker", "workers", "developer", "researcher",
            "tester", "planner", "code", "python", "programmation",
        },
        {
            "domotique", "homeassistant", "home-assistant", "zigbee", "zha",
            "zigbee2mqtt", "mqtt", "capteur", "capteurs", "automation",
            "automatisation", "dashboard",
        },
        {
            "cuisine", "manger", "repas", "recette", "recettes", "aliment",
            "aliments", "nourriture",
        },
    )

    STOPWORDS = {
        "alors", "avec", "avoir", "dans", "depuis", "des", "elle", "elles",
        "encore", "est", "fait", "faire", "fais", "il", "ils", "j'ai", "je",
        "les", "leur", "leurs", "mais", "mes", "moi", "mon", "ma", "ne",
        "nous", "notre", "nos", "pas", "pour", "que", "qui", "quoi", "sans",
        "ses", "son", "sur", "tes", "toi", "ton", "tous", "tout", "tres",
        "tu", "une", "vos", "votre", "vous", "ca", "c'est", "d'un", "d'une",
        "de", "du", "et", "en", "la", "le", "un", "a", "au", "aux",
    }

    EMOTIONAL_PATTERNS: dict[str, tuple[tuple[str, str, float], ...]] = {
        "energy": (
            ("low", r"\b(?:creve|crevee|fatigue|fatiguee|epuise|epuisee|claque|claquee|ko|hs)\b", 0.92),
            ("low", r"\b(?:pas|plus)\s+d['’ ]?energie\b", 0.95),
            ("high", r"\b(?:en forme|plein d['’ ]?energie|pleine d['’ ]?energie|repose|reposee|energique)\b", 0.90),
        ),
        "motivation": (
            ("low", r"\b(?:(?:pas|pas trop) envie de bosser|(?:pas|pas trop) envie de travailler|aucune motivation|demotive|demotivee|pas motive|pas motivee)\b", 0.94),
            ("high", r"\b(?:je suis motive|je suis motivee|bien motive|bien motivee|j['’ ]?ai envie d['’ ]?avancer|chaud pour avancer|pret a bosser|prete a bosser|on attaque)\b", 0.90),
        ),
        "stress": (
            ("high", r"\b(?:stresse|stressee|anxieux|anxieuse|sous pression|tendu|tendue|deborde|debordee)\b", 0.90),
            ("low", r"\b(?:detendu|detendue|serein|sereine|relax|calme)\b", 0.82),
        ),
        "frustration": (
            ("high", r"\b(?:frustre|frustree|enerve|enervee|agace|agacee|saoule|saoulee|marre|blas[eé])\b", 0.90),
            ("low", r"\b(?:plus frustre|plus frustree|ca va mieux maintenant)\b", 0.75),
        ),
        "mood": (
            ("positive", r"\b(?:content|contente|heureux|heureuse|de bonne humeur|ca va super|ca va beaucoup mieux|ca va mieux|je vais bien)\b", 0.86),
            ("negative", r"\b(?:triste|de mauvaise humeur|ca va mal|ca va pas|moral bas|moral a zero)\b", 0.88),
        ),
    }

    EMOTIONAL_LABELS = {
        "energy": ("Énergie", {"low": "basse", "high": "haute"}),
        "motivation": ("Motivation", {"low": "basse", "high": "haute"}),
        "stress": ("Stress", {"low": "bas", "high": "élevé"}),
        "frustration": ("Frustration", {"low": "basse", "high": "élevée"}),
        "mood": ("Humeur", {"positive": "positive", "negative": "négative"}),
    }

    def __init__(self) -> None:
        self.store = JsonStore(
            DATA_DIR / "memory.json",
            self._default_data(),
        )
        loaded = self.store.load()
        self.data = self._migrate(loaded)
        self._sanitize_all()
        self._save()

    # =========================================================
    # BASIC HELPERS
    # =========================================================

    @classmethod
    def _default_data(cls) -> dict[str, Any]:
        now = cls._now()
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "session": [],
            "long_term": [],
            "profile": [],
            "episodic": [],
            "operational": [],
            "working": [],
            "emotional": {
                "current": {},
                "history": [],
            },
            "meta": {
                "created_at": now,
                "updated_at": now,
            },
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clean_text(text: Any) -> str:
        return " ".join(str(text).strip().split())

    @staticmethod
    def _key(text: Any) -> str:
        return " ".join(str(text).lower().strip().split()).rstrip(" .!?,;:")

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _ascii(text: Any) -> str:
        normalized = unicodedata.normalize("NFKD", str(text).lower())
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result

    def _save(self) -> None:
        meta = self.data.setdefault("meta", {})
        meta["updated_at"] = self._now()
        self.data["schema_version"] = self.SCHEMA_VERSION
        self.store.save(self.data)

    # =========================================================
    # MIGRATION / SANITIZE
    # =========================================================

    @classmethod
    def _looks_like_question(cls, text: str) -> bool:
        clean = cls._clean_text(text)
        if not clean:
            return False
        lower = clean.lower()
        if clean.endswith("?"):
            return True
        return any(lower.startswith(starter) for starter in cls.QUESTION_STARTERS)

    @classmethod
    def _normalize_explicit_memory(cls, text: str) -> str:
        clean = cls._clean_text(text)
        for pattern in cls.EXPLICIT_PATTERNS:
            cleaned = re.sub(pattern, "", clean, count=1, flags=re.IGNORECASE).strip()
            if cleaned != clean:
                return cleaned
        return clean

    @classmethod
    def _looks_operational_text(cls, text: str) -> bool:
        clean = cls._clean_text(text)
        lower = cls._ascii(clean)
        if not clean:
            return False
        if re.search(r"\bM-\d{1,6}\b", clean, flags=re.IGNORECASE):
            return True
        if re.search(r"\bworkspace[/\\][^\s]+", clean, flags=re.IGNORECASE):
            return True
        if any(marker in lower for marker in (
            "mission terminee", "mission echouee", "mission annulee",
            "mission refusee", "attend ton autorisation", "developer",
            "researcher", "tester", "ai_worker", "task_",
        )):
            return True
        return False

    @classmethod
    def _is_operational_entry(cls, item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        kind = cls._clean_text(item.get("kind", "")).lower()
        source = cls._clean_text(item.get("source", "")).lower()
        content = cls._clean_text(item.get("content", ""))
        return (
            source == "agentos"
            or kind in cls.OPERATIONAL_KINDS
            or kind.startswith("mission_")
            or cls._looks_operational_text(content)
        )

    def _migrate(self, loaded: Any) -> dict[str, Any]:
        if not isinstance(loaded, dict):
            loaded = {}

        result = self._default_data()
        for key in ("session", "long_term", "profile", "working"):
            value = loaded.get(key, [])
            result[key] = value if isinstance(value, list) else []

        old_operational = loaded.get("operational", [])
        if isinstance(old_operational, list):
            result["operational"].extend(old_operational)

        old_episodic = loaded.get("episodic", [])
        if isinstance(old_episodic, list):
            for item in old_episodic:
                if self._is_operational_entry(item):
                    result["operational"].append(item)
                else:
                    result["episodic"].append(item)

        emotional = loaded.get("emotional", {})
        if isinstance(emotional, dict):
            current = emotional.get("current", {})
            history = emotional.get("history", [])
            result["emotional"] = {
                "current": current if isinstance(current, dict) else {},
                "history": history if isinstance(history, list) else [],
            }

        old_meta = loaded.get("meta", {})
        if isinstance(old_meta, dict):
            result["meta"].update(old_meta)

        result["schema_version"] = self.SCHEMA_VERSION
        return result

    def _normalize_memory_item(
        self,
        item: Any,
        *,
        default_kind: str,
        default_source: str,
        default_confidence: float,
    ) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        content = self._clean_text(item.get("content", ""))
        if not content or self._looks_like_question(content):
            return None
        kind = self._clean_text(item.get("kind", default_kind)) or default_kind
        if kind == "explicit":
            content = self._normalize_explicit_memory(content)
        if not content:
            return None
        created_at = str(item.get("created_at", item.get("at", self._now())))
        updated_at = str(item.get("updated_at", created_at))
        last_seen_at = str(item.get("last_seen_at", updated_at))
        try:
            occurrences = max(1, int(item.get("occurrences", 1)))
        except (TypeError, ValueError):
            occurrences = 1
        return {
            "kind": kind,
            "content": content,
            "source": self._clean_text(item.get("source", default_source)) or default_source,
            "confidence": self._clamp_confidence(item.get("confidence", default_confidence)),
            "occurrences": occurrences,
            "created_at": created_at,
            "updated_at": updated_at,
            "last_seen_at": last_seen_at,
        }

    def _sanitize_all(self) -> None:
        # Session
        session = []
        for item in self.data.get("session", []):
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if content:
                session.append({
                    "role": str(item.get("role", "?")),
                    "content": content,
                    "at": str(item.get("at", self._now())),
                })
        self.data["session"] = session[-self.SESSION_LIMIT:]

        # Durable memories: dedupe exact content.
        semantic: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        for raw in self.data.get("long_term", []):
            item = self._normalize_memory_item(
                raw,
                default_kind="fact",
                default_source="legacy",
                default_confidence=0.75,
            )
            if item is None:
                continue
            key = self._key(item["content"])
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                semantic.append(item)
            else:
                existing["occurrences"] = max(int(existing["occurrences"]), int(item["occurrences"]))
                existing["confidence"] = max(float(existing["confidence"]), float(item["confidence"]))
                existing["last_seen_at"] = max(str(existing["last_seen_at"]), str(item["last_seen_at"]))
        self.data["long_term"] = semantic[-self.LONG_TERM_LIMIT:]

        # Profile: one value per key, latest wins.
        profile: list[dict[str, Any]] = []
        seen_profile = set()
        for raw in reversed(self.data.get("profile", [])):
            if not isinstance(raw, dict):
                continue
            key = self._clean_text(raw.get("key", ""))
            value = self._clean_text(raw.get("value", ""))
            if not key or not value or key.lower() in seen_profile:
                continue
            seen_profile.add(key.lower())
            now = self._now()
            profile.append({
                "key": key,
                "value": value,
                "source": self._clean_text(raw.get("source", "legacy")) or "legacy",
                "confidence": self._clamp_confidence(raw.get("confidence", 0.95)),
                "created_at": str(raw.get("created_at", raw.get("at", now))),
                "updated_at": str(raw.get("updated_at", raw.get("at", now))),
            })
        self.data["profile"] = list(reversed(profile))[-self.PROFILE_LIMIT:]

        # Personal episodes and operational entries are re-split on every boot.
        personal_candidates = list(self.data.get("episodic", []))
        operational_candidates = list(self.data.get("operational", []))
        personal: list[dict[str, Any]] = []
        operational: list[dict[str, Any]] = []
        personal_seen = set()
        operational_seen = set()

        for raw in personal_candidates + operational_candidates:
            item = self._normalize_memory_item(
                raw,
                default_kind="event",
                default_source="memory",
                default_confidence=0.8,
            )
            if item is None:
                continue
            target_operational = self._is_operational_entry(item)
            key = self._key(item["content"])
            if target_operational:
                if key in operational_seen:
                    continue
                operational_seen.add(key)
                operational.append(item)
            else:
                if key in personal_seen:
                    continue
                personal_seen.add(key)
                personal.append(item)

        self.data["episodic"] = personal[-self.EPISODIC_LIMIT:]
        self.data["operational"] = operational[-self.OPERATIONAL_LIMIT:]

        # Working memory
        working: list[dict[str, Any]] = []
        working_seen = set()
        for raw in reversed(self.data.get("working", [])):
            if not isinstance(raw, dict):
                continue
            key = self._clean_text(raw.get("key", ""))
            content = self._clean_text(raw.get("content", ""))
            if not key or not content or key.lower() in working_seen:
                continue
            working_seen.add(key.lower())
            now = self._now()
            working.append({
                "key": key,
                "kind": self._clean_text(raw.get("kind", "working")) or "working",
                "content": content,
                "source": self._clean_text(raw.get("source", "system")) or "system",
                "created_at": str(raw.get("created_at", raw.get("at", now))),
                "updated_at": str(raw.get("updated_at", raw.get("at", now))),
            })
        self.data["working"] = list(reversed(working))[-self.WORKING_LIMIT:]

        # Emotional state/history
        emotional = self.data.get("emotional", {})
        if not isinstance(emotional, dict):
            emotional = {}
        current = emotional.get("current", {})
        history = emotional.get("history", [])
        if not isinstance(current, dict):
            current = {}
        if not isinstance(history, list):
            history = []

        clean_current: dict[str, dict[str, Any]] = {}
        for dimension, item in current.items():
            if dimension not in self.EMOTIONAL_LABELS or not isinstance(item, dict):
                continue
            value = self._clean_text(item.get("value", ""))
            observed_at = str(item.get("observed_at", item.get("at", self._now())))
            source = self._clean_text(item.get("source", ""))
            confidence = self._clamp_confidence(item.get("confidence", 0.0))
            if value and confidence > 0:
                clean_current[dimension] = {
                    "value": value,
                    "confidence": confidence,
                    "observed_at": observed_at,
                    "source": source,
                }

        clean_history = []
        for item in history[-self.EMOTIONAL_HISTORY_LIMIT:]:
            if not isinstance(item, dict):
                continue
            source = self._clean_text(item.get("source", ""))
            at = str(item.get("at", self._now()))
            signals = item.get("signals", {})
            if not isinstance(signals, dict):
                continue
            normalized_signals = {}
            for dimension, signal in signals.items():
                if dimension not in self.EMOTIONAL_LABELS or not isinstance(signal, dict):
                    continue
                value = self._clean_text(signal.get("value", ""))
                confidence = self._clamp_confidence(signal.get("confidence", 0.0))
                if value and confidence > 0:
                    normalized_signals[dimension] = {
                        "value": value,
                        "confidence": confidence,
                    }
            if normalized_signals:
                clean_history.append({"at": at, "source": source, "signals": normalized_signals})

        # V4.6 migration : si l'ancien fichier n'avait pas encore de couche
        # émotionnelle, on peut reconstruire prudemment l'état récent à partir
        # des événements personnels des 72 dernières heures.
        now_dt = datetime.now(timezone.utc)
        for episode in reversed(self.data["episodic"][-30:]):
            if not isinstance(episode, dict):
                continue
            created = self._parse_time(episode.get("created_at", ""))
            if created is None:
                continue
            age_hours = max(0.0, (now_dt - created).total_seconds() / 3600.0)
            if age_hours > 72.0:
                continue
            content = self._clean_text(episode.get("content", ""))
            signals = self._detect_emotional_signals(content)
            if not signals:
                continue
            for dimension, signal in signals.items():
                if dimension in clean_current:
                    continue
                clean_current[dimension] = {
                    "value": signal["value"],
                    "confidence": self._clamp_confidence(signal["confidence"]),
                    "observed_at": created.isoformat(),
                    "source": content,
                }
            signature = (created.isoformat(), content)
            if not any(
                isinstance(item, dict)
                and (str(item.get("at", "")), self._clean_text(item.get("source", ""))) == signature
                for item in clean_history
            ):
                clean_history.append({
                    "at": created.isoformat(),
                    "source": content,
                    "signals": signals,
                })

        self.data["emotional"] = {
            "current": clean_current,
            "history": clean_history[-self.EMOTIONAL_HISTORY_LIMIT:],
        }

    # =========================================================
    # SESSION
    # =========================================================

    def add_session(self, role: str, content: str) -> None:
        content = str(content).strip()
        if not content:
            return
        self.data["session"].append({
            "role": role,
            "content": content,
            "at": self._now(),
        })
        self.data["session"] = self.data["session"][-self.SESSION_LIMIT:]
        self._save()

    # =========================================================
    # DURABLE MEMORY / PROFILE
    # =========================================================

    def remember(
        self,
        text: str,
        *,
        kind: str = "memory",
        source: str = "user",
        confidence: float = 0.8,
    ) -> None:
        text = self._clean_text(text)
        if not text or self._looks_like_question(text):
            return
        key = self._key(text)
        now = self._now()
        for item in self.data["long_term"]:
            if not isinstance(item, dict):
                continue
            if self._key(item.get("content", "")) != key:
                continue
            occurrences = int(item.get("occurrences", 1)) + 1
            item["occurrences"] = occurrences
            item["last_seen_at"] = now
            item["updated_at"] = now
            item["confidence"] = self._clamp_confidence(
                max(float(item.get("confidence", 0.0)), confidence)
                + min(0.02 * (occurrences - 1), 0.12)
            )
            if source == "user_explicit":
                item["source"] = source
                item["kind"] = kind
                item["confidence"] = 1.0
            self._save()
            return

        self.data["long_term"].append({
            "kind": kind,
            "content": text,
            "source": source,
            "confidence": self._clamp_confidence(confidence),
            "occurrences": 1,
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        })
        self.data["long_term"] = self.data["long_term"][-self.LONG_TERM_LIMIT:]
        self._save()

    def remember_profile(
        self,
        *,
        key: str,
        value: str,
        source: str,
        confidence: float = 0.95,
    ) -> None:
        key = self._clean_text(key)
        value = self._clean_text(value)
        if not key or not value:
            return
        now = self._now()
        remaining = []
        created_at = now
        for item in self.data["profile"]:
            if not isinstance(item, dict):
                continue
            if str(item.get("key", "")).lower() == key.lower():
                created_at = str(item.get("created_at", now))
                continue
            remaining.append(item)
        remaining.append({
            "key": key,
            "value": value,
            "source": source,
            "confidence": self._clamp_confidence(confidence),
            "created_at": created_at,
            "updated_at": now,
        })
        self.data["profile"] = remaining[-self.PROFILE_LIMIT:]
        self._save()

    # =========================================================
    # PERSONAL / OPERATIONAL EPISODES
    # =========================================================

    def _remember_timeline(
        self,
        bucket: str,
        text: str,
        *,
        kind: str,
        source: str,
        confidence: float,
        limit: int,
    ) -> None:
        text = self._clean_text(text)
        if not text or self._looks_like_question(text):
            return
        key = self._key(text)
        now = self._now()
        for item in reversed(self.data[bucket][-40:]):
            if not isinstance(item, dict):
                continue
            if self._key(item.get("content", "")) == key:
                item["last_seen_at"] = now
                item["updated_at"] = now
                item["occurrences"] = int(item.get("occurrences", 1)) + 1
                self._save()
                return
        self.data[bucket].append({
            "kind": kind,
            "content": text,
            "source": source,
            "confidence": self._clamp_confidence(confidence),
            "occurrences": 1,
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        })
        self.data[bucket] = self.data[bucket][-limit:]
        self._save()

    def remember_episode(
        self,
        text: str,
        *,
        kind: str = "event",
        source: str = "user",
        confidence: float = 0.85,
    ) -> None:
        # Sécurité : une mission ne doit plus contaminer la mémoire perso.
        if source == "agentos" or kind in self.OPERATIONAL_KINDS or self._looks_operational_text(text):
            self.remember_operational(
                text,
                kind=kind,
                source=source,
                confidence=confidence,
            )
            return
        self._remember_timeline(
            "episodic",
            text,
            kind=kind,
            source=source,
            confidence=confidence,
            limit=self.EPISODIC_LIMIT,
        )

    def remember_operational(
        self,
        text: str,
        *,
        kind: str = "operation",
        source: str = "agentos",
        confidence: float = 1.0,
    ) -> None:
        self._remember_timeline(
            "operational",
            text,
            kind=kind,
            source=source,
            confidence=confidence,
            limit=self.OPERATIONAL_LIMIT,
        )

    # =========================================================
    # WORKING MEMORY
    # =========================================================

    def remember_working(
        self,
        *,
        key: str,
        content: str,
        kind: str = "working",
        source: str = "system",
    ) -> None:
        key = self._clean_text(key)
        content = self._clean_text(content)
        if not key or not content:
            return
        now = self._now()
        remaining = []
        created_at = now
        for item in self.data["working"]:
            if not isinstance(item, dict):
                continue
            if str(item.get("key", "")).lower() == key.lower():
                created_at = str(item.get("created_at", now))
                continue
            remaining.append(item)
        remaining.append({
            "key": key,
            "kind": kind,
            "content": content,
            "source": source,
            "created_at": created_at,
            "updated_at": now,
        })
        self.data["working"] = remaining[-self.WORKING_LIMIT:]
        self._save()

    def forget_working(self, key: str) -> None:
        normalized = self._clean_text(key).lower()
        if not normalized:
            return
        before = len(self.data["working"])
        self.data["working"] = [
            item
            for item in self.data["working"]
            if (
                not isinstance(item, dict)
                or str(item.get("key", "")).lower() != normalized
            )
        ]
        if len(self.data["working"]) != before:
            self._save()

    # =========================================================
    # EMOTIONAL CONTEXT
    # =========================================================

    @classmethod
    def _detect_emotional_signals(cls, text: str) -> dict[str, dict[str, Any]]:
        clean = cls._clean_text(text)
        if not clean or cls._looks_like_question(clean):
            return {}
        normalized = cls._ascii(clean)
        signals: dict[str, dict[str, Any]] = {}
        for dimension, patterns in cls.EMOTIONAL_PATTERNS.items():
            best: dict[str, Any] | None = None
            for value, pattern, confidence in patterns:
                if re.search(pattern, normalized, flags=re.IGNORECASE):
                    candidate = {"value": value, "confidence": confidence}
                    if best is None or confidence > float(best["confidence"]):
                        best = candidate
            if best is not None:
                signals[dimension] = best
        return signals

    @staticmethod
    def _decay_factor(age_hours: float) -> float:
        if age_hours <= 6:
            return 1.0
        if age_hours <= 12:
            return 0.90
        if age_hours <= 24:
            return 0.75
        if age_hours <= 48:
            return 0.45
        if age_hours <= 72:
            return 0.20
        return 0.0

    def observe_emotional_state(self, text: str) -> dict[str, dict[str, Any]]:
        signals = self._detect_emotional_signals(text)
        if not signals:
            return {}
        clean = self._clean_text(text)
        normalized = self._ascii(clean)
        now = self._now()
        current = self.data["emotional"].setdefault("current", {})

        # V4.6.1 — réconciliation émotionnelle.
        # Exemple : "Finalement ça va mieux, je suis motivé." remplace
        # explicitement l'ancien état négatif global. Si le nouveau message
        # ne dit rien sur l'énergie, on ne prétend ni qu'elle est haute ni
        # qu'elle est encore basse : l'ancienne estimation est invalidée.
        improved_globally = any(
            re.search(pattern, normalized, flags=re.IGNORECASE)
            for pattern in self.GLOBAL_IMPROVEMENT_PATTERNS
        )
        if improved_globally:
            for dimension, negative_values in self.NEGATIVE_EMOTIONAL_VALUES.items():
                if dimension in signals:
                    continue
                existing = current.get(dimension)
                if not isinstance(existing, dict):
                    continue
                if str(existing.get("value", "")) in negative_values:
                    current.pop(dimension, None)

        for dimension, signal in signals.items():
            current[dimension] = {
                "value": signal["value"],
                "confidence": self._clamp_confidence(signal["confidence"]),
                "observed_at": now,
                "source": clean,
            }
        self.data["emotional"].setdefault("history", []).append({
            "at": now,
            "source": clean,
            "signals": signals,
        })
        self.data["emotional"]["history"] = (
            self.data["emotional"]["history"][-self.EMOTIONAL_HISTORY_LIMIT:]
        )
        # Une observation émotionnelle est un événement personnel, pas un fait durable.
        self._remember_timeline(
            "episodic",
            clean,
            kind="emotional_observation",
            source="automatic",
            confidence=max(float(item["confidence"]) for item in signals.values()),
            limit=self.EPISODIC_LIMIT,
        )
        # _remember_timeline a déjà sauvegardé.
        return signals

    def current_emotional_state(self) -> dict[str, dict[str, Any]]:
        now = datetime.now(timezone.utc)
        result: dict[str, dict[str, Any]] = {}
        current = self.data.get("emotional", {}).get("current", {})
        if not isinstance(current, dict):
            return result
        for dimension, item in current.items():
            if dimension not in self.EMOTIONAL_LABELS or not isinstance(item, dict):
                continue
            observed = self._parse_time(item.get("observed_at", ""))
            if observed is None:
                continue
            age_hours = max(0.0, (now - observed).total_seconds() / 3600.0)
            effective = self._clamp_confidence(item.get("confidence", 0.0)) * self._decay_factor(age_hours)
            if effective < 0.25:
                continue
            result[dimension] = {
                "value": self._clean_text(item.get("value", "")),
                "confidence": effective,
                "base_confidence": self._clamp_confidence(item.get("confidence", 0.0)),
                "observed_at": str(item.get("observed_at", "")),
                "age_hours": age_hours,
                "source": self._clean_text(item.get("source", "")),
            }
        return result

    @staticmethod
    def _age_label(age_hours: float) -> str:
        if age_hours < 1:
            minutes = max(1, int(age_hours * 60))
            return f"il y a environ {minutes} min"
        if age_hours < 24:
            return f"il y a environ {max(1, int(age_hours))} h"
        days = max(1, int(age_hours / 24))
        return f"il y a environ {days} j"

    def emotional_context(self) -> str:
        state = self.current_emotional_state()
        if not state:
            return "(aucun état émotionnel récent suffisamment fiable)"
        lines = []
        for dimension in ("mood", "energy", "motivation", "stress", "frustration"):
            item = state.get(dimension)
            if item is None:
                continue
            label, values = self.EMOTIONAL_LABELS[dimension]
            value_label = values.get(str(item["value"]), str(item["value"]))
            lines.append(
                f"- {label} : {value_label} "
                f"(confiance {float(item['confidence']):.2f}, {self._age_label(float(item['age_hours']))})"
            )
        return "\n".join(lines) or "(aucun état émotionnel récent suffisamment fiable)"

    def emotional_summary(self) -> str:
        state = self.current_emotional_state()
        if not state:
            history = self.data.get("emotional", {}).get("history", [])
            if history:
                last = history[-1]
                source = self._clean_text(last.get("source", "")) if isinstance(last, dict) else ""
                if source:
                    return "Je n'ai plus d'état émotionnel actuel assez fiable. Ta dernière observation enregistrée était : « " + source + " »."
            return "Je n'ai pas assez d'éléments récents pour estimer ton état du moment."

        lines = ["ÉTAT DU MOMENT"]
        for dimension in ("mood", "energy", "motivation", "stress", "frustration"):
            item = state.get(dimension)
            if item is None:
                continue
            label, values = self.EMOTIONAL_LABELS[dimension]
            value_label = values.get(str(item["value"]), str(item["value"]))
            lines.append(
                f"- {label} : {value_label} (confiance {float(item['confidence']):.2f})"
            )
        newest = max(state.values(), key=lambda item: str(item.get("observed_at", "")))
        source = self._clean_text(newest.get("source", ""))
        if source:
            lines.append(f"\nDernière observation : « {source} »")
        lines.append("Cet état est temporaire et sa confiance diminue avec le temps.")
        return "\n".join(lines)

    # =========================================================
    # AUTOMATIC EXTRACTION
    # =========================================================

    @classmethod
    def explicit_memory_fact(cls, text: str) -> str | None:
        if cls._looks_like_question(text):
            return None
        clean = cls._clean_text(text)
        for pattern in cls.EXPLICIT_PATTERNS:
            if re.search(pattern, clean, flags=re.IGNORECASE):
                fact = cls._normalize_explicit_memory(clean)
                return fact or None
        return None

    def _explicit_memory(self, text: str) -> bool:
        fact = self.explicit_memory_fact(text)
        if fact is None:
            return False
        signals = self._detect_emotional_signals(fact)
        temporal = any(marker in fact.lower() for marker in self.TEMPORAL_MARKERS)
        if signals or temporal:
            if signals:
                self.observe_emotional_state(fact)
            else:
                self.remember_episode(fact, kind="user_event", source="user_explicit", confidence=1.0)
        else:
            self.remember(fact, kind="explicit", source="user_explicit", confidence=1.0)
        return True

    def _extract_profile(self, text: str) -> None:
        clean = self._clean_text(text)
        if not clean or self._looks_like_question(clean):
            return
        match = re.search(
            r"^(?:je m'appelle|je m’appelle|mon prénom est|mon prenom est)\s+([A-Za-zÀ-ÿ'-]{2,40})\b",
            clean,
            flags=re.IGNORECASE,
        )
        if match:
            self.remember_profile(key="first_name", value=match.group(1), source="user", confidence=1.0)
        match = re.search(
            r"^(?:j'habite|j’habite|je vis)\s+(?:à|a)\s+([^,.!?]{2,80})",
            clean,
            flags=re.IGNORECASE,
        )
        if match:
            self.remember_profile(key="location", value=match.group(1).strip(), source="user", confidence=0.98)

    def _extract_preferences(self, text: str) -> None:
        clean = self._clean_text(text)
        if not clean or self._looks_like_question(clean):
            return
        patterns = (
            r"^je préfère\s+.{2,180}$", r"^je prefere\s+.{2,180}$",
            r"^j'aime\s+.{2,180}$", r"^j’aime\s+.{2,180}$",
            r"^j'adore\s+.{2,180}$", r"^j’adore\s+.{2,180}$",
            r"^je n'aime pas\s+.{2,180}$", r"^je n’aime pas\s+.{2,180}$",
            r"^j'aime pas\s+.{2,180}$", r"^j’aime pas\s+.{2,180}$",
            r"^je déteste\s+.{2,180}$", r"^je deteste\s+.{2,180}$",
            r"^mon .{1,80} préféré est\s+.{2,120}$",
            r"^mon .{1,80} prefere est\s+.{2,120}$",
        )
        if any(re.search(pattern, clean, flags=re.IGNORECASE) for pattern in patterns):
            self.remember(clean, kind="preference", source="automatic", confidence=0.90)

    def _extract_habits(self, text: str) -> None:
        clean = self._clean_text(text)
        if not clean or self._looks_like_question(clean):
            return
        patterns = (
            r"^d'habitude\s+.{2,180}$", r"^d’habitude\s+.{2,180}$",
            r"^habituellement\s+.{2,180}$", r"^en général,?\s+je\s+.{2,180}$",
            r"^en general,?\s+je\s+.{2,180}$", r"^je\s+.{1,80}\s+tous les jours\b.*$",
            r"^je\s+.{1,80}\s+chaque semaine\b.*$",
        )
        if any(re.search(pattern, clean, flags=re.IGNORECASE) for pattern in patterns):
            self.remember(clean, kind="habit", source="automatic", confidence=0.80)

    def _extract_episode(self, text: str) -> None:
        clean = self._clean_text(text)
        if not clean or self._looks_like_question(clean) or self._looks_operational_text(clean):
            return
        lower = clean.lower()
        if any(marker in lower for marker in self.TEMPORAL_MARKERS):
            self.remember_episode(clean, kind="user_event", source="automatic", confidence=0.80)

    def maybe_remember(self, text: str) -> dict[str, dict[str, Any]]:
        """Analyse un message utilisateur et retourne les signaux émotionnels détectés.

        Le retour permet au Manager d'adapter immédiatement sa réponse sans
        relancer une deuxième analyse ni enregistrer deux fois le même état.
        """
        if self._looks_like_question(text):
            return {}
        # Une demande opérationnelle n'est pas une information personnelle.
        operational = self._looks_operational_text(text)
        explicit = self._explicit_memory(text)
        if explicit or operational:
            return {}
        self._extract_profile(text)
        self._extract_preferences(text)
        self._extract_habits(text)
        emotional = self.observe_emotional_state(text)
        if not emotional:
            self._extract_episode(text)
        return emotional

    # =========================================================
    # SELECTIVE RETRIEVAL
    # =========================================================

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        normalized = cls._ascii(text)
        values = re.findall(r"[a-z0-9_-]{2,}", normalized)
        return {value for value in values if value not in cls.STOPWORDS}

    @classmethod
    def _active_topic_tokens(cls, text: str) -> set[str]:
        """Retourne uniquement les groupes thématiques explicitement activés.

        Cette barrière évite qu'une préférence générique liée à Agent-OS soit
        remontée dans une question sur l'aquariophilie simplement parce que les
        deux souvenirs sont des "préférences".
        """
        tokens = cls._tokens(text)
        active: set[str] = set()
        for group in cls.TOPIC_GROUPS:
            normalized_group = {cls._ascii(value) for value in group}
            if tokens & normalized_group:
                active.update(normalized_group)
        return active

    @classmethod
    def _expanded_tokens(cls, text: str) -> set[str]:
        tokens = cls._tokens(text)
        return tokens | cls._active_topic_tokens(text)

    def _relevant_long_term(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        query_tokens = self._expanded_tokens(query)
        topic_tokens = self._active_topic_tokens(query)
        scored = []
        for index, item in enumerate(self.data["long_term"]):
            if not isinstance(item, dict):
                continue
            content = self._clean_text(item.get("content", ""))
            if not content:
                continue
            memory_tokens = self._tokens(content)

            # Si la question cible clairement un domaine connu, un souvenir doit
            # réellement appartenir à ce domaine. Les mots génériques comme
            # "préférence", "goût" ou "travail" ne suffisent pas.
            if topic_tokens and not (memory_tokens & topic_tokens):
                continue

            overlap = len(query_tokens & memory_tokens)
            confidence = float(item.get("confidence", 0.0))
            occurrences = int(item.get("occurrences", 1))
            explicit_bonus = 0.35 if str(item.get("kind", "")) == "explicit" else 0.0
            score = overlap * 3.0 + confidence + min(occurrences, 5) * 0.15 + explicit_bonus
            if overlap > 0:
                scored.append((score, index, item))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [row[2] for row in scored[:limit]]

    def _relevant_episodic(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        query_tokens = self._expanded_tokens(query)
        topic_tokens = self._active_topic_tokens(query)
        now = datetime.now(timezone.utc)
        scored = []
        for index, item in enumerate(self.data["episodic"]):
            if not isinstance(item, dict):
                continue
            content = self._clean_text(item.get("content", ""))
            if not content:
                continue
            event_tokens = self._tokens(content)

            if topic_tokens and not (event_tokens & topic_tokens):
                continue

            overlap = len(query_tokens & event_tokens)
            created = self._parse_time(item.get("created_at", ""))
            age_hours = 9999.0
            if created is not None:
                age_hours = max(0.0, (now - created).total_seconds() / 3600.0)
            recent_bonus = 2.0 if age_hours <= 24 else 0.75 if age_hours <= 72 else 0.0
            score = overlap * 3.0 + recent_bonus
            if overlap > 0 or (age_hours <= 24 and not topic_tokens):
                scored.append((score, index, item))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [row[2] for row in scored[:limit]]

    @staticmethod
    def _format_memory_items(items: list[dict[str, Any]], *, episodic: bool = False) -> str:
        lines = []
        for item in items:
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if episodic:
                lines.append(f"- {item.get('created_at', '')} — {content}")
            else:
                kind = str(item.get("kind", "fact"))
                confidence = float(item.get("confidence", 0.0))
                lines.append(f"- [{kind} | confiance {confidence:.2f}] {content}")
        return "\n".join(lines) or "(aucun souvenir pertinent)"

    def relevant_context(self, query: str) -> str:
        durable = self._format_memory_items(self._relevant_long_term(query))
        episodic = self._format_memory_items(self._relevant_episodic(query), episodic=True)
        return (
            "PROFIL UTILISATEUR:\n"
            + self.profile_context()
            + "\n\nSOUVENIRS PERSONNELS PERTINENTS:\n"
            + durable
            + "\n\nÉVÉNEMENTS PERSONNELS RÉCENTS:\n"
            + episodic
            + "\n\nÉTAT ÉMOTIONNEL ACTUEL (temporaire, estimation):\n"
            + self.emotional_context()
            + "\n\nCONVERSATION RÉCENTE:\n"
            + self.session_context(limit=8)
        )

    def relevant_personal_summary(self, query: str, *, limit: int = 6) -> str | None:
        """Réponse factuelle directe à une question sur les goûts/souvenirs.

        Contrairement à ``relevant_context``, cette méthode ne passe pas par le
        LLM. Elle restitue uniquement les souvenirs réellement enregistrés qui
        partagent le sujet demandé. Cela évite les embellissements du type
        "tu as sûrement passé de belles heures..." qui ne sont pas en mémoire.
        """
        durable = self._relevant_long_term(query, limit=limit)

        query_tokens = self._expanded_tokens(query)
        topic_tokens = self._active_topic_tokens(query)
        episodic_scored: list[tuple[float, int, dict[str, Any]]] = []
        for index, item in enumerate(self.data["episodic"]):
            if not isinstance(item, dict):
                continue
            content = self._clean_text(item.get("content", ""))
            if not content:
                continue
            content_tokens = self._tokens(content)
            if topic_tokens and not (content_tokens & topic_tokens):
                continue
            overlap = len(query_tokens & content_tokens)
            if overlap <= 0:
                continue
            confidence = self._clamp_confidence(item.get("confidence", 0.0))
            episodic_scored.append((overlap * 3.0 + confidence, index, item))
        episodic_scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        episodic = [row[2] for row in episodic_scored[:3]]

        if not durable and not episodic:
            return None

        lines = ["Sur ce sujet, j'ai retenu :"]
        seen: set[str] = set()
        for item in durable + episodic:
            content = self._clean_text(item.get("content", ""))
            key = self._key(content)
            if not content or key in seen:
                continue
            seen.add(key)
            lines.append(f"- {content}")

        return "\n".join(lines) if len(lines) > 1 else None

    # =========================================================
    # FORMATTERS
    # =========================================================

    def session_context(self, limit: int = 8) -> str:
        lines = []
        for item in self.data["session"][-limit:]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", ""))
            if content:
                lines.append(f"{item.get('role', '?')}: {content}")
        return "\n".join(lines) or "(vide)"

    def profile_context(self) -> str:
        labels = {"first_name": "Prénom", "location": "Lieu de vie"}
        lines = []
        for item in self.data["profile"]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", ""))
            value = str(item.get("value", ""))
            if value:
                lines.append(f"- {labels.get(key, key)} : {value}")
        return "\n".join(lines) or "(vide)"

    def long_term_context(self, limit: int = 30) -> str:
        items = [
            item for item in self.data["long_term"]
            if isinstance(item, dict) and str(item.get("content", "")).strip()
        ][-limit:]
        items.sort(
            key=lambda item: (
                float(item.get("confidence", 0.0)),
                int(item.get("occurrences", 1)),
            ),
            reverse=True,
        )
        return self._format_memory_items(items) if items else "(vide)"

    def episodic_context(self, limit: int = 12) -> str:
        items = [item for item in self.data["episodic"][-limit:] if isinstance(item, dict)]
        return self._format_memory_items(items, episodic=True) if items else "(vide)"

    def operational_context(self, limit: int = 12) -> str:
        lines = []
        for item in self.data["operational"][-limit:]:
            if not isinstance(item, dict):
                continue
            content = self._clean_text(item.get("content", ""))
            if content:
                lines.append(f"- {item.get('created_at', '')} — {content}")
        return "\n".join(lines) or "(vide)"

    def working_context(self) -> str:
        lines = []
        for item in self.data["working"]:
            if not isinstance(item, dict):
                continue
            content = self._clean_text(item.get("content", ""))
            if content:
                lines.append(f"- {content}")
        return "\n".join(lines) or "(vide)"

    def personal_summary(self) -> str:
        return (
            "PROFIL\n"
            + self.profile_context()
            + "\n\nSOUVENIRS DURABLES\n"
            + self.long_term_context(limit=20)
            + "\n\nÉVÉNEMENTS PERSONNELS RÉCENTS\n"
            + self.episodic_context(limit=8)
            + "\n\nÉTAT DU MOMENT\n"
            + self.emotional_context()
        )

    def operational_summary(self) -> str:
        return (
            "MÉMOIRE OPÉRATIONNELLE\n\n"
            "TRAVAIL EN COURS\n"
            + self.working_context()
            + "\n\nHISTORIQUE RÉCENT\n"
            + self.operational_context(limit=15)
        )

    def concise_summary(self) -> str:
        stats = self.stats()
        return (
            "MÉMOIRE PERSONNELLE\n"
            f"Profil : {stats['profile']} | "
            f"Souvenirs durables : {stats['long_term']} | "
            f"Événements personnels : {stats['episodic']}\n\n"
            + self.personal_summary()
            + "\n\nLes missions sont séparées de la mémoire personnelle. "
            + "Utilise `memory operations` pour l'historique Agent-OS."
        )

    def context(self) -> str:
        return (
            "MÉMOIRE PERSONNELLE\n"
            + self.personal_summary()
            + "\n\nMÉMOIRE OPÉRATIONNELLE\n"
            + self.operational_summary()
            + "\n\nCONVERSATION RÉCENTE\n"
            + self.session_context(limit=12)
        )

    def stats(self) -> dict[str, int | str]:
        emotional_current = len(self.current_emotional_state())
        return {
            "schema_version": self.SCHEMA_VERSION,
            "session": len(self.data["session"]),
            "profile": len(self.data["profile"]),
            "long_term": len(self.data["long_term"]),
            "episodic": len(self.data["episodic"]),
            "operational": len(self.data["operational"]),
            "working": len(self.data["working"]),
            "emotional_current": emotional_current,
            "emotional_history": len(self.data["emotional"].get("history", [])),
        }

    def format(self) -> str:
        stats = self.stats()
        return (
            "MEMORY ENGINE V4.6.2 — DEBUG\n"
            f"Profil : {stats['profile']} | Durable : {stats['long_term']} | "
            f"Épisodique perso : {stats['episodic']} | Opérationnel : {stats['operational']} | "
            f"Travail : {stats['working']} | Émotion courant : {stats['emotional_current']} | "
            f"Session : {stats['session']}\n\n"
            + self.context()
        )
