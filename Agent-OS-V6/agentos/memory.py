from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore
from agentos.personal_memory_v2 import PersonalMemoryV2
from agentos.personal_profile import PersonalProfileMemory
from agentos.people_profiles import PeopleProfileMemory


class Memory:
    """
    Agent-OS V4.7.3 — Personal / Operational / Emotional / Relational Memory.

    Layers:
    - session      : recent conversation;
    - profile      : stable identity facts;
    - long_term    : legacy/general durable memories;
    - relational   : structured communication, interests, habits,
                     preferences and important people/relations;
    - episodic     : dated PERSONAL events;
    - operational  : Agent-OS mission/task history;
    - working      : temporary operational context;
    - emotional    : current emotional estimate + observation history.

    V4.7.3 is backward compatible with V4.6.x. Existing long_term memories are
    kept and, when they can be classified safely, mirrored into relational
    memory during migration.
    """

    SCHEMA_VERSION = "4.7.3"

    SESSION_LIMIT = 60
    LONG_TERM_LIMIT = 2000
    PROFILE_LIMIT = 100
    EPISODIC_LIMIT = 5000
    OPERATIONAL_LIMIT = 300
    WORKING_LIMIT = 100
    EMOTIONAL_HISTORY_LIMIT = 120
    RELATIONAL_LIMIT = 500
    RELATIONAL_HISTORY_LIMIT = 300
    RELATIONAL_REINFORCEMENT_COOLDOWN_SECONDS = 60

    # Un état émotionnel est du contexte du moment, pas un trait durable.
    # Au-delà de ces durées, l'observation reste dans l'historique mais ne
    # doit plus influencer la conversation courante.
    EMOTIONAL_CURRENT_MAX_AGE_HOURS = {
        "mood": 4.0,
        "energy": 3.0,
        "motivation": 4.0,
        "stress": 3.0,
        "frustration": 3.0,
    }

    TERMINAL_WORKING_MARKERS = (
        "(terminée)", "(terminee)", "(completed)",
        "(échouée)", "(echouee)", "(failed)",
        "(refusée)", "(refusee)", "(rejected)",
        "(annulée)", "(annulee)", "(cancelled)",
    )

    RELATIONAL_CATEGORIES = (
        "communication",
        "interests",
        "habits",
        "preferences",
        "relations",
    )

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

    FORGET_PATTERNS = (
        r"^\s*oublie\s+ce\s+que\s+je\s+t['’]?ai\s+dit\s+sur\s+",
        r"^\s*oublie\s+(?:que\s+)?",
        r"^\s*ne\s+retiens\s+plus\s+(?:que\s+)?",
        r"^\s*efface\s+(?:de\s+ta\s+mémoire\s+|de\s+ta\s+memoire\s+)?",
        r"^\s*supprime\s+(?:de\s+ta\s+mémoire\s+|de\s+ta\s+memoire\s+)?",
        r"^\s*(?:peux-tu|peux tu|pourrais-tu|pourrais tu)\s+oublier\s+",
        r"^\s*je\s+veux\s+que\s+tu\s+oublies\s+",
        r"^\s*j['’]?aimerais\s+que\s+tu\s+oublies\s+",
    )

    TEMPORAL_MARKERS = (
        "aujourd'hui", "aujourd’hui", "ce matin", "cet après-midi",
        "cet apres-midi", "ce soir", "cette nuit", "hier", "avant-hier",
        "avant hier", "demain", "cette semaine", "ce week-end", "ce weekend",
        "en ce moment", "actuellement",
    )

    GLOBAL_IMPROVEMENT_PATTERNS = (
        r"\b(?:finalement\s+)?ca va mieux\b",
        r"\bje vais mieux\b",
        r"\bca va beaucoup mieux\b",
        r"\bje me sens mieux\b",
    )

    NEGATIVE_EMOTIONAL_VALUES = {
        "energy": {"low"},
        "motivation": {"low"},
        "stress": {"moderate", "high"},
        "frustration": {"high"},
        "mood": {"negative"},
    }

    OPERATIONAL_KINDS = {
        "mission", "mission_created", "mission_completed", "mission_failed",
        "mission_cancelled", "mission_rejected", "mission_paused",
        "mission_resumed", "approval", "approval_required", "repair",
        "task", "task_completed", "task_failed",
    }

    TOPIC_GROUPS: dict[str, set[str]] = {
        "aquariophilie": {
            "aquariophilie", "aquarium", "aquariums", "poisson", "poissons",
            "rasbora", "brigittae", "crevette", "crevettes", "bac", "bacs",
            "nano", "plante", "plantes", "neritina",
        },
        "agent_os": {
            "agentos", "agent-os", "agent", "agents", "manager", "mission",
            "missions", "worker", "workers", "developer", "researcher",
            "tester", "planner", "code", "python", "programmation",
        },
        "domotique": {
            "domotique", "homeassistant", "home-assistant", "home assistant",
            "zigbee", "zha", "zigbee2mqtt", "mqtt", "capteur", "capteurs",
            "automation", "automatisation", "dashboard",
        },
        "cuisine": {
            "cuisine", "manger", "repas", "recette", "recettes", "aliment",
            "aliments", "nourriture",
        },
    }

    TOPIC_LABELS = {
        "aquariophilie": "Aquariophilie",
        "agent_os": "Agent-OS / agents IA",
        "domotique": "Domotique / Home Assistant",
        "cuisine": "Cuisine",
    }

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
            ("moderate", r"\b(?:un peu|legerement|plutot)\s+(?:stresse|stressee|anxieux|anxieuse|tendu|tendue)\b", 0.95),
            ("high", r"\b(?:tres|vraiment|extremement)\s+(?:stresse|stressee|anxieux|anxieuse|tendu|tendue)\b", 0.96),
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
        "stress": ("Stress", {"low": "bas", "moderate": "modéré", "high": "élevé"}),
        "frustration": ("Frustration", {"low": "basse", "high": "élevée"}),
        "mood": ("Humeur", {"positive": "positive", "negative": "négative"}),
    }

    def __init__(self) -> None:
        # Action transitoire consommée par le Manager pendant le message courant.
        # Elle n'est jamais persistée dans memory.json.
        self._last_memory_action: dict[str, Any] | None = None

        self.store = JsonStore(DATA_DIR / "memory.json", self._default_data())
        loaded = self.store.load()
        self.data = self._migrate(loaded)
        self._sanitize_all()
        self._migrate_legacy_relational()
        self._consolidate_relational_memory()
        self._prune_stale_emotional_current()
        self._save()

        # V6.3 : SQLite devient la source principale pour les événements
        # personnels. Le JSON historique reste en dual-write pour compatibilité
        # pendant la période de validation.
        self.personal_v2 = None
        try:
            self.personal_v2 = PersonalMemoryV2(
                DATA_DIR / "personal_memory.db",
                known_people_provider=self._personal_v2_known_people,
            )
            migration = self.personal_v2.migrate_legacy(
                self.data.get("episodic", [])
            )
            self.data.setdefault("meta", {})["personal_memory_v2"] = {
                "schema_version": 2,
                "migration_seen": migration.get("seen", 0),
                "migration_imported": migration.get("imported", 0),
                "updated_at": self._now(),
            }
            self.data.get("meta", {}).pop("personal_memory_v2_error", None)
            self._save()
        except Exception as exc:
            self.personal_v2 = None
            self.data.setdefault("meta", {})["personal_memory_v2_error"] = str(exc)
            self._save()

        # PERSONAL PROFILE V6.5 — concepts durables séparés des événements.
        self.profile_v2 = None
        try:
            self.profile_v2 = PersonalProfileMemory(
                DATA_DIR / "personal_profile.db"
            )
            migration_profile = self.profile_v2.migrate_legacy(self.data)
            self.data.setdefault("meta", {})["personal_profile_v65"] = {
                "schema_version": 1,
                "migration_seen": migration_profile.get("seen", 0),
                "migration_imported": migration_profile.get("imported", 0),
                "updated_at": self._now(),
            }
            self.data.get("meta", {}).pop("personal_profile_v65_error", None)
            self._save()
        except Exception as exc:
            self.profile_v2 = None
            self.data.setdefault("meta", {})["personal_profile_v65_error"] = str(exc)
            self._save()

        # PEOPLE PROFILES V6.5.2 — profils individuels et alias relationnels.
        # Cette couche partage personal_profile.db avec PersonalProfileMemory.
        self.people_v2 = None
        try:
            self.people_v2 = PeopleProfileMemory(
                DATA_DIR / "personal_profile.db",
                personal_event_store_provider=lambda: getattr(
                    self,
                    "personal_v2",
                    None,
                ),
            )

            if self.profile_v2 is not None:
                self.people_v2.sync_from_profile(self.profile_v2)

            if self.personal_v2 is not None:
                self.people_v2.sync_from_events(self.personal_v2)
                # V6.5.2 : Personal Memory V2 sait désormais résoudre
                # « ma copine » vers le nom canonique de la personne.
                self.personal_v2.person_reference_resolver = (
                    self.people_v2.resolve_reference_name
                )

            self.data.setdefault("meta", {})["people_profiles_v652"] = {
                "schema_version": 1,
                "updated_at": self._now(),
            }
            self.data.get("meta", {}).pop("people_profiles_v652_error", None)
            self._save()
        except Exception as exc:
            self.people_v2 = None
            self.data.setdefault("meta", {})["people_profiles_v652_error"] = str(exc)
            self._save()

    # =========================================================
    # PERSONAL PROFILE V6.5
    # =========================================================

    def personal_profile_observe(
        self,
        message: str,
        understanding,
        *,
        decision_owner: str = "",
    ) -> list[dict[str, Any]]:
        stored: list[dict[str, Any]] = []

        if self.profile_v2 is not None:
            stored = self.profile_v2.ingest_understanding(
                message,
                understanding,
                decision_owner=decision_owner,
            )

        # V6.5.2 : les informations concernant une personne sont également
        # envoyées à son profil individuel. Les questions n'écrivent rien.
        people = getattr(self, "people_v2", None)
        if people is not None:
            try:
                people.ingest(
                    message,
                    understanding,
                    profile_items=stored,
                )
            except Exception:
                pass

        return stored

    def personal_profile_context(
        self,
        query: str,
        *,
        limit: int = 14,
    ) -> str:
        if self.profile_v2 is None:
            return "(Personal Profile V6.5 indisponible)"
        return self.profile_v2.context_for(query, limit=limit)

    def personal_profile_summary(
        self,
        category: str | None = None,
    ) -> str:
        if self.profile_v2 is None:
            return "Personal Profile V6.5 indisponible."
        return self.profile_v2.summary(category=category)

    def personal_profile_status(self) -> str:
        if self.profile_v2 is None:
            return "Personal Profile V6.5 indisponible."
        return self.profile_v2.status_summary()

    def personal_profile_forget(self, query: str) -> int:
        if self.profile_v2 is None or not str(query or "").strip():
            return 0
        return self.profile_v2.forget_matching(query)


    # =========================================================
    # PEOPLE PROFILES V6.5.2
    # =========================================================

    def personal_person_response(
        self,
        message: str,
    ) -> str | None:
        people = getattr(self, "people_v2", None)
        if people is None:
            return None
        try:
            return people.direct_response(message)
        except Exception:
            return None

    def personal_people_context(
        self,
        message: str,
    ) -> str:
        people = getattr(self, "people_v2", None)
        if people is None:
            return "(People Profiles V6.5.2 indisponible)"
        try:
            return people.context_for(message)
        except Exception:
            return "(People Profiles V6.5.2 indisponible)"

    def personal_people_status(self) -> str:
        people = getattr(self, "people_v2", None)
        if people is None:
            return "People Profiles V6.5.2 indisponible."
        try:
            return people.status_summary()
        except Exception:
            return "People Profiles V6.5.2 indisponible."

    def personal_known_people(self) -> list[str]:
        people = getattr(self, "people_v2", None)
        if people is None:
            return []
        try:
            return people.known_people()
        except Exception:
            return []

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
            "relational": {
                "communication": [],
                "interests": [],
                "habits": [],
                "preferences": [],
                "relations": [],
                "history": [],
            },
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
    def _clamp(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        return max(0.0, min(1.0, numeric))

    _clamp_confidence = _clamp

    @staticmethod
    def _ascii(text: Any) -> str:
        normalized = unicodedata.normalize("NFKD", str(text).lower())
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    @classmethod
    def _slug(cls, text: Any, *, max_length: int = 80) -> str:
        value = cls._ascii(cls._clean_text(text))
        value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
        return value[:max_length] or "item"

    @classmethod
    def _has_temporal_marker(cls, text: str) -> bool:
        """Détecte les marqueurs temporels comme des mots/expressions entiers."""
        normalized = cls._ascii(cls._clean_text(text))
        for marker in cls.TEMPORAL_MARKERS:
            wanted = cls._ascii(marker)
            pattern = r"(?<![a-z0-9_])" + re.escape(wanted) + r"(?![a-z0-9_])"
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return True

        # V6.2.3 : couvre les formulations naturelles absentes de la liste
        # historique : "dimanche dernier", "mardi", "il y a 3 jours", etc.
        natural = re.sub(r"[^a-z0-9]+", " ", normalized)
        natural = " ".join(natural.split())
        if re.search(
            r"\b(?:aujourd\s+hui|avant\s+hier|ce\s+matin|ce\s+soir|cette\s+nuit|la\s+semaine\s+derniere|le\s+mois\s+dernier|ce\s+week(?:end|-end)|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\s+dernier(?:e)?)?\b",
            natural,
        ):
            return True
        if re.search(
            r"\bil y a\s+(?:\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze)\s+(?:jour|jours|semaine|semaines|mois|an|ans)\b",
            natural,
        ):
            return True
        return False


    # =========================================================
    # EVENT TIMELINE V6.2.3
    # =========================================================

    @classmethod
    def _event_date_from_text(
        cls,
        text: str,
        *,
        reference_at: Any = None,
    ) -> str | None:
        """Résout une date d'événement quand le texte la rend explicite.

        La résolution se fait relativement au moment où le souvenir a été
        raconté. C'est essentiel pour les anciens épisodes : un ancien "hier"
        ne doit pas être recalculé par rapport à la date du prochain redémarrage.
        """
        normalized = cls._ascii(cls._clean_text(text))
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        normalized = " ".join(normalized.split())
        if not normalized:
            return None

        reference = cls._parse_time(reference_at) if reference_at else None
        if reference is None:
            reference = datetime.now().astimezone()
        else:
            try:
                reference = reference.astimezone()
            except Exception:
                pass

        base = reference.replace(
            hour=12,
            minute=0,
            second=0,
            microsecond=0,
        )

        # Expressions les plus précises d'abord.
        if re.search(r"\bavant hier\b", normalized):
            return (base - timedelta(days=2)).date().isoformat()

        if re.search(r"(?<!avant )\bhier\b", normalized):
            return (base - timedelta(days=1)).date().isoformat()

        if any(
            marker in normalized
            for marker in (
                "aujourd hui",
                "ce matin",
                "cet apres midi",
                "ce soir",
                "cette nuit",
            )
        ):
            return base.date().isoformat()

        if re.search(r"\bdemain\b", normalized):
            return (base + timedelta(days=1)).date().isoformat()

        number_words = {
            "un": 1,
            "une": 1,
            "deux": 2,
            "trois": 3,
            "quatre": 4,
            "cinq": 5,
            "six": 6,
            "sept": 7,
            "huit": 8,
            "neuf": 9,
            "dix": 10,
            "onze": 11,
            "douze": 12,
            "treize": 13,
            "quatorze": 14,
            "quinze": 15,
        }
        ago = re.search(
            r"\bil y a\s+(\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze)\s+jours?\b",
            normalized,
        )
        if ago:
            raw = ago.group(1)
            days = int(raw) if raw.isdigit() else number_words.get(raw)
            if days is not None:
                return (base - timedelta(days=days)).date().isoformat()

        weekdays = {
            "lundi": 0,
            "mardi": 1,
            "mercredi": 2,
            "jeudi": 3,
            "vendredi": 4,
            "samedi": 5,
            "dimanche": 6,
        }
        weekday_match = re.search(
            r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+dernier(?:e)?\b",
            normalized,
        )
        if weekday_match:
            target_weekday = weekdays[weekday_match.group(1)]
            delta = (base.weekday() - target_weekday) % 7
            if delta == 0:
                delta = 7
            return (base - timedelta(days=delta)).date().isoformat()

        return None

    def _attach_event_date(
        self,
        text: str,
    ) -> None:
        event_date = self._event_date_from_text(
            text,
            reference_at=self._now(),
        )
        if not event_date:
            return

        wanted = self._key(text)
        for item in reversed(self.data.get("episodic", [])[-60:]):
            if not isinstance(item, dict):
                continue
            if self._key(item.get("content", "")) != wanted:
                continue
            if item.get("event_date") != event_date:
                item["event_date"] = event_date
                self._save()
            return

    def _resolved_event_date(
        self,
        item: dict[str, Any],
    ) -> str | None:
        current = self._clean_text(
            item.get("event_date", "")
        )
        if current:
            return current

        content = self._clean_text(
            item.get("content", "")
        )
        if not content:
            return None

        resolved = self._event_date_from_text(
            content,
            reference_at=item.get("created_at"),
        )
        if resolved:
            item["event_date"] = resolved
            self._save()
        return resolved

    def latest_episodic_match(
        self,
        query: str,
    ) -> dict[str, Any] | None:
        """Retourne le dernier événement vécu correspondant à la requête.

        On compare la date de l'événement, pas la date à laquelle le souvenir
        a été raconté. Les anciens épisodes sans ``event_date`` sont résolus à
        la volée à partir de leur texte et de leur ``created_at``.
        """
        # V6.3 : la base structurée SQLite est consultée en premier.
        store = getattr(self, "personal_v2", None)
        if store is not None:
            try:
                result = store.latest_match(query)
            except Exception:
                result = None
            if isinstance(result, dict) and result:
                # Compatibilité avec le format historique attendu par Paul.
                return {
                    "content": result.get("content", ""),
                    "kind": result.get("kind", "user_event"),
                    "source": result.get("source", "user"),
                    "confidence": result.get("confidence", 0.9),
                    "event_date": result.get("event_start"),
                    "event_end": result.get("event_end"),
                    "people": result.get("people", []),
                    "places": result.get("places", []),
                    "transport": result.get("transport"),
                    "transport_inferred": result.get("transport_inferred", False),
                    "created_at": result.get("recorded_at", ""),
                }

        ignored = {
            "quand", "derniere", "dernier", "fois", "pour", "la", "le",
            "les", "est", "ce", "que", "jai", "j", "ai", "je", "tu",
            "me", "moi", "souviens", "rappelle", "date", "moment",
        }
        query_tokens = {
            token
            for token in self._expanded_tokens(query)
            if token not in ignored
        }
        if not query_tokens:
            query_tokens = self._expanded_tokens(query)
        if not query_tokens:
            return None

        candidates: list[tuple[int, int, float, int, dict[str, Any]]] = []

        for index, item in enumerate(self.data.get("episodic", [])):
            if not isinstance(item, dict):
                continue
            content = self._clean_text(item.get("content", ""))
            if not content:
                continue

            content_tokens = self._expanded_tokens(content)
            overlap = len(query_tokens & content_tokens)
            if overlap <= 0:
                continue

            event_date = self._resolved_event_date(item)
            event_rank = 0
            has_event_date = 0
            if event_date:
                try:
                    event_rank = int(event_date.replace("-", ""))
                    has_event_date = 1
                except ValueError:
                    event_rank = 0

            created = self._parse_time(item.get("created_at", ""))
            created_rank = created.timestamp() if created is not None else 0.0

            candidates.append(
                (
                    overlap,
                    has_event_date,
                    float(event_rank),
                    index,
                    {
                        **dict(item),
                        "event_date": event_date,
                        "created_rank": created_rank,
                    },
                )
            )

        if not candidates:
            return None

        # D'abord la meilleure correspondance sémantique. Parmi les souvenirs
        # aussi pertinents, le plus récent dans la chronologie vécue gagne.
        best_overlap = max(row[0] for row in candidates)
        relevant = [row for row in candidates if row[0] == best_overlap]
        relevant.sort(
            key=lambda row: (
                row[1],
                row[2],
                row[4].get("created_rank", 0.0),
                row[3],
            ),
            reverse=True,
        )
        result = dict(relevant[0][4])
        result.pop("created_rank", None)
        return result

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result

    def _effective_importance(self, item: dict[str, Any]) -> float:
        """Retourne l'importance actuelle d'un souvenir relationnel.

        L'importance enregistrée reste la valeur de référence. Cette méthode
        applique seulement un vieillissement progressif en fonction de la
        dernière confirmation du souvenir. Les préférences de communication
        et les relations importantes vieillissent plus lentement que les
        habitudes ou centres d'intérêt occasionnels.
        """
        if not isinstance(item, dict):
            return 0.0

        base = self._clamp(item.get("importance", 0.65))
        if base <= 0.0:
            return 0.0

        observed = self._parse_time(
            item.get(
                "last_seen_at",
                item.get(
                    "updated_at",
                    item.get("created_at", ""),
                ),
            )
        )
        if observed is None:
            return base

        now = datetime.now(timezone.utc)
        age_days = max(
            0.0,
            (now - observed).total_seconds() / 86400.0,
        )

        if age_days <= 30:
            factor = 1.00
        elif age_days <= 90:
            factor = 0.97
        elif age_days <= 180:
            factor = 0.93
        elif age_days <= 365:
            factor = 0.88
        elif age_days <= 730:
            factor = 0.80
        else:
            factor = 0.70

        category = self._clean_text(
            item.get("category", "")
        ).lower()

        minimum_factor = {
            "communication": 0.85,
            "relations": 0.80,
            "preferences": 0.70,
            "interests": 0.65,
            "habits": 0.55,
        }.get(category, 0.60)

        source = self._clean_text(
            item.get("source", "")
        ).lower()

        if source == "user_explicit":
            minimum_factor = max(
                minimum_factor,
                0.85,
            )

        occurrences = max(
            1,
            int(item.get("occurrences", 1)),
        )
        if occurrences >= 5:
            minimum_factor = max(
                minimum_factor,
                0.80,
            )
        elif occurrences >= 3:
            minimum_factor = max(
                minimum_factor,
                0.72,
            )

        factor = max(
            factor,
            minimum_factor,
        )

        return self._clamp(
            base * factor
        )

    @classmethod
    def _latest_time_text(cls, *values: Any) -> str:
        valid: list[tuple[datetime, str]] = []
        for value in values:
            parsed = cls._parse_time(value)
            if parsed is not None:
                valid.append((parsed, str(value)))
        if not valid:
            return cls._now()
        valid.sort(key=lambda row: row[0])
        return valid[-1][1]

    @classmethod
    def _earliest_time_text(cls, *values: Any) -> str:
        valid: list[tuple[datetime, str]] = []
        for value in values:
            parsed = cls._parse_time(value)
            if parsed is not None:
                valid.append((parsed, str(value)))
        if not valid:
            return cls._now()
        valid.sort(key=lambda row: row[0])
        return valid[0][1]

    def _canonical_relational_descriptor(
        self,
        category: str,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Trouve une représentation plus structurée d'un ancien souvenir.

        Cette passe vise surtout les données créées pendant V4.7.1, par
        exemple une préférence générique « je préfère qu'on aille droit au
        but » qui doit désormais vivre dans COMMUNICATION.
        """
        content = self._clean_text(item.get("content", ""))
        if not content:
            return None

        descriptors = self._relational_descriptors(content)
        if not descriptors:
            return None

        current_key = self._clean_text(item.get("key", "")).lower()

        for descriptor in descriptors:
            if self._clean_text(descriptor.get("key", "")).lower() == current_key:
                return descriptor

        # Les anciennes préférences génériques de forme doivent être
        # reclassées en préférences de communication quand on sait le faire.
        if category == "preferences":
            for descriptor in descriptors:
                if descriptor.get("category") == "communication":
                    return descriptor

        return None

    def _merge_relational_items(
        self,
        first: dict[str, Any],
        second: dict[str, Any],
        *,
        category: str,
        key: str,
        descriptor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fusionne deux représentations du même fait sans doubler la preuve.

        ``occurrences`` utilise le maximum et non la somme : les doublons
        historiques peuvent provenir d'une migration du même message.
        """
        first_time = self._parse_time(first.get("updated_at", ""))
        second_time = self._parse_time(second.get("updated_at", ""))
        newer = second if (second_time and (not first_time or second_time >= first_time)) else first

        result = dict(newer)
        result["category"] = category
        result["key"] = key
        result["status"] = "active"
        result["occurrences"] = max(
            1,
            int(first.get("occurrences", 1) or 1),
            int(second.get("occurrences", 1) or 1),
        )
        result["importance"] = self._clamp(max(
            float(first.get("importance", 0.0) or 0.0),
            float(second.get("importance", 0.0) or 0.0),
            float((descriptor or {}).get("importance", 0.0) or 0.0),
        ))
        result["confidence"] = self._clamp(max(
            float(first.get("confidence", 0.0) or 0.0),
            float(second.get("confidence", 0.0) or 0.0),
            float((descriptor or {}).get("confidence", 0.0) or 0.0),
        ))
        result["created_at"] = self._earliest_time_text(
            first.get("created_at", ""),
            second.get("created_at", ""),
        )
        result["updated_at"] = self._latest_time_text(
            first.get("updated_at", ""),
            second.get("updated_at", ""),
        )
        result["last_seen_at"] = self._latest_time_text(
            first.get("last_seen_at", ""),
            second.get("last_seen_at", ""),
        )
        result["last_reinforced_at"] = self._latest_time_text(
            first.get("last_reinforced_at", first.get("last_seen_at", "")),
            second.get("last_reinforced_at", second.get("last_seen_at", "")),
        )
        if newer is second:
            result["last_evidence_key"] = self._clean_text(second.get("last_evidence_key", ""))
        else:
            result["last_evidence_key"] = self._clean_text(first.get("last_evidence_key", ""))

        if (
            self._clean_text(first.get("source", "")) == "user_explicit"
            or self._clean_text(second.get("source", "")) == "user_explicit"
        ):
            result["source"] = "user_explicit"

        if descriptor is not None:
            result["value"] = self._clean_text(descriptor.get("value", result.get("value", "")))
            result["content"] = self._clean_text(descriptor.get("content", result.get("content", "")))

        return result

    def _consolidate_relational_memory(self) -> dict[str, int]:
        """Répare les doublons conceptuels des premières versions V4.7."""
        relational = self.data.setdefault("relational", {})
        rebuilt: dict[str, list[dict[str, Any]]] = {
            category: [] for category in self.RELATIONAL_CATEGORIES
        }
        indexes: dict[str, dict[str, int]] = {
            category: {} for category in self.RELATIONAL_CATEGORIES
        }
        reclassified = 0
        merged = 0

        for original_category in self.RELATIONAL_CATEGORIES:
            for raw in relational.get(original_category, []):
                item = self._normalize_relational_item(raw, category=original_category)
                if item is None:
                    continue

                descriptor = self._canonical_relational_descriptor(
                    original_category,
                    item,
                )
                target_category = original_category
                target_key = self._clean_text(item.get("key", ""))

                if descriptor is not None:
                    target_category = str(descriptor.get("category", original_category))
                    target_key = self._clean_text(descriptor.get("key", target_key))
                    if target_category != original_category or target_key.lower() != self._clean_text(item.get("key", "")).lower():
                        reclassified += 1
                    item["category"] = target_category
                    item["key"] = target_key
                    item["value"] = self._clean_text(descriptor.get("value", item.get("value", "")))
                    item["content"] = self._clean_text(descriptor.get("content", item.get("content", "")))
                    item["importance"] = self._clamp(max(
                        float(item.get("importance", 0.0) or 0.0),
                        float(descriptor.get("importance", 0.0) or 0.0),
                    ))
                    item["confidence"] = self._clamp(max(
                        float(item.get("confidence", 0.0) or 0.0),
                        float(descriptor.get("confidence", 0.0) or 0.0),
                    ))

                if target_category not in rebuilt:
                    target_category = original_category

                normalized_key = target_key.lower()
                existing_index = indexes[target_category].get(normalized_key)
                if existing_index is None:
                    indexes[target_category][normalized_key] = len(rebuilt[target_category])
                    rebuilt[target_category].append(item)
                    continue

                existing = rebuilt[target_category][existing_index]
                rebuilt[target_category][existing_index] = self._merge_relational_items(
                    existing,
                    item,
                    category=target_category,
                    key=target_key,
                    descriptor=descriptor,
                )
                merged += 1

        for category in self.RELATIONAL_CATEGORIES:
            relational[category] = rebuilt[category][-self.RELATIONAL_LIMIT:]

        return {
            "reclassified": reclassified,
            "merged": merged,
        }

    def _prune_stale_emotional_current(self) -> int:
        current = self.data.setdefault("emotional", {}).setdefault("current", {})
        if not isinstance(current, dict):
            self.data["emotional"]["current"] = {}
            return 0

        now = datetime.now(timezone.utc)
        removed = 0
        for dimension in list(current):
            item = current.get(dimension)
            if not isinstance(item, dict):
                current.pop(dimension, None)
                removed += 1
                continue
            observed = self._parse_time(item.get("observed_at", ""))
            maximum = float(self.EMOTIONAL_CURRENT_MAX_AGE_HOURS.get(dimension, 3.0))
            if observed is None:
                current.pop(dimension, None)
                removed += 1
                continue
            age_hours = max(0.0, (now - observed).total_seconds() / 3600.0)
            if age_hours > maximum:
                current.pop(dimension, None)
                removed += 1

        return removed

    def run_maintenance(self, *, persist: bool = True) -> dict[str, Any]:
        """Lance une maintenance sûre sur la mémoire personnelle active."""
        before = self.stats()
        relational = self._consolidate_relational_memory()
        stale_emotions = self._prune_stale_emotional_current()

        # Le sanitize retire aussi d'éventuelles anciennes missions terminales
        # restées dans ``working`` et normalise les couches legacy.
        working_before = len(self.data.get("working", []))
        self._sanitize_all()
        working_removed = max(0, working_before - len(self.data.get("working", [])))

        if persist:
            self._save()

        after = self.stats()
        return {
            "reclassified": int(relational.get("reclassified", 0)),
            "merged": int(relational.get("merged", 0)),
            "stale_emotions_removed": stale_emotions,
            "working_removed": working_removed,
            "before": before,
            "after": after,
        }

    def _save(self) -> None:
        meta = self.data.setdefault("meta", {})
        meta["updated_at"] = self._now()
        self.data["schema_version"] = self.SCHEMA_VERSION
        self.store.save(self.data)

    def _set_memory_action(self, action: dict[str, Any] | None) -> None:
        self._last_memory_action = dict(action) if isinstance(action, dict) else None

    def consume_memory_action(self) -> dict[str, Any] | None:
        """Retourne puis efface l'action mémoire du message courant."""
        action = self._last_memory_action
        self._last_memory_action = None
        return action

    def peek_memory_action(self) -> dict[str, Any] | None:
        action = self._last_memory_action
        return dict(action) if isinstance(action, dict) else None

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
    def explicit_forget_fact(cls, text: str) -> str | None:
        clean = cls._clean_text(text)
        for pattern in cls.FORGET_PATTERNS:
            replaced = re.sub(
                pattern,
                "",
                clean,
                count=1,
                flags=re.IGNORECASE,
            )
            if replaced != clean:
                cleaned = replaced.strip(" .!?,;:")
                return cleaned or None
        return None

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
        return any(marker in lower for marker in (
            "mission terminee", "mission echouee", "mission annulee",
            "mission refusee", "attend ton autorisation", "developer",
            "researcher", "tester", "ai_worker", "task_",
        ))

    @classmethod
    def _looks_task_request_text(cls, text: str) -> bool:
        """Repère une vraie demande de travail sans confondre une habitude.

        Exemples considérés comme demandes :
        - "Analyse tes fichiers..."
        - "Peux-tu modifier workspace/app.py ?"
        - "Je veux que tu testes ce fichier."

        Exemples NON considérés comme demandes :
        - "D'habitude je teste le code le soir."
        - "Je préfère que tu me donnes le fichier complet quand tu modifies du code."
        """
        clean = cls._clean_text(text)
        if not clean:
            return False

        normalized = cls._ascii(clean)

        personal_starters = (
            "d'habitude ", "habituellement ", "en general je ",
            "en general, je ", "j'aime ", "j'adore ", "je deteste ",
            "mon poisson prefere est ", "ma copine s'appelle ",
            "mon compagnon s'appelle ", "ma compagne s'appelle ",
        )
        if normalized.startswith(personal_starters):
            return False

        action = (
            r"(?:analyse|analyser|cree|creer|modifie|modifier|corrige|corriger|"
            r"ajoute|ajouter|supprime|supprimer|remplace|remplacer|"
            r"teste|tester|verifie|verifier|compile|compiler|"
            r"recherche|rechercher|cherche|planifie|planifier|prepare|preparer)"
        )

        if re.search(rf"^\s*{action}\b", normalized):
            return True

        request_prefixes = (
            "peux-tu ", "peux tu ", "pourrais-tu ", "pourrais tu ",
            "tu peux ", "est-ce que tu peux ", "est ce que tu peux ",
            "je veux que tu ", "j'aimerais que tu ", "j aimerais que tu ",
            "je voudrais que tu ", "merci de ", "il faut que tu ",
        )

        if any(normalized.startswith(prefix) for prefix in request_prefixes):
            return bool(re.search(rf"\b{action}\b", normalized))

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

        old_relational = loaded.get("relational", {})
        if isinstance(old_relational, dict):
            for category in self.RELATIONAL_CATEGORIES:
                values = old_relational.get(category, [])
                result["relational"][category] = values if isinstance(values, list) else []
            history = old_relational.get("history", [])
            result["relational"]["history"] = history if isinstance(history, list) else []

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
        had_emotional_layer = (
            isinstance(emotional, dict)
            and (
                "current" in emotional
                or "history" in emotional
            )
        )
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

        # Le backfill émotionnel ne sert qu'aux très anciennes mémoires
        # qui n'avaient aucune couche emotional. Une mémoire V4.6+ ne doit
        # jamais ressusciter un ancien stress/une ancienne fatigue invalidés.
        result["meta"]["needs_emotional_backfill"] = not had_emotional_layer

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
        now = self._now()
        created_at = str(item.get("created_at", item.get("at", now)))
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
            "confidence": self._clamp(item.get("confidence", default_confidence)),
            "occurrences": occurrences,
            "created_at": created_at,
            "updated_at": updated_at,
            "last_seen_at": last_seen_at,
        }

    def _normalize_relational_item(
        self,
        item: Any,
        *,
        category: str,
    ) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        key = self._clean_text(item.get("key", ""))
        value = self._clean_text(item.get("value", ""))
        content = self._clean_text(item.get("content", value))
        if not key or not value or not content:
            return None
        now = self._now()
        try:
            occurrences = max(1, int(item.get("occurrences", 1)))
        except (TypeError, ValueError):
            occurrences = 1
        return {
            "category": category,
            "key": key,
            "value": value,
            "content": content,
            "source": self._clean_text(item.get("source", "legacy")) or "legacy",
            "importance": self._clamp(item.get("importance", 0.65)),
            "confidence": self._clamp(item.get("confidence", 0.85)),
            "occurrences": occurrences,
            "created_at": str(item.get("created_at", now)),
            "updated_at": str(item.get("updated_at", now)),
            "last_seen_at": str(item.get("last_seen_at", item.get("updated_at", now))),
            "last_reinforced_at": str(
                item.get(
                    "last_reinforced_at",
                    item.get("last_seen_at", item.get("updated_at", now)),
                )
            ),
            "last_evidence_key": self._clean_text(item.get("last_evidence_key", "")),
            "status": "active",
        }

    def _sanitize_all(self) -> None:
        session: list[dict[str, Any]] = []
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

        profile: list[dict[str, Any]] = []
        seen_profile: set[str] = set()
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
                "confidence": self._clamp(raw.get("confidence", 0.95)),
                "created_at": str(raw.get("created_at", raw.get("at", now))),
                "updated_at": str(raw.get("updated_at", raw.get("at", now))),
            })
        self.data["profile"] = list(reversed(profile))[-self.PROFILE_LIMIT:]

        relational = self.data.setdefault("relational", {})
        for category in self.RELATIONAL_CATEGORIES:
            clean_items: list[dict[str, Any]] = []
            by_rel_key: dict[str, dict[str, Any]] = {}
            for raw in relational.get(category, []):
                item = self._normalize_relational_item(raw, category=category)
                if item is None:
                    continue
                normalized_key = item["key"].lower()
                existing = by_rel_key.get(normalized_key)
                if existing is None:
                    by_rel_key[normalized_key] = item
                    clean_items.append(item)
                    continue
                existing_time = self._parse_time(existing.get("updated_at", ""))
                item_time = self._parse_time(item.get("updated_at", ""))
                if item_time and (not existing_time or item_time >= existing_time):
                    clean_items.remove(existing)
                    by_rel_key[normalized_key] = item
                    clean_items.append(item)
            relational[category] = clean_items[-self.RELATIONAL_LIMIT:]

        history: list[dict[str, Any]] = []
        for raw in relational.get("history", []):
            if not isinstance(raw, dict):
                continue
            content = self._clean_text(raw.get("content", raw.get("value", "")))
            if not content:
                continue
            history.append(dict(raw))
        relational["history"] = history[-self.RELATIONAL_HISTORY_LIMIT:]

        personal_candidates = list(self.data.get("episodic", []))
        operational_candidates = list(self.data.get("operational", []))
        personal: list[dict[str, Any]] = []
        operational: list[dict[str, Any]] = []
        personal_seen: set[str] = set()
        operational_seen: set[str] = set()
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
            content = self._clean_text(item.get("content", ""))

            # Nettoyage V4.7.1.1 : les préférences/habitudes/relation ne sont
            # pas des événements datés. Les anciennes demandes de travail
            # enregistrées par erreur ne sont pas non plus des souvenirs perso.
            if (
                not target_operational
                and (
                    (
                        self._relational_descriptors(content)
                        and not self._has_temporal_marker(content)
                    )
                    or self._looks_task_request_text(content)
                )
            ):
                continue

            key = self._key(content)
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

        working: list[dict[str, Any]] = []
        working_seen: set[str] = set()
        for raw in reversed(self.data.get("working", [])):
            if not isinstance(raw, dict):
                continue
            key = self._clean_text(raw.get("key", ""))
            content = self._clean_text(raw.get("content", ""))
            if not key or not content or key.lower() in working_seen:
                continue
            normalized_content = self._ascii(content)
            if any(
                self._ascii(marker) in normalized_content
                for marker in self.TERMINAL_WORKING_MARKERS
            ):
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
            confidence = self._clamp(item.get("confidence", 0.0))
            if value and confidence > 0:
                clean_current[dimension] = {
                    "value": value,
                    "confidence": confidence,
                    "observed_at": observed_at,
                    "source": source,
                }

        clean_history: list[dict[str, Any]] = []
        for item in history[-self.EMOTIONAL_HISTORY_LIMIT:]:
            if not isinstance(item, dict):
                continue
            source = self._clean_text(item.get("source", ""))
            at = str(item.get("at", self._now()))
            signals = item.get("signals", {})
            if not isinstance(signals, dict):
                continue
            normalized_signals: dict[str, dict[str, Any]] = {}
            for dimension, signal in signals.items():
                if dimension not in self.EMOTIONAL_LABELS or not isinstance(signal, dict):
                    continue
                value = self._clean_text(signal.get("value", ""))
                confidence = self._clamp(signal.get("confidence", 0.0))
                if value and confidence > 0:
                    normalized_signals[dimension] = {
                        "value": value,
                        "confidence": confidence,
                    }
            if normalized_signals:
                clean_history.append({"at": at, "source": source, "signals": normalized_signals})

        # Réconciliation de sécurité au démarrage.
        # Si l'historique contient une amélioration globale plus récente que
        # d'anciens signaux négatifs, on applique la même invalidation que
        # observe_emotional_state(). Cela nettoie aussi les états négatifs
        # "ressuscités" par le bug de backfill des versions précédentes.
        latest_improvement_at: datetime | None = None
        latest_improvement_signals: dict[str, Any] = {}
        for history_item in clean_history:
            source = self._clean_text(history_item.get("source", ""))
            normalized_source = self._ascii(source)
            if not any(
                re.search(pattern, normalized_source, flags=re.IGNORECASE)
                for pattern in self.GLOBAL_IMPROVEMENT_PATTERNS
            ):
                continue
            observed = self._parse_time(history_item.get("at", ""))
            if observed is None:
                continue
            if (
                latest_improvement_at is None
                or observed >= latest_improvement_at
            ):
                latest_improvement_at = observed
                latest_improvement_signals = (
                    history_item.get("signals", {})
                    if isinstance(history_item.get("signals", {}), dict)
                    else {}
                )

        if latest_improvement_at is not None:
            for dimension, negative_values in self.NEGATIVE_EMOTIONAL_VALUES.items():
                if dimension in latest_improvement_signals:
                    continue
                existing = clean_current.get(dimension)
                if not isinstance(existing, dict):
                    continue
                if str(existing.get("value", "")) not in negative_values:
                    continue
                observed = self._parse_time(existing.get("observed_at", ""))
                if observed is not None and observed <= latest_improvement_at:
                    clean_current.pop(dimension, None)

        # Backfill uniquement pour les anciennes mémoires sans couche
        # émotionnelle. Si V4.6+ a volontairement supprimé une dimension
        # (ex. fatigue/stress après "ça va mieux"), on ne la recrée pas.
        needs_backfill = bool(
            self.data.get("meta", {}).get("needs_emotional_backfill", False)
        )
        if needs_backfill and not clean_current:
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
                    if dimension not in clean_current:
                        clean_current[dimension] = {
                            "value": signal["value"],
                            "confidence": self._clamp(signal["confidence"]),
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

        self.data.setdefault("meta", {})["needs_emotional_backfill"] = False

        self.data["emotional"] = {
            "current": clean_current,
            "history": clean_history[-self.EMOTIONAL_HISTORY_LIMIT:],
        }
        self.data["episodic"] = [
            item for item in self.data["episodic"]
            if not isinstance(item, dict) or str(item.get("kind", "")) != "emotional_observation"
        ][-self.EPISODIC_LIMIT:]

    # =========================================================
    # RELATIONAL MEMORY
    # =========================================================

    @classmethod
    def _topic_mentions(cls, text: str) -> list[str]:
        normalized = cls._ascii(text)
        tokens = set(re.findall(r"[a-z0-9_-]{2,}", normalized))
        result: list[str] = []
        for topic, words in cls.TOPIC_GROUPS.items():
            normalized_words = {cls._ascii(word) for word in words}
            if tokens & normalized_words or any(
                " " in word and cls._ascii(word) in normalized
                for word in words
            ):
                result.append(topic)
        return result

    @classmethod
    def _interest_importance(cls, text: str) -> float:
        value = cls._ascii(text)
        if any(marker in value for marker in (
            "tres important", "vraiment important", "super important",
            "passion", "passionne", "passionnee",
        )):
            return 0.90
        if any(marker in value for marker in ("j'adore", "jadore")):
            return 0.80
        if any(marker in value for marker in ("important pour moi", "beaucoup")):
            return 0.82
        return 0.68

    @classmethod
    def _relational_descriptors(cls, text: str) -> list[dict[str, Any]]:
        clean = cls._clean_text(text)
        if not clean or cls._looks_like_question(clean):
            return []

        # Les corrections naturelles doivent viser la même clé relationnelle.
        # Exemple : "Finalement mon poisson préféré est le tétra amande."
        clean = re.sub(
            r"^\s*(?:finalement|en fait|désormais|desormais|maintenant|je corrige(?:\s*[:,])?|corrige(?:\s*[:,])?)\s*[:,]?\s*",
            "",
            clean,
            count=1,
            flags=re.IGNORECASE,
        ).strip() or clean

        normalized = cls._ascii(clean)
        descriptors: list[dict[str, Any]] = []

        communication_markers = (
            "je prefere que tu", "je prefere qu'on", "je prefere qu on",
            "je veux que tu", "reponds", "repond moi",
            "droit au but", "direct", "sans blabla", "sans bla bla",
            "etape par etape", "fichier complet", "fichiers complets",
            "code complet",
        )
        looks_communication = any(marker in normalized for marker in communication_markers)

        if looks_communication and any(marker in normalized for marker in (
            "droit au but", "direct", "sans blabla", "sans bla bla",
        )):
            descriptors.append({
                "category": "communication",
                "key": "response_directness",
                "value": "direct",
                "content": "Préfère des réponses directes et allant droit au but.",
                "importance": 0.92,
                "confidence": 0.95,
            })

        if looks_communication and "etape par etape" in normalized:
            descriptors.append({
                "category": "communication",
                "key": "step_by_step",
                "value": "step_by_step",
                "content": "Préfère avancer étape par étape quand une procédure est technique.",
                "importance": 0.88,
                "confidence": 0.94,
            })

        if looks_communication and any(marker in normalized for marker in (
            "fichier complet", "fichiers complets", "code complet",
        )):
            descriptors.append({
                "category": "communication",
                "key": "code_delivery",
                "value": "full_files",
                "content": "Préfère recevoir le fichier complet lorsqu'un fichier de code doit être modifié.",
                "importance": 0.98,
                "confidence": 0.99,
            })

        favorite = re.search(
            r"^mon\s+(.{1,80}?)\s+(?:préféré|prefere)\s+est\s+(.{2,120})$",
            clean,
            flags=re.IGNORECASE,
        )
        if favorite:
            subject = cls._clean_text(favorite.group(1))
            value = cls._clean_text(favorite.group(2)).rstrip(" .!?,;:")
            descriptors.append({
                "category": "preferences",
                "key": f"favorite:{cls._slug(subject)}",
                "value": value,
                "content": f"{subject.capitalize()} préféré : {value}",
                "importance": 0.78,
                "confidence": 0.96,
            })

        planted_aquarium = (
            any(word in normalized for word in ("aquarium", "aquariums", "bac", "bacs"))
            and any(word in normalized for word in (
                "tres plante", "tres plantes", "bien plante", "bien plantes",
            ))
            and any(word in normalized for word in (
                "j'aime", "jaime", "j'adore", "jadore", "je prefere",
            ))
        )
        if planted_aquarium:
            descriptors.append({
                "category": "preferences",
                "key": "aquarium_style",
                "value": "very_planted",
                "content": "Préfère les aquariums très plantés.",
                "importance": 0.82,
                "confidence": 0.94,
            })

        relation = re.search(
            r"^(?:ma|mon)\s+(copine|compagnon|compagne|femme|mari|frère|frere|sœur|soeur|mère|mere|père|pere|ami|amie)\s+s['’]?appelle\s+([A-Za-zÀ-ÿ'-]{2,60})\b",
            clean,
            flags=re.IGNORECASE,
        )
        if relation:
            role = cls._ascii(relation.group(1))
            name = cls._clean_text(relation.group(2))
            descriptors.append({
                "category": "relations",
                "key": f"person:{cls._slug(role)}",
                "value": name,
                "content": f"{relation.group(1).capitalize()} : {name}",
                "importance": 0.90,
                "confidence": 0.98,
            })

        habit_patterns = (
            r"^d'habitude\s+.{2,180}$", r"^d’habitude\s+.{2,180}$",
            r"^habituellement\s+.{2,180}$", r"^en général,?\s+je\s+.{2,180}$",
            r"^en general,?\s+je\s+.{2,180}$", r"^je\s+.{1,100}\s+tous les jours\b.*$",
            r"^je\s+.{1,100}\s+chaque semaine\b.*$",
        )
        if any(re.search(pattern, clean, flags=re.IGNORECASE) for pattern in habit_patterns):
            descriptors.append({
                "category": "habits",
                "key": f"habit:{cls._slug(clean, max_length=60)}",
                "value": clean,
                "content": clean,
                "importance": 0.62,
                "confidence": 0.84,
            })

        topics = cls._topic_mentions(clean)
        interest_signal = any(marker in normalized for marker in (
            "j'aime", "jaime", "j'adore", "jadore", "je m'interesse",
            "je suis passionne", "je suis passionnee", "important pour moi",
            "importante pour moi", "compte beaucoup pour moi",
            "m'interesse beaucoup", "m’intéresse beaucoup",
        ))
        if topics and interest_signal:
            importance = cls._interest_importance(clean)
            for topic in topics:
                descriptors.append({
                    "category": "interests",
                    "key": f"topic:{topic}",
                    "value": cls.TOPIC_LABELS.get(topic, topic),
                    "content": f"Centre d'intérêt : {cls.TOPIC_LABELS.get(topic, topic)}",
                    "importance": importance,
                    "confidence": 0.90,
                })

        generic_preference = any(re.search(pattern, clean, flags=re.IGNORECASE) for pattern in (
            r"^je préfère\s+.{2,180}$", r"^je prefere\s+.{2,180}$",
            r"^je n'aime pas\s+.{2,180}$", r"^je n’aime pas\s+.{2,180}$",
            r"^j'aime pas\s+.{2,180}$", r"^j’aime pas\s+.{2,180}$",
            r"^je déteste\s+.{2,180}$", r"^je deteste\s+.{2,180}$",
        ))
        if generic_preference and not looks_communication and favorite is None:
            descriptors.append({
                "category": "preferences",
                "key": f"preference:{cls._slug(clean, max_length=60)}",
                "value": clean,
                "content": clean,
                "importance": 0.68,
                "confidence": 0.88,
            })

        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for item in descriptors:
            unique[(item["category"], item["key"])] = item
        return list(unique.values())

    def _archive_relational(
        self,
        item: dict[str, Any],
        *,
        reason: str,
        replacement: str | None = None,
    ) -> None:
        now = self._now()

        if reason == "forgotten":
            # Un oubli explicite ne doit pas conserver la donnée oubliée dans
            # un historique caché. On ne garde qu'un tombstone technique.
            archived = {
                "category": self._clean_text(item.get("category", "")),
                "key": self._clean_text(item.get("key", "")),
                "status": "forgotten",
                "archived_at": now,
                "redacted": True,
            }
        else:
            archived = dict(item)
            archived["status"] = reason
            archived["archived_at"] = now
            if replacement:
                archived["replaced_by"] = replacement

        self.data["relational"]["history"].append(archived)
        self.data["relational"]["history"] = (
            self.data["relational"]["history"][-self.RELATIONAL_HISTORY_LIMIT:]
        )

    def remember_relational(
        self,
        *,
        category: str,
        key: str,
        value: str,
        content: str,
        importance: float = 0.65,
        confidence: float = 0.85,
        source: str = "automatic",
        occurrences: int = 1,
        created_at: str | None = None,
        updated_at: str | None = None,
        last_seen_at: str | None = None,
        evidence: str = "",
        persist: bool = True,
    ) -> dict[str, Any] | None:
        if category not in self.RELATIONAL_CATEGORIES:
            return None
        key = self._clean_text(key)
        value = self._clean_text(value)
        content = self._clean_text(content)
        if not key or not value or not content:
            return None

        now = self._now()
        evidence_key = self._key(evidence) if evidence else ""
        bucket = self.data["relational"].setdefault(category, [])
        wanted_key = key.lower()

        for existing in list(bucket):
            if not isinstance(existing, dict):
                continue
            if self._clean_text(existing.get("key", "")).lower() != wanted_key:
                continue

            old_value = self._key(existing.get("value", ""))
            new_value = self._key(value)

            if old_value == new_value:
                increment = max(1, int(occurrences))
                old_occurrences = max(1, int(existing.get("occurrences", 1)))

                # Une même assertion reçue deux fois quasi instantanément
                # (double envoi Telegram, double clic, retry HTTP) ne doit pas
                # gonfler artificiellement le nombre de confirmations.
                should_reinforce = True
                last_reinforced = self._parse_time(
                    existing.get(
                        "last_reinforced_at",
                        existing.get("last_seen_at", ""),
                    )
                )
                now_dt = self._parse_time(now)
                if last_reinforced is not None and now_dt is not None:
                    elapsed = max(0.0, (now_dt - last_reinforced).total_seconds())
                    same_evidence = bool(
                        evidence_key
                        and evidence_key == self._clean_text(existing.get("last_evidence_key", ""))
                    )
                    if (
                        same_evidence
                        and elapsed < self.RELATIONAL_REINFORCEMENT_COOLDOWN_SECONDS
                    ):
                        should_reinforce = False

                if should_reinforce:
                    existing["occurrences"] = old_occurrences + increment
                    existing["importance"] = self._clamp(
                        max(float(existing.get("importance", 0.0)), importance)
                        + min(0.025 * increment, 0.10)
                    )
                    existing["confidence"] = self._clamp(
                        max(float(existing.get("confidence", 0.0)), confidence)
                        + min(0.01 * increment, 0.05)
                    )
                    existing["last_reinforced_at"] = last_seen_at or now
                    if evidence_key:
                        existing["last_evidence_key"] = evidence_key
                else:
                    existing["occurrences"] = old_occurrences
                    existing["importance"] = self._clamp(
                        max(float(existing.get("importance", 0.0)), importance)
                    )
                    existing["confidence"] = self._clamp(
                        max(float(existing.get("confidence", 0.0)), confidence)
                    )

                existing["content"] = content
                existing["source"] = source if source == "user_explicit" else existing.get("source", source)
                existing["last_seen_at"] = last_seen_at or now
                existing["updated_at"] = updated_at or now
                existing["status"] = "active"
                if persist:
                    self._save()
                return existing

            self._archive_relational(existing, reason="superseded", replacement=value)
            bucket.remove(existing)
            break

        item = {
            "category": category,
            "key": key,
            "value": value,
            "content": content,
            "source": source,
            "importance": self._clamp(importance),
            "confidence": self._clamp(confidence),
            "occurrences": max(1, int(occurrences)),
            "created_at": created_at or now,
            "updated_at": updated_at or now,
            "last_seen_at": last_seen_at or updated_at or now,
            "last_reinforced_at": last_seen_at or updated_at or now,
            "last_evidence_key": evidence_key,
            "status": "active",
        }
        bucket.append(item)
        self.data["relational"][category] = bucket[-self.RELATIONAL_LIMIT:]
        if persist:
            self._save()
        return item

    def _extract_relational(
        self,
        text: str,
        *,
        source: str = "automatic",
        confidence_boost: float = 0.0,
        persist: bool = True,
        track_action: bool = True,
    ) -> int:
        descriptors = self._relational_descriptors(text)
        changes: list[dict[str, Any]] = []

        for descriptor in descriptors:
            category = descriptor["category"]
            wanted_key = self._clean_text(descriptor["key"]).lower()
            wanted_value = self._key(descriptor["value"])
            bucket = self.data["relational"].setdefault(category, [])

            existing = next(
                (
                    candidate
                    for candidate in bucket
                    if (
                        isinstance(candidate, dict)
                        and self._clean_text(candidate.get("key", "")).lower()
                        == wanted_key
                    )
                ),
                None,
            )

            previous_occurrences = (
                max(1, int(existing.get("occurrences", 1)))
                if isinstance(existing, dict)
                else 0
            )

            if existing is None:
                change_status = "added"
                previous_content = ""
            elif self._key(existing.get("value", "")) == wanted_value:
                change_status = "reinforced"
                previous_content = self._clean_text(existing.get("content", ""))
            else:
                change_status = "replaced"
                previous_content = self._clean_text(existing.get("content", ""))

            result = self.remember_relational(
                category=category,
                key=descriptor["key"],
                value=descriptor["value"],
                content=descriptor["content"],
                importance=descriptor["importance"],
                confidence=self._clamp(descriptor["confidence"] + confidence_boost),
                source=source,
                evidence=self._clean_text(text),
                persist=False,
            )

            if result is not None:
                if (
                    change_status == "reinforced"
                    and int(result.get("occurrences", 1)) <= previous_occurrences
                ):
                    change_status = "unchanged"

                changes.append({
                    "status": change_status,
                    "category": category,
                    "key": descriptor["key"],
                    "value": descriptor["value"],
                    "content": descriptor["content"],
                    "previous_content": previous_content,
                    "occurrences": int(result.get("occurrences", 1)),
                })

        if descriptors and persist:
            self._save()

        if changes and track_action:
            self._set_memory_action({
                "type": "relational_update",
                "source_text": self._clean_text(text),
                "changes": changes,
            })

        return len(descriptors)

    @classmethod
    def _forget_direct_keys(cls, target: str) -> set[str]:
        clean = cls._clean_text(target)
        normalized = cls._ascii(clean)
        keys: set[str] = set()

        favorite = re.search(
            r"(?:mon|ma|mes|le|la|les)?\s*(.{1,80}?)\s+(?:préféré|préférée|prefere|preferee)",
            clean,
            flags=re.IGNORECASE,
        )
        if favorite:
            subject = cls._clean_text(favorite.group(1))
            if subject:
                keys.add(f"favorite:{cls._slug(subject)}")

        role_match = re.search(
            r"\b(copine|compagnon|compagne|femme|mari|frère|frere|sœur|soeur|mère|mere|père|pere|ami|amie)\b",
            clean,
            flags=re.IGNORECASE,
        )
        if role_match:
            keys.add(f"person:{cls._slug(cls._ascii(role_match.group(1)))}")

        if any(marker in normalized for marker in ("fichier complet", "fichiers complets", "code complet")):
            keys.add("code_delivery")
        if any(marker in normalized for marker in ("droit au but", "reponse directe", "reponses directes")):
            keys.add("response_directness")
        if "etape par etape" in normalized:
            keys.add("step_by_step")

        explicit_topic_markers = {
            "aquariophilie": ("aquariophilie",),
            "agent_os": ("agent-os", "agent os", "agents ia"),
            "domotique": ("domotique", "home assistant", "homeassistant"),
            "cuisine": ("cuisine",),
        }
        for topic, markers in explicit_topic_markers.items():
            if any(marker in normalized for marker in markers):
                keys.add(f"topic:{topic}")

        return keys

    @classmethod
    def _forget_matches_text(cls, target: str, searchable: str) -> bool:
        # Pour un oubli explicite on reste strict : les synonymes thématiques
        # ne doivent pas transformer "oublie mon poisson préféré" en
        # "oublie tout mon intérêt pour l'aquariophilie".
        query_tokens = cls._tokens(target)
        if not query_tokens:
            return False
        memory_tokens = cls._tokens(searchable)
        overlap = len(query_tokens & memory_tokens)
        if overlap <= 0:
            return False
        if len(query_tokens) == 1:
            return overlap == 1
        return (overlap / len(query_tokens)) >= 0.60

    def forget_personal(
        self,
        target: str,
        *,
        source: str = "user_explicit",
        persist: bool = True,
        track_action: bool = True,
    ) -> dict[str, Any]:
        """Oublie une information personnelle active sans toucher aux missions.

        Les souvenirs relationnels explicitement oubliés sont remplacés dans
        l'historique par un tombstone redacted : la valeur elle-même n'est pas
        conservée. Les souvenirs legacy correspondants sont également retirés.
        """
        clean = self._clean_text(target).strip(" .!?,;:")
        result: dict[str, Any] = {
            "type": "forget",
            "target": clean,
            "count": 0,
            "categories": [],
            "forgotten_labels": [],
            "source": source,
        }

        if not clean:
            if track_action:
                self._set_memory_action(result)
            return result

        direct_keys = {key.lower() for key in self._forget_direct_keys(clean)}
        forgotten_values: set[str] = set()
        changed = False

        for category in self.RELATIONAL_CATEGORIES:
            bucket = self.data["relational"].setdefault(category, [])
            kept: list[dict[str, Any]] = []
            for item in bucket:
                if not isinstance(item, dict):
                    continue
                key = self._clean_text(item.get("key", "")).lower()
                searchable = " ".join([
                    key,
                    self._clean_text(item.get("value", "")),
                    self._clean_text(item.get("content", "")),
                ])
                matched = (
                    key in direct_keys
                    or self._forget_matches_text(clean, searchable)
                )
                if not matched:
                    kept.append(item)
                    continue

                label = self._clean_text(item.get("content", ""))
                forgotten_value = self._clean_text(item.get("value", ""))
                if forgotten_value:
                    forgotten_values.add(forgotten_value)
                self._archive_relational(item, reason="forgotten")
                result["count"] += 1
                if category not in result["categories"]:
                    result["categories"].append(category)
                if label:
                    result["forgotten_labels"].append(label)
                changed = True

            self.data["relational"][category] = kept[-self.RELATIONAL_LIMIT:]

        # Un oubli explicite doit aussi nettoyer les anciennes versions
        # superseded de la même information. Sinon /memoryhistory pourrait
        # encore révéler une valeur que l'utilisateur a demandé d'oublier.
        clean_history: list[dict[str, Any]] = []
        scrubbed_history_keys: set[tuple[str, str]] = set()
        existing_tombstones: set[tuple[str, str]] = set()

        for item in self.data["relational"].get("history", []):
            if not isinstance(item, dict):
                continue

            category = self._clean_text(item.get("category", ""))
            key = self._clean_text(item.get("key", "")).lower()
            status = self._clean_text(item.get("status", ""))
            redacted = bool(item.get("redacted"))

            if status == "forgotten" and redacted:
                clean_history.append(item)
                existing_tombstones.add((category, key))
                continue

            searchable = " ".join([
                key,
                self._clean_text(item.get("value", "")),
                self._clean_text(item.get("content", "")),
                self._clean_text(item.get("replaced_by", "")),
            ])

            if (
                key in direct_keys
                or self._forget_matches_text(clean, searchable)
            ):
                for candidate_value in (
                    item.get("value", ""),
                    item.get("replaced_by", ""),
                ):
                    candidate_value = self._clean_text(candidate_value)
                    if candidate_value:
                        forgotten_values.add(candidate_value)
                scrubbed_history_keys.add((category, key))
                result["count"] += 1
                changed = True
                continue

            clean_history.append(item)

        for category, key in sorted(scrubbed_history_keys):
            if (category, key) in existing_tombstones:
                continue
            clean_history.append({
                "category": category,
                "key": key,
                "status": "forgotten",
                "archived_at": self._now(),
                "redacted": True,
            })

        self.data["relational"]["history"] = (
            clean_history[-self.RELATIONAL_HISTORY_LIMIT:]
        )

        # Profil stable : on ne retire que les clés clairement visées.
        normalized = self._ascii(clean)
        profile_keys: set[str] = set()
        if any(marker in normalized for marker in ("prenom", "mon nom", "comment je m'appelle", "comment je m appelle")):
            profile_keys.add("first_name")
        if any(marker in normalized for marker in ("ou j'habite", "ou j habite", "adresse", "lieu de vie", "location")):
            profile_keys.add("location")

        if profile_keys:
            kept_profile = []
            for item in self.data.get("profile", []):
                if not isinstance(item, dict):
                    continue
                key = self._clean_text(item.get("key", ""))
                if key in profile_keys:
                    profile_value = self._clean_text(item.get("value", ""))
                    if profile_value:
                        forgotten_values.add(profile_value)
                    result["count"] += 1
                    if "profile" not in result["categories"]:
                        result["categories"].append("profile")
                    changed = True
                else:
                    kept_profile.append(item)
            self.data["profile"] = kept_profile[-self.PROFILE_LIMIT:]

        # Nettoyage des anciennes couches personnelles afin qu'une donnée
        # oubliée ne puisse pas réapparaître via le moteur legacy.
        for bucket_name, limit in (
            ("long_term", self.LONG_TERM_LIMIT),
            ("episodic", self.EPISODIC_LIMIT),
        ):
            kept_items = []
            for item in self.data.get(bucket_name, []):
                if not isinstance(item, dict):
                    continue
                content = self._clean_text(item.get("content", ""))
                if (
                    content
                    and not self._is_operational_entry(item)
                    and self._forget_matches_text(clean, content)
                ):
                    result["count"] += 1
                    if bucket_name not in result["categories"]:
                        result["categories"].append(bucket_name)
                    changed = True
                    continue
                kept_items.append(item)
            self.data[bucket_name] = kept_items[-limit:]

        # L'oubli doit aussi rendre la donnée inaccessible depuis la
        # conversation récente. Sans ce nettoyage, le LLM pourrait retrouver
        # une valeur supprimée dans un ancien message utilisateur/assistant.
        session_removed = 0
        if forgotten_values:
            normalized_values = [
                self._ascii(value)
                for value in forgotten_values
                if len(self._clean_text(value)) >= 2
            ]
            kept_session: list[dict[str, Any]] = []
            for item in self.data.get("session", []):
                if not isinstance(item, dict):
                    continue
                content = self._clean_text(item.get("content", ""))
                normalized_content = self._ascii(content)
                if content and any(
                    value and value in normalized_content
                    for value in normalized_values
                ):
                    session_removed += 1
                    changed = True
                    continue
                kept_session.append(item)
            self.data["session"] = kept_session[-self.SESSION_LIMIT:]

        result["session_removed"] = session_removed
        # Valeurs internes utilisées par les autres couches de contexte
        # (notamment le fil conversationnel persistant) pour appliquer le
        # même oubli. Elles ne sont jamais affichées à l'utilisateur.
        result["forgotten_values"] = sorted(forgotten_values)

        # V6.3 : un oubli explicite s'applique aussi à la base SQLite.
        if persist:
            store = getattr(self, "personal_v2", None)
            if store is not None:
                try:
                    removed_v2 = int(store.forget(clean))
                except Exception:
                    removed_v2 = 0
                if removed_v2 > 0:
                    result["count"] += removed_v2
                    if "personal_v2" not in result["categories"]:
                        result["categories"].append("personal_v2")
                    changed = True

        if changed and persist:
            self._save()

        if track_action:
            self._set_memory_action(result)

        return result

    def _migrate_legacy_relational(self) -> None:
        """Consolide les anciens long_term vers relational sans écraser le récent.

        V4.7.1.1 fait de ``relational`` la source de vérité pour tout souvenir
        qu'on sait structurer. Un ancien long_term déjà représenté est retiré
        afin d'éviter les doublons et surtout les contradictions obsolètes.
        """
        marker = self.data.setdefault("meta", {}).get("relational_migration")
        if marker == self.SCHEMA_VERSION:
            return

        remaining_long_term: list[dict[str, Any]] = []

        for item in self.data.get("long_term", []):
            if not isinstance(item, dict):
                continue

            legacy_text = self._clean_text(item.get("content", ""))
            if not legacy_text:
                continue

            descriptors = self._relational_descriptors(legacy_text)
            if not descriptors:
                remaining_long_term.append(item)
                continue

            for descriptor in descriptors:
                category = descriptor["category"]
                wanted_key = self._clean_text(descriptor["key"]).lower()
                bucket = self.data["relational"].setdefault(category, [])

                existing = next(
                    (
                        candidate
                        for candidate in bucket
                        if (
                            isinstance(candidate, dict)
                            and self._clean_text(candidate.get("key", "")).lower()
                            == wanted_key
                        )
                    ),
                    None,
                )

                # Une donnée déjà structurée par V4.7 est plus récente/fiable
                # qu'un ancien long_term. On ne la remplace jamais pendant
                # une migration, même si la valeur legacy est différente.
                if existing is not None:
                    continue

                self.remember_relational(
                    category=category,
                    key=descriptor["key"],
                    value=descriptor["value"],
                    content=descriptor["content"],
                    importance=max(
                        descriptor["importance"],
                        min(
                            1.0,
                            float(item.get("confidence", 0.75)) * 0.85,
                        ),
                    ),
                    confidence=max(
                        descriptor["confidence"],
                        float(item.get("confidence", 0.75)),
                    ),
                    source="migration_v46",
                    occurrences=max(
                        1,
                        int(item.get("occurrences", 1)),
                    ),
                    created_at=str(
                        item.get("created_at", self._now())
                    ),
                    updated_at=str(
                        item.get("updated_at", self._now())
                    ),
                    last_seen_at=str(
                        item.get(
                            "last_seen_at",
                            item.get("updated_at", self._now()),
                        )
                    ),
                    persist=False,
                )

            # Si au moins un descriptor existe, le souvenir est désormais
            # géré par relational. On ne le garde plus en double dans long_term.

        self.data["long_term"] = remaining_long_term[-self.LONG_TERM_LIMIT:]
        self.data["meta"]["relational_migration"] = self.SCHEMA_VERSION

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
            item["confidence"] = self._clamp(
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
            "confidence": self._clamp(confidence),
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
            "confidence": self._clamp(confidence),
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
            "confidence": self._clamp(confidence),
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
        if source == "agentos" or kind in self.OPERATIONAL_KINDS or self._looks_operational_text(text):
            self.remember_operational(text, kind=kind, source=source, confidence=confidence)
            return
        self._remember_timeline(
            "episodic",
            text,
            kind=kind,
            source=source,
            confidence=confidence,
            limit=self.EPISODIC_LIMIT,
        )
        # V6.2.3 : mémorise aussi quand l'événement s'est réellement produit.
        self._attach_event_date(text)

        # V6.3 : dual-write vers la mémoire événementielle SQLite.
        store = getattr(self, "personal_v2", None)
        if store is not None:
            try:
                store.remember_event(
                    text,
                    kind=kind,
                    source=source,
                    confidence=confidence,
                    recorded_at=self._now(),
                )
            except Exception:
                pass

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

        normalized_content = self._ascii(content)
        if (
            kind == "mission"
            and source == "agentos"
            and any(
                self._ascii(marker) in normalized_content
                for marker in self.TERMINAL_WORKING_MARKERS
            )
        ):
            self.forget_working(key)
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
            item for item in self.data["working"]
            if not isinstance(item, dict) or str(item.get("key", "")).lower() != normalized
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

        improved_globally = any(
            re.search(pattern, normalized, flags=re.IGNORECASE)
            for pattern in self.GLOBAL_IMPROVEMENT_PATTERNS
        )
        if improved_globally:
            for dimension, negative_values in self.NEGATIVE_EMOTIONAL_VALUES.items():
                if dimension in signals:
                    continue
                existing = current.get(dimension)
                if isinstance(existing, dict) and str(existing.get("value", "")) in negative_values:
                    current.pop(dimension, None)

        for dimension, signal in signals.items():
            current[dimension] = {
                "value": signal["value"],
                "confidence": self._clamp(signal["confidence"]),
                "observed_at": now,
                "source": clean,
            }
        self.data["emotional"].setdefault("history", []).append({
            "at": now,
            "source": clean,
            "signals": signals,
        })
        self.data["emotional"]["history"] = self.data["emotional"]["history"][-self.EMOTIONAL_HISTORY_LIMIT:]
        self._save()
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
            maximum = float(self.EMOTIONAL_CURRENT_MAX_AGE_HOURS.get(dimension, 3.0))
            if age_hours > maximum:
                continue
            effective = self._clamp(item.get("confidence", 0.0)) * self._decay_factor(age_hours)
            if effective < 0.25:
                continue
            result[dimension] = {
                "value": self._clean_text(item.get("value", "")),
                "confidence": effective,
                "base_confidence": self._clamp(item.get("confidence", 0.0)),
                "observed_at": str(item.get("observed_at", "")),
                "age_hours": age_hours,
                "source": self._clean_text(item.get("source", "")),
            }
        return result

    @staticmethod
    def _age_label(age_hours: float) -> str:
        if age_hours < 1:
            return f"il y a environ {max(1, int(age_hours * 60))} min"
        if age_hours < 24:
            return f"il y a environ {max(1, int(age_hours))} h"
        return f"il y a environ {max(1, int(age_hours / 24))} j"

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
            lines.append(f"- {label} : {value_label} (confiance {float(item['confidence']):.2f})")
        newest = max(state.values(), key=lambda item: str(item.get("observed_at", "")))
        source = self._clean_text(newest.get("source", ""))
        if source:
            lines.append(f"\nDernière observation : « {source} »")
        lines.append("Cet état est temporaire et sa confiance diminue avec le temps.")
        return "\n".join(lines)

    def emotional_history_summary(self, limit: int = 10) -> str:
        history = self.data.get("emotional", {}).get("history", [])
        if not isinstance(history, list) or not history:
            return "Aucune observation émotionnelle n'est encore enregistrée."
        now = datetime.now(timezone.utc)
        rows = [item for item in history[-max(1, limit):] if isinstance(item, dict)]
        if not rows:
            return "Aucune observation émotionnelle n'est encore enregistrée."

        lines = ["HISTORIQUE ÉMOTIONNEL"]
        for item in rows:
            observed = self._parse_time(item.get("at", ""))
            when = self._age_label(max(0.0, (now - observed).total_seconds() / 3600.0)) if observed else "date inconnue"
            signals = item.get("signals", {})
            source = self._clean_text(item.get("source", ""))
            lines.append(f"\n- {when}")
            if isinstance(signals, dict):
                for dimension in ("mood", "energy", "motivation", "stress", "frustration"):
                    signal = signals.get(dimension)
                    if not isinstance(signal, dict):
                        continue
                    label, values = self.EMOTIONAL_LABELS[dimension]
                    raw_value = self._clean_text(signal.get("value", ""))
                    value_label = values.get(raw_value, raw_value)
                    confidence = self._clamp(signal.get("confidence", 0.0))
                    lines.append(f"  {label} : {value_label} (confiance {confidence:.2f})")
            if source:
                lines.append(f"  Source : « {source} »")
        lines.append("\nCes observations restent dans l'historique même lorsqu'elles ne décrivent plus ton état actuel.")
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
        temporal = self._has_temporal_marker(fact)
        if signals or temporal:
            if signals:
                self.observe_emotional_state(fact)
            else:
                self.remember_episode(fact, kind="user_event", source="user_explicit", confidence=1.0)
            return True

        structured = self._extract_relational(
            fact,
            source="user_explicit",
            confidence_boost=0.08,
            persist=True,
            track_action=False,
        )
        if structured == 0:
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
        self._extract_relational(text, source="automatic", persist=True)

    def _extract_habits(self, text: str) -> None:
        self._extract_relational(text, source="automatic", persist=True)

    def _extract_episode(self, text: str) -> None:
        clean = self._clean_text(text)
        if (
            not clean
            or self._looks_like_question(clean)
            or self._looks_operational_text(clean)
            or self._looks_task_request_text(clean)
            or self._relational_descriptors(clean)
        ):
            return
        if self._has_temporal_marker(clean):
            self.remember_episode(clean, kind="user_event", source="automatic", confidence=0.80)

    def maybe_remember(self, text: str) -> dict[str, dict[str, Any]]:
        # Toujours repartir d'une action transitoire propre pour le message.
        self._last_memory_action = None

        forget_target = self.explicit_forget_fact(text)
        if forget_target is not None:
            self.forget_personal(
                forget_target,
                source="user_explicit",
                persist=True,
                track_action=True,
            )
            return {}

        if self._looks_like_question(text):
            return {}

        operational = self._looks_operational_text(text)
        explicit = self._explicit_memory(text)
        if explicit or operational:
            return {}

        self._extract_profile(text)
        self._extract_relational(
            text,
            source="automatic",
            persist=True,
            track_action=True,
        )
        emotional = self.observe_emotional_state(text)
        if not emotional:
            self._extract_episode(text)
        return emotional


    def maybe_remember_with_understanding(
        self,
        text: str,
        understanding: Any,
    ) -> dict[str, dict[str, Any]]:
        # V6.1 — ingestion mémoire guidée par UnderstandingEngine.
        self._last_memory_action = None

        forget_target = self.explicit_forget_fact(text)
        if forget_target is not None:
            self.forget_personal(
                forget_target,
                source="user_explicit",
                persist=True,
                track_action=True,
            )
            return {}

        operational = self._looks_operational_text(text)
        explicit = self._explicit_memory(text)

        if explicit or operational:
            return {}

        # Les couches déjà fiables de V4.7 restent actives.
        self._extract_profile(text)
        self._extract_relational(
            text,
            source="automatic",
            persist=True,
            track_action=True,
        )

        # D'abord l'extracteur émotionnel historique.
        emotional = self.observe_emotional_state(text)

        # Une phrase mixte terminée par "?" était historiquement considérée
        # comme une question entière et faisait perdre "je suis fatigué".
        # UnderstandingEngine peut compléter cet état sans court-circuiter
        # la demande conversationnelle.
        if not emotional:
            state = getattr(
                understanding,
                "user_state",
                {},
            )
            if isinstance(state, dict):
                allowed = {
                    "energy": {"low", "high"},
                    "motivation": {"low", "high"},
                    "stress": {"low", "moderate", "high"},
                    "mood": {"positive", "negative"},
                }

                signals: dict[str, dict[str, Any]] = {}

                for dimension, values in allowed.items():
                    raw_value = self._clean_text(
                        state.get(dimension, "")
                    ).lower()
                    if raw_value not in values:
                        continue

                    signals[dimension] = {
                        "value": raw_value,
                        "confidence": 0.82,
                    }

                if signals:
                    now = self._now()
                    source_text = self._clean_text(text)
                    current = self.data[
                        "emotional"
                    ].setdefault(
                        "current",
                        {},
                    )

                    for dimension, signal in signals.items():
                        current[dimension] = {
                            "value": signal["value"],
                            "confidence": signal["confidence"],
                            "observed_at": now,
                            "source": source_text,
                        }

                    self.data[
                        "emotional"
                    ].setdefault(
                        "history",
                        [],
                    ).append(
                        {
                            "at": now,
                            "source": source_text,
                            "signals": signals,
                        }
                    )
                    self.data["emotional"]["history"] = (
                        self.data["emotional"]["history"][
                            -self.EMOTIONAL_HISTORY_LIMIT:
                        ]
                    )
                    self._save()
                    emotional = signals

        raw_items = getattr(
            understanding,
            "memory_items",
            [],
        )
        memory_items = (
            raw_items
            if isinstance(raw_items, list)
            else []
        )

        ingested = 0

        for raw in memory_items[:12]:
            if isinstance(raw, dict):
                kind = self._clean_text(
                    raw.get(
                        "kind",
                        raw.get("type", ""),
                    )
                ).lower()
                content = self._clean_text(
                    raw.get("content", "")
                )
                confidence = self._clamp(
                    raw.get("confidence", 0.8)
                )
            else:
                kind = self._clean_text(
                    getattr(raw, "kind", "")
                ).lower()
                content = self._clean_text(
                    getattr(raw, "content", "")
                )
                confidence = self._clamp(
                    getattr(raw, "confidence", 0.8)
                )

            if (
                not content
                or confidence < 0.45
                or self._looks_like_question(content)
                or self._looks_task_request_text(content)
                or self._looks_operational_text(content)
            ):
                continue

            if kind == "episode":
                self.remember_episode(
                    content,
                    kind="user_event",
                    source="understanding",
                    confidence=confidence,
                )
                ingested += 1
                continue

            if kind == "fact":
                self.remember(
                    content,
                    kind="fact",
                    source="understanding",
                    confidence=confidence,
                )
                ingested += 1
                continue

            if kind == "profile":
                before = len(
                    self.data.get(
                        "profile",
                        [],
                    )
                )
                self._extract_profile(
                    content
                )
                after = len(
                    self.data.get(
                        "profile",
                        [],
                    )
                )
                if after == before:
                    self.remember(
                        content,
                        kind="profile_fact",
                        source="understanding",
                        confidence=confidence,
                    )
                ingested += 1
                continue

            if kind in {
                "preference",
                "habit",
                "relation",
            }:
                structured = self._extract_relational(
                    content,
                    source="understanding",
                    confidence_boost=0.03,
                    persist=True,
                    track_action=False,
                )
                if structured == 0:
                    self.remember(
                        content,
                        kind=kind,
                        source="understanding",
                        confidence=confidence,
                    )
                ingested += 1
                continue

        # Filet de sécurité historique si aucun élément structuré n'a été
        # produit. Une question entière ne devient jamais un épisode.
        if (
            ingested == 0
            and not emotional
            and not self._looks_like_question(text)
        ):
            self._extract_episode(
                text
            )

        return emotional


    # =========================================================
    # PERSONAL MEMORY V2 / SQLITE V6.3
    # =========================================================

    def _personal_v2_known_people(self) -> list[str]:
        result: list[str] = []
        try:
            items = self.relational_active_items("relations")
        except Exception:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            value = self._clean_text(item.get("value", ""))
            if value and value not in result:
                result.append(value)
        return result

    def personal_memory_v2_observe(
        self,
        text: str,
    ) -> dict[str, Any] | None:
        store = getattr(self, "personal_v2", None)
        if store is None:
            return None
        try:
            if not store.looks_personal_statement(text):
                return None
            return store.remember_event(
                text,
                kind="user_event",
                source="user",
                confidence=0.92,
                recorded_at=self._now(),
            )
        except Exception:
            return None

    def personal_memory_v2_should_own(
        self,
        query: str,
    ) -> bool:
        store = getattr(self, "personal_v2", None)
        if store is None:
            return False
        try:
            return bool(store.looks_personal_query(query))
        except Exception:
            return False

    def personal_memory_v2_context(
        self,
        query: str,
        *,
        limit: int = 8,
    ) -> str:
        store = getattr(self, "personal_v2", None)
        if store is None:
            return "(mémoire personnelle V2 indisponible)"
        try:
            return store.context(query, limit=limit)
        except Exception as exc:
            return f"(mémoire personnelle V2 indisponible : {exc})"

    def personal_memory_v2_direct_answer(
        self,
        query: str,
        *,
        force: bool = False,
    ) -> str | None:
        store = getattr(self, "personal_v2", None)
        if store is None:
            return None
        try:
            if not force and not store.looks_personal_query(query):
                return None
            # direct_answer vérifie lui-même les questions privées. En mode
            # force (relance pronominale), on utilise une copie enrichie par le
            # fil utilisateur qui contient normalement un ancrage personnel.
            return store.direct_answer(query)
        except Exception:
            return None

    def personal_memory_v2_status(self) -> str:
        store = getattr(self, "personal_v2", None)
        if store is None:
            error = self.data.get("meta", {}).get(
                "personal_memory_v2_error"
            )
            if error:
                return (
                    "MÉMOIRE PERSONNELLE V2 indisponible.\n"
                    f"Erreur : {error}"
                )
            return "MÉMOIRE PERSONNELLE V2 indisponible."
        try:
            return store.status_summary()
        except Exception as exc:
            return f"MÉMOIRE PERSONNELLE V2 indisponible : {exc}"

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
        tokens = cls._tokens(text)
        active: set[str] = set()
        for words in cls.TOPIC_GROUPS.values():
            normalized_group = {cls._ascii(value) for value in words}
            if tokens & normalized_group:
                active.update(normalized_group)
        return active

    @classmethod
    def _expanded_tokens(cls, text: str) -> set[str]:
        return cls._tokens(text) | cls._active_topic_tokens(text)

    def _relational_score(self, item: dict[str, Any], query: str) -> float:
        searchable = " ".join([
            str(item.get("key", "")),
            str(item.get("value", "")),
            str(item.get("content", "")),
        ])
        query_tokens = self._expanded_tokens(query)
        memory_tokens = self._expanded_tokens(searchable)
        overlap = len(query_tokens & memory_tokens)
        importance = self._effective_importance(item)
        confidence = self._clamp(item.get("confidence", 0.0))
        occurrences = max(1, int(item.get("occurrences", 1)))
        return overlap * 3.0 + importance * 2.0 + confidence + min(occurrences, 6) * 0.12

    def _relevant_relational(
        self,
        query: str,
        *,
        category: str,
        limit: int = 5,
        always: bool = False,
    ) -> list[dict[str, Any]]:
        rows: list[tuple[float, int, dict[str, Any]]] = []
        query_tokens = self._expanded_tokens(query)
        for index, item in enumerate(self.data["relational"].get(category, [])):
            if not isinstance(item, dict):
                continue
            searchable = " ".join([
                str(item.get("key", "")), str(item.get("value", "")), str(item.get("content", "")),
            ])
            overlap = len(query_tokens & self._expanded_tokens(searchable))
            if not always and overlap <= 0:
                continue
            rows.append((self._relational_score(item, query), index, item))
        rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [row[2] for row in rows[:limit]]

    def _relevant_long_term(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        query_tokens = self._expanded_tokens(query)
        topic_tokens = self._active_topic_tokens(query)
        structured_contents = {
            self._key(item.get("content", ""))
            for category in self.RELATIONAL_CATEGORIES
            for item in self.data["relational"].get(category, [])
            if isinstance(item, dict)
        }
        scored = []
        for index, item in enumerate(self.data["long_term"]):
            if not isinstance(item, dict):
                continue
            content = self._clean_text(item.get("content", ""))
            if not content or self._key(content) in structured_contents:
                continue
            memory_tokens = self._tokens(content)
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
            age_hours = 9999.0 if created is None else max(0.0, (now - created).total_seconds() / 3600.0)
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

    def _format_relational_items(self, items: list[dict[str, Any]]) -> str:
        lines = []
        for item in items:
            content = self._clean_text(item.get("content", ""))
            if not content:
                continue
            importance = self._effective_importance(item)
            occurrences = max(1, int(item.get("occurrences", 1)))
            lines.append(f"- {content} [importance {importance:.2f}, occurrences {occurrences}]")
        return "\n".join(lines) or "(aucun élément pertinent)"

    def relational_context(self, query: str = "") -> str:
        communication = self._relevant_relational(query, category="communication", limit=6, always=True)
        interests = self._relevant_relational(query, category="interests", limit=4)
        habits = self._relevant_relational(query, category="habits", limit=4)
        preferences = self._relevant_relational(query, category="preferences", limit=5)
        relations = self._relevant_relational(query, category="relations", limit=4)

        sections = [
            "PRÉFÉRENCES DE COMMUNICATION:\n" + self._format_relational_items(communication),
        ]
        if interests:
            sections.append("CENTRES D'INTÉRÊT PERTINENTS:\n" + self._format_relational_items(interests))
        if habits:
            sections.append("HABITUDES PERTINENTES:\n" + self._format_relational_items(habits))
        if preferences:
            sections.append("PRÉFÉRENCES PERSONNELLES PERTINENTES:\n" + self._format_relational_items(preferences))
        if relations:
            sections.append("RELATIONS / PERSONNES PERTINENTES:\n" + self._format_relational_items(relations))
        return "\n\n".join(sections)

    def personal_conversation_context(
        self,
        query: str,
        *,
        include_session: bool = True,
    ) -> str:
        durable = self._format_memory_items(self._relevant_long_term(query))
        episodic = self._format_memory_items(
            self._relevant_episodic(query),
            episodic=True,
        )
        value = (
            "PROFIL UTILISATEUR:\n"
            + self.profile_context()
            + "\n\nMÉMOIRE RELATIONNELLE:\n"
            + self.relational_context(query)
            + "\n\nAUTRES SOUVENIRS PERSONNELS PERTINENTS:\n"
            + durable
            + "\n\nÉVÉNEMENTS PERSONNELS PERTINENTS/RÉCENTS:\n"
            + episodic
            + "\n\nÉTAT ÉMOTIONNEL ACTUEL (temporaire, estimation):\n"
            + self.emotional_context()
        )
        if include_session:
            value += (
                "\n\nCONVERSATION PERSONNELLE RÉCENTE (hors missions):\n"
                + self.personal_session_context(limit=8)
            )
        return value

    def relevant_context(self, query: str) -> str:
        durable = self._format_memory_items(self._relevant_long_term(query))
        episodic = self._format_memory_items(self._relevant_episodic(query), episodic=True)
        return (
            "PROFIL UTILISATEUR:\n"
            + self.profile_context()
            + "\n\nMÉMOIRE RELATIONNELLE:\n"
            + self.relational_context(query)
            + "\n\nAUTRES SOUVENIRS PERSONNELS PERTINENTS:\n"
            + durable
            + "\n\nÉVÉNEMENTS PERSONNELS RÉCENTS:\n"
            + episodic
            + "\n\nÉTAT ÉMOTIONNEL ACTUEL (temporaire, estimation):\n"
            + self.emotional_context()
            + "\n\nCONVERSATION RÉCENTE:\n"
            + self.personal_session_context(limit=8)
        )

    def relevant_personal_summary(self, query: str, *, limit: int = 6) -> str | None:
        relational: list[dict[str, Any]] = []
        for category in self.RELATIONAL_CATEGORIES:
            relational.extend(self._relevant_relational(query, category=category, limit=limit))
        relational.sort(key=lambda item: self._relational_score(item, query), reverse=True)
        relational = relational[:limit]

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
            confidence = self._clamp(item.get("confidence", 0.0))
            episodic_scored.append((overlap * 3.0 + confidence, index, item))
        episodic_scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        episodic = [row[2] for row in episodic_scored[:3]]

        if not relational and not durable and not episodic:
            return None

        lines = ["Sur ce sujet, j'ai retenu :"]
        seen: set[str] = set()
        for item in relational + durable + episodic:
            content = self._clean_text(item.get("content", ""))
            key = self._key(content)
            if not content or key in seen:
                continue
            seen.add(key)
            lines.append(f"- {content}")
        return "\n".join(lines) if len(lines) > 1 else None

    # =========================================================
    # DETERMINISTIC RELATIONAL LOOKUPS
    # =========================================================

    def relational_active_items(
        self,
        category: str,
    ) -> list[dict[str, Any]]:
        if category not in self.RELATIONAL_CATEGORIES:
            return []
        return [
            dict(item)
            for item in self.data.get("relational", {}).get(category, [])
            if isinstance(item, dict)
            and self._clean_text(item.get("status", "active")) == "active"
        ]

    def relational_value(
        self,
        category: str,
        key: str,
    ) -> str | None:
        wanted = self._clean_text(key).lower()
        for item in self.relational_active_items(category):
            if self._clean_text(item.get("key", "")).lower() != wanted:
                continue
            value = self._clean_text(item.get("value", ""))
            return value or None
        return None

    def relation_value(
        self,
        role: str,
    ) -> str | None:
        normalized_role = self._slug(self._ascii(role))
        return self.relational_value(
            "relations",
            f"person:{normalized_role}",
        )

    def favorite_value(
        self,
        subject: str,
    ) -> str | None:
        return self.relational_value(
            "preferences",
            f"favorite:{self._slug(subject)}",
        )

    def relational_category_summary(
        self,
        category: str,
    ) -> str:
        labels = {
            "communication": (
                "Préférences de communication retenues :",
                "Je n'ai aucune préférence de communication enregistrée.",
            ),
            "interests": (
                "Centres d'intérêt retenus :",
                "Je n'ai aucun centre d'intérêt enregistré.",
            ),
            "habits": (
                "Habitudes retenues :",
                "Je n'ai aucune habitude enregistrée.",
            ),
            "preferences": (
                "Préférences personnelles retenues :",
                "Je n'ai aucune préférence personnelle enregistrée.",
            ),
            "relations": (
                "Relations / personnes retenues :",
                "Je n'ai aucune relation ou personne importante enregistrée.",
            ),
        }

        items = self.relational_active_items(category)
        if not items:
            return labels.get(
                category,
                ("Souvenirs :", "Je n'ai aucun souvenir enregistré dans cette catégorie."),
            )[1]

        # Importance puis récence, sans faire intervenir les autres catégories.
        items.sort(
            key=lambda item: (
                self._effective_importance(item),
                self._clean_text(item.get("last_seen_at", "")),
            ),
            reverse=True,
        )

        title = labels.get(category, ("Souvenirs :", ""))[0]
        lines = [title]
        seen: set[str] = set()
        for item in items:
            content = self._clean_text(item.get("content", ""))
            content_key = self._key(content)
            if not content or content_key in seen:
                continue
            seen.add(content_key)
            lines.append(f"- {content}")

        return "\n".join(lines)

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

    def personal_session_context(self, limit: int = 8) -> str:
        """Conversation récente nettoyée des notifications/anciens plans de mission."""
        selected: list[str] = []
        operational_markers = (
            "plan de travail", "mission m-", "mission créée", "mission creee",
            "mission terminée", "mission terminee", "mission échouée", "mission echouee",
            "je te tiens au courant de l'avancement", "approbation requise",
            "étape :", "detail :", "détail :",
        )

        for item in reversed(self.data["session"]):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "?"))
            content = self._clean_text(item.get("content", ""))
            if not content or role == "system":
                continue

            normalized = self._ascii(content)
            if (
                self._looks_operational_text(content)
                or self._looks_task_request_text(content)
                or any(self._ascii(marker) in normalized for marker in operational_markers)
            ):
                continue

            selected.append(f"{role}: {content}")
            if len(selected) >= max(1, limit):
                break

        selected.reverse()
        return "\n".join(selected) or "(vide)"

    def clear_session(self) -> None:
        """Vide uniquement le tampon conversationnel récent.

        Les souvenirs personnels structurés, épisodes et missions ne sont pas
        affectés. Le fil conversationnel V4.8 possède sa propre persistance.
        """
        if self.data.get("session"):
            self.data["session"] = []
            self._save()

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

    def relational_full_context(self) -> str:
        labels = {
            "communication": "COMMUNICATION",
            "interests": "CENTRES D'INTÉRÊT",
            "habits": "HABITUDES",
            "preferences": "PRÉFÉRENCES PERSONNELLES",
            "relations": "RELATIONS / PERSONNES IMPORTANTES",
        }
        sections: list[str] = []
        for category in self.RELATIONAL_CATEGORIES:
            items = [item for item in self.data["relational"].get(category, []) if isinstance(item, dict)]
            items.sort(
                key=lambda item: (
                    self._effective_importance(item),
                    int(item.get("occurrences", 1)),
                ),
                reverse=True,
            )
            sections.append(labels[category] + "\n" + self._format_relational_items(items[:20]))
        return "\n\n".join(sections)

    def relational_history_summary(self, limit: int = 20) -> str:
        history = self.data.get("relational", {}).get("history", [])
        rows = [item for item in history if isinstance(item, dict)][-max(1, limit):]
        if not rows:
            return "Aucun remplacement ou oubli relationnel enregistré."

        lines = ["HISTORIQUE RELATIONNEL"]
        for item in reversed(rows):
            status = self._clean_text(item.get("status", "historique"))
            category = self._clean_text(item.get("category", "?"))
            key = self._clean_text(item.get("key", "?"))
            at = self._clean_text(item.get("archived_at", ""))

            if status == "forgotten" or bool(item.get("redacted")):
                lines.append(
                    f"- {category}/{key} — oublié explicitement"
                    + (f" ({at})" if at else "")
                )
                continue

            content = self._clean_text(item.get("content", ""))
            replacement = self._clean_text(item.get("replaced_by", ""))
            detail = content or f"{category}/{key}"
            if replacement:
                detail += f" → remplacé par {replacement}"
            lines.append(
                f"- {detail} [{status}]"
                + (f" ({at})" if at else "")
            )

        return "\n".join(lines)

    def long_term_context(self, limit: int = 30) -> str:
        items = [
            item for item in self.data["long_term"]
            if isinstance(item, dict) and str(item.get("content", "")).strip()
        ][-limit:]
        items.sort(
            key=lambda item: (float(item.get("confidence", 0.0)), int(item.get("occurrences", 1))),
            reverse=True,
        )
        return self._format_memory_items(items) if items else "(vide)"

    def episodic_context(self, limit: int = 12) -> str:
        items = [
            item for item in self.data["episodic"]
            if isinstance(item, dict) and str(item.get("kind", "")) != "emotional_observation"
        ][-limit:]
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
            + "\n\nMÉMOIRE RELATIONNELLE\n"
            + self.relational_full_context()
            + "\n\nAUTRES SOUVENIRS DURABLES\n"
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
        visible_episodic = sum(
            1 for item in self.data["episodic"]
            if isinstance(item, dict) and str(item.get("kind", "")) != "emotional_observation"
        )
        return (
            "MÉMOIRE PERSONNELLE\n"
            f"Profil : {stats['profile']} | "
            f"Relationnel : {stats['relational']} | "
            f"Souvenirs durables : {stats['long_term']} | "
            f"Événements personnels : {visible_episodic}\n\n"
            + self.personal_summary()
            + "\n\nLes missions sont séparées de la mémoire personnelle. "
            + "Utilise `memory operations` pour l'historique Agent-OS et "
            + "`emotion history` pour l'historique émotionnel."
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
        relational_count = sum(
            len(self.data["relational"].get(category, []))
            for category in self.RELATIONAL_CATEGORIES
        )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "session": len(self.data["session"]),
            "profile": len(self.data["profile"]),
            "relational": relational_count,
            "relational_history": len(self.data["relational"].get("history", [])),
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
            "MEMORY ENGINE V4.7.3 — DEBUG\n"
            f"Profil : {stats['profile']} | Relationnel : {stats['relational']} | "
            f"Historique relationnel : {stats['relational_history']} | Durable : {stats['long_term']} | "
            f"Épisodique perso : {stats['episodic']} | Opérationnel : {stats['operational']} | "
            f"Travail : {stats['working']} | Émotion courant : {stats['emotional_current']} | "
            f"Session : {stats['session']}\n\n"
            + self.context()
        )
