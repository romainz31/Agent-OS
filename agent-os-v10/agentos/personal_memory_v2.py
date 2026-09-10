from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


class PersonalMemoryV2:
    """Mémoire personnelle événementielle structurée V6.3.

    Principes :
    - SQLite est la source principale pour les événements personnels ;
    - la date vécue de l'événement est séparée de la date d'enregistrement ;
    - personnes, lieux et mots-clés sont indexés séparément ;
    - seules les informations venant de l'utilisateur peuvent devenir des
      souvenirs personnels ;
    - le stockage historique JSON peut être migré sans être détruit.

    Cette classe n'appelle jamais le Web et n'appelle jamais le LLM. Elle sert
    de couche de vérité structurée sur ce que l'utilisateur a réellement dit.
    """

    SCHEMA_VERSION = 4

    QUESTION_WORDS = {
        "qui", "que", "quoi", "quel", "quelle", "quels", "quelles",
        "ou", "où", "quand", "comment", "pourquoi", "combien",
        "est", "ce", "estce", "jusqua", "jusqu", "a", "quelle",
    }

    STOPWORDS = {
        "alors", "avec", "avoir", "dans", "depuis", "des", "elle", "elles",
        "encore", "est", "fait", "faire", "fais", "il", "ils", "je", "j",
        "jai", "j ai", "les", "leur", "leurs", "mais", "mes", "moi", "mon",
        "ma", "ne", "nous", "notre", "nos", "pas", "pour", "que", "qui",
        "quoi", "sans", "ses", "son", "sur", "tes", "toi", "ton", "tous",
        "tout", "tres", "tu", "une", "vos", "votre", "vous", "ca", "cest",
        "c est", "dun", "dune", "de", "du", "et", "en", "la", "le", "un",
        "a", "au", "aux", "ce", "cette", "cet", "ces", "quand", "comment",
        "ou", "où", "dernier", "derniere", "fois", "hier", "aujourdhui",
        "aujourd", "hui", "demain", "avant", "apres", "après", "dernierement",
        "ai", "avais", "etais", "suis", "sommes",
    }

    GENERIC_PLACE_TERMS = {
        "aeroport": "aéroport",
        "aéroport": "aéroport",
        "gare": "gare",
        "hopital": "hôpital",
        "hôpital": "hôpital",
        "restaurant": "restaurant",
        "bureau": "bureau",
        "travail": "travail",
        "ecole": "école",
        "école": "école",
        "maison": "maison",
        "supermarche": "supermarché",
        "supermarché": "supermarché",
        "magasin": "magasin",
        "cinema": "cinéma",
        "cinéma": "cinéma",
        "hotel": "hôtel",
        "hôtel": "hôtel",
    }

    TRANSPORT_TERMS = {
        "avion": "avion",
        "vol": "avion",
        "easyjet": "avion",
        "ryanair": "avion",
        "airfrance": "avion",
        "air france": "avion",
        "train": "train",
        "tgv": "train",
        "ter": "train",
        "voiture": "voiture",
        "auto": "voiture",
        "bus": "bus",
        "car": "bus",
        "metro": "métro",
        "métro": "métro",
        "tram": "tramway",
        "tramway": "tramway",
        "bateau": "bateau",
        "ferry": "bateau",
        "velo": "vélo",
        "vélo": "vélo",
        "moto": "moto",
    }

    WEEKDAYS = {
        "lundi": 0,
        "mardi": 1,
        "mercredi": 2,
        "jeudi": 3,
        "vendredi": 4,
        "samedi": 5,
        "dimanche": 6,
    }

    NUMBER_WORDS = {
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
        "seize": 16,
        "vingt": 20,
        "trente": 30,
    }

    def __init__(
        self,
        db_path: str | Path,
        *,
        known_people_provider: Callable[[], list[str] | set[str] | tuple[str, ...]]
        | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.known_people_provider = known_people_provider
        self._ensure_schema()

    # =========================================================
    # NORMALISATION
    # =========================================================

    @staticmethod
    def _clean(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _ascii(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        return "".join(
            char
            for char in text
            if not unicodedata.combining(char)
        )

    @classmethod
    def normalize(cls, value: Any) -> str:
        text = cls._ascii(cls._clean(value))
        replacements = (
            (r"\bjai\b", "j ai"),
            (r"\bjavais\b", "j avais"),
            (r"\bjetais\b", "j etais"),
            (r"\bjsuis\b", "je suis"),
            (r"\bjusqua\b", "jusqu a"),
            (r"\bcest\b", "c est"),
            (r"\bquest\b", "qu est"),
        )
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    @classmethod
    def _tokens(cls, value: Any) -> set[str]:
        normalized = cls.normalize(value)
        return {
            token
            for token in normalized.split()
            if len(token) >= 2 and token not in cls.STOPWORDS
        }

    @classmethod
    def _fingerprint(
        cls,
        content: str,
        event_start: str | None,
        event_end: str | None,
        source: str,
    ) -> str:
        raw = "|".join(
            [
                cls.normalize(content),
                str(event_start or ""),
                str(event_end or ""),
                cls.normalize(source),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

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

    @classmethod
    def _reference_dt(cls, value: Any = None) -> datetime:
        parsed = cls._parse_dt(value)
        if parsed is None:
            return datetime.now().astimezone()
        try:
            return parsed.astimezone()
        except Exception:
            return parsed

    # =========================================================
    # SQLITE
    # =========================================================

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    normalized_content TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    event_start TEXT,
                    event_end TEXT,
                    date_precision TEXT,
                    temporal_expression TEXT,
                    recorded_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    people_json TEXT NOT NULL DEFAULT '[]',
                    places_json TEXT NOT NULL DEFAULT '[]',
                    topics_json TEXT NOT NULL DEFAULT '[]',
                    transport TEXT,
                    transport_confidence REAL,
                    transport_inferred INTEGER NOT NULL DEFAULT 0,
                    legacy_key TEXT,
                    occurrences INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_personal_events_start "
                "ON personal_events(event_start)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_personal_events_recorded "
                "ON personal_events(recorded_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_personal_events_kind "
                "ON personal_events(kind)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_memory_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_event_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_name TEXT,
                    predicate TEXT NOT NULL,
                    object_text TEXT,
                    place TEXT,
                    confidence REAL NOT NULL DEFAULT 0.9,
                    inferred INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(event_id) REFERENCES personal_events(id)
                        ON DELETE CASCADE
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_personal_event_facts_event "
                "ON personal_event_facts(event_id)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_personal_event_facts_predicate "
                "ON personal_event_facts(predicate)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_personal_event_facts_subject "
                "ON personal_event_facts(subject_type, subject_name)"
            )
            db.execute(
                "INSERT OR REPLACE INTO personal_memory_meta(key, value) "
                "VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )

        self._backfill_event_facts()

    # =========================================================
    # EVENT FACTS / ACTOR IDENTITY V6.3.1
    # =========================================================

    @staticmethod
    def _fact_subject_label(
        subject_type: str,
        subject_name: str | None,
    ) -> str:
        if subject_type == "user":
            return "toi"
        if subject_type == "person" and subject_name:
            return str(subject_name)
        return "quelqu'un"

    def extract_facts(
        self,
        content: str,
        *,
        people: list[str] | None = None,
        places: list[str] | None = None,
        transport: str | None = None,
        transport_inferred: bool = False,
    ) -> list[dict[str, Any]]:
        """Extrait des faits simples sujet -> action -> objet.

        Dans une déclaration utilisateur, ``je`` désigne toujours
        l'utilisateur, jamais Paul.
        """
        raw = self._clean(content)
        normalized = self.normalize(raw)
        people = list(people or self.extract_people(raw))
        places = list(places or self.extract_places(raw))
        place = places[0] if places else None
        result: list[dict[str, Any]] = []

        def add(
            subject_type: str,
            predicate: str,
            *,
            subject_name: str | None = None,
            object_text: str | None = None,
            fact_place: str | None = None,
            confidence: float = 0.95,
            inferred: bool = False,
        ) -> None:
            item = {
                "subject_type": subject_type,
                "subject_name": self._clean(subject_name) or None,
                "predicate": self._clean(predicate),
                "object_text": self._clean(object_text) or None,
                "place": self._clean(fact_place) or None,
                "confidence": max(0.0, min(1.0, float(confidence))),
                "inferred": bool(inferred),
            }
            key = (
                item["subject_type"],
                self.normalize(item["subject_name"] or ""),
                self.normalize(item["predicate"]),
                self.normalize(item["object_text"] or ""),
                self.normalize(item["place"] or ""),
            )
            for existing in result:
                existing_key = (
                    existing["subject_type"],
                    self.normalize(existing.get("subject_name") or ""),
                    self.normalize(existing["predicate"]),
                    self.normalize(existing.get("object_text") or ""),
                    self.normalize(existing.get("place") or ""),
                )
                if existing_key == key:
                    return
            result.append(item)

        if re.search(
            r"\bj ai (?:emmene|accompagne|conduit|depose|amene)\b",
            normalized,
        ):
            target = people[0] if people else None
            add(
                "user",
                "emmener",
                object_text=target,
                fact_place=place,
                confidence=0.99,
            )

        if re.search(
            r"\b(?:je suis alle|je suis allee|j ai ete)\b",
            normalized,
        ) and place:
            add(
                "user",
                "aller",
                object_text=place,
                fact_place=place,
                confidence=0.98,
            )

        seen_match = re.search(
            r"\bj ai (?:vu|observe|apercu|croise)\s+(.+?)(?:\s+(?:a|au|aux|dans|sur)\s+|$)",
            normalized,
        )
        if seen_match:
            seen_object = self._clean(seen_match.group(1))
            seen_object = re.sub(
                r"^(?:un|une|le|la|les)\s+",
                "",
                seen_object,
            ).strip()
            if seen_object:
                add(
                    "user",
                    "voir",
                    object_text=seen_object,
                    fact_place=place,
                    confidence=0.97,
                )

        for person in people:
            person_norm = self.normalize(person)
            escaped = re.escape(person_norm)
            if re.search(
                rf"(?<![a-z0-9]){escaped}(?![a-z0-9]).*"
                r"\b(?:est partie|est parti|est allee|est alle|"
                r"a voyage|a quitte|est rentree|est rentre)\b",
                normalized,
            ):
                add(
                    "person",
                    "partir_voyage",
                    subject_name=person,
                    object_text="voyage",
                    fact_place=place,
                    confidence=0.97,
                )

        if people and re.search(
            r"\belle est partie\b|\belle partait\b|\belle est allee\b",
            normalized,
        ):
            add(
                "person",
                "partir_voyage",
                subject_name=people[0],
                object_text="voyage",
                fact_place=place,
                confidence=0.96,
            )

        if transport and (
            "voyage" in normalized
            or re.search(r"\b(?:partie|parti|depart|vol|train)\b", normalized)
        ):
            traveler = people[0] if people else None
            if traveler:
                add(
                    "person",
                    "voyager_transport",
                    subject_name=traveler,
                    object_text=transport,
                    fact_place=place,
                    confidence=0.82 if transport_inferred else 0.99,
                    inferred=transport_inferred,
                )

        return result

    def _replace_event_facts(
        self,
        db: sqlite3.Connection,
        event_id: int,
        facts: list[dict[str, Any]],
    ) -> None:
        db.execute(
            "DELETE FROM personal_event_facts WHERE event_id = ?",
            (int(event_id),),
        )
        for fact in facts:
            db.execute(
                """
                INSERT INTO personal_event_facts (
                    event_id, subject_type, subject_name, predicate,
                    object_text, place, confidence, inferred
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(event_id),
                    str(fact.get("subject_type") or "unknown"),
                    fact.get("subject_name"),
                    str(fact.get("predicate") or "related"),
                    fact.get("object_text"),
                    fact.get("place"),
                    float(fact.get("confidence", 0.9) or 0.9),
                    1 if fact.get("inferred") else 0,
                ),
            )

    def _facts_for_event(
        self,
        event_id: int,
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT subject_type, subject_name, predicate, object_text,
                       place, confidence, inferred
                FROM personal_event_facts
                WHERE event_id = ?
                ORDER BY id ASC
                """,
                (int(event_id),),
            ).fetchall()
        return [
            {
                "subject_type": str(row["subject_type"]),
                "subject_name": row["subject_name"],
                "predicate": str(row["predicate"]),
                "object_text": row["object_text"],
                "place": row["place"],
                "confidence": float(row["confidence"] or 0.0),
                "inferred": bool(row["inferred"]),
            }
            for row in rows
        ]

    def _backfill_event_facts(self) -> None:
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT * FROM personal_events ORDER BY id ASC"
                ).fetchall()
                for row in rows:
                    event_id = int(row["id"])
                    count = db.execute(
                        "SELECT COUNT(*) FROM personal_event_facts "
                        "WHERE event_id = ?",
                        (event_id,),
                    ).fetchone()[0]
                    if int(count or 0) > 0:
                        continue
                    people = self._json_list(row["people_json"])
                    places = self._json_list(row["places_json"])
                    transport = self._clean(row["transport"])
                    facts = self.extract_facts(
                        str(row["content"]),
                        people=people,
                        places=places,
                        transport=transport or None,
                        transport_inferred=bool(row["transport_inferred"]),
                    )
                    self._replace_event_facts(db, event_id, facts)
        except sqlite3.Error:
            return

    # =========================================================
    # DATES / TIMELINE
    # =========================================================

    @classmethod
    def _weekday_before(
        cls,
        reference: datetime,
        weekday: int,
        *,
        force_previous: bool = True,
    ) -> date:
        delta = (reference.weekday() - weekday) % 7
        if delta == 0 and force_previous:
            delta = 7
        return (reference - timedelta(days=delta)).date()

    @classmethod
    def _weekday_after_or_equal(
        cls,
        reference: datetime,
        weekday: int,
    ) -> date:
        delta = (weekday - reference.weekday()) % 7
        return (reference + timedelta(days=delta)).date()

    @classmethod
    def resolve_date_range(
        cls,
        text: str,
        *,
        reference_at: Any = None,
        for_end_expression: bool = False,
    ) -> dict[str, Any] | None:
        raw_text = cls._clean(text)
        normalized = cls.normalize(raw_text)
        if not normalized:
            return None

        reference = cls._reference_dt(reference_at)
        base = reference.replace(
            hour=12,
            minute=0,
            second=0,
            microsecond=0,
        )

        # Date explicite JJ/MM/AAAA ou JJ-MM-AAAA.
        explicit = re.search(
            r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b",
            raw_text,
        )
        if explicit:
            day, month, year = map(int, explicit.groups())
            try:
                resolved = date(year, month, day)
            except ValueError:
                resolved = None
            if resolved is not None:
                iso = resolved.isoformat()
                return {
                    "start": iso,
                    "end": iso,
                    "precision": "day",
                    "expression": explicit.group(0),
                }

        if "avant hier" in normalized:
            target = (base - timedelta(days=2)).date().isoformat()
            return {
                "start": target,
                "end": target,
                "precision": "day",
                "expression": "avant-hier",
            }

        if re.search(r"(?<!avant )\bhier\b", normalized):
            target = (base - timedelta(days=1)).date().isoformat()
            return {
                "start": target,
                "end": target,
                "precision": "day",
                "expression": "hier",
            }

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
            target = base.date().isoformat()
            return {
                "start": target,
                "end": target,
                "precision": "day",
                "expression": "aujourd'hui",
            }

        if re.search(r"\bdemain\b", normalized):
            target = (base + timedelta(days=1)).date().isoformat()
            return {
                "start": target,
                "end": target,
                "precision": "day",
                "expression": "demain",
            }

        ago = re.search(
            r"\bil y a\s+(\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|"
            r"neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt|trente)\s+"
            r"(jour|jours|semaine|semaines|mois|an|ans)\b",
            normalized,
        )
        if ago:
            raw_number = ago.group(1)
            count = (
                int(raw_number)
                if raw_number.isdigit()
                else cls.NUMBER_WORDS.get(raw_number)
            )
            unit = ago.group(2)
            if count is not None:
                if unit.startswith("jour"):
                    target = (base - timedelta(days=count)).date()
                    return {
                        "start": target.isoformat(),
                        "end": target.isoformat(),
                        "precision": "day",
                        "expression": ago.group(0),
                    }
                if unit.startswith("semaine"):
                    target = (base - timedelta(weeks=count)).date()
                    return {
                        "start": target.isoformat(),
                        "end": target.isoformat(),
                        "precision": "day",
                        "expression": ago.group(0),
                    }
                if unit == "mois":
                    year = base.year
                    month = base.month - count
                    while month <= 0:
                        month += 12
                        year -= 1
                    day = min(base.day, monthrange(year, month)[1])
                    target = date(year, month, day)
                    return {
                        "start": target.isoformat(),
                        "end": target.isoformat(),
                        "precision": "day",
                        "expression": ago.group(0),
                    }
                if unit in {"an", "ans"}:
                    year = base.year - count
                    day = min(base.day, monthrange(year, base.month)[1])
                    target = date(year, base.month, day)
                    return {
                        "start": target.isoformat(),
                        "end": target.isoformat(),
                        "precision": "day",
                        "expression": ago.group(0),
                    }

        weekday_match = re.search(
            r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
            r"dernier(?:e)?\b",
            normalized,
        )
        if weekday_match:
            target = cls._weekday_before(
                base,
                cls.WEEKDAYS[weekday_match.group(1)],
                force_previous=True,
            )
            return {
                "start": target.isoformat(),
                "end": target.isoformat(),
                "precision": "day",
                "expression": weekday_match.group(0),
            }

        # « jusqu'à samedi » décrit une borne de fin future, pas un ancien samedi.
        if for_end_expression:
            weekday_simple = re.search(
                r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b",
                normalized,
            )
            if weekday_simple:
                target = cls._weekday_after_or_equal(
                    base,
                    cls.WEEKDAYS[weekday_simple.group(1)],
                )
                return {
                    "start": target.isoformat(),
                    "end": target.isoformat(),
                    "precision": "day",
                    "expression": weekday_simple.group(1),
                }

        if any(
            marker in normalized
            for marker in (
                "la semaine derniere",
                "semaine derniere",
            )
        ):
            current_monday = base.date() - timedelta(days=base.weekday())
            start = current_monday - timedelta(days=7)
            end = start + timedelta(days=6)
            return {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "precision": "week",
                "expression": "la semaine dernière",
            }

        if any(
            marker in normalized
            for marker in (
                "le mois dernier",
                "mois dernier",
            )
        ):
            if base.month == 1:
                year, month = base.year - 1, 12
            else:
                year, month = base.year, base.month - 1
            start = date(year, month, 1)
            end = date(year, month, monthrange(year, month)[1])
            return {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "precision": "month",
                "expression": "le mois dernier",
            }

        return None

    @classmethod
    def resolve_event_dates(
        cls,
        content: str,
        *,
        reference_at: Any = None,
    ) -> dict[str, Any]:
        main = cls.resolve_date_range(
            content,
            reference_at=reference_at,
        )

        normalized = cls.normalize(content)
        end_date = None
        end_expression = None
        until = re.search(
            r"\bjusqu a\s+(.{1,40})$",
            normalized,
        )
        if until:
            resolved_end = cls.resolve_date_range(
                until.group(1),
                reference_at=reference_at,
                for_end_expression=True,
            )
            if resolved_end is not None:
                end_date = resolved_end.get("end")
                end_expression = resolved_end.get("expression")

        return {
            "event_start": main.get("start") if main else None,
            "event_end": end_date or (main.get("end") if main else None),
            "date_precision": main.get("precision") if main else None,
            "temporal_expression": main.get("expression") if main else None,
            "end_expression": end_expression,
        }

    # =========================================================
    # STRUCTURED EXTRACTION
    # =========================================================

    def known_people(self) -> set[str]:
        result: set[str] = set()

        provider = self.known_people_provider
        if provider is not None:
            try:
                values = provider() or []
            except Exception:
                values = []
            for value in values:
                clean = self._clean(value)
                if len(clean) >= 2:
                    result.add(clean)

        # V6.3.1 : une personne déjà présente dans les événements SQLite reste
        # une ancre personnelle même si la mémoire relationnelle n'est pas
        # encore parfaitement structurée.
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT people_json FROM personal_events "
                    "WHERE people_json <> '[]' ORDER BY id DESC LIMIT 500"
                ).fetchall()
            for row in rows:
                for value in self._json_list(row["people_json"]):
                    clean = self._clean(value)
                    if len(clean) >= 2:
                        result.add(clean)
        except sqlite3.Error:
            pass

        return result

    def extract_people(self, content: str) -> list[str]:
        normalized = self.normalize(content)
        found: list[str] = []

        for person in sorted(self.known_people(), key=len, reverse=True):
            wanted = self.normalize(person)
            if wanted and re.search(
                rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])",
                normalized,
            ):
                found.append(person)

        relation_name = re.search(
            r"\b(?:ma copine|mon copain|ma compagne|mon compagnon|ma femme|"
            r"mon mari|ma mere|mon pere|ma soeur|mon frere|mon ami|mon amie)\s+"
            r"([a-z][a-z'-]{1,30})\b",
            normalized,
        )
        if relation_name:
            candidate = relation_name.group(1).capitalize()
            if candidate not in found:
                found.append(candidate)

        # Noms propres visibles dans le texte original ; utile avant que la
        # relation ne soit déjà connue.
        for candidate in re.findall(
            r"(?<![.!?]\s)(?<!^)\b([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ'-]{2,30})\b",
            str(content or ""),
        ):
            if candidate not in found:
                found.append(candidate)

        return found[:12]

    @classmethod
    def extract_places(cls, content: str) -> list[str]:
        normalized = cls.normalize(content)
        found: list[str] = []

        for raw, display in cls.GENERIC_PLACE_TERMS.items():
            if re.search(
                rf"(?<![a-z0-9]){re.escape(cls.normalize(raw))}(?![a-z0-9])",
                normalized,
            ):
                found.append(display)

        # Formes « aéroport de Toulouse », « gare de Gaillac ».
        place_with_city = re.finditer(
            r"\b(aeroport|gare|hopital|restaurant|hotel)\s+de\s+"
            r"([a-z][a-z'-]{2,30}(?:\s+[a-z][a-z'-]{2,30})?)\b",
            normalized,
        )
        for match in place_with_city:
            base = cls.GENERIC_PLACE_TERMS.get(match.group(1), match.group(1))
            city = match.group(2).title()
            display = f"{base} de {city}"
            if display not in found:
                found.append(display)

        # Destination / vers + nom propre dans le texte original.
        original = str(content or "")
        for match in re.finditer(
            r"\b(?:vers|destination|à|a)\s+"
            r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ'-]{2,30}(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ'-]{2,30})?)",
            original,
        ):
            candidate = cls._clean(match.group(1))
            if candidate and candidate not in found:
                found.append(candidate)

        # Déduplique en conservant l'ordre.
        unique: list[str] = []
        seen: set[str] = set()
        for item in found:
            key = cls.normalize(item)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique[:12]

    @classmethod
    def extract_transport(
        cls,
        content: str,
    ) -> tuple[str | None, float | None, bool]:
        normalized = cls.normalize(content)
        for marker, transport in cls.TRANSPORT_TERMS.items():
            wanted = cls.normalize(marker)
            if re.search(
                rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])",
                normalized,
            ):
                return transport, 0.98, False

        # Inférence simple : aéroport + départ/voyage implique très probablement
        # un avion. Elle reste marquée comme déduction et non comme fait brut.
        if (
            "aeroport" in normalized
            and any(
                marker in normalized
                for marker in (
                    "voyage", "partie", "parti", "depart", "départ",
                    "decoll", "décoll", "embarq",
                )
            )
        ):
            return "avion", 0.82, True

        return None, None, False

    @classmethod
    def extract_topics(cls, content: str) -> list[str]:
        tokens = list(cls._tokens(content))
        priority = [
            token
            for token in tokens
            if token not in {
                "copine", "copain", "compagne", "compagnon", "femme",
                "mari", "mere", "pere", "soeur", "frere", "ami", "amie",
            }
        ]
        return sorted(priority, key=lambda item: (-len(item), item))[:16]

    # =========================================================
    # STATEMENT / QUERY CLASSIFICATION
    # =========================================================

    @classmethod
    def explicit_web_request(cls, message: str) -> bool:
        normalized = cls.normalize(message)
        return any(
            marker in normalized
            for marker in (
                "cherche sur internet",
                "recherche sur internet",
                "cherche sur le web",
                "recherche sur le web",
                "verifie sur internet",
                "verifie sur le web",
                "google",
            )
        )

    @classmethod
    def question_like(cls, message: str) -> bool:
        raw = cls._clean(message)
        if not raw:
            return False
        if raw.endswith("?"):
            return True
        normalized = cls.normalize(raw)
        return normalized.startswith(
            (
                "qui ", "que ", "quoi ", "quel ", "quelle ", "quels ",
                "quelles ", "ou ", "quand ", "comment ", "pourquoi ",
                "combien ", "est ce ", "jusqu a quand ", "tu te souviens ",
                "rappelle moi ",
            )
        )

    def looks_personal_statement(self, message: str) -> bool:
        if self.question_like(message) or self.explicit_web_request(message):
            return False

        normalized = self.normalize(message)
        if not normalized:
            return False

        # Évite de transformer une demande, un besoin ou un état corporel
        # instantané en épisode vécu. Ces informations ont déjà leurs couches
        # dédiées (conversation / STATE / relationnel).
        non_event_after_jai = (
            "besoin", "envie", "faim", "soif", "peur", "chaud", "froid",
            "raison", "tort", "une question", "l impression", "du mal",
        )
        first_person_past = bool(
            re.search(
                r"\b(?:j ai|j avais)\b",
                normalized,
            )
        )
        if first_person_past:
            after = normalized.split("j ai", 1)[1].strip() if "j ai" in normalized else ""
            if after and any(after.startswith(marker) for marker in non_event_after_jai):
                first_person_past = False

        movement_past = bool(
            re.search(
                r"\bje suis (?:alle|allee|parti|partie|rentre|rentree|venu|venue|reste|restee)\b",
                normalized,
            )
        )

        temporal = self.resolve_date_range(message) is not None
        relation = bool(
            re.search(
                r"\b(?:ma copine|mon copain|ma compagne|mon compagnon|ma femme|"
                r"mon mari|ma mere|mon pere|ma soeur|mon frere|mon ami|mon amie)\b",
                normalized,
            )
        )

        known_person = False
        for person in self.known_people():
            wanted = self.normalize(person)
            if wanted and re.search(
                rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])",
                normalized,
            ):
                known_person = True
                break

        third_person_event = bool(
            (relation or known_person)
            and re.search(
                r"\b(?:est partie|est parti|est allee|est alle|a pris|a voyage|"
                r"a quitte|a commence|a termine|a fini|est rentree|est rentre)\b",
                normalized,
            )
        )

        return (
            first_person_past
            or movement_past
            or third_person_event
            or (temporal and (relation or known_person))
        )

    def looks_personal_query(self, message: str) -> bool:
        if not self.question_like(message):
            return False
        if self.explicit_web_request(message):
            return False

        normalized = self.normalize(message)
        if not normalized:
            return False

        explicit_recall = any(
            marker in normalized
            for marker in (
                "tu te souviens",
                "je t ai dit",
                "je t avais dit",
                "je t ai raconte",
                "je t avais raconte",
                "rappelle moi",
                "d apres ce que je t ai dit",
                "derniere fois",
            )
        )
        if explicit_recall:
            return True

        first_person = bool(
            re.search(
                r"\b(?:j ai|j avais|j etais|je suis|je vais|je suis alle|"
                r"je suis allee|moi|mon|ma|mes|notre|nos)\b",
                normalized,
            )
        )
        if first_person:
            return True

        relation_anchor = bool(
            re.search(
                r"\b(?:ma copine|mon copain|ma compagne|mon compagnon|ma femme|"
                r"mon mari|ma mere|mon pere|ma soeur|mon frere|mon ami|mon amie|"
                r"mes parents)\b",
                normalized,
            )
        )
        if relation_anchor:
            return True

        for person in self.known_people():
            wanted = self.normalize(person)
            if wanted and re.search(
                rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])",
                normalized,
            ):
                return True

        return False

    # =========================================================
    # WRITE / MIGRATION
    # =========================================================

    def remember_event(
        self,
        content: str,
        *,
        kind: str = "event",
        source: str = "user",
        confidence: float = 0.85,
        recorded_at: Any = None,
        event_start: str | None = None,
        event_end: str | None = None,
        date_precision: str | None = None,
        temporal_expression: str | None = None,
        people: list[str] | None = None,
        places: list[str] | None = None,
        topics: list[str] | None = None,
        legacy_key: str | None = None,
    ) -> dict[str, Any] | None:
        content = self._clean(content)
        if not content:
            return None

        normalized_source = self.normalize(source)
        if normalized_source in {"assistant", "paul", "agentos", "system"}:
            return None

        recorded_dt = self._reference_dt(recorded_at)
        recorded_iso = recorded_dt.isoformat()

        resolved = self.resolve_event_dates(
            content,
            reference_at=recorded_iso,
        )
        event_start = event_start or resolved.get("event_start")
        event_end = event_end or resolved.get("event_end")
        date_precision = date_precision or resolved.get("date_precision")
        temporal_expression = temporal_expression or resolved.get(
            "temporal_expression"
        )

        people = list(people or self.extract_people(content))
        places = list(places or self.extract_places(content))
        topics = list(topics or self.extract_topics(content))
        transport, transport_confidence, transport_inferred = (
            self.extract_transport(content)
        )

        fingerprint = self._fingerprint(
            content,
            event_start,
            event_end,
            source,
        )

        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM personal_events WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()

            if existing is None:
                db.execute(
                    """
                    INSERT INTO personal_events (
                        fingerprint, content, normalized_content, kind, source,
                        confidence, event_start, event_end, date_precision,
                        temporal_expression, recorded_at, updated_at,
                        people_json, places_json, topics_json, transport,
                        transport_confidence, transport_inferred, legacy_key,
                        occurrences
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        fingerprint,
                        content,
                        self.normalize(content),
                        self._clean(kind) or "event",
                        self._clean(source) or "user",
                        max(0.0, min(1.0, float(confidence))),
                        event_start,
                        event_end,
                        date_precision,
                        temporal_expression,
                        recorded_iso,
                        recorded_iso,
                        json.dumps(people, ensure_ascii=False),
                        json.dumps(places, ensure_ascii=False),
                        json.dumps(topics, ensure_ascii=False),
                        transport,
                        transport_confidence,
                        1 if transport_inferred else 0,
                        legacy_key,
                    ),
                )
            else:
                previous_updated = self._parse_dt(existing["updated_at"])
                increment = True
                if previous_updated is not None:
                    age = abs(
                        (recorded_dt.astimezone(timezone.utc)
                         - previous_updated.astimezone(timezone.utc)).total_seconds()
                    )
                    # Évite le double comptage immédiat dû au dual-write
                    # Manager + Memory pendant le même tour.
                    if age <= 10.0:
                        increment = False

                occurrences = int(existing["occurrences"] or 1)
                if increment:
                    occurrences += 1

                db.execute(
                    """
                    UPDATE personal_events
                    SET updated_at = ?, occurrences = ?, confidence = ?,
                        people_json = ?, places_json = ?, topics_json = ?,
                        transport = COALESCE(transport, ?),
                        transport_confidence = COALESCE(transport_confidence, ?),
                        transport_inferred = CASE
                            WHEN transport IS NULL THEN ?
                            ELSE transport_inferred
                        END
                    WHERE fingerprint = ?
                    """,
                    (
                        recorded_iso,
                        occurrences,
                        max(float(existing["confidence"] or 0.0), float(confidence)),
                        json.dumps(people, ensure_ascii=False),
                        json.dumps(places, ensure_ascii=False),
                        json.dumps(topics, ensure_ascii=False),
                        transport,
                        transport_confidence,
                        1 if transport_inferred else 0,
                        fingerprint,
                    ),
                )

            row = db.execute(
                "SELECT * FROM personal_events WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()

            if row is not None:
                facts = self.extract_facts(
                    content,
                    people=people,
                    places=places,
                    transport=transport,
                    transport_inferred=transport_inferred,
                )
                self._replace_event_facts(
                    db,
                    int(row["id"]),
                    facts,
                )

        return self._row_to_dict(row) if row is not None else None

    def migrate_legacy(
        self,
        items: list[dict[str, Any]] | None,
    ) -> dict[str, int]:
        result = {
            "seen": 0,
            "imported": 0,
            "skipped": 0,
        }

        with self._connect() as db:
            existing_fingerprints = {
                str(row[0])
                for row in db.execute(
                    "SELECT fingerprint FROM personal_events"
                ).fetchall()
            }

        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            result["seen"] += 1

            source = self._clean(item.get("source", "user")) or "user"
            kind = self._clean(item.get("kind", "event")) or "event"
            if self.normalize(source) in {"agentos", "assistant", "system", "paul"}:
                result["skipped"] += 1
                continue

            content = self._clean(item.get("content", ""))
            if not content:
                result["skipped"] += 1
                continue

            recorded_at = item.get("created_at")
            event_start = self._clean(item.get("event_date", "")) or None
            resolved = self.resolve_event_dates(
                content,
                reference_at=recorded_at,
            )
            effective_start = event_start or resolved.get("event_start")
            effective_end = resolved.get("event_end")
            fingerprint = self._fingerprint(
                content,
                effective_start,
                effective_end,
                source,
            )
            if fingerprint in existing_fingerprints:
                result["skipped"] += 1
                continue

            self.remember_event(
                content,
                kind=kind,
                source=source,
                confidence=float(item.get("confidence", 0.8) or 0.8),
                recorded_at=recorded_at,
                event_start=event_start,
                legacy_key=f"episodic:{index}:{self.normalize(content)[:80]}",
            )
            result["imported"] += 1
            existing_fingerprints.add(fingerprint)

        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO personal_memory_meta(key, value) "
                "VALUES('legacy_migration_last_at', ?)",
                (datetime.now().astimezone().isoformat(),),
            )

        return result

    # =========================================================
    # READ / SEARCH
    # =========================================================

    @staticmethod
    def _json_list(value: Any) -> list[str]:
        try:
            loaded = json.loads(str(value or "[]"))
        except Exception:
            return []
        if not isinstance(loaded, list):
            return []
        return [str(item) for item in loaded if str(item).strip()]

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        result = dict(row)
        result["people"] = self._json_list(result.pop("people_json", "[]"))
        result["places"] = self._json_list(result.pop("places_json", "[]"))
        result["topics"] = self._json_list(result.pop("topics_json", "[]"))
        result["transport_inferred"] = bool(result.get("transport_inferred"))
        try:
            result["facts"] = self._facts_for_event(int(result["id"]))
        except Exception:
            result["facts"] = []
        return result

    @classmethod
    def _query_plan(cls, query: str) -> dict[str, Any]:
        normalized = cls.normalize(query)
        latest = any(
            marker in normalized
            for marker in (
                "derniere fois",
                "dernier fois",
                "plus recemment",
                "plus recent",
            )
        )

        if "jusqu a quand" in normalized or re.search(
            r"\bquand\s+(?:est ce que\s+)?(?:elle|il|coralie|\w+)\s+"
            r"(?:rentre|revient|termine|finit)\b",
            normalized,
        ):
            intent = "until"
        elif normalized.startswith("quand ") or " quelle date " in f" {normalized} ":
            intent = "when"
        elif normalized.startswith("ou ") or " ou est " in f" {normalized} ":
            intent = "where"
        elif normalized.startswith("comment "):
            intent = "how"
        elif normalized.startswith("avec qui ") or normalized.startswith("qui "):
            intent = "who"
        else:
            intent = "recall"

        return {
            "normalized": normalized,
            "intent": intent,
            "latest": latest,
        }

    @classmethod
    def _query_keywords(cls, query: str) -> set[str]:
        ignored = {
            "derniere", "dernier", "fois", "plus", "recent", "recemment",
            "quand", "date", "moment", "ou", "comment", "avec", "qui",
            "jusqu", "jusqua", "est", "elle", "il", "lui", "je", "jai",
            "ai", "suis", "alle", "allee", "partie", "parti", "voyage",
        }
        return {
            token
            for token in cls._tokens(query)
            if token not in ignored
        }

    def _candidate_rows(
        self,
        *,
        date_filter: dict[str, Any] | None = None,
        limit: int = 800,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM personal_events"
        params: list[Any] = []
        if date_filter and date_filter.get("start") and date_filter.get("end"):
            sql += (
                " WHERE event_start IS NOT NULL "
                "AND event_start >= ? AND event_start <= ?"
            )
            params.extend(
                [date_filter["start"], date_filter["end"]]
            )
        sql += (
            " ORDER BY COALESCE(event_start, '') DESC, recorded_at DESC "
            "LIMIT ?"
        )
        params.append(max(1, int(limit)))
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        plan = self._query_plan(query)
        normalized = plan["normalized"]
        date_filter = self.resolve_date_range(query)
        keywords = self._query_keywords(query)
        known_people = {
            self.normalize(person): person
            for person in self.known_people()
        }
        query_people = {
            original
            for normalized_name, original in known_people.items()
            if normalized_name
            and re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_name)}(?![a-z0-9])",
                normalized,
            )
        }

        rows = self._candidate_rows(
            date_filter=date_filter,
        )
        scored: list[tuple[float, str, str, int, dict[str, Any]]] = []

        for index, item in enumerate(rows):
            content = item.get("content", "")
            content_tokens = self._tokens(content)
            topic_tokens = {
                self.normalize(topic)
                for topic in item.get("topics", [])
            }
            place_tokens = set()
            for place in item.get("places", []):
                place_tokens.update(self._tokens(place))
            people_tokens = set()
            for person in item.get("people", []):
                people_tokens.update(self._tokens(person))

            fact_tokens = set()
            for fact in item.get("facts", []):
                if not isinstance(fact, dict):
                    continue
                fact_tokens.update(self._tokens(fact.get("subject_name", "")))
                fact_tokens.update(self._tokens(fact.get("predicate", "")))
                fact_tokens.update(self._tokens(fact.get("object_text", "")))
                fact_tokens.update(self._tokens(fact.get("place", "")))

            searchable_tokens = (
                content_tokens
                | topic_tokens
                | place_tokens
                | people_tokens
                | fact_tokens
            )
            overlap = len(keywords & searchable_tokens)
            score = float(overlap * 4)

            if query_people:
                item_people_normalized = {
                    self.normalize(person)
                    for person in item.get("people", [])
                }
                matched_person = any(
                    self.normalize(person) in item_people_normalized
                    for person in query_people
                )
                if not matched_person:
                    continue
                score += 10.0

            if date_filter is not None:
                score += 8.0

            if plan["intent"] == "where" and item.get("places"):
                score += 3.0
            if plan["intent"] == "how" and item.get("transport"):
                score += 3.0
            if (
                plan["intent"] == "until"
                and item.get("event_end")
                and item.get("event_end") != item.get("event_start")
            ):
                score += 4.0
            if plan["intent"] == "when" and item.get("event_start"):
                score += 2.0

            # Une requête purement temporelle comme « où suis-je allé hier ? »
            # n'a parfois aucun mot-clé événementiel. Le filtre date suffit.
            if not keywords and date_filter is not None:
                score = max(score, 8.0)

            # Sans filtre date ni personne, il faut au moins une vraie
            # correspondance sémantique pour éviter de ressortir un souvenir
            # arbitraire.
            if (
                date_filter is None
                and not query_people
                and overlap <= 0
            ):
                continue

            if score <= 0:
                continue

            event_start = str(item.get("event_start") or "")
            recorded_at = str(item.get("recorded_at") or "")
            scored.append(
                (score, event_start, recorded_at, index, item)
            )

        if not scored:
            return []

        if plan["latest"]:
            best_semantic = max(row[0] for row in scored)
            # On garde une petite marge sémantique : un événement parfaitement
            # daté mais hors sujet ne doit pas gagner juste parce qu'il est récent.
            eligible = [
                row for row in scored if row[0] >= best_semantic - 1.0
            ]
            eligible.sort(
                key=lambda row: (
                    row[1], row[2], row[0], -row[3]
                ),
                reverse=True,
            )
            return [row[4] for row in eligible[: max(1, int(limit))]]

        scored.sort(
            key=lambda row: (
                row[0], row[1], row[2], -row[3]
            ),
            reverse=True,
        )
        return [row[4] for row in scored[: max(1, int(limit))]]

    def latest_match(self, query: str) -> dict[str, Any] | None:
        query = self._clean(query)
        if "derni" not in self.normalize(query):
            query = query + " dernière fois"
        matches = self.search(query, limit=1)
        return matches[0] if matches else None

    # =========================================================
    # ANSWER / CONTEXT
    # =========================================================

    @staticmethod
    def _place_destination_phrase(place: str) -> str:
        clean = str(place or "").strip()
        normalized = PersonalMemoryV2.normalize(clean)
        phrases = {
            "aeroport": "à l'aéroport",
            "gare": "à la gare",
            "hopital": "à l'hôpital",
            "restaurant": "au restaurant",
            "bureau": "au bureau",
            "travail": "au travail",
            "ecole": "à l'école",
            "maison": "à la maison",
            "supermarche": "au supermarché",
            "magasin": "au magasin",
            "cinema": "au cinéma",
            "hotel": "à l'hôtel",
        }
        return phrases.get(normalized, "à " + clean)

    @staticmethod
    def _weekday_fr(value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return None
        names = (
            "lundi", "mardi", "mercredi", "jeudi",
            "vendredi", "samedi", "dimanche",
        )
        return names[parsed.weekday()]

    @staticmethod
    def _format_date_fr(value: str | None) -> str:
        if not value:
            return "date inconnue"
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return value
        months = (
            "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        )
        return f"{parsed.day} {months[parsed.month - 1]} {parsed.year}"

    @classmethod
    def _relative_label(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            target = date.fromisoformat(value)
        except ValueError:
            return None
        today = datetime.now().astimezone().date()
        delta = (target - today).days
        if delta == 0:
            return "aujourd'hui"
        if delta == -1:
            return "hier"
        if delta == -2:
            return "avant-hier"
        if delta == 1:
            return "demain"
        return None


    # =========================================================
    # ACTOR-AWARE PERSONAL RECALL V6.5.1
    # =========================================================

    @classmethod
    def _v651_primary_query_text(cls, query: str) -> str:
        raw = str(query or "")
        parts = re.split(
            r"\n\s*Contexte utilisateur précédent\s*:",
            raw,
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        return cls._clean(parts[0])

    def _v651_query_actor(self, query: str) -> dict[str, str | None]:
        """Résout d'abord QUI est le sujet de la question."""
        primary = self._v651_primary_query_text(query)
        normalized = self.normalize(primary)

        # Première personne = utilisateur, même si Coralie est l'objet.
        if re.search(r"\b(?:je|moi)\b", normalized):
            return {"type": "user", "name": None}

        # V6.5.2 : résolution des alias relationnels par People Profiles.
        resolver = getattr(self, "person_reference_resolver", None)
        if callable(resolver):
            try:
                resolved_name = resolver(primary)
            except Exception:
                resolved_name = None
            if resolved_name:
                return {
                    "type": "person",
                    "name": self._clean(resolved_name),
                }

        explicit_people = []
        for person in self.known_people():
            wanted = self.normalize(person)
            if wanted and re.search(
                rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])",
                normalized,
            ):
                explicit_people.append(person)

        if len(explicit_people) == 1:
            return {"type": "person", "name": explicit_people[0]}

        # Relance avec pronom : le contexte utilisateur enrichi sert seulement
        # à résoudre « elle / il », jamais à changer un « je » en autre chose.
        if re.search(r"\b(?:elle|il|lui)\b", normalized):
            full = self.normalize(query)
            contextual = []
            for person in self.known_people():
                wanted = self.normalize(person)
                if wanted and re.search(
                    rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])",
                    full,
                ):
                    contextual.append(person)

            unique = []
            seen = set()
            for person in contextual:
                key = self.normalize(person)
                if key and key not in seen:
                    seen.add(key)
                    unique.append(person)

            if len(unique) == 1:
                return {"type": "person", "name": unique[0]}

        return {"type": "unknown", "name": None}

    def _v651_fact_matches_actor(
        self,
        fact: dict[str, Any],
        actor: dict[str, str | None],
    ) -> bool:
        actor_type = str(actor.get("type") or "unknown")
        subject_type = str(fact.get("subject_type") or "")

        if actor_type == "unknown":
            return True
        if actor_type == "user":
            return subject_type == "user"
        if actor_type == "person":
            if subject_type != "person":
                return False
            wanted = self.normalize(actor.get("name") or "")
            actual = self.normalize(fact.get("subject_name") or "")
            return bool(wanted and actual and wanted == actual)
        return False

    def _v651_actor_facts(
        self,
        item: dict[str, Any],
        actor: dict[str, str | None],
        *,
        predicates: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        for fact in item.get("facts", []):
            if not isinstance(fact, dict):
                continue
            if not self._v651_fact_matches_actor(fact, actor):
                continue
            predicate = str(fact.get("predicate") or "")
            if predicates is not None and predicate not in predicates:
                continue
            result.append(fact)
        return result

    def _v651_matches_for_actor(
        self,
        matches: list[dict[str, Any]],
        actor: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        if str(actor.get("type") or "unknown") == "unknown":
            return list(matches)
        return [
            item
            for item in matches
            if self._v651_actor_facts(item, actor)
        ]

    def _v651_explicit_person_destination(
        self,
        item: dict[str, Any],
        person: str,
    ) -> str | None:
        """N'utilise un lieu comme destination que si le texte dit allé(e)."""
        content = self.normalize(item.get("content", ""))
        wanted = self.normalize(person)
        if not wanted:
            return None

        named_move = re.search(
            rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9]).{{0,60}}"
            r"\b(?:est allee|est alle|s est rendue|s est rendu)\b",
            content,
        )
        pronoun_move = re.search(
            r"\b(?:elle est allee|il est alle|elle s est rendue|il s est rendu)\b",
            content,
        )

        if not (named_move or pronoun_move):
            return None

        places = [
            self._clean(place)
            for place in item.get("places", [])
            if self._clean(place)
        ]
        return places[0] if places else None

    @staticmethod
    def _v651_unknown_actor_property(
        actor: dict[str, str | None],
        field: str,
    ) -> str:
        actor_type = str(actor.get("type") or "unknown")
        name = str(actor.get("name") or "").strip()

        if actor_type == "person" and name:
            if field == "where":
                return f"Je n'ai pas de destination enregistrée pour {name}."
            if field == "when":
                return f"Je n'ai pas de date suffisamment précise enregistrée pour {name}."
            if field == "how":
                return f"Je n'ai pas de moyen de transport enregistré pour {name}."

        if field == "where":
            return "Je n'ai pas de lieu suffisamment précis enregistré pour ça."
        if field == "when":
            return "Je n'ai pas de date suffisamment précise enregistrée pour ça."
        if field == "how":
            return "Je n'ai pas de moyen de transport suffisamment précis enregistré pour ça."
        return "Je n'ai pas cette information de façon suffisamment précise."

    def direct_answer(self, query: str) -> str | None:
        if not self.looks_personal_query(query):
            return None

        plan = self._query_plan(query)
        matches = self.search(query, limit=6)
        if not matches:
            return None

        first = matches[0]

        if plan["intent"] == "when" or plan["latest"]:
            actor = self._v651_query_actor(query)
            if str(actor.get("type") or "unknown") != "unknown":
                scoped = self._v651_matches_for_actor(matches, actor)
                if not scoped:
                    return self._v651_unknown_actor_property(actor, "when")
                first = scoped[0]

            event_start = first.get("event_start")
            if not event_start:
                return self._v651_unknown_actor_property(actor, "when")
            relative = self._relative_label(event_start)
            formatted = self._format_date_fr(event_start)
            when = (
                f"{relative} ({formatted})"
                if relative
                else formatted
            )
            if plan["latest"]:
                return f"La dernière fois, c'était {when}."
            return f"C'était {when}."

        if plan["intent"] == "until":
            actor = self._v651_query_actor(query)
            if str(actor.get("type") or "unknown") != "unknown":
                scoped = self._v651_matches_for_actor(matches, actor)
                if not scoped:
                    return self._v651_unknown_actor_property(actor, "when")
                first = scoped[0]

            event_end = first.get("event_end")
            if not event_end:
                return self._v651_unknown_actor_property(actor, "when")
            relative = self._relative_label(event_end)
            formatted = self._format_date_fr(event_end)
            temporal_expression = self._clean(first.get("temporal_expression", ""))
            if relative:
                return f"D'après ce que tu m'as dit, jusqu'à {relative} ({formatted})."
            weekday = self._weekday_fr(event_end)
            if weekday:
                return f"D'après ce que tu m'as dit, jusqu'à {weekday} {formatted}."
            return f"D'après ce que tu m'as dit, jusqu'au {formatted}."

        if plan["intent"] == "where":
            actor = self._v651_query_actor(query)
            actor_type = str(actor.get("type") or "unknown")
            places: list[str] = []

            if actor_type == "person":
                # Un aéroport présent dans le même événement peut être le lieu
                # où TOI tu as emmené la personne. Ce n'est pas sa destination.
                # On exige donc un vrai déplacement de cette personne.
                for item in matches:
                    for fact in self._v651_actor_facts(
                        item,
                        actor,
                        predicates={"aller"},
                    ):
                        place = self._clean(
                            fact.get("place") or fact.get("object_text") or ""
                        )
                        if place and place not in places:
                            places.append(place)

                    if not places:
                        explicit = self._v651_explicit_person_destination(
                            item,
                            str(actor.get("name") or ""),
                        )
                        if explicit and explicit not in places:
                            places.append(explicit)

                if not places:
                    return self._v651_unknown_actor_property(actor, "where")

                name = str(actor.get("name") or "cette personne")
                if len(places) == 1:
                    return (
                        f"Le lieu enregistré pour {name} est "
                        f"{self._place_destination_phrase(places[0])}."
                    )
                return (
                    f"J'ai plusieurs destinations enregistrées pour {name} : "
                    + ", ".join(places[:4])
                    + "."
                )

            if actor_type == "user":
                for item in matches:
                    for fact in self._v651_actor_facts(item, actor):
                        place = self._clean(fact.get("place") or "")
                        if place and place not in places:
                            places.append(place)

                if not places:
                    return self._v651_unknown_actor_property(actor, "where")
                if len(places) == 1:
                    return f"Tu es allé {self._place_destination_phrase(places[0])}."
                return (
                    "Tu m'as parlé de ces lieux où tu étais : "
                    + ", ".join(places[:4])
                    + "."
                )

            # Aucun acteur résolu : réponse neutre, jamais attribuée arbitrairement.
            for item in matches:
                for place in item.get("places", []):
                    if place not in places:
                        places.append(place)
            if not places:
                return None
            if len(places) == 1:
                return (
                    "Le lieu correspondant dans ta mémoire est "
                    f"{self._place_destination_phrase(places[0])}."
                )
            return "Les lieux correspondants sont : " + ", ".join(places[:4]) + "."

        if plan["intent"] == "how":
            actor = self._v651_query_actor(query)
            actor_type = str(actor.get("type") or "unknown")

            if actor_type != "unknown":
                for item in matches:
                    for fact in self._v651_actor_facts(
                        item,
                        actor,
                        predicates={"voyager_transport"},
                    ):
                        transport = self._clean(
                            fact.get("object_text") or item.get("transport") or ""
                        )
                        if not transport:
                            continue

                        inferred = bool(
                            fact.get("inferred")
                            or item.get("transport_inferred")
                        )

                        if actor_type == "person":
                            name = str(actor.get("name") or "cette personne")
                            if inferred:
                                return (
                                    f"Probablement en {transport} pour {name}. "
                                    "C'est une déduction à partir de ce que tu m'as dit."
                                )
                            return (
                                f"D'après ce que tu m'as dit, {name} "
                                f"a voyagé en {transport}."
                            )

                        if inferred:
                            return (
                                f"Probablement en {transport}. "
                                "C'est une déduction à partir de ce que tu m'as dit."
                            )
                        return (
                            f"D'après ce que tu m'as dit, tu as voyagé "
                            f"en {transport}."
                        )

                return self._v651_unknown_actor_property(actor, "how")

            transport = self._clean(first.get("transport", ""))
            if not transport:
                return None
            if first.get("transport_inferred"):
                return (
                    f"Probablement en {transport}. "
                    "C'est une déduction à partir de ce que tu m'as dit."
                )
            return f"Le moyen de transport enregistré est {transport}."

        if plan["intent"] == "who":
            normalized_query = plan["normalized"]
            target_people = []
            for person in self.known_people():
                wanted = self.normalize(person)
                if wanted and re.search(
                    rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])",
                    normalized_query,
                ):
                    target_people.append(person)

            # "Avec qui est-elle partie ?" demande un compagnon de voyage.
            # L'événement ne contient pas cette information : ne transforme
            # surtout pas l'accompagnateur vers l'aéroport en compagnon de voyage.
            if "avec qui" in normalized_query:
                return None

            wants_escort = bool(
                re.search(
                    r"\b(?:emmene|accompagne|conduit|depose|amene)\b",
                    normalized_query,
                )
            )
            if not wants_escort:
                return None

            for item in matches:
                for fact in item.get("facts", []):
                    if not isinstance(fact, dict):
                        continue
                    if wants_escort and fact.get("predicate") != "emmener":
                        continue
                    object_text = self._clean(fact.get("object_text", ""))
                    if target_people and not any(
                        self.normalize(person) in self.normalize(object_text)
                        or self.normalize(object_text) in self.normalize(person)
                        for person in target_people
                        if object_text
                    ):
                        continue

                    subject_type = str(fact.get("subject_type") or "")
                    subject_name = self._clean(fact.get("subject_name", ""))
                    if subject_type == "user":
                        target = (
                            target_people[0]
                            if target_people
                            else object_text or "cette personne"
                        )
                        if wants_escort:
                            place = self._clean(fact.get("place", ""))
                            suffix = (
                                " " + self._place_destination_phrase(place)
                                if place
                                else ""
                            )
                            return f"C'est toi qui as emmené {target}{suffix}."
                        return "C'est toi."

                    if subject_type == "person" and subject_name:
                        return f"C'est {subject_name}."

            return None

        return None

    def context(
        self,
        query: str,
        *,
        limit: int = 8,
    ) -> str:
        matches = self.search(query, limit=limit)
        if not matches:
            return "(aucun événement personnel V2 correspondant)"

        lines = [
            "MÉMOIRE PERSONNELLE V2 — SOURCE UTILISATEUR",
            "Les éléments ci-dessous viennent uniquement de souvenirs personnels "
            "enregistrés depuis les déclarations utilisateur.",
        ]

        for item in matches:
            bits = []
            if item.get("event_start"):
                if (
                    item.get("event_end")
                    and item.get("event_end") != item.get("event_start")
                ):
                    bits.append(
                        f"date={item['event_start']}→{item['event_end']}"
                    )
                else:
                    bits.append(f"date={item['event_start']}")
            if item.get("people"):
                bits.append("personnes=" + ", ".join(item["people"]))
            if item.get("places"):
                bits.append("lieux=" + ", ".join(item["places"]))
            if item.get("transport"):
                mode = "déduit" if item.get("transport_inferred") else "dit"
                bits.append(f"transport={item['transport']} ({mode})")
            metadata = " | ".join(bits) if bits else "sans métadonnée structurée"
            facts = []
            for fact in item.get("facts", []):
                if not isinstance(fact, dict):
                    continue
                subject = self._fact_subject_label(
                    str(fact.get("subject_type") or ""),
                    self._clean(fact.get("subject_name", "")) or None,
                )
                predicate = self._clean(fact.get("predicate", ""))
                obj = self._clean(fact.get("object_text", ""))
                if not predicate:
                    continue
                phrase = f"{subject} -> {predicate}"
                if obj:
                    phrase += f" -> {obj}"
                if fact.get("place"):
                    phrase += f" @ {fact.get('place')}"
                if fact.get("inferred"):
                    phrase += " [déduit]"
                facts.append(phrase)

            line = f"- [{metadata}] {item.get('content', '')}"
            if facts:
                line += " | faits: " + " ; ".join(facts[:6])
            lines.append(line)

        return "\n".join(lines)

    # =========================================================
    # FORGET
    # =========================================================

    def forget(self, target: str) -> int:
        """Supprime les événements personnels correspondant à un oubli explicite."""
        normalized_target = self.normalize(target)
        target_tokens = self._tokens(target)
        if not normalized_target or len(normalized_target) < 2:
            return 0

        to_delete: list[int] = []
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, normalized_content, people_json, places_json, topics_json "
                "FROM personal_events"
            ).fetchall()
            for row in rows:
                searchable = " ".join(
                    [
                        str(row["normalized_content"] or ""),
                        self.normalize(row["people_json"]),
                        self.normalize(row["places_json"]),
                        self.normalize(row["topics_json"]),
                    ]
                )
                searchable_tokens = self._tokens(searchable)
                phrase_match = normalized_target in searchable
                token_match = bool(
                    target_tokens
                    and target_tokens.issubset(searchable_tokens)
                )
                if phrase_match or token_match:
                    to_delete.append(int(row["id"]))

            if to_delete:
                db.executemany(
                    "DELETE FROM personal_events WHERE id = ?",
                    [(item_id,) for item_id in to_delete],
                )

        return len(to_delete)

    # =========================================================
    # STATUS
    # =========================================================

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            events = int(
                db.execute(
                    "SELECT COUNT(*) FROM personal_events"
                ).fetchone()[0]
            )
            dated = int(
                db.execute(
                    "SELECT COUNT(*) FROM personal_events "
                    "WHERE event_start IS NOT NULL"
                ).fetchone()[0]
            )
            with_people = int(
                db.execute(
                    "SELECT COUNT(*) FROM personal_events "
                    "WHERE people_json <> '[]'"
                ).fetchone()[0]
            )
            with_places = int(
                db.execute(
                    "SELECT COUNT(*) FROM personal_events "
                    "WHERE places_json <> '[]'"
                ).fetchone()[0]
            )
            facts = int(
                db.execute(
                    "SELECT COUNT(*) FROM personal_event_facts"
                ).fetchone()[0]
            )
            user_facts = int(
                db.execute(
                    "SELECT COUNT(*) FROM personal_event_facts "
                    "WHERE subject_type = 'user'"
                ).fetchone()[0]
            )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "events": events,
            "dated_events": dated,
            "events_with_people": with_people,
            "events_with_places": with_places,
            "facts": facts,
            "user_actor_facts": user_facts,
            "db_path": str(self.db_path),
        }

    def status_summary(self) -> str:
        stats = self.stats()
        return "\n".join(
            [
                "MÉMOIRE PERSONNELLE V2",
                f"Base : {stats['db_path']}",
                f"Événements : {stats['events']}",
                f"Événements datés : {stats['dated_events']}",
                f"Avec personnes : {stats['events_with_people']}",
                f"Avec lieux : {stats['events_with_places']}",
                f"Faits structurés : {stats['facts']}",
                f"Faits dont l'acteur est toi : {stats['user_actor_facts']}",
                "Source principale des événements personnels : SQLite.",
            ]
        )
