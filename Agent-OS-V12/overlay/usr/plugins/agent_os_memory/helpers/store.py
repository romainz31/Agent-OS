from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

from .normalization import clean, normalize, parse_iso, tokens


KINDS = {
    "task", "appointment", "event", "action", "mood", "note",
    "fact", "preference", "relation",
}
FACT_KINDS = {"fact", "preference", "relation"}
STATUSES = {"pending", "scheduled", "done", "logged", "cancelled", "archived"}
DATE_PRECISIONS = {"exact", "day", "week", "month", "unknown"}
SEMANTIC_STATES = {"planned", "in_progress", "completed", "cancelled", "unknown"}
SEMANTIC_STATE_ALIASES = {
    "planifie": "planned", "planifiée": "planned", "planned": "planned",
    "en cours": "in_progress", "in progress": "in_progress",
    "in_progress": "in_progress", "started": "in_progress",
    "termine": "completed", "terminé": "completed", "completed": "completed",
    "annule": "cancelled", "annulé": "cancelled", "cancelled": "cancelled",
    "inconnu": "unknown", "unknown": "unknown",
}

KIND_ALIASES = {
    "todo": "task", "tache": "task", "tâche": "task",
    "rdv": "appointment", "rendez-vous": "appointment",
    "humeur": "mood", "ressenti": "mood",
    "souvenir": "note", "journal": "action",
    "préférence": "preference", "preference": "preference",
    "relation": "relation", "fait": "fact",
}


class PersonalMemoryStore:
    """SQLite source of truth for Paul's durable personal memory.

    V12 keeps the complete user wording in source_text and stores normalized
    projections beside it. Projections make queries reliable while the raw
    wording keeps every memory auditable and lossless.
    """

    SCHEMA_VERSION = 3

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._ensure_schema()

    def now(self) -> datetime:
        value = self.clock()
        return value if value.tzinfo else value.astimezone()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=15.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _ensure_schema(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS records(
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    semantic_state TEXT NOT NULL DEFAULT 'unknown',
                    action_verb TEXT NOT NULL DEFAULT '',
                    object_text TEXT NOT NULL DEFAULT '',
                    location_text TEXT NOT NULL DEFAULT '',
                    start_at TEXT,
                    end_at TEXT,
                    due_at TEXT,
                    completed_at TEXT,
                    date_precision TEXT NOT NULL DEFAULT 'unknown',
                    time_expression TEXT,
                    recurrence_rule TEXT,
                    priority TEXT,
                    importance REAL NOT NULL DEFAULT 0.5,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    inferred INTEGER NOT NULL DEFAULT 0,
                    source_role TEXT NOT NULL DEFAULT 'user',
                    source_text TEXT NOT NULL,
                    context_id TEXT,
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_records_time
                    ON records(kind, status, start_at, due_at, completed_at);
                CREATE INDEX IF NOT EXISTS idx_records_title
                    ON records(normalized_title);

                CREATE TABLE IF NOT EXISTS entities(
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(entity_type, normalized_name)
                );

                CREATE TABLE IF NOT EXISTS record_entities(
                    record_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    PRIMARY KEY(record_id, entity_id, role),
                    FOREIGN KEY(record_id) REFERENCES records(id),
                    FOREIGN KEY(entity_id) REFERENCES entities(id)
                );

                CREATE TABLE IF NOT EXISTS entity_attributes(
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    attribute TEXT NOT NULL,
                    normalized_attribute TEXT NOT NULL,
                    value TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    current INTEGER NOT NULL DEFAULT 1,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    inferred INTEGER NOT NULL DEFAULT 0,
                    source_record_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(entity_id) REFERENCES entities(id),
                    FOREIGN KEY(source_record_id) REFERENCES records(id)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_attributes_current
                    ON entity_attributes(entity_id, normalized_attribute, current);

                CREATE TABLE IF NOT EXISTS facts(
                    id TEXT PRIMARY KEY,
                    fact_kind TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    normalized_subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    normalized_predicate TEXT NOT NULL,
                    value TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    current INTEGER NOT NULL DEFAULT 1,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    inferred INTEGER NOT NULL DEFAULT 0,
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    source_record_id TEXT,
                    supersedes_fact_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_record_id) REFERENCES records(id)
                );
                CREATE INDEX IF NOT EXISTS idx_facts_current
                    ON facts(normalized_subject, normalized_predicate, current);

                CREATE TABLE IF NOT EXISTS record_history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    reason TEXT,
                    context_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_state(
                    context_id TEXT PRIMARY KEY,
                    last_intent TEXT,
                    last_query_json TEXT NOT NULL DEFAULT '{}',
                    last_record_ids_json TEXT NOT NULL DEFAULT '[]',
                    last_entity_id TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_clarifications(
                    id TEXT PRIMARY KEY,
                    context_id TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    missing_json TEXT NOT NULL DEFAULT '[]',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pending_clarifications_context
                    ON pending_clarifications(context_id, active, updated_at);

                CREATE TABLE IF NOT EXISTS migrations(
                    migration_key TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )

            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(records)")
            }
            additions = {
                "semantic_state": "TEXT NOT NULL DEFAULT 'unknown'",
                "action_verb": "TEXT NOT NULL DEFAULT ''",
                "object_text": "TEXT NOT NULL DEFAULT ''",
                "location_text": "TEXT NOT NULL DEFAULT ''",
            }
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE records ADD COLUMN {name} {definition}")
            db.execute(
                """CREATE INDEX IF NOT EXISTS idx_records_semantic
                   ON records(kind, status, semantic_state, start_at, due_at, completed_at)"""
            )

            db.execute(
                """UPDATE records
                   SET semantic_state=CASE
                       WHEN kind='task' AND status IN ('done','archived') THEN 'completed'
                       WHEN kind='action' OR status='done' THEN 'completed'
                       WHEN kind IN ('task','event','appointment') THEN 'planned'
                       WHEN status='cancelled' THEN 'cancelled'
                       ELSE 'unknown'
                   END
                   WHERE semantic_state IS NULL OR semantic_state='' OR semantic_state='unknown'"""
            )
            db.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _bounded(value: Any, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        try:
            result["metadata"] = json.loads(result.pop("metadata_json", "{}") or "{}")
        except json.JSONDecodeError:
            result["metadata"] = {}
        result["inferred"] = bool(result.get("inferred"))
        result["active"] = bool(result.get("active"))
        return result

    @staticmethod
    def _public_id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"

    @staticmethod
    def _default_status(kind: str) -> str:
        if kind == "task":
            return "pending"
        if kind in {"appointment", "event"}:
            return "scheduled"
        if kind == "action":
            return "done"
        return "logged"

    @staticmethod
    def _default_semantic_state(kind: str) -> str:
        if kind in {"task", "appointment", "event"}:
            return "planned"
        if kind == "action":
            return "completed"
        return "unknown"

    @staticmethod
    def _semantic_state(value: Any, default: str = "unknown") -> str:
        raw = clean(value).casefold()
        state = SEMANTIC_STATE_ALIASES.get(raw, raw.replace("-", "_"))
        if not state:
            state = default
        if state not in SEMANTIC_STATES:
            raise ValueError(f"État sémantique inconnu : {value}")
        return state

    def _audit(
        self,
        db: sqlite3.Connection,
        record_id: str,
        action: str,
        before: Any,
        after: Any,
        *,
        reason: str = "",
        context_id: str = "",
    ) -> None:
        db.execute(
            """INSERT INTO record_history(
                record_id,action,before_json,after_json,reason,context_id,created_at
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                record_id, action,
                self._json(before) if before is not None else None,
                self._json(after) if after is not None else None,
                clean(reason), clean(context_id), self.now().isoformat(),
            ),
        )

    def _find_exact_duplicate(
        self,
        db: sqlite3.Connection,
        *,
        kind: str,
        normalized_title: str,
        start_at: str | None,
        due_at: str | None,
        completed_at: str | None,
    ) -> sqlite3.Row | None:
        day = (completed_at or start_at or due_at or self.now().isoformat())[:10]
        return db.execute(
            """SELECT * FROM records
               WHERE active=1 AND kind=? AND normalized_title=?
                 AND substr(COALESCE(completed_at,start_at,due_at,created_at),1,10)=?
               ORDER BY updated_at DESC LIMIT 1""",
            (kind, normalized_title, day),
        ).fetchone()

    @staticmethod
    def _word_stems(value: str) -> set[str]:
        return {word[:5] for word in tokens(value) if len(word) >= 5}

    def _pending_task_match(
        self, db: sqlite3.Connection, title: str
    ) -> sqlite3.Row | None:
        wanted = tokens(title)
        stems = self._word_stems(title)
        if not wanted:
            return None
        candidates = db.execute(
            "SELECT * FROM records WHERE active=1 AND kind='task' AND status='pending'"
        ).fetchall()
        ranked: list[tuple[float, sqlite3.Row]] = []
        for row in candidates:
            current = tokens(row["title"])
            overlap = len(wanted & current) / max(1, len(wanted | current))
            overlap = max(
                overlap,
                len(stems & self._word_stems(row["title"])) / max(
                    1, len(stems | self._word_stems(row["title"]))
                ),
                SequenceMatcher(None, normalize(title), row["normalized_title"]).ratio(),
            )
            if normalize(title) in row["normalized_title"] or row["normalized_title"] in normalize(title):
                overlap = max(overlap, 0.95)
            if overlap >= 0.55:
                ranked.append((overlap, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
            return None
        return ranked[0][1]

    def capture(
        self,
        *,
        kind: str,
        title: str,
        status: str = "",
        semantic_state: str = "",
        action_verb: str = "",
        object_text: str = "",
        location_text: str = "",
        start_at: str | None = None,
        end_at: str | None = None,
        due_at: str | None = None,
        completed_at: str | None = None,
        date_precision: str = "unknown",
        time_expression: str = "",
        recurrence_rule: str = "",
        priority: str = "",
        importance: float = 0.5,
        confidence: float = 1.0,
        inferred: bool = False,
        source_role: str = "user",
        source_text: str = "",
        context_id: str = "",
        metadata: dict[str, Any] | None = None,
        entities: Iterable[dict[str, str]] | None = None,
        entity_attributes: Iterable[dict[str, Any]] | None = None,
        subject: str = "user",
        predicate: str = "",
        value: str = "",
        occurrences: int = 1,
    ) -> dict[str, Any]:
        kind = KIND_ALIASES.get(normalize(kind), normalize(kind))
        if kind not in KINDS:
            raise ValueError(f"Type personnel inconnu : {kind}")
        title = clean(title or value)
        if not title:
            raise ValueError("Un titre ou une valeur est obligatoire.")
        if source_role != "user":
            raise ValueError("Seules les déclarations de l'utilisateur peuvent être capturées.")
        status = normalize(status) or self._default_status(kind)
        if status not in STATUSES:
            raise ValueError(f"Statut inconnu : {status}")
        semantic_state = self._semantic_state(
            semantic_state, self._default_semantic_state(kind)
        )
        date_precision = normalize(date_precision) or "unknown"
        if date_precision not in DATE_PRECISIONS:
            raise ValueError(f"Précision de date inconnue : {date_precision}")
        try:
            occurrences = max(1, min(1000, int(occurrences or 1)))
        except (TypeError, ValueError):
            occurrences = 1

        start_at = parse_iso(start_at)
        end_at = parse_iso(end_at)
        due_at = parse_iso(due_at)
        completed_at = parse_iso(completed_at)
        now = self.now()
        if semantic_state == "completed" and kind == "action" and not completed_at:
            completed_at = now.isoformat()
        if kind == "task" and status == "done" and not completed_at:
            completed_at = now.isoformat()
        if kind in {"appointment", "event"} and not (start_at or due_at):
            raise ValueError("Un rendez-vous ou événement doit avoir une date explicite.")

        metadata = dict(metadata or {})
        source_text = clean(source_text) or title
        normalized_title = normalize(title)
        entities = list(entities or [])
        entity_attributes = list(entity_attributes or [])

        with self.connect() as db:
            if kind == "action":
                pending = self._pending_task_match(db, title)
                if pending is not None:
                    before = self._record(pending)
                    db.execute(
                        """UPDATE records
                           SET status='done',semantic_state='completed',
                               completed_at=?,occurrences=occurrences+?,
                               action_verb=?,object_text=?,location_text=?,updated_at=?
                           WHERE id=?""",
                        (
                            completed_at or now.isoformat(), occurrences,
                            clean(action_verb), clean(object_text), clean(location_text),
                            now.isoformat(), pending["id"],
                        ),
                    )
                    for entity in entities:
                        self._link_entity(db, pending["id"], entity)
                    for attribute in entity_attributes:
                        self._upsert_entity_attribute(
                            db, pending["id"], attribute, confidence, inferred
                        )
                    after = self._record(
                        db.execute(
                            "SELECT * FROM records WHERE id=?", (pending["id"],)
                        ).fetchone()
                    )
                    self._audit(
                        db, pending["id"], "complete", before, after,
                        reason="Action reliée à une tâche existante",
                        context_id=context_id,
                    )
                    self._remember_state(
                        db, context_id, "capture", {}, [pending["id"]]
                    )
                    return {"operation": "completed_existing_task", "record": after}

            duplicate = None if kind in FACT_KINDS else self._find_exact_duplicate(
                db, kind=kind, normalized_title=normalized_title,
                start_at=start_at, due_at=due_at, completed_at=completed_at,
            )
            if duplicate is not None:
                db.execute(
                    """UPDATE records
                       SET occurrences=occurrences+?,updated_at=? WHERE id=?""",
                    (occurrences, now.isoformat(), duplicate["id"]),
                )
                for entity in entities:
                    self._link_entity(db, duplicate["id"], entity)
                for attribute in entity_attributes:
                    self._upsert_entity_attribute(
                        db, duplicate["id"], attribute, confidence, inferred
                    )
                row = db.execute(
                    "SELECT * FROM records WHERE id=?", (duplicate["id"],)
                ).fetchone()
                result = self._record(row)
                self._audit(
                    db, row["id"], "reinforce", self._record(duplicate), result,
                    reason="Déclaration identique", context_id=context_id,
                )
                return {"operation": "reinforced", "record": result}

            record_id = self._public_id("L")
            db.execute(
                """INSERT INTO records(
                    id,kind,title,normalized_title,status,semantic_state,
                    action_verb,object_text,location_text,start_at,end_at,due_at,
                    completed_at,date_precision,time_expression,recurrence_rule,
                    priority,importance,confidence,inferred,source_role,source_text,
                    context_id,occurrences,metadata_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_id, kind, title, normalized_title, status, semantic_state,
                    clean(action_verb), clean(object_text), clean(location_text),
                    start_at, end_at, due_at, completed_at, date_precision,
                    clean(time_expression), clean(recurrence_rule), clean(priority),
                    self._bounded(importance, 0.5), self._bounded(confidence, 1.0),
                    int(bool(inferred)), source_role, source_text, clean(context_id),
                    occurrences, self._json(metadata), now.isoformat(), now.isoformat(),
                ),
            )
            for entity in entities:
                self._link_entity(db, record_id, entity)
            for attribute in entity_attributes:
                self._upsert_entity_attribute(
                    db, record_id, attribute, confidence, inferred
                )

            fact_result = None
            if kind in FACT_KINDS:
                fact_result = self._upsert_fact(
                    db, record_id=record_id, fact_kind=kind,
                    subject=subject or "user", predicate=predicate or title,
                    value=value or title, confidence=confidence, inferred=inferred,
                )

            row = db.execute(
                "SELECT * FROM records WHERE id=?", (record_id,)
            ).fetchone()
            result = self._record(row)
            self._audit(db, record_id, "create", None, result, context_id=context_id)
            self._remember_state(db, context_id, "capture", {}, [record_id])
            payload = {"operation": "created", "record": result}
            if fact_result:
                payload["fact"] = fact_result
            return payload

    def _link_entity(
        self, db: sqlite3.Connection, record_id: str, entity: dict[str, str]
    ) -> str | None:
        entity_type = normalize(entity.get("type", "person")) or "person"
        name = clean(entity.get("name", ""))
        role = normalize(entity.get("role", "related")) or "related"
        if not name:
            return None
        normalized_name = normalize(name)
        row = db.execute(
            "SELECT id FROM entities WHERE entity_type=? AND normalized_name=?",
            (entity_type, normalized_name),
        ).fetchone()
        entity_id = row["id"] if row else self._public_id("E")
        now = self.now().isoformat()
        if row is None:
            db.execute(
                "INSERT INTO entities VALUES(?,?,?,?,?,?,?)",
                (entity_id, entity_type, name, normalized_name, "[]", now, now),
            )
        db.execute(
            "INSERT OR IGNORE INTO record_entities(record_id,entity_id,role) VALUES(?,?,?)",
            (record_id, entity_id, role),
        )
        return entity_id

    def _entity_id(
        self, db: sqlite3.Connection, name: str, entity_type: str = "person"
    ) -> str | None:
        row = db.execute(
            """SELECT id FROM entities
               WHERE normalized_name=? AND (?='' OR entity_type=?)
               ORDER BY entity_type LIMIT 1""",
            (normalize(name), normalize(entity_type), normalize(entity_type)),
        ).fetchone()
        return row["id"] if row else None

    def _upsert_entity_attribute(
        self,
        db: sqlite3.Connection,
        record_id: str,
        attribute: dict[str, Any],
        confidence: float,
        inferred: bool,
    ) -> None:
        name = clean(attribute.get("entity") or attribute.get("name"))
        attr = clean(attribute.get("attribute") or attribute.get("key"))
        value = clean(attribute.get("value"))
        if not name or not attr or not value:
            return
        entity_type = clean(attribute.get("type") or "person")
        entity_id = self._entity_id(db, name, entity_type)
        if not entity_id:
            entity_id = self._link_entity(
                db, record_id,
                {"type": entity_type, "name": name, "role": "subject"},
            )
        if not entity_id:
            return
        now = self.now().isoformat()
        db.execute(
            """UPDATE entity_attributes SET current=0,updated_at=?
               WHERE entity_id=? AND normalized_attribute=? AND current=1""",
            (now, entity_id, normalize(attr)),
        )
        db.execute(
            """INSERT INTO entity_attributes(
                id,entity_id,attribute,normalized_attribute,value,normalized_value,
                current,confidence,inferred,source_record_id,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._public_id("A"), entity_id, attr, normalize(attr), value,
                normalize(value), 1, self._bounded(confidence, 1.0),
                int(bool(inferred)), record_id, now, now,
            ),
        )

    def _upsert_fact(
        self,
        db: sqlite3.Connection,
        *,
        record_id: str,
        fact_kind: str,
        subject: str,
        predicate: str,
        value: str,
        confidence: float,
        inferred: bool,
    ) -> dict[str, Any]:
        now = self.now().isoformat()
        subject = clean(subject) or "user"
        predicate = clean(predicate)
        value = clean(value)
        if not predicate or not value:
            raise ValueError("Un fait exige subject, predicate et value.")
        current = db.execute(
            """SELECT * FROM facts WHERE current=1
               AND normalized_subject=? AND normalized_predicate=?
               ORDER BY updated_at DESC LIMIT 1""",
            (normalize(subject), normalize(predicate)),
        ).fetchone()
        if current and current["normalized_value"] == normalize(value):
            db.execute(
                """UPDATE facts
                   SET occurrences=occurrences+1,updated_at=?,
                       confidence=max(confidence,?) WHERE id=?""",
                (now, self._bounded(confidence, 1.0), current["id"]),
            )
            return dict(db.execute(
                "SELECT * FROM facts WHERE id=?", (current["id"],)
            ).fetchone())

        previous_id = None
        if current:
            previous_id = current["id"]
            db.execute(
                "UPDATE facts SET current=0,valid_to=?,updated_at=? WHERE id=?",
                (now, now, previous_id),
            )
        fact_id = self._public_id("F")
        db.execute(
            """INSERT INTO facts(
                id,fact_kind,subject,normalized_subject,predicate,
                normalized_predicate,value,normalized_value,valid_from,current,
                confidence,inferred,source_record_id,supersedes_fact_id,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)""",
            (
                fact_id, fact_kind, subject, normalize(subject), predicate,
                normalize(predicate), value, normalize(value), now,
                self._bounded(confidence, 1.0), int(bool(inferred)), record_id,
                previous_id, now, now,
            ),
        )
        return dict(db.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone())

    def _remember_state(
        self,
        db: sqlite3.Connection,
        context_id: str,
        intent: str,
        query: dict[str, Any],
        ids: list[str],
    ) -> None:
        context_id = clean(context_id)
        if not context_id:
            return
        db.execute(
            """INSERT INTO conversation_state(
                context_id,last_intent,last_query_json,last_record_ids_json,updated_at
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(context_id) DO UPDATE SET
                last_intent=excluded.last_intent,
                last_query_json=excluded.last_query_json,
                last_record_ids_json=excluded.last_record_ids_json,
                updated_at=excluded.updated_at""",
            (
                context_id, intent, self._json(query), self._json(ids),
                self.now().isoformat(),
            ),
        )

    def _load_state(self, db: sqlite3.Connection, context_id: str) -> dict[str, Any]:
        if not clean(context_id):
            return {}
        row = db.execute(
            "SELECT * FROM conversation_state WHERE context_id=?", (clean(context_id),)
        ).fetchone()
        if not row:
            return {}
        try:
            return {
                "intent": row["last_intent"],
                "query": json.loads(row["last_query_json"] or "{}"),
                "record_ids": json.loads(row["last_record_ids_json"] or "[]"),
            }
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _entities_for_record(
        db: sqlite3.Connection, record_id: str
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in db.execute(
            """SELECT e.id,e.entity_type,e.canonical_name,re.role
               FROM record_entities re
               JOIN entities e ON e.id=re.entity_id
               WHERE re.record_id=? ORDER BY e.entity_type,e.canonical_name""",
            (record_id,),
        ).fetchall()]

    def _attributes_for_record(
        self, db: sqlite3.Connection, record_id: str
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in db.execute(
            """SELECT e.canonical_name AS entity, e.entity_type,
                      a.attribute, a.value, a.confidence, a.inferred
               FROM entity_attributes a
               JOIN entities e ON e.id=a.entity_id
               JOIN record_entities re ON re.entity_id=e.id
               WHERE re.record_id=? AND a.current=1
               ORDER BY e.canonical_name,a.attribute""",
            (record_id,),
        ).fetchall()]

    def query(
        self,
        *,
        text: str = "",
        kinds: Iterable[str] | None = None,
        statuses: Iterable[str] | None = None,
        states: Iterable[str] | None = None,
        semantic_state: str = "",
        start: str | None = None,
        end: str | None = None,
        subject: str = "",
        predicate: str = "",
        entity: str = "",
        entity_type: str = "",
        current_facts_only: bool = True,
        aggregate: str = "list",
        context_id: str = "",
        follow_up: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        query_spec: dict[str, Any] = {
            "text": clean(text), "kinds": list(kinds or []),
            "statuses": list(statuses or []), "states": list(states or []),
            "semantic_state": clean(semantic_state),
            "start": start, "end": end,
            "subject": clean(subject), "predicate": clean(predicate),
            "entity": clean(entity), "entity_type": normalize(entity_type),
            "current_facts_only": bool(current_facts_only),
            "aggregate": normalize(aggregate) or "list",
        }
        with self.connect() as db:
            if follow_up:
                previous = self._load_state(db, context_id).get("query", {})
                for key, value in previous.items():
                    if query_spec.get(key) in (None, "", [], "list"):
                        query_spec[key] = value
                if start:
                    query_spec["start"] = start
                if end:
                    query_spec["end"] = end

            start_iso = parse_iso(query_spec.get("start"))
            end_iso = parse_iso(query_spec.get("end"), end_of_day=True)
            wanted_kinds = {
                KIND_ALIASES.get(normalize(item), normalize(item))
                for item in query_spec.get("kinds", []) if normalize(item)
            }
            wanted_statuses = {
                normalize(item) for item in query_spec.get("statuses", []) if normalize(item)
            }
            wanted_states = {
                self._semantic_state(item) for item in query_spec.get("states", [])
                if clean(item)
            }
            if query_spec.get("semantic_state"):
                wanted_states.add(self._semantic_state(query_spec["semantic_state"]))

            rows = db.execute(
                "SELECT * FROM records WHERE active=1 ORDER BY updated_at DESC"
            ).fetchall()
            result: list[dict[str, Any]] = []
            query_tokens = tokens(query_spec.get("text", ""))
            for row in rows:
                item = self._record(row)
                if item["kind"] in FACT_KINDS:
                    continue
                if wanted_kinds and item["kind"] not in wanted_kinds:
                    continue
                if wanted_statuses and item["status"] not in wanted_statuses:
                    continue
                if wanted_states and item["semantic_state"] not in wanted_states:
                    continue
                item["entities"] = self._entities_for_record(db, item["id"])
                item["entity_attributes"] = self._attributes_for_record(db, item["id"])
                if query_spec.get("entity") and not any(
                    normalize(query_spec["entity"]) in normalize(link["canonical_name"])
                    for link in item["entities"]
                ):
                    continue
                if query_spec.get("entity_type") and not any(
                    normalize(link["entity_type"]) == query_spec["entity_type"]
                    for link in item["entities"]
                ):
                    continue
                moment = (
                    item.get("completed_at") or item.get("start_at")
                    or item.get("due_at") or item["created_at"]
                )
                if start_iso and moment < start_iso:
                    continue
                if end_iso and moment > end_iso:
                    continue
                if query_tokens:
                    candidate = tokens(
                        " ".join(
                            str(item.get(key, ""))
                            for key in ("title", "source_text", "action_verb",
                                        "object_text", "location_text")
                        )
                    )
                    if not (query_tokens & candidate) and normalize(
                        query_spec["text"]
                    ) not in item["normalized_title"]:
                        continue
                result.append(item)

            facts: list[dict[str, Any]] = []
            fact_requested = bool(wanted_kinds & FACT_KINDS) or bool(
                query_spec.get("subject") or query_spec.get("predicate")
            ) or bool(not wanted_kinds and not start_iso and not end_iso)
            if fact_requested:
                fact_rows = db.execute(
                    "SELECT * FROM facts WHERE (?=0 OR current=1) ORDER BY updated_at DESC",
                    (int(bool(query_spec.get("current_facts_only"))),),
                ).fetchall()
                for row in fact_rows:
                    item = dict(row)
                    if query_spec.get("subject") and normalize(
                        query_spec["subject"]
                    ) != item["normalized_subject"]:
                        continue
                    if query_spec.get("predicate") and normalize(
                        query_spec["predicate"]
                    ) not in item["normalized_predicate"]:
                        continue
                    if query_tokens and not (
                        query_tokens & tokens(
                            item["subject"] + " " + item["predicate"] + " " + item["value"]
                        )
                    ):
                        continue
                    facts.append(item)

            limit = max(1, min(100, int(limit or 20)))
            result = result[:limit]
            facts = facts[:limit]
            ids = [item["id"] for item in result]
            if not ids:
                ids = [
                    str(item.get("source_record_id"))
                    for item in facts if item.get("source_record_id")
                ]
            self._remember_state(db, context_id, "query", query_spec, ids)
            observation_count = sum(
                int(item.get("occurrences") or 1) for item in result
            ) + sum(int(item.get("occurrences") or 1) for item in facts)
            payload: dict[str, Any] = {
                "query": query_spec,
                "records": result,
                "activities": result,
                "facts": facts,
                "found": len(result) + len(facts),
                "count_rows": len(result) + len(facts),
                "observation_count": observation_count,
                "source": "local_personal_memory",
                "web_needed": False,
            }
            if query_spec["aggregate"] == "count":
                payload["count"] = observation_count
            return payload

    def known_entities(self, *, entity_type: str = "", limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            params: list[Any] = []
            where = ""
            if entity_type:
                where = "WHERE entity_type=?"
                params.append(normalize(entity_type))
            params.append(max(1, min(500, int(limit or 100))))
            return [dict(row) for row in db.execute(
                f"""SELECT id,entity_type,canonical_name,normalized_name
                    FROM entities {where}
                    ORDER BY updated_at DESC LIMIT ?""",
                params,
            ).fetchall()]

    def entity_attributes(
        self, *, entity: str = "", entity_type: str = "", current_only: bool = True
    ) -> list[dict[str, Any]]:
        with self.connect() as db:
            clauses = ["1=1"]
            params: list[Any] = []
            if entity:
                clauses.append("e.normalized_name LIKE ?")
                params.append(f"%{normalize(entity)}%")
            if entity_type:
                clauses.append("e.entity_type=?")
                params.append(normalize(entity_type))
            if current_only:
                clauses.append("a.current=1")
            return [dict(row) for row in db.execute(
                f"""SELECT e.id,e.entity_type,e.canonical_name,
                           a.attribute,a.value,a.current,a.confidence,a.inferred
                    FROM entity_attributes a
                    JOIN entities e ON e.id=a.entity_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY a.updated_at DESC""",
                params,
            ).fetchall()]

    def save_pending_clarification(
        self, *, context_id: str, source_text: str, missing: Iterable[str]
    ) -> dict[str, Any]:
        context_id = clean(context_id) or "default"
        missing_list = list(missing)
        with self.connect() as db:
            now = self.now().isoformat()
            db.execute(
                """UPDATE pending_clarifications SET active=0,updated_at=?
                   WHERE context_id=? AND active=1""",
                (now, context_id),
            )
            item_id = self._public_id("P")
            db.execute(
                """INSERT INTO pending_clarifications(
                    id,context_id,source_text,missing_json,active,created_at,updated_at
                ) VALUES(?,?,?,?,1,?,?)""",
                (item_id, context_id, clean(source_text),
                 self._json(missing_list), now, now),
            )
            return {
                "id": item_id, "context_id": context_id,
                "source_text": clean(source_text), "missing": missing_list,
            }

    def pending_clarification(self, context_id: str = "") -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                """SELECT * FROM pending_clarifications
                   WHERE context_id=? AND active=1
                   ORDER BY updated_at DESC LIMIT 1""",
                (clean(context_id) or "default",),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            try:
                result["missing"] = json.loads(result.pop("missing_json") or "[]")
            except json.JSONDecodeError:
                result["missing"] = []
            result["active"] = bool(result["active"])
            return result

    def clear_pending_clarification(self, context_id: str = "") -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE pending_clarifications SET active=0,updated_at=?
                   WHERE context_id=? AND active=1""",
                (self.now().isoformat(), clean(context_id) or "default"),
            )

    def last_query_state(self, context_id: str = "") -> dict[str, Any]:
        with self.connect() as db:
            return self._load_state(db, context_id)

    def _resolve_record(
        self,
        db: sqlite3.Connection,
        *,
        record_id: str = "",
        query: str = "",
        context_id: str = "",
    ) -> tuple[sqlite3.Row | None, list[dict[str, Any]]]:
        if clean(record_id):
            row = db.execute(
                "SELECT * FROM records WHERE id=? AND active=1", (clean(record_id),)
            ).fetchone()
            return row, []
        if not clean(query):
            state_ids = self._load_state(db, context_id).get("record_ids", [])
            if len(state_ids) == 1:
                row = db.execute(
                    "SELECT * FROM records WHERE id=? AND active=1", (state_ids[0],)
                ).fetchone()
                return row, []
            return None, []
        wanted = tokens(query)
        candidates = []
        for row in db.execute(
            "SELECT * FROM records WHERE active=1 ORDER BY updated_at DESC"
        ):
            current = tokens(row["title"] + " " + row["source_text"])
            score = len(wanted & current) / max(1, len(wanted | current))
            if normalize(query) in row["normalized_title"] or row["normalized_title"] in normalize(query):
                score = max(score, 0.95)
            if score >= 0.45:
                candidates.append((score, row))
        candidates.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
        if len(candidates) == 1 or (
            candidates and candidates[0][0] > candidates[1][0] + 0.15
        ):
            return candidates[0][1], []
        return None, [self._record(item[1]) for item in candidates[:5]]

    def update(
        self,
        *,
        record_id: str = "",
        query: str = "",
        context_id: str = "",
        action: str = "update",
        changes: dict[str, Any] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        changes = dict(changes or {})
        action = normalize(action) or "update"
        with self.connect() as db:
            row, ambiguous = self._resolve_record(
                db, record_id=record_id, query=query, context_id=context_id
            )
            if row is None:
                return {
                    "operation": "ambiguous" if ambiguous else "not_found",
                    "candidates": ambiguous,
                    "requires_user_choice": bool(ambiguous),
                }
            before = self._record(row)
            allowed = {
                "title", "status", "semantic_state", "action_verb", "object_text",
                "location_text", "start_at", "end_at", "due_at", "completed_at",
                "date_precision", "time_expression", "recurrence_rule",
                "priority", "importance", "confidence", "metadata",
            }
            clean_changes = {
                key: value for key, value in changes.items() if key in allowed
            }
            if action == "complete":
                clean_changes.update(
                    status="done", semantic_state="completed",
                    completed_at=self.now().isoformat(),
                )
            elif action == "cancel":
                clean_changes.update(status="cancelled", semantic_state="cancelled")
            elif action == "archive":
                clean_changes["status"] = "archived"
            elif action == "reschedule":
                clean_changes.setdefault("semantic_state", "planned")
                if not any(key in clean_changes for key in ("start_at", "due_at")):
                    raise ValueError("Une nouvelle date est obligatoire pour reporter.")

            if "status" in clean_changes:
                clean_changes["status"] = normalize(clean_changes["status"])
                if clean_changes["status"] not in STATUSES:
                    raise ValueError("Statut de mise à jour invalide.")
                if clean_changes["status"] == "done":
                    clean_changes.setdefault("semantic_state", "completed")
            if "semantic_state" in clean_changes:
                clean_changes["semantic_state"] = self._semantic_state(
                    clean_changes["semantic_state"]
                )
            for key in ("start_at", "end_at", "due_at", "completed_at"):
                if key in clean_changes:
                    clean_changes[key] = parse_iso(clean_changes[key])
            if "title" in clean_changes:
                clean_changes["title"] = clean(clean_changes["title"])
                clean_changes["normalized_title"] = normalize(clean_changes["title"])
            if "metadata" in clean_changes:
                merged = dict(before.get("metadata", {}))
                merged.update(dict(clean_changes.pop("metadata") or {}))
                clean_changes["metadata_json"] = self._json(merged)
            clean_changes["updated_at"] = self.now().isoformat()
            if not clean_changes:
                return {"operation": "unchanged", "record": before}
            assignments = ",".join(f"{key}=?" for key in clean_changes)
            db.execute(
                f"UPDATE records SET {assignments} WHERE id=?",
                (*clean_changes.values(), row["id"]),
            )
            after = self._record(
                db.execute("SELECT * FROM records WHERE id=?", (row["id"],)).fetchone()
            )
            self._audit(
                db, row["id"], action, before, after,
                reason=reason, context_id=context_id,
            )
            self._remember_state(db, context_id, action, {}, [row["id"]])
            return {"operation": action, "record": after}

    def forget(
        self,
        *,
        record_ids: Iterable[str] | None = None,
        query: str = "",
        context_id: str = "",
        reason: str = "user_request",
    ) -> dict[str, Any]:
        ids = [clean(item) for item in (record_ids or []) if clean(item)]
        with self.connect() as db:
            if not ids:
                row, ambiguous = self._resolve_record(
                    db, query=query, context_id=context_id
                )
                if row is None:
                    return {
                        "operation": "ambiguous" if ambiguous else "not_found",
                        "candidates": ambiguous,
                        "requires_user_choice": bool(ambiguous),
                    }
                ids = [row["id"]]
            removed = []
            for record_id in ids:
                row = db.execute(
                    "SELECT * FROM records WHERE id=? AND active=1", (record_id,)
                ).fetchone()
                if not row:
                    continue
                before = self._record(row)
                now = self.now().isoformat()
                db.execute(
                    """UPDATE records
                       SET active=0,status='archived',semantic_state='cancelled',
                           updated_at=? WHERE id=?""",
                    (now, record_id),
                )
                db.execute(
                    """UPDATE facts SET current=0,valid_to=?,updated_at=?
                       WHERE source_record_id=? AND current=1""",
                    (now, now, record_id),
                )
                after = self._record(
                    db.execute(
                        "SELECT * FROM records WHERE id=?", (record_id,)
                    ).fetchone()
                )
                self._audit(
                    db, record_id, "forget", before, after,
                    reason=reason, context_id=context_id,
                )
                removed.append(record_id)
            return {
                "operation": "forgotten", "record_ids": removed, "count": len(removed)
            }

    def rollover(self, *, target_date: str | None = None) -> dict[str, Any]:
        target = (parse_iso(target_date) or self.now().isoformat())[:10]
        moved: list[dict[str, Any]] = []
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM records
                   WHERE active=1 AND kind='task' AND status='pending'
                     AND due_at IS NOT NULL AND substr(due_at,1,10) < ?
                     AND date_precision IN ('exact','day')""",
                (target,),
            ).fetchall()
            for row in rows:
                before = self._record(row)
                old_due = datetime.fromisoformat(row["due_at"])
                new_due = old_due.replace(
                    year=int(target[:4]), month=int(target[5:7]), day=int(target[8:10])
                ).isoformat()
                metadata = dict(before.get("metadata", {}))
                metadata["reschedule_count"] = int(
                    metadata.get("reschedule_count", 0)
                ) + 1
                metadata.setdefault("original_due_at", row["due_at"])
                db.execute(
                    """UPDATE records
                       SET due_at=?,metadata_json=?,updated_at=?
                       WHERE id=?""",
                    (new_due, self._json(metadata), self.now().isoformat(), row["id"]),
                )
                after = self._record(
                    db.execute(
                        "SELECT * FROM records WHERE id=?", (row["id"],)
                    ).fetchone()
                )
                self._audit(
                    db, row["id"], "rollover", before, after,
                    reason="Tâche datée non terminée",
                )
                moved.append(after)
        return {
            "operation": "rollover", "target_date": target,
            "moved": moved, "count": len(moved),
        }

    def history(self, record_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM record_history WHERE record_id=? ORDER BY id",
                (clean(record_id),),
            ).fetchall()]

    def register_migration(self, key: str, details: dict[str, Any]) -> bool:
        with self.connect() as db:
            if db.execute(
                "SELECT 1 FROM migrations WHERE migration_key=?", (clean(key),)
            ).fetchone():
                return False
            db.execute(
                "INSERT INTO migrations VALUES(?,?,?)",
                (clean(key), self.now().isoformat(), self._json(details)),
            )
            return True

    def migration_applied(self, key: str) -> bool:
        with self.connect() as db:
            return db.execute(
                "SELECT 1 FROM migrations WHERE migration_key=?", (clean(key),)
            ).fetchone() is not None
