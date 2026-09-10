from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PersonalProfileMemory:
    """Mémoire durable structurée du profil utilisateur — Agent-OS V6.5.

    Cette couche ne remplace ni la mémoire épisodique ni l'agenda. Elle stocke
    seulement les informations relativement durables : profil, relations,
    centres d'intérêt, projets, objectifs, compétences, préférences et habitudes.

    Une information explicite et une information inférée restent distinctes.
    Les sujets récurrents peuvent produire un centre d'intérêt *inféré*, mais
    jamais un fait certain sur l'utilisateur.
    """

    SCHEMA_VERSION = 1

    CATEGORIES = {
        "profile",
        "relation",
        "interest",
        "project",
        "goal",
        "skill",
        "preference",
        "habit",
    }

    CATEGORY_LABELS = {
        "profile": "Profil",
        "relation": "Relations",
        "interest": "Centres d'intérêt",
        "project": "Projets",
        "goal": "Objectifs",
        "skill": "Compétences",
        "preference": "Préférences",
        "habit": "Habitudes",
    }

    QUERY_CATEGORY_MARKERS = {
        "interest": (
            "centre d interet", "centres d interet", "interets", "interet",
            "ce qui m interesse", "ce que j aime",
        ),
        "project": ("mes projets", "projets personnels", "projet principal"),
        "goal": ("mes objectifs", "mes buts", "objectif personnel", "objectifs personnels"),
        "skill": ("mes competences", "ce que je sais faire", "mes savoir faire"),
        "preference": ("mes preferences", "ce que je prefere", "preferences de communication"),
        "habit": ("mes habitudes", "mes routines", "d habitude"),
        "relation": ("mes relations", "personnes importantes", "ma famille", "ma copine", "mon copain"),
        "profile": ("mon profil", "mon identite", "qui je suis"),
    }

    TOPIC_IGNORE = {
        "conversation", "question", "agenda", "planning", "samedi", "dimanche",
        "lundi", "mardi", "mercredi", "jeudi", "vendredi", "aujourd hui",
        "demain", "memoire", "memory", "mission", "missions", "statut",
        "status", "discussion", "message", "utilisateur",
    }

    TOPIC_CANONICAL = {
        "agent os": "Agent-OS",
        "agent-os": "Agent-OS",
        "agentos": "Agent-OS",
        "home assistant": "Home Assistant",
        "home-assistant": "Home Assistant",
        "domotique home assistant": "Home Assistant / domotique",
        "raspberry pi": "Raspberry Pi",
        "aquarium": "Aquariophilie",
        "aquariophilie": "Aquariophilie",
        "dofus": "Dofus",
    }

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _clean(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _ascii(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))

    @classmethod
    def normalize(cls, value: Any) -> str:
        text = cls._ascii(cls._clean(value))
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    @classmethod
    def _subject_key(cls, value: Any) -> str:
        normalized = cls.normalize(value)
        return cls.TOPIC_CANONICAL.get(normalized, normalized).lower()

    @staticmethod
    def _clamp(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return max(0.0, min(1.0, number))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _evidence_hash(cls, category: str, subject: str, message: str) -> str:
        raw = "|".join((cls.normalize(category), cls.normalize(subject), cls.normalize(message)))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # =========================================================
    # SQLITE
    # =========================================================

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.db_path), timeout=10.0)
        db.row_factory = sqlite3.Row
        return db

    def _ensure_schema(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    normalized_subject TEXT NOT NULL,
                    value TEXT NOT NULL DEFAULT '',
                    normalized_value TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    confidence REAL NOT NULL DEFAULT 0.8,
                    importance REAL NOT NULL DEFAULT 0.6,
                    explicit INTEGER NOT NULL DEFAULT 1,
                    inferred INTEGER NOT NULL DEFAULT 0,
                    mentions INTEGER NOT NULL DEFAULT 1,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    last_evidence_hash TEXT NOT NULL DEFAULT '',
                    UNIQUE(category, normalized_subject)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER,
                    category TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    action TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '',
                    at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_signals (
                    normalized_topic TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    mentions INTEGER NOT NULL DEFAULT 1,
                    active_days_json TEXT NOT NULL DEFAULT '[]',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    last_message_hash TEXT NOT NULL DEFAULT ''
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            db.execute(
                "INSERT OR REPLACE INTO profile_meta(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_profile_category ON profile_items(category, status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_profile_importance ON profile_items(importance DESC)")

    # =========================================================
    # ITEM STORAGE
    # =========================================================

    def upsert_item(
        self,
        *,
        category: str,
        subject: str,
        value: str = "",
        content: str = "",
        source: str = "user",
        confidence: float = 0.8,
        importance: float = 0.6,
        explicit: bool = True,
        inferred: bool = False,
        evidence: str = "",
    ) -> dict[str, Any] | None:
        category = self.normalize(category)
        if category not in self.CATEGORIES:
            return None

        subject = self._clean(subject)
        value = self._clean(value)
        content = self._clean(content) or (f"{subject} : {value}" if value else subject)
        if not subject:
            return None

        normalized_subject = self._subject_key(subject)
        normalized_value = self.normalize(value)
        confidence = self._clamp(confidence, 0.8)
        importance = self._clamp(importance, 0.6)
        now = self._now()
        evidence_hash = self._evidence_hash(category, subject, evidence or content)

        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM profile_items WHERE category=? AND normalized_subject=? LIMIT 1",
                (category, normalized_subject),
            ).fetchone()

            if row is None:
                cursor = db.execute(
                    """
                    INSERT INTO profile_items(
                        category, subject, normalized_subject, value,
                        normalized_value, content, source, confidence,
                        importance, explicit, inferred, mentions,
                        first_seen, last_seen, status, last_evidence_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'active', ?)
                    """,
                    (
                        category, subject, normalized_subject, value,
                        normalized_value, content, source, confidence,
                        importance, int(bool(explicit)), int(bool(inferred)),
                        now, now, evidence_hash,
                    ),
                )
                item_id = int(cursor.lastrowid)
                db.execute(
                    """
                    INSERT INTO profile_history(
                        item_id, category, subject, old_value, new_value,
                        action, evidence, at
                    ) VALUES (?, ?, ?, '', ?, 'created', ?, ?)
                    """,
                    (item_id, category, subject, value, self._clean(evidence), now),
                )
                return dict(db.execute("SELECT * FROM profile_items WHERE id=?", (item_id,)).fetchone())

            current = dict(row)
            same_evidence = str(current.get("last_evidence_hash") or "") == evidence_hash
            mentions = int(current.get("mentions") or 1) + (0 if same_evidence else 1)

            old_value = self._clean(current.get("value", ""))
            old_explicit = bool(current.get("explicit"))
            incoming_explicit = bool(explicit)

            # Une inférence ne remplace jamais une information explicite.
            chosen_value = old_value
            chosen_content = self._clean(current.get("content", ""))
            action = "reinforced"
            if incoming_explicit and (not old_explicit or (value and self.normalize(value) != self.normalize(old_value))):
                chosen_value = value
                chosen_content = content
                action = "updated" if old_explicit else "promoted"
            elif not old_explicit and value:
                chosen_value = value
                chosen_content = content

            chosen_explicit = old_explicit or incoming_explicit
            chosen_inferred = (bool(current.get("inferred")) or bool(inferred)) and not chosen_explicit
            chosen_confidence = max(float(current.get("confidence") or 0.0), confidence)
            chosen_importance = max(float(current.get("importance") or 0.0), importance)

            # La répétition augmente légèrement l'importance mais pas la vérité.
            if not same_evidence:
                chosen_importance = min(0.98, max(chosen_importance, 0.52 + 0.07 * math.log1p(mentions)))

            db.execute(
                """
                UPDATE profile_items
                SET subject=?, value=?, normalized_value=?, content=?, source=?,
                    confidence=?, importance=?, explicit=?, inferred=?, mentions=?,
                    last_seen=?, status='active', last_evidence_hash=?
                WHERE id=?
                """,
                (
                    subject, chosen_value, self.normalize(chosen_value), chosen_content,
                    source if incoming_explicit else current.get("source", source),
                    chosen_confidence, chosen_importance, int(chosen_explicit),
                    int(chosen_inferred), mentions, now, evidence_hash, int(current["id"]),
                ),
            )
            if action != "reinforced" or not same_evidence:
                db.execute(
                    """
                    INSERT INTO profile_history(
                        item_id, category, subject, old_value, new_value,
                        action, evidence, at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(current["id"]), category, subject, old_value,
                        chosen_value, action, self._clean(evidence), now,
                    ),
                )
            return dict(db.execute("SELECT * FROM profile_items WHERE id=?", (int(current["id"]),)).fetchone())

    # =========================================================
    # LEGACY MIGRATION
    # =========================================================

    def migrate_legacy(self, data: dict[str, Any]) -> dict[str, int]:
        seen = 0
        imported = 0

        for item in data.get("profile", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            key = self._clean(item.get("key", ""))
            value = self._clean(item.get("value", ""))
            if not key or not value:
                continue
            seen += 1
            before = self.count_items()
            self.upsert_item(
                category="profile", subject=key, value=value,
                content=f"{key} : {value}", source=str(item.get("source", "legacy_json")),
                confidence=self._clamp(item.get("confidence", 0.9), 0.9),
                importance=0.72, explicit=True, inferred=False,
                evidence=f"legacy-profile:{key}:{value}",
            )
            imported += int(self.count_items() > before)

        relational = data.get("relational", {}) if isinstance(data, dict) else {}
        if isinstance(relational, dict):
            mapping = {
                "communication": "preference",
                "interests": "interest",
                "habits": "habit",
                "preferences": "preference",
                "relations": "relation",
            }
            for old_category, new_category in mapping.items():
                for item in relational.get(old_category, []):
                    if not isinstance(item, dict):
                        continue
                    subject = self._clean(item.get("key", "")) or self._clean(item.get("value", ""))
                    value = self._clean(item.get("value", ""))
                    content = self._clean(item.get("content", "")) or value or subject
                    if not subject:
                        continue
                    seen += 1
                    before = self.count_items()
                    self.upsert_item(
                        category=new_category,
                        subject=subject,
                        value=value,
                        content=content,
                        source=str(item.get("source", "legacy_json")),
                        confidence=self._clamp(item.get("confidence", 0.82), 0.82),
                        importance=self._clamp(item.get("importance", 0.65), 0.65),
                        explicit=True,
                        inferred=False,
                        evidence=f"legacy-relational:{old_category}:{subject}:{value}",
                    )
                    imported += int(self.count_items() > before)

        return {"seen": seen, "imported": imported}

    # =========================================================
    # UNDERSTANDING INGESTION
    # =========================================================


    @classmethod
    def _v6521_question_like(cls, message: str) -> bool:
        raw = cls._clean(message)
        if not raw:
            return False
        if raw.endswith("?"):
            return True
        n = cls.normalize(raw)
        return n.startswith(
            (
                "qui ", "que ", "quoi ", "quel ", "quelle ", "quels ",
                "quelles ", "ou ", "quand ", "comment ", "pourquoi ",
                "combien ", "est ce ", "qu est ce ", "sais tu ",
                "tu sais ", "rappelle moi ",
            )
        )

    @classmethod
    def _fallback_items(cls, message: str) -> list[dict[str, Any]]:
        """Petit filet local si le LLM omet durable_items."""
        raw = cls._clean(message)
        n = cls.normalize(raw)
        if not raw or raw.endswith("?"):
            return []
        result: list[dict[str, Any]] = []

        # V7.0.1 : l'identité déclarée par l'utilisateur ne dépend jamais de
        # l'extraction du LLM. Les sujets fixes permettent aussi de mettre à
        # jour proprement une ancienne valeur au lieu d'empiler des doublons.
        name_match = re.search(
            r"\b(?:je\s+m['’ ]appelle|mon\s+pr[eé]nom\s+est|mon\s+nom\s+est)\s+"
            r"([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,59})",
            raw,
            flags=re.I,
        )
        if name_match:
            result.append({
                "category": "profile",
                "subject": "prénom",
                "value": cls._clean(name_match.group(1)).strip(" .,:;-"),
                "confidence": 0.99,
                "importance": 0.95,
                "explicit": True,
            })

        location_match = re.search(
            r"\b(?:j['’ ]habite|je\s+vis|je\s+r[eé]side)\s+"
            r"(?:(?:à|a|au|aux|en)\s+)?([^,.!?;]{2,120})",
            raw,
            flags=re.I,
        )
        if location_match:
            location = cls._clean(location_match.group(1)).strip(" .,:;-")
            if location:
                result.append({
                    "category": "profile",
                    "subject": "lieu de vie",
                    "value": location,
                    "confidence": 0.99,
                    "importance": 0.90,
                    "explicit": True,
                })

        patterns = (
            ("interest", r"\b(?:j aime|j adore|je m interesse a|je suis passionne par)\s+(.+)$", "aime"),
            ("goal", r"\b(?:mon objectif est|mon but est|je veux arriver a|j aimerais arriver a)\s+(.+)$", "objectif"),
            ("skill", r"\b(?:je maitrise|je sais faire|je suis bon en|je suis competent en)\s+(.+)$", "maîtrise"),
            ("project", r"\b(?:mon projet(?: principal)? est|je developpe|je travaille sur)\s+(.+)$", "projet actif"),
        )
        for category, pattern, value in patterns:
            m = re.search(pattern, n, flags=re.I)
            if not m:
                continue
            subject = cls._clean(m.group(1)).strip(" .,:;-")
            if subject:
                result.append({
                    "category": category,
                    "subject": subject,
                    "value": value,
                    "confidence": 0.68,
                    "importance": 0.65,
                    "explicit": True,
                })
        return result

    @classmethod
    def explicit_identity_facts(cls, message: str) -> list[dict[str, Any]]:
        """Retourne uniquement les faits d'identité explicitement déclarés."""
        return [
            item for item in cls._fallback_items(message)
            if item.get("category") == "profile"
            and item.get("subject") in {"prénom", "lieu de vie"}
        ]

    def profile_value(self, *subjects: str) -> str | None:
        wanted = {self.normalize(subject) for subject in subjects if self._clean(subject)}
        if not wanted:
            return None
        for item in self.items("profile", limit=100):
            if self.normalize(item.get("subject", "")) in wanted:
                return self._clean(item.get("value", "")) or self._clean(item.get("content", ""))
        return None

    def ingest_understanding(
        self,
        message: str,
        understanding: Any,
        *,
        decision_owner: str = "",
    ) -> list[dict[str, Any]]:
        # V6.5.2.1 : une question peut lire la mémoire mais jamais l'écrire.
        if self._v6521_question_like(message):
            return []

        owner = self.normalize(decision_owner)

        # Les informations explicitement extraites par UnderstandingEngine
        # peuvent être conservées même si la phrase contient aussi une autre
        # action (agenda, recherche, mission). En revanche, ces domaines ne
        # servent jamais à inférer passivement un centre d'intérêt.
        raw_items = getattr(understanding, "durable_items", None) if understanding is not None else None
        if not isinstance(raw_items, list):
            raw_items = []

        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if isinstance(raw, dict):
                items.append(raw)
            else:
                # dataclass DurableProfileItem
                try:
                    items.append({
                        "category": getattr(raw, "category", ""),
                        "subject": getattr(raw, "subject", ""),
                        "value": getattr(raw, "value", ""),
                        "confidence": getattr(raw, "confidence", 0.8),
                        "importance": getattr(raw, "importance", 0.6),
                        "explicit": getattr(raw, "explicit", True),
                    })
                except Exception:
                    pass

        if not items:
            # Réutilise aussi les anciennes extractions sûres.
            legacy_memory = getattr(understanding, "memory_items", []) if understanding is not None else []
            category_map = {
                "preference": "preference",
                "habit": "habit",
                "relation": "relation",
                "profile": "profile",
            }
            for old in legacy_memory or []:
                kind = self.normalize(getattr(old, "kind", ""))
                if kind not in category_map:
                    continue
                content = self._clean(getattr(old, "content", ""))
                if content:
                    items.append({
                        "category": category_map[kind],
                        "subject": content[:160],
                        "value": content,
                        "confidence": getattr(old, "confidence", 0.75),
                        "importance": 0.62,
                        "explicit": True,
                    })

        if not items:
            items = self._fallback_items(message)

        # Le texte utilisateur brut reste la source de vérité pour son prénom
        # et son domicile. Une extraction LLM concurrente ne peut ni masquer
        # ni remplacer ces deux faits explicites.
        identity_items = self.explicit_identity_facts(message)
        if identity_items:
            identity_subjects = {
                self.normalize(item.get("subject", ""))
                for item in identity_items
            }
            items = [
                item for item in items
                if not (
                    self.normalize(item.get("category", "")) == "profile"
                    and self.normalize(item.get("subject", "")) in identity_subjects
                )
            ] + identity_items

        stored: list[dict[str, Any]] = []
        for raw in items[:12]:
            category = self.normalize(raw.get("category", ""))
            subject = self._clean(raw.get("subject", ""))
            value = self._clean(raw.get("value", ""))
            if category not in self.CATEGORIES or not subject:
                continue
            item = self.upsert_item(
                category=category,
                subject=subject,
                value=value,
                content=self._clean(raw.get("content", "")) or message,
                source="user",
                confidence=self._clamp(raw.get("confidence", 0.8), 0.8),
                importance=self._clamp(raw.get("importance", 0.62), 0.62),
                explicit=bool(raw.get("explicit", True)),
                inferred=not bool(raw.get("explicit", True)),
                evidence=message,
            )
            if item is not None:
                stored.append(item)

        # Le sujet courant sert seulement de signal statistique. Il ne devient
        # un centre d'intérêt qu'après répétition suffisante.
        topic = self._clean(getattr(understanding, "topic", "")) if understanding is not None else ""
        if topic and owner not in {"agenda", "external", "operational", "personal_memory"}:
            self.observe_topic(topic, message)

        return stored

    # =========================================================
    # INFERRED INTERESTS FROM REPEATED TOPICS
    # =========================================================

    def observe_topic(self, topic: str, message: str = "") -> None:
        topic = self._clean(topic)
        normalized = self.normalize(topic)
        if not normalized or len(normalized) < 3:
            return
        if normalized in self.TOPIC_IGNORE:
            return
        if any(normalized == ignored or normalized.startswith(ignored + " ") for ignored in self.TOPIC_IGNORE):
            return

        if "agent os" in normalized or "agentos" in normalized:
            canonical = "Agent-OS"
        elif "home assistant" in normalized or "homeassistant" in normalized or "domotique" in normalized:
            canonical = "Home Assistant / domotique"
        elif "aquari" in normalized or "rasbora" in normalized or "crevette" in normalized:
            canonical = "Aquariophilie"
        elif "dofus" in normalized:
            canonical = "Dofus"
        else:
            canonical = self.TOPIC_CANONICAL.get(normalized, topic)
        normalized = self._subject_key(canonical)
        now = datetime.now().astimezone()
        now_iso = now.isoformat()
        day = now.date().isoformat()
        msg_hash = hashlib.sha256(self.normalize(message).encode("utf-8")).hexdigest() if message else ""

        with self._connect() as db:
            row = db.execute("SELECT * FROM topic_signals WHERE normalized_topic=?", (normalized,)).fetchone()
            if row is None:
                db.execute(
                    """
                    INSERT INTO topic_signals(
                        normalized_topic, topic, mentions, active_days_json,
                        first_seen, last_seen, last_message_hash
                    ) VALUES (?, ?, 1, ?, ?, ?, ?)
                    """,
                    (normalized, canonical, json.dumps([day]), now_iso, now_iso, msg_hash),
                )
                mentions = 1
                active_days = [day]
            else:
                item = dict(row)
                try:
                    active_days = list(json.loads(item.get("active_days_json") or "[]"))
                except Exception:
                    active_days = []
                if day not in active_days:
                    active_days.append(day)
                same_message = bool(msg_hash and msg_hash == str(item.get("last_message_hash") or ""))
                mentions = int(item.get("mentions") or 1) + (0 if same_message else 1)
                db.execute(
                    """
                    UPDATE topic_signals
                    SET topic=?, mentions=?, active_days_json=?, last_seen=?, last_message_hash=?
                    WHERE normalized_topic=?
                    """,
                    (canonical, mentions, json.dumps(active_days[-60:]), now_iso, msg_hash, normalized),
                )

        days = len(set(active_days))
        # Inference conservatrice : plusieurs occurrences et/ou plusieurs jours.
        if mentions >= 5 or (mentions >= 3 and days >= 2):
            confidence = min(0.86, 0.55 + mentions * 0.035 + days * 0.04)
            importance = min(0.92, 0.50 + mentions * 0.04 + days * 0.05)
            self.upsert_item(
                category="interest",
                subject=canonical,
                value="centre d'intérêt probable",
                content=f"Sujet récurrent dans les échanges : {canonical}",
                source="topic_frequency",
                confidence=confidence,
                importance=importance,
                explicit=False,
                inferred=True,
                evidence=f"topic-signal:{normalized}:{mentions}:{days}",
            )

    # =========================================================
    # QUERY / SUMMARY
    # =========================================================

    def count_items(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM profile_items WHERE status='active'").fetchone()[0])

    def items(self, category: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM profile_items WHERE status='active'"
        params: list[Any] = []
        if category in self.CATEGORIES:
            sql += " AND category=?"
            params.append(category)
        sql += " ORDER BY explicit DESC, importance DESC, mentions DESC, last_seen DESC LIMIT ?"
        params.append(max(1, min(500, int(limit))))
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    @classmethod
    def _requested_category(cls, query: str) -> str | None:
        n = cls.normalize(query)
        for category, markers in cls.QUERY_CATEGORY_MARKERS.items():
            if any(marker in n for marker in markers):
                return category
        return None

    @classmethod
    def _tokens(cls, text: Any) -> set[str]:
        ignored = {
            "que", "quoi", "qui", "sur", "mes", "mon", "ma", "moi", "je",
            "tu", "sais", "savoir", "resume", "resumer", "profil", "de", "des",
            "le", "la", "les", "un", "une", "et", "est", "sont", "principal",
        }
        return {t for t in cls.normalize(text).split() if len(t) >= 2 and t not in ignored}

    def relevant_items(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        requested = self._requested_category(query)
        candidates = self.items(requested, limit=250) if requested else self.items(limit=250)
        query_tokens = self._tokens(query)
        if not query_tokens:
            return candidates[:limit]

        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in candidates:
            text = " ".join((
                str(item.get("subject", "")),
                str(item.get("value", "")),
                str(item.get("content", "")),
                str(item.get("category", "")),
            ))
            tokens = self._tokens(text)
            overlap = len(query_tokens & tokens)
            score = overlap * 2.0
            score += float(item.get("importance") or 0.0)
            score += 0.25 if item.get("explicit") else 0.0
            if requested and item.get("category") == requested:
                score += 2.5
            if overlap or requested:
                ranked.append((score, item))

        ranked.sort(key=lambda row: row[0], reverse=True)
        return [item for _, item in ranked[:limit]] if ranked else []

    def context_for(self, query: str, limit: int = 14) -> str:
        items = self.relevant_items(query, limit=limit)
        if not items:
            return "(aucune information durable pertinente dans Personal Profile V6.5)"
        lines = ["PROFIL DURABLE STRUCTURÉ V6.5"]
        for item in items:
            certainty = "EXPLICITE" if item.get("explicit") else "INFÉRÉ"
            lines.append(
                f"- [{item['category']}] {item['subject']} = {item['value'] or item['content']} "
                f"| {certainty} | confiance={float(item['confidence']):.2f} "
                f"| importance={float(item['importance']):.2f} | mentions={int(item['mentions'])}"
            )
        lines.append(
            "Règle : EXPLICITE peut être affirmé comme fait utilisateur ; INFÉRÉ doit être formulé comme une tendance/probabilité."
        )
        return "\n".join(lines)

    def summary(self, category: str | None = None, limit: int = 80) -> str:
        categories = [category] if category in self.CATEGORIES else [
            "profile", "relation", "interest", "project", "goal", "skill", "preference", "habit"
        ]
        lines = ["PERSONAL PROFILE V6.5"]
        any_item = False
        for current in categories:
            values = self.items(current, limit=limit)
            if not values:
                continue
            any_item = True
            lines.append("")
            lines.append(self.CATEGORY_LABELS[current].upper())
            for item in values:
                suffix = " [inféré]" if item.get("inferred") and not item.get("explicit") else ""
                value = self._clean(item.get("value", ""))
                if value and self.normalize(value) != self.normalize(item.get("subject", "")):
                    text = f"{item['subject']} — {value}"
                else:
                    text = str(item["subject"])
                lines.append(f"- {text}{suffix}")
        if not any_item:
            lines.append("Aucune information durable structurée pour le moment.")
        return "\n".join(lines)

    def status_summary(self) -> str:
        with self._connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM profile_items WHERE status='active'").fetchone()[0])
            explicit = int(db.execute("SELECT COUNT(*) FROM profile_items WHERE status='active' AND explicit=1").fetchone()[0])
            inferred = int(db.execute("SELECT COUNT(*) FROM profile_items WHERE status='active' AND explicit=0 AND inferred=1").fetchone()[0])
            signals = int(db.execute("SELECT COUNT(*) FROM topic_signals").fetchone()[0])
            rows = db.execute(
                "SELECT category, COUNT(*) AS n FROM profile_items WHERE status='active' GROUP BY category ORDER BY category"
            ).fetchall()
        counts = {str(row["category"]): int(row["n"]) for row in rows}
        lines = [
            "PERSONAL PROFILE V6.5",
            f"Base : {self.db_path}",
            f"Informations actives : {total}",
            f"Explicites : {explicit}",
            f"Inférées : {inferred}",
            f"Sujets suivis : {signals}",
        ]
        for category in ("profile", "relation", "interest", "project", "goal", "skill", "preference", "habit"):
            lines.append(f"{self.CATEGORY_LABELS[category]} : {counts.get(category, 0)}")
        return "\n".join(lines)

    # =========================================================
    # FORGET
    # =========================================================

    def forget_matching(self, query: str) -> int:
        tokens = self._tokens(query)
        normalized = self.normalize(query)
        if not normalized:
            return 0
        changed = 0
        now = self._now()
        with self._connect() as db:
            rows = db.execute("SELECT * FROM profile_items WHERE status='active'").fetchall()
            for row in rows:
                item = dict(row)
                # Pour l'oubli, on cible l'identité structurée de l'item
                # (subject/value), pas toute la phrase d'évidence. Une phrase
                # peut mentionner Coralie, Brens et Agent-OS à la fois sans que
                # « oublie Coralie » doive supprimer les trois concepts.
                text = " ".join((str(item.get("subject", "")), str(item.get("value", ""))))
                item_norm = self.normalize(text)
                item_tokens = self._tokens(text)
                overlap = len(tokens & item_tokens)
                if normalized not in item_norm and not (tokens and overlap >= max(1, min(2, len(tokens)))):
                    continue
                db.execute("UPDATE profile_items SET status='forgotten', last_seen=? WHERE id=?", (now, int(item["id"])))
                db.execute(
                    """
                    INSERT INTO profile_history(item_id, category, subject, old_value, new_value, action, evidence, at)
                    VALUES (?, ?, ?, ?, '', 'forgotten', ?, ?)
                    """,
                    (int(item["id"]), item["category"], item["subject"], item.get("value", ""), query, now),
                )
                changed += 1
        return changed
