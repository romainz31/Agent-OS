from __future__ import annotations

import re
import sqlite3

from agentos.sqlite_utils import connect as sqlite_connect
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable


class PeopleProfileMemory:
    """Profils structurés des personnes de la vie de l'utilisateur — V6.5.2.

    Cette couche partage ``personal_profile.db`` avec PersonalProfileMemory.
    Elle résout les alias relationnels (ex. ``ma copine`` -> ``Coralie``),
    conserve les faits stables sur une personne et quelques états temporels
    explicites (ex. localisation actuelle jusqu'à une date).

    Les réponses de Paul/assistant ne sont jamais une source de vérité ici.
    """

    SCHEMA_VERSION = 2

    RELATION_ALIASES = {
        "ma copine": "copine",
        "mon copain": "copain",
        "ma compagne": "compagne",
        "mon compagnon": "compagnon",
        "ma partenaire": "partenaire",
        "mon partenaire": "partenaire",
        "ma femme": "femme",
        "mon mari": "mari",
        "ma mere": "mère",
        "mon pere": "père",
        "ma soeur": "sœur",
        "mon frere": "frère",
        "mon fils": "fils",
        "ma fille": "fille",
        "mon ami": "ami",
        "mon amie": "amie",
    }

    RELATION_VALUE_ALIASES = {
        "partenaire": ("ma partenaire", "mon partenaire"),
        "copine": ("ma copine",),
        "copain": ("mon copain",),
        "compagne": ("ma compagne",),
        "compagnon": ("mon compagnon",),
        "femme": ("ma femme",),
        "mari": ("mon mari",),
        "mere": ("ma mere",),
        "pere": ("mon pere",),
        "soeur": ("ma soeur",),
        "frere": ("mon frere",),
        "fils": ("mon fils",),
        "fille": ("ma fille",),
        "ami": ("mon ami",),
        "amie": ("mon amie",),
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

    MONTHS = {
        "janvier": 1,
        "fevrier": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "aout": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "decembre": 12,
    }

    QUESTION_STARTERS = (
        "qui ", "que ", "quoi ", "quel ", "quelle ", "quels ",
        "quelles ", "ou ", "quand ", "comment ", "est ce ",
        "sais tu ", "tu sais ", "parle moi ", "rappelle moi ",
    )

    # V6.5.2.1 — jamais de mot interrogatif/pronom comme identité.
    INVALID_PERSON_NAMES = {
        "qui", "ou", "que", "quoi", "quel", "quelle", "quels", "quelles",
        "comment", "quand", "pourquoi", "combien", "lequel", "laquelle",
        "elle", "il", "lui", "eux", "elles", "on", "je", "moi", "tu", "toi",
        "nous", "vous", "ma", "mon", "mes", "ta", "ton", "tes", "sa", "son", "ses",
        "ce", "ca", "cela", "cette", "cet", "ces", "est", "suis", "es",
        "copine", "copain", "partenaire", "compagne", "compagnon",
        "femme", "mari", "mere", "pere", "soeur", "frere", "ami", "amie",
        "aujourd hui", "demain", "hier",
    }

    INVALID_PERSON_PREFIXES = (
        "qui ", "ou ", "que ", "quoi ", "quel ", "quelle ", "comment ",
        "quand ", "pourquoi ", "elle ", "il ", "ma copine", "mon copain",
        "ma partenaire", "mon partenaire", "ma compagne", "mon compagnon",
    )

    def __init__(
        self,
        db_path: str | Path,
        *,
        personal_event_store_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.personal_event_store_provider = personal_event_store_provider
        self._last_observation: dict[str, Any] | None = None
        self._ensure_schema()
        self.cleanup_invalid_people()

    # =========================================================
    # NORMALISATION
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
        text = re.sub(r"\bjai\b", "j ai", text)
        text = re.sub(r"\bcest\b", "c est", text)
        text = re.sub(r"\bquest\b", "qu est", text)
        text = re.sub(r"\bjusqua\b", "jusqu a", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    @classmethod
    def _pretty_name(cls, value: Any) -> str:
        clean = cls._clean(value).strip(" .,:;!?-'\"")
        if not clean:
            return ""
        small = {"de", "du", "des", "le", "la", "les", "d"}
        parts = []
        for i, token in enumerate(clean.split()):
            low = token.lower()
            parts.append(low if i > 0 and low in small else token[:1].upper() + token[1:].lower())
        return " ".join(parts)

    @classmethod
    def _pretty_place(cls, value: Any) -> str:
        clean = cls._clean(value).strip(" .,:;!?-'\"")
        if not clean:
            return ""
        known = {
            "londres": "Londres",
            "toulouse": "Toulouse",
            "paris": "Paris",
            "gaillac": "Gaillac",
            "brens": "Brens",
        }
        normalized = cls.normalize(clean)
        if normalized in known:
            return known[normalized]
        if normalized in {"aeroport", "l aeroport"}:
            return "l'aéroport"
        if normalized in {"gare", "la gare"}:
            return "la gare"
        return " ".join(token[:1].upper() + token[1:] for token in clean.split())

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat()

    # =========================================================
    # SQLITE
    # =========================================================

    def _connect(self) -> sqlite3.Connection:
        db = sqlite_connect(str(self.db_path), timeout=10.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _ensure_schema(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS people_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    relation TEXT NOT NULL DEFAULT '',
                    relation_label TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.9,
                    importance REAL NOT NULL DEFAULT 0.7,
                    source TEXT NOT NULL DEFAULT 'user',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS people_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id INTEGER NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL UNIQUE,
                    alias_type TEXT NOT NULL DEFAULT 'name',
                    confidence REAL NOT NULL DEFAULT 0.9,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    FOREIGN KEY(person_id) REFERENCES people_profiles(id)
                        ON DELETE CASCADE
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS person_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id INTEGER NOT NULL,
                    fact_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.9,
                    explicit INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'user',
                    source_text TEXT NOT NULL DEFAULT '',
                    observed_at TEXT NOT NULL,
                    valid_from TEXT,
                    valid_until TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(person_id) REFERENCES people_profiles(id)
                        ON DELETE CASCADE
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_people_relation "
                "ON people_profiles(relation, status)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_people_facts_active "
                "ON person_facts(person_id, fact_type, active, observed_at DESC)"
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
                "INSERT OR REPLACE INTO profile_meta(key, value) "
                "VALUES('people_schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )


    @classmethod
    def _valid_person_name(cls, value: Any) -> bool:
        name = cls._pretty_name(value)
        normalized = cls.normalize(name)
        if not normalized:
            return False
        if normalized in cls.INVALID_PERSON_NAMES:
            return False
        if any(normalized.startswith(prefix) for prefix in cls.INVALID_PERSON_PREFIXES):
            return False
        tokens = normalized.split()
        if not 1 <= len(tokens) <= 4:
            return False
        if tokens[0] in cls.INVALID_PERSON_NAMES:
            return False
        if any(token.isdigit() for token in tokens):
            return False
        if len(tokens) == 1 and len(tokens[0]) < 2:
            return False
        return True

    def cleanup_invalid_people(self) -> int:
        """Supprime les faux profils créés par les anciennes questions."""
        removed = 0
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT id, canonical_name FROM people_profiles"
                ).fetchall()
                for row in rows:
                    if self._valid_person_name(row["canonical_name"]):
                        continue
                    db.execute(
                        "DELETE FROM people_profiles WHERE id=?",
                        (int(row["id"]),),
                    )
                    removed += 1
                db.execute(
                    "INSERT OR REPLACE INTO profile_meta(key, value) "
                    "VALUES('people_hygiene_v6521', '1')"
                )
        except sqlite3.Error:
            return removed
        return removed


    # =========================================================
    # PERSON / ALIAS STORAGE
    # =========================================================

    def _person_by_id(self, person_id: int) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM people_profiles WHERE id=? AND status='active'",
                (int(person_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def _person_by_name(self, name: str) -> dict[str, Any] | None:
        normalized = self.normalize(name)
        if not normalized:
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM people_profiles "
                "WHERE normalized_name=? AND status='active' LIMIT 1",
                (normalized,),
            ).fetchone()
        return dict(row) if row is not None else None

    def upsert_person(
        self,
        name: str,
        *,
        relation: str = "",
        relation_label: str = "",
        source: str = "user",
        confidence: float = 0.95,
        importance: float = 0.75,
        aliases: list[str] | None = None,
    ) -> dict[str, Any] | None:
        name = self._pretty_name(name)
        normalized = self.normalize(name)
        if not name or len(normalized) < 2:
            return None
        if not self._valid_person_name(name):
            return None

        now = self._now_iso()
        relation = self.normalize(relation)
        relation_label = self._clean(relation_label)

        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM people_profiles WHERE normalized_name=? LIMIT 1",
                (normalized,),
            ).fetchone()

            if row is None:
                cursor = db.execute(
                    """
                    INSERT INTO people_profiles(
                        canonical_name, normalized_name, relation, relation_label,
                        confidence, importance, source, first_seen, last_seen, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                    """,
                    (
                        name, normalized, relation, relation_label,
                        float(confidence), float(importance), source, now, now,
                    ),
                )
                person_id = int(cursor.lastrowid)
            else:
                current = dict(row)
                person_id = int(current["id"])
                new_relation = relation or str(current.get("relation") or "")
                new_label = relation_label or str(current.get("relation_label") or "")
                db.execute(
                    """
                    UPDATE people_profiles
                    SET canonical_name=?, relation=?, relation_label=?,
                        confidence=?, importance=?, source=?, last_seen=?, status='active'
                    WHERE id=?
                    """,
                    (
                        name,
                        new_relation,
                        new_label,
                        max(float(current.get("confidence") or 0.0), float(confidence)),
                        max(float(current.get("importance") or 0.0), float(importance)),
                        source or str(current.get("source") or "user"),
                        now,
                        person_id,
                    ),
                )

        self.add_alias(person_id, name, alias_type="name", confidence=1.0)
        for alias in aliases or []:
            self.add_alias(person_id, alias, alias_type="relation", confidence=0.98)

        if relation:
            for alias in self.RELATION_VALUE_ALIASES.get(relation, ()):
                self.add_alias(person_id, alias, alias_type="relation", confidence=0.9)

        return self._person_by_id(person_id)

    def add_alias(
        self,
        person_id: int,
        alias: str,
        *,
        alias_type: str = "relation",
        confidence: float = 0.9,
    ) -> None:
        alias = self._clean(alias)
        normalized = self.normalize(alias)
        if not normalized:
            return
        now = self._now_iso()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM people_aliases WHERE normalized_alias=? LIMIT 1",
                (normalized,),
            ).fetchone()
            if row is None:
                db.execute(
                    """
                    INSERT INTO people_aliases(
                        person_id, alias, normalized_alias, alias_type,
                        confidence, first_seen, last_seen, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                    """,
                    (
                        int(person_id), alias, normalized, alias_type,
                        float(confidence), now, now,
                    ),
                )
            else:
                current = dict(row)
                # Une relation explicite récente peut réassigner « ma copine »
                # à une autre personne sans casser l'historique des personnes.
                db.execute(
                    """
                    UPDATE people_aliases
                    SET person_id=?, alias=?, alias_type=?, confidence=?,
                        last_seen=?, status='active'
                    WHERE id=?
                    """,
                    (
                        int(person_id), alias, alias_type,
                        max(float(current.get("confidence") or 0.0), float(confidence)),
                        now, int(current["id"]),
                    ),
                )

    def resolve_reference(self, text: str) -> dict[str, Any] | None:
        normalized = self.normalize(text)
        if not normalized:
            return None
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT a.*, p.canonical_name, p.relation, p.relation_label,
                       p.confidence AS person_confidence,
                       p.importance AS person_importance
                FROM people_aliases a
                JOIN people_profiles p ON p.id=a.person_id
                WHERE a.status='active' AND p.status='active'
                ORDER BY LENGTH(a.normalized_alias) DESC, a.confidence DESC
                """
            ).fetchall()

        for row in rows:
            alias = str(row["normalized_alias"] or "")
            if alias and re.search(
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                normalized,
            ):
                return {
                    "id": int(row["person_id"]),
                    "name": str(row["canonical_name"]),
                    "relation": str(row["relation"] or ""),
                    "relation_label": str(row["relation_label"] or ""),
                    "matched_alias": str(row["alias"]),
                }
        return None

    def resolve_reference_name(self, text: str) -> str | None:
        person = self.resolve_reference(text)
        return str(person["name"]) if person else None

    def known_people(self) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT canonical_name FROM people_profiles "
                "WHERE status='active' ORDER BY importance DESC, last_seen DESC"
            ).fetchall()
        return [str(row["canonical_name"]) for row in rows]

    # =========================================================
    # RELATION EXTRACTION
    # =========================================================

    @classmethod
    def _relation_from_value(cls, value: str) -> tuple[str, str]:
        n = cls.normalize(value)
        direct = {
            "partenaire": ("partenaire", "partenaire"),
            "copine": ("copine", "copine"),
            "copain": ("copain", "copain"),
            "compagne": ("compagne", "compagne"),
            "compagnon": ("compagnon", "compagnon"),
            "femme": ("femme", "femme"),
            "mari": ("mari", "mari"),
            "mere": ("mere", "mère"),
            "pere": ("pere", "père"),
            "soeur": ("soeur", "sœur"),
            "frere": ("frere", "frère"),
            "fils": ("fils", "fils"),
            "fille": ("fille", "fille"),
            "ami": ("ami", "ami"),
            "amie": ("amie", "amie"),
        }
        if n in direct:
            return direct[n]
        if "partenaire" in n:
            return "partenaire", "partenaire"
        return "", ""

    @classmethod
    def _relation_statements(cls, message: str) -> list[dict[str, str]]:
        # V6.5.2.1 : une question ne crée JAMAIS de personne/relation.
        if cls._question_like(message):
            return []

        n = cls.normalize(message)
        result: list[dict[str, str]] = []

        # « ma copine est Coralie » / « ma copine s'appelle Coralie »
        relation_terms = "|".join(
            re.escape(alias) for alias in sorted(cls.RELATION_ALIASES, key=len, reverse=True)
        )
        m = re.search(
            rf"\b({relation_terms})\s+(?:est|s appelle|se nomme)\s+([a-z][a-z0-9 -]{{1,60}})$",
            n,
        )
        if m:
            alias = m.group(1)
            name = cls._pretty_name(m.group(2))
            if name:
                result.append({
                    "name": name,
                    "alias": alias,
                    "relation": cls.RELATION_ALIASES.get(alias, ""),
                    "relation_label": cls.RELATION_ALIASES.get(alias, ""),
                })

        # « Coralie est ma copine »
        m = re.search(
            rf"^([a-z][a-z0-9 -]{{1,60}}?)\s+est\s+({relation_terms})\b",
            n,
        )
        if m:
            name = cls._pretty_name(m.group(1))
            alias = m.group(2)
            if name:
                result.append({
                    "name": name,
                    "alias": alias,
                    "relation": cls.RELATION_ALIASES.get(alias, ""),
                    "relation_label": cls.RELATION_ALIASES.get(alias, ""),
                })

        return result

    def sync_from_profile(self, profile_store: Any) -> int:
        if profile_store is None:
            return 0
        try:
            items = profile_store.items("relation", limit=250)
        except Exception:
            return 0
        changed = 0
        for item in items:
            subject = self._clean(item.get("subject", ""))
            value = self._clean(item.get("value", ""))
            content = self._clean(item.get("content", ""))

            found = []
            for candidate in (content, subject, " ".join((subject, value, content))):
                if not candidate:
                    continue
                found.extend(self._relation_statements(candidate))
            if found:
                dedup = []
                seen = set()
                for rel in found:
                    key = (self.normalize(rel.get("name", "")), self.normalize(rel.get("alias", "")))
                    if key in seen:
                        continue
                    seen.add(key)
                    dedup.append(rel)
                for rel in dedup:
                    if self.upsert_person(
                        rel["name"],
                        relation=rel["relation"],
                        relation_label=rel["relation_label"],
                        aliases=[rel["alias"]],
                        source="profile_v65",
                    ):
                        changed += 1
                continue

            relation, label = self._relation_from_value(value)
            # V6.5 normalise normalement subject=nom, value=relation.
            if relation and subject and len(self.normalize(subject).split()) <= 4:
                if self.upsert_person(
                    subject,
                    relation=relation,
                    relation_label=label,
                    source="profile_v65",
                ):
                    changed += 1
        return changed

    # =========================================================
    # PERSON FACTS / TEMPORAL STATE
    # =========================================================

    @classmethod
    def _resolve_until(cls, text: str) -> str | None:
        n = cls.normalize(text)
        marker = re.search(r"\bjusqu a\s+(.+)$", n)
        if not marker:
            return None
        expr = marker.group(1).strip()
        today = datetime.now().astimezone().date()

        if expr.startswith("aujourd hui"):
            return today.isoformat()
        if expr.startswith("demain"):
            return (today + timedelta(days=1)).isoformat()
        if expr.startswith("apres demain"):
            return (today + timedelta(days=2)).isoformat()

        for name, weekday in cls.WEEKDAYS.items():
            if re.search(rf"\b{re.escape(name)}\b", expr):
                delta = (weekday - today.weekday()) % 7
                return (today + timedelta(days=delta)).isoformat()

        numeric = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\b", expr)
        if numeric:
            day = int(numeric.group(1))
            month = int(numeric.group(2))
            year = int(numeric.group(3) or today.year)
            try:
                candidate = date(year, month, day)
                if numeric.group(3) is None and candidate < today:
                    candidate = date(year + 1, month, day)
                return candidate.isoformat()
            except ValueError:
                return None

        written = re.search(
            r"\b(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)(?:\s+(\d{4}))?\b",
            expr,
        )
        if written:
            day = int(written.group(1))
            month = cls.MONTHS[written.group(2)]
            year = int(written.group(3) or today.year)
            try:
                candidate = date(year, month, day)
                if written.group(3) is None and candidate < today:
                    candidate = date(year + 1, month, day)
                return candidate.isoformat()
            except ValueError:
                return None
        return None

    def set_fact(
        self,
        person_id: int,
        fact_type: str,
        value: str,
        *,
        confidence: float = 0.95,
        explicit: bool = True,
        source: str = "user",
        source_text: str = "",
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> dict[str, Any] | None:
        fact_type = self.normalize(fact_type).replace(" ", "_")
        value = self._clean(value)
        if not fact_type or not value:
            return None
        now = self._now_iso()

        with self._connect() as db:
            current = db.execute(
                """
                SELECT * FROM person_facts
                WHERE person_id=? AND fact_type=? AND active=1
                ORDER BY observed_at DESC LIMIT 1
                """,
                (int(person_id), fact_type),
            ).fetchone()

            if current is not None:
                old = dict(current)
                if (
                    self.normalize(old.get("value", "")) == self.normalize(value)
                    and str(old.get("valid_until") or "") == str(valid_until or "")
                ):
                    db.execute(
                        "UPDATE person_facts SET observed_at=?, confidence=? WHERE id=?",
                        (
                            now,
                            max(float(old.get("confidence") or 0.0), float(confidence)),
                            int(old["id"]),
                        ),
                    )
                    row = db.execute(
                        "SELECT * FROM person_facts WHERE id=?",
                        (int(old["id"]),),
                    ).fetchone()
                    return dict(row) if row is not None else None

                db.execute(
                    "UPDATE person_facts SET active=0 WHERE id=?",
                    (int(old["id"]),),
                )

            cursor = db.execute(
                """
                INSERT INTO person_facts(
                    person_id, fact_type, value, normalized_value, confidence,
                    explicit, source, source_text, observed_at,
                    valid_from, valid_until, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    int(person_id), fact_type, value, self.normalize(value),
                    float(confidence), int(bool(explicit)), source,
                    self._clean(source_text), now, valid_from, valid_until,
                ),
            )
            row = db.execute(
                "SELECT * FROM person_facts WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
        return dict(row) if row is not None else None

    @classmethod
    def _question_like(cls, text: str) -> bool:
        raw = cls._clean(text)
        if not raw:
            return False
        if raw.endswith("?"):
            return True
        n = cls.normalize(raw)
        return n.startswith(cls.QUESTION_STARTERS)

    @classmethod
    def _extract_location_statement(cls, message: str) -> dict[str, str] | None:
        if cls._question_like(message):
            return None
        n = cls.normalize(message)

        patterns = (
            r"\b(?:est|se trouve)\s+(?:actuellement\s+)?(?:en vacances\s+|en voyage\s+)?(?:a|au|aux)\s+(.+?)(?=\s+jusqu a\b|\s+depuis\b|$)",
            r"\b(?:est partie|est parti|est allee|est alle|part|va)\s+(?:en vacances\s+|en voyage\s+)?(?:a|au|aux|pour)\s+(.+?)(?=\s+jusqu a\b|\s+depuis\b|$)",
        )
        for pattern in patterns:
            m = re.search(pattern, n)
            if not m:
                continue
            place = cls._pretty_place(m.group(1))
            if not place:
                continue
            # « ma copine est Coralie » n'entre pas ici car il n'y a pas de
            # préposition de lieu après le verbe.
            return {
                "place": place,
                "valid_until": cls._resolve_until(message) or "",
                "travel": "1" if ("vacances" in n or "voyage" in n) else "0",
            }
        return None

    def ingest(
        self,
        message: str,
        understanding: Any = None,
        *,
        profile_items: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        self._last_observation = None
        raw = self._clean(message)
        if not raw:
            return []

        stored: list[dict[str, Any]] = []

        # 1) Relation explicite extraite directement de la phrase.
        for rel in self._relation_statements(raw):
            person = self.upsert_person(
                rel["name"],
                relation=rel["relation"],
                relation_label=rel["relation_label"],
                aliases=[rel["alias"]],
                source="user",
                confidence=0.99,
                importance=0.9,
            )
            if person:
                stored.append(person)
                self._last_observation = {
                    "kind": "relation",
                    "name": person["canonical_name"],
                    "relation": rel["relation_label"],
                    "alias": rel["alias"],
                }

        # 2) Relation extraite par Understanding/Profile V6.5.
        for item in profile_items or []:
            if self.normalize(item.get("category", "")) != "relation":
                continue
            subject = self._clean(item.get("subject", ""))
            value = self._clean(item.get("value", ""))
            relation, label = self._relation_from_value(value)
            if relation and subject and len(self.normalize(subject).split()) <= 4:
                person = self.upsert_person(
                    subject,
                    relation=relation,
                    relation_label=label,
                    source="user",
                    confidence=float(item.get("confidence") or 0.9),
                    importance=float(item.get("importance") or 0.75),
                )
                if person:
                    stored.append(person)

        # 3) État/localisation explicite d'une personne déjà résoluble.
        location = self._extract_location_statement(raw)
        if location:
            person = self.resolve_reference(raw)
            if person:
                fact = self.set_fact(
                    int(person["id"]),
                    "current_location",
                    location["place"],
                    confidence=0.98,
                    explicit=True,
                    source="user",
                    source_text=raw,
                    valid_until=location["valid_until"] or None,
                )
                if location["travel"] == "1":
                    self.set_fact(
                        int(person["id"]),
                        "travel_status",
                        "en vacances" if "vacances" in self.normalize(raw) else "en voyage",
                        confidence=0.97,
                        explicit=True,
                        source="user",
                        source_text=raw,
                        valid_until=location["valid_until"] or None,
                    )
                if fact:
                    self._last_observation = {
                        "kind": "current_location",
                        "name": person["name"],
                        "value": location["place"],
                        "valid_until": location["valid_until"],
                    }

        return stored

    # =========================================================
    # SYNC FROM USER-AUTHORED PERSONAL EVENTS
    # =========================================================

    def _event_store(self) -> Any:
        provider = self.personal_event_store_provider
        if provider is None:
            return None
        try:
            return provider()
        except Exception:
            return None

    def _ingest_event_for_person(self, person: dict[str, Any], item: dict[str, Any]) -> None:
        content = self._clean(item.get("content", ""))
        source = self.normalize(item.get("source", "user"))
        if not content or source in {"assistant", "paul", "agentos", "system"}:
            return

        location = self._extract_location_statement(content)
        if not location:
            return

        # L'événement doit réellement parler de CETTE personne comme sujet.
        name_norm = self.normalize(person["name"])
        content_norm = self.normalize(content)
        named_subject = bool(
            name_norm
            and re.search(
                rf"(?<![a-z0-9]){re.escape(name_norm)}(?![a-z0-9]).{{0,80}}"
                r"\b(?:est|se trouve|est partie|est parti|est allee|est alle|part|va)\b",
                content_norm,
            )
        )

        event_people = [self.normalize(x) for x in item.get("people", [])]
        pronoun_subject = bool(
            len(set(event_people)) == 1
            and name_norm in event_people
            and re.search(
                r"\b(?:elle|il)\s+(?:est|se trouve|part|va)\b",
                content_norm,
            )
        )

        if not (named_subject or pronoun_subject):
            return

        valid_until = self._clean(item.get("event_end", "")) or location["valid_until"] or None
        self.set_fact(
            int(person["id"]),
            "current_location",
            location["place"],
            confidence=0.94,
            explicit=True,
            source="personal_memory_v2",
            source_text=content,
            valid_until=valid_until,
        )
        if location["travel"] == "1":
            self.set_fact(
                int(person["id"]),
                "travel_status",
                "en vacances" if "vacances" in content_norm else "en voyage",
                confidence=0.92,
                explicit=True,
                source="personal_memory_v2",
                source_text=content,
                valid_until=valid_until,
            )

    def sync_from_events(self, event_store: Any = None) -> int:
        store = event_store or self._event_store()
        if store is None:
            return 0
        try:
            names = list(store.known_people())
        except Exception:
            return 0

        processed = 0
        for name in names:
            person = self._person_by_name(name)
            if person is None:
                person = self.upsert_person(
                    name,
                    source="personal_memory_v2",
                    confidence=0.85,
                    importance=0.55,
                )
            if not person:
                continue
            try:
                events = store.search(name, limit=80)
            except Exception:
                events = []
            person_view = {
                "id": int(person["id"]),
                "name": str(person["canonical_name"]),
            }
            for item in events:
                if isinstance(item, dict):
                    self._ingest_event_for_person(person_view, item)
                    processed += 1
        return processed

    def sync_person_from_events(self, person: dict[str, Any]) -> None:
        store = self._event_store()
        if store is None:
            return
        try:
            events = store.search(str(person["name"]), limit=80)
        except Exception:
            return
        for item in events:
            if isinstance(item, dict):
                self._ingest_event_for_person(person, item)

    # =========================================================
    # READ / ANSWER
    # =========================================================

    @staticmethod
    def _date_active(valid_until: str | None) -> bool:
        if not valid_until:
            return True
        raw = str(valid_until)
        try:
            target = date.fromisoformat(raw[:10])
        except ValueError:
            return True
        return target >= datetime.now().astimezone().date()

    def _active_facts(self, person_id: int, fact_type: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM person_facts WHERE person_id=? AND active=1"
        params: list[Any] = [int(person_id)]
        if fact_type:
            sql += " AND fact_type=?"
            params.append(self.normalize(fact_type).replace(" ", "_"))
        sql += " ORDER BY explicit DESC, confidence DESC, observed_at DESC"
        with self._connect() as db:
            rows = [dict(row) for row in db.execute(sql, params).fetchall()]
        return [row for row in rows if self._date_active(row.get("valid_until"))]

    @classmethod
    def _asks_location(cls, message: str) -> bool:
        n = cls.normalize(message)
        return bool(
            re.search(r"\bou\s+(?:est|se trouve|va|est alle|est allee)\b", n)
            or re.search(r"\bou est\b", n)
        )

    @classmethod
    def _asks_identity(cls, message: str) -> bool:
        n = cls.normalize(message)
        return bool(
            re.search(r"\bqui est\b", n)
            or re.search(r"\bcomment s appelle\b", n)
            or re.search(r"\bquel est (?:le )?nom\b", n)
        )

    @classmethod
    def _asks_person_summary(cls, message: str) -> bool:
        n = cls.normalize(message)
        return any(
            marker in n
            for marker in (
                "que sais tu sur",
                "qu est ce que tu sais sur",
                "parle moi de",
                "profil de",
                "profile de",
                "resume moi",
            )
        )

    def relationship_phrase(self, person: dict[str, Any]) -> str:
        alias = self._clean(person.get("matched_alias", ""))
        name = self._clean(person.get("name", ""))
        if alias and self.normalize(alias) != self.normalize(name):
            return alias
        relation = self.normalize(person.get("relation", ""))
        labels = {
            "copine": "ta copine",
            "copain": "ton copain",
            "compagne": "ta compagne",
            "compagnon": "ton compagnon",
            "partenaire": "ta partenaire",
            "femme": "ta femme",
            "mari": "ton mari",
            "mere": "ta mère",
            "pere": "ton père",
            "soeur": "ta sœur",
            "frere": "ton frère",
            "fils": "ton fils",
            "fille": "ta fille",
            "ami": "ton ami",
            "amie": "ton amie",
        }
        return labels.get(relation, name)

    @classmethod
    def _format_valid_until(cls, value: str) -> str:
        raw = cls._clean(value)
        if not raw:
            return ""
        try:
            target = date.fromisoformat(raw[:10])
        except ValueError:
            return raw
        today = datetime.now().astimezone().date()
        delta = (target - today).days
        if delta == 0:
            return "aujourd'hui"
        if delta == 1:
            return "demain"
        if 0 < delta <= 7:
            names = (
                "lundi", "mardi", "mercredi", "jeudi",
                "vendredi", "samedi", "dimanche",
            )
            return names[target.weekday()]
        return target.strftime("%d/%m/%Y")

    def direct_response(self, message: str) -> str | None:
        raw = self._clean(message)
        if not raw:
            return None

        # Une affirmation relationnelle fraîche reçoit un accusé de réception
        # déterministe, ce qui empêche le LLM d'inventer d'autres détails.
        if not self._question_like(raw):
            for rel in self._relation_statements(raw):
                person = self.resolve_reference(rel["name"])
                if person:
                    relation = rel["relation_label"] or "proche"
                    return f"C'est retenu : {person['name']} est ta {relation}."

            loc = self._extract_location_statement(raw)
            if loc:
                person = self.resolve_reference(raw)
                if person:
                    return f"C'est retenu : {person['name']} est à {loc['place']}."
            return None

        person = self.resolve_reference(raw)
        if person is None:
            return None

        # Rafraîchit les états depuis les souvenirs utilisateur avant réponse.
        self.sync_person_from_events(person)

        if self._asks_identity(raw):
            relation = self.relationship_phrase(person)
            if self.normalize(relation) != self.normalize(person["name"]):
                return f"{relation[:1].upper() + relation[1:]} est {person['name']}."
            return f"Il s'agit de {person['name']}."

        if self._asks_location(raw):
            locations = self._active_facts(int(person["id"]), "current_location")
            if locations:
                fact = locations[0]
                place = self._clean(fact.get("value", ""))
                valid_until = self._clean(fact.get("valid_until", ""))
                suffix = f" jusqu'à {self._format_valid_until(valid_until)}" if valid_until else ""
                return f"{person['name']} est à {place}{suffix}."

            relation = self.relationship_phrase(person)
            if self.normalize(relation) != self.normalize(person["name"]):
                return (
                    f"Je sais que {relation} est {person['name']}, "
                    "mais je n'ai pas de localisation actuelle fiable pour elle/lui."
                )
            return f"Je n'ai pas de localisation actuelle fiable pour {person['name']}."

        if self._asks_person_summary(raw):
            return self.person_summary(person)

        return None

    def person_summary(self, reference: str | dict[str, Any]) -> str:
        person = reference if isinstance(reference, dict) else self.resolve_reference(str(reference))
        if not person:
            return "Je ne trouve pas cette personne dans les profils personnels."
        facts = self._active_facts(int(person["id"]))
        lines = [f"PROFIL PERSONNE — {person['name']}"]
        relation = self.relationship_phrase(person)
        if self.normalize(relation) != self.normalize(person["name"]):
            lines.append(f"Relation : {relation}")
        for fact in facts[:20]:
            label = {
                "current_location": "Localisation actuelle",
                "travel_status": "Situation",
            }.get(str(fact.get("fact_type")), str(fact.get("fact_type")))
            value = self._clean(fact.get("value", ""))
            if fact.get("valid_until"):
                value += f" (jusqu'à {fact['valid_until']})"
            lines.append(f"{label} : {value}")
        if len(lines) == 1:
            lines.append("Aucun fait personnel supplémentaire enregistré.")
        return "\n".join(lines)

    def context_for(self, message: str) -> str:
        person = self.resolve_reference(message)
        if not person:
            return "(aucun profil de personne pertinent)"
        return self.person_summary(person)

    def observation_ack(self, message: str) -> str | None:
        return self.direct_response(message)

    def status_summary(self) -> str:
        with self._connect() as db:
            people = int(db.execute(
                "SELECT COUNT(*) FROM people_profiles WHERE status='active'"
            ).fetchone()[0])
            aliases = int(db.execute(
                "SELECT COUNT(*) FROM people_aliases WHERE status='active'"
            ).fetchone()[0])
            facts = int(db.execute(
                "SELECT COUNT(*) FROM person_facts WHERE active=1"
            ).fetchone()[0])
        return (
            "PEOPLE PROFILES V6.5.2\n"
            f"Personnes : {people}\n"
            f"Alias actifs : {aliases}\n"
            f"Faits actifs : {facts}"
        )
