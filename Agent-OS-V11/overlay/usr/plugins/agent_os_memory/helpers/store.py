from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

from .normalization import clean, normalize, parse_user_date, tokens


KINDS = {
    "task", "appointment", "event", "action", "mood", "note",
    "fact", "preference", "relation",
}
FACT_KINDS = {"fact", "preference", "relation"}
STATUSES = {"pending", "scheduled", "done", "logged", "cancelled", "archived"}
DATE_PRECISIONS = {"exact", "day", "week", "month", "unknown"}
TASK_BUCKETS = {"daily", "backlog"}
TASK_BUCKET_ALIASES = {
    "jour": "daily", "quotidien": "daily", "daily": "daily",
    "general": "backlog", "général": "backlog", "backlog": "backlog",
    "todo": "backlog", "todolist": "backlog", "liste": "backlog",
}
OBSERVATION_KINDS = {"capture", "reinforced", "action", "completion", "rollover"}

KIND_ALIASES = {
    "todo": "task", "tache": "task", "tâche": "task",
    "rdv": "appointment", "rendez-vous": "appointment",
    "humeur": "mood", "ressenti": "mood",
    "souvenir": "note", "journal": "action",
    "préférence": "preference", "preference": "preference",
    "relation": "relation", "fait": "fact",
}


class PersonalMemoryStore:
    """Transactional, event-audited personal memory.

    SQL is the source of truth. Agent Zero's vector memory may summarize or
    retrieve general knowledge, but it must not own lifecycle state here.
    """

    SCHEMA_VERSION = 2

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
                    start_at TEXT,
                    end_at TEXT,
                    due_at TEXT,
                    task_bucket TEXT NOT NULL DEFAULT 'backlog',
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

                CREATE TABLE IF NOT EXISTS record_observations(
                    id TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL,
                    observation_kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    context_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(record_id) REFERENCES records(id)
                );
                CREATE INDEX IF NOT EXISTS idx_observations_record
                    ON record_observations(record_id, occurred_at);
                CREATE INDEX IF NOT EXISTS idx_observations_kind_time
                    ON record_observations(observation_kind, occurred_at);

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

                CREATE TABLE IF NOT EXISTS migrations(
                    migration_key TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(records)").fetchall()
            }
            added_task_bucket = False
            if "task_bucket" not in columns:
                db.execute(
                    "ALTER TABLE records ADD COLUMN task_bucket TEXT NOT NULL DEFAULT 'backlog'"
                )
                added_task_bucket = True
            db.execute(
                """UPDATE records
                   SET task_bucket=CASE
                       WHEN kind='task' AND due_at IS NOT NULL THEN 'daily'
                       ELSE 'backlog'
                       END
                   WHERE ?=1 OR task_bucket IS NULL OR task_bucket=''""",
                (int(added_task_bucket),),
            )
            self._backfill_observations(db)
            db.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    def _backfill_observations(self, db: sqlite3.Connection) -> None:
        """Create one evidence row for records created by V11.0.

        Older V11 records kept only a compressed source_text and an occurrences
        counter. We cannot recreate details that were never stored, but we can
        make those records queryable through the new evidence API without
        changing their logical meaning.
        """
        rows = db.execute(
            """SELECT r.* FROM records r
               LEFT JOIN record_observations o ON o.record_id=r.id
               WHERE o.id IS NULL"""
        ).fetchall()
        for row in rows:
            occurred_at = (
                row["completed_at"] or row["start_at"] or row["due_at"]
                or row["created_at"]
            )
            observation_kind = "action" if row["kind"] == "action" else "capture"
            self._append_observation(
                db,
                record_id=row["id"],
                observation_kind=observation_kind,
                title=row["title"],
                source_text=row["source_text"] or row["title"],
                occurred_at=occurred_at,
                context_id=row["context_id"] or "",
                metadata={"legacy_v11_backfill": True},
                occurrences=max(1, int(row["occurrences"] or 1)),
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
        result.setdefault("task_bucket", "backlog")
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
    def _observation(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        try:
            result["metadata"] = json.loads(result.pop("metadata_json", "{}") or "{}")
        except json.JSONDecodeError:
            result["metadata"] = {}
        return result

    def _append_observation(
        self,
        db: sqlite3.Connection,
        *,
        record_id: str,
        observation_kind: str,
        title: str,
        source_text: str,
        occurred_at: str | None,
        context_id: str = "",
        metadata: dict[str, Any] | None = None,
        occurrences: int = 1,
    ) -> dict[str, Any]:
        observation_kind = normalize(observation_kind) or "capture"
        if observation_kind not in OBSERVATION_KINDS:
            raise ValueError(f"Type d'observation inconnu : {observation_kind}")
        now = self.now().isoformat()
        observation_id = self._public_id("O")
        db.execute(
            """INSERT INTO record_observations(
                id,record_id,observation_kind,title,source_text,occurred_at,
                context_id,metadata_json,occurrences,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                observation_id,
                record_id,
                observation_kind,
                clean(title),
                clean(source_text) or clean(title),
                occurred_at or now,
                clean(context_id),
                self._json(metadata or {}),
                max(1, int(occurrences or 1)),
                now,
            ),
        )
        return self._observation(
            db.execute(
                "SELECT * FROM record_observations WHERE id=?", (observation_id,)
            ).fetchone()
        )

    def _observations_for_record(
        self,
        db: sqlite3.Connection,
        record_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = db.execute(
            """SELECT * FROM record_observations
               WHERE record_id=? ORDER BY occurred_at DESC, created_at DESC LIMIT ?""",
            (record_id, max(1, min(200, int(limit or 50)))),
        ).fetchall()
        return [self._observation(row) for row in rows]

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
        if kind == "task" and not due_at:
            return db.execute(
                """SELECT * FROM records
                   WHERE active=1 AND kind='task' AND status='pending'
                     AND task_bucket='backlog' AND normalized_title=?
                   ORDER BY updated_at DESC LIMIT 1""",
                (normalized_title,),
            ).fetchone()
        day = (completed_at or start_at or due_at or self.now().isoformat())[:10]
        return db.execute(
            """SELECT * FROM records
               WHERE active=1 AND kind=? AND normalized_title=?
                 AND substr(COALESCE(completed_at,start_at,due_at,created_at),1,10)=?
               ORDER BY updated_at DESC LIMIT 1""",
            (kind, normalized_title, day),
        ).fetchone()

    def _pending_task_match(
        self, db: sqlite3.Connection, title: str
    ) -> sqlite3.Row | None:
        wanted = tokens(title)
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
                SequenceMatcher(
                    None, normalize(title), row["normalized_title"]
                ).ratio(),
            )
            if normalize(title) in row["normalized_title"] or row["normalized_title"] in normalize(title):
                overlap = max(overlap, 0.95)
            if overlap >= 0.65:
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
        subject: str = "user",
        predicate: str = "",
        value: str = "",
        task_bucket: str = "",
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
        date_precision = normalize(date_precision) or "unknown"
        if date_precision not in DATE_PRECISIONS:
            raise ValueError(f"Précision de date inconnue : {date_precision}")

        now = self.now()
        start_at = parse_user_date(start_at, reference=now)
        end_at = parse_user_date(end_at, reference=now)
        due_at = parse_user_date(due_at, reference=now)
        completed_at = parse_user_date(completed_at, reference=now)
        if kind == "task":
            task_bucket = TASK_BUCKET_ALIASES.get(
                normalize(task_bucket), normalize(task_bucket)
            ) or ("daily" if due_at else "backlog")
            if task_bucket not in TASK_BUCKETS:
                raise ValueError(f"Catégorie de tâche inconnue : {task_bucket}")
            if not due_at:
                task_bucket = "backlog"
        else:
            task_bucket = "backlog"
        if kind == "action" and not completed_at:
            completed_at = now.isoformat()
        if kind == "task" and status == "done" and not completed_at:
            completed_at = now.isoformat()
        if kind in {"appointment", "event"} and not (start_at or due_at):
            raise ValueError("Un rendez-vous ou événement doit avoir une date explicite.")

        metadata = dict(metadata or {})
        source_text = clean(source_text) or title
        normalized_title = normalize(title)

        with self.connect() as db:
            if kind == "action":
                pending = self._pending_task_match(db, title)
                if pending is not None:
                    before = self._record(pending)
                    db.execute(
                        "UPDATE records SET status='done',completed_at=?,updated_at=? WHERE id=?",
                        (completed_at, now.isoformat(), pending["id"]),
                    )
                    after_row = db.execute("SELECT * FROM records WHERE id=?", (pending["id"],)).fetchone()
                    after = self._record(after_row)
                    observation = self._append_observation(
                        db,
                        record_id=pending["id"],
                        observation_kind="completion",
                        title=title,
                        source_text=source_text or title,
                        occurred_at=completed_at,
                        context_id=context_id,
                        metadata=metadata,
                    )
                    self._audit(db, pending["id"], "complete", before, after,
                                reason="Action reliée à une tâche existante", context_id=context_id)
                    self._remember_state(db, context_id, "capture", {}, [pending["id"]])
                    return {
                        "operation": "completed_existing_task",
                        "record": after,
                        "observation": observation,
                    }

            duplicate = None if kind in FACT_KINDS else self._find_exact_duplicate(
                db, kind=kind, normalized_title=normalized_title,
                start_at=start_at, due_at=due_at, completed_at=completed_at,
            )
            if duplicate is not None:
                db.execute(
                    "UPDATE records SET occurrences=occurrences+1,updated_at=? WHERE id=?",
                    (now.isoformat(), duplicate["id"]),
                )
                row = db.execute("SELECT * FROM records WHERE id=?", (duplicate["id"],)).fetchone()
                result = self._record(row)
                observation = self._append_observation(
                    db,
                    record_id=row["id"],
                    observation_kind="action" if kind == "action" else "reinforced",
                    title=title,
                    source_text=source_text,
                    occurred_at=completed_at or start_at or due_at or now.isoformat(),
                    context_id=context_id,
                    metadata=metadata,
                )
                self._audit(db, row["id"], "reinforce", self._record(duplicate), result,
                            reason="Déclaration identique", context_id=context_id)
                return {"operation": "reinforced", "record": result, "observation": observation}

            record_id = self._public_id("L")
            db.execute(
                """INSERT INTO records(
                    id,kind,title,normalized_title,status,start_at,end_at,due_at,
                    task_bucket,completed_at,date_precision,time_expression,recurrence_rule,
                    priority,importance,confidence,inferred,source_role,source_text,
                    context_id,metadata_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_id, kind, title, normalized_title, status, start_at,
                    end_at, due_at, task_bucket, completed_at, date_precision,
                    clean(time_expression), clean(recurrence_rule), clean(priority),
                    self._bounded(importance, 0.5), self._bounded(confidence, 1.0),
                    int(bool(inferred)), source_role, source_text, clean(context_id),
                    self._json(metadata), now.isoformat(), now.isoformat(),
                ),
            )
            for entity in entities or []:
                self._link_entity(db, record_id, entity)

            fact_result = None
            if kind in FACT_KINDS:
                fact_result = self._upsert_fact(
                    db, record_id=record_id, fact_kind=kind,
                    subject=subject or "user", predicate=predicate or title,
                    value=value or title, confidence=confidence, inferred=inferred,
                )

            observation = self._append_observation(
                db,
                record_id=record_id,
                observation_kind=(
                    "action" if kind == "action"
                    else "completion" if kind == "task" and status == "done"
                    else "capture"
                ),
                title=title,
                source_text=source_text,
                occurred_at=completed_at or start_at or due_at or now.isoformat(),
                context_id=context_id,
                metadata=metadata,
            )

            row = db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            result = self._record(row)
            self._audit(db, record_id, "create", None, result, context_id=context_id)
            self._remember_state(db, context_id, "capture", {}, [record_id])
            payload = {"operation": "created", "record": result, "observation": observation}
            if fact_result:
                payload["fact"] = fact_result
            return payload

    def _link_entity(
        self, db: sqlite3.Connection, record_id: str, entity: dict[str, str]
    ) -> None:
        entity_type = normalize(entity.get("type", "person")) or "person"
        name = clean(entity.get("name", ""))
        role = normalize(entity.get("role", "related")) or "related"
        if not name:
            return
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
                "UPDATE facts SET occurrences=occurrences+1,updated_at=?,confidence=max(confidence,?) WHERE id=?",
                (now, self._bounded(confidence, 1.0), current["id"]),
            )
            return dict(db.execute("SELECT * FROM facts WHERE id=?", (current["id"],)).fetchone())

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
            (context_id, intent, self._json(query), self._json(ids), self.now().isoformat()),
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

    def query(
        self,
        *,
        text: str = "",
        kinds: Iterable[str] | None = None,
        statuses: Iterable[str] | None = None,
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
        task_bucket: str = "",
        include_details: bool = True,
    ) -> dict[str, Any]:
        raw_kinds = [kinds] if isinstance(kinds, str) else list(kinds or [])
        raw_statuses = [statuses] if isinstance(statuses, str) else list(statuses or [])
        query_spec: dict[str, Any] = {
            "text": clean(text), "kinds": raw_kinds,
            "statuses": raw_statuses, "start": start, "end": end,
            "subject": clean(subject), "predicate": clean(predicate),
            "entity": clean(entity), "entity_type": normalize(entity_type),
            "current_facts_only": bool(current_facts_only),
            "aggregate": normalize(aggregate) or "list",
            "task_bucket": TASK_BUCKET_ALIASES.get(
                normalize(task_bucket), normalize(task_bucket)
            ),
            "include_details": bool(include_details),
        }
        with self.connect() as db:
            if follow_up:
                previous = self._load_state(db, context_id).get("query", {})
                for key, value in previous.items():
                    if query_spec.get(key) in (None, "", [], "list"):
                        query_spec[key] = value
                # A newly supplied date replaces the old time window.
                if start:
                    query_spec["start"] = start
                if end:
                    query_spec["end"] = end

            if query_spec["task_bucket"] not in ("", *TASK_BUCKETS):
                raise ValueError(
                    f"Catégorie de tâche inconnue : {query_spec['task_bucket']}"
                )
            reference = self.now()
            start_iso = parse_user_date(query_spec.get("start"), reference=reference)
            end_iso = parse_user_date(
                query_spec.get("end"), reference=reference, end_of_day=True
            )
            wanted_kinds = {
                KIND_ALIASES.get(normalize(item), normalize(item))
                for item in query_spec.get("kinds", []) if normalize(item)
            }
            wanted_statuses = {normalize(item) for item in query_spec.get("statuses", []) if normalize(item)}
            rows = db.execute("SELECT * FROM records WHERE active=1 ORDER BY updated_at DESC").fetchall()
            result: list[dict[str, Any]] = []
            query_tokens = tokens(query_spec.get("text", ""))

            def in_window(values: Iterable[str | None]) -> bool:
                usable = [str(value) for value in values if value]
                if not usable:
                    return not start_iso and not end_iso
                return any(
                    (not start_iso or value >= start_iso)
                    and (not end_iso or value <= end_iso)
                    for value in usable
                )

            def matches_text(values: Iterable[str]) -> bool:
                if not query_tokens:
                    return True
                candidate = tokens(" ".join(values))
                normalized_query = normalize(query_spec["text"])
                return bool(query_tokens & candidate) or any(
                    normalized_query and normalized_query in normalize(value)
                    for value in values
                )

            for row in rows:
                item = self._record(row)
                # Facts have their own versioned projection below. Returning the
                # supporting record too would count the same statement twice.
                if item["kind"] in FACT_KINDS:
                    continue
                if wanted_kinds and item["kind"] not in wanted_kinds:
                    continue
                if wanted_statuses and item["status"] not in wanted_statuses:
                    continue
                if query_spec["task_bucket"] and (
                    item["kind"] != "task"
                    or item["task_bucket"] != query_spec["task_bucket"]
                ):
                    continue
                item["entities"] = self._entities_for_record(db, item["id"])
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
                observations = self._observations_for_record(db, item["id"])
                if item["kind"] == "task":
                    time_values = [
                        item.get("due_at") or item.get("completed_at")
                        or item["created_at"]
                    ]
                elif item["kind"] in {"appointment", "event"}:
                    time_values = [
                        item.get("start_at") or item.get("due_at")
                        or item["created_at"]
                    ]
                elif item["kind"] == "action":
                    time_values = [item.get("completed_at") or item["created_at"]]
                else:
                    time_values = [item["created_at"]]
                if not in_window(
                    time_values
                ):
                    continue
                if not matches_text(
                    [
                        item["title"], item["source_text"],
                        *(observation.get("title", "") for observation in observations),
                        *(observation.get("source_text", "") for observation in observations),
                    ]
                ):
                    continue
                item["occurrence_count"] = int(item.get("occurrences") or 1)
                if query_spec["include_details"]:
                    item["observations"] = observations
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
                    if query_spec.get("subject") and normalize(query_spec["subject"]) != item["normalized_subject"]:
                        continue
                    if query_spec.get("predicate") and normalize(query_spec["predicate"]) not in item["normalized_predicate"]:
                        continue
                    if query_tokens and not (
                        query_tokens & tokens(item["subject"] + " " + item["predicate"] + " " + item["value"])
                    ):
                        continue
                    if end_iso and item["valid_from"] > end_iso:
                        continue
                    if start_iso and item.get("valid_to") and item["valid_to"] < start_iso:
                        continue
                    facts.append(item)

            activities: list[dict[str, Any]] = []
            activity_requested = bool(
                "action" in wanted_kinds
                or (not wanted_kinds and (query_tokens or query_spec["aggregate"] == "count"))
            )
            if activity_requested:
                activity_rows = db.execute(
                    """SELECT o.*, r.kind AS record_kind, r.title AS record_title,
                              r.status AS record_status, r.task_bucket AS record_task_bucket
                       FROM record_observations o
                       JOIN records r ON r.id=o.record_id
                       WHERE r.active=1
                         AND o.observation_kind IN ('action','completion')
                       ORDER BY o.occurred_at DESC, o.created_at DESC"""
                ).fetchall()
                for row in activity_rows:
                    if wanted_kinds and "action" not in wanted_kinds:
                        continue
                    if wanted_statuses and row["record_status"] not in wanted_statuses:
                        continue
                    if query_spec["task_bucket"] and (
                        row["record_kind"] != "task"
                        or row["record_task_bucket"] != query_spec["task_bucket"]
                    ):
                        continue
                    if not in_window([row["occurred_at"]]):
                        continue
                    if not matches_text(
                        [row["title"], row["source_text"], row["record_title"]]
                    ):
                        continue
                    entities = self._entities_for_record(db, row["record_id"])
                    if query_spec.get("entity") and not any(
                        normalize(query_spec["entity"]) in normalize(link["canonical_name"])
                        for link in entities
                    ):
                        continue
                    if query_spec.get("entity_type") and not any(
                        normalize(link["entity_type"]) == query_spec["entity_type"]
                        for link in entities
                    ):
                        continue
                    activity = self._observation(row)
                    activity.update(
                        {
                            "record_id": row["record_id"],
                            "record_kind": row["record_kind"],
                            "record_title": row["record_title"],
                            "record_status": row["record_status"],
                            "task_bucket": row["record_task_bucket"],
                            "entities": entities,
                        }
                    )
                    activities.append(activity)

            record_occurrence_count = sum(
                int(item.get("occurrences") or 1) for item in result
            )
            fact_occurrence_count = sum(
                int(item.get("occurrences") or 1) for item in facts
            )
            activity_count = sum(
                int(item.get("occurrences") or 1) for item in activities
            )
            limit = max(1, min(100, int(limit or 20)))
            result = result[:limit]
            facts = facts[:limit]
            activities = activities[:limit]
            ids: list[str] = []
            for item in [*result, *facts, *activities]:
                record_id = item.get("id") or item.get("source_record_id") or item.get("record_id")
                if record_id and record_id not in ids:
                    ids.append(str(record_id))
            self._remember_state(db, context_id, "query", query_spec, ids)
            if "action" in wanted_kinds or (not wanted_kinds and query_tokens and activity_count):
                count = activity_count
            else:
                count = record_occurrence_count + fact_occurrence_count
            payload: dict[str, Any] = {
                "query": query_spec,
                "records": result,
                "facts": facts,
                "activities": activities,
                "found": len(result) + len(facts) or len(activities),
                "record_count": len(result),
                "fact_count": len(facts),
                "occurrence_count": record_occurrence_count + fact_occurrence_count,
                "activity_count": activity_count,
                "source": "local_personal_memory",
                "web_needed": False,
            }
            if query_spec["aggregate"] == "count":
                payload["count"] = count
            return payload

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
        for row in db.execute("SELECT * FROM records WHERE active=1 ORDER BY updated_at DESC"):
            current = tokens(row["title"])
            score = len(wanted & current) / max(1, len(wanted | current))
            if normalize(query) in row["normalized_title"] or row["normalized_title"] in normalize(query):
                score = max(score, 0.95)
            if score >= 0.45:
                candidates.append((score, row))
        candidates.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
        if len(candidates) == 1 or (
            candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0] + 0.15)
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
                "title", "status", "start_at", "end_at", "due_at",
                "completed_at", "date_precision", "time_expression",
                "recurrence_rule", "priority", "importance", "confidence",
                "metadata", "task_bucket",
            }
            clean_changes = {key: value for key, value in changes.items() if key in allowed}
            completes_task = False
            if action == "complete":
                clean_changes.update(status="done", completed_at=self.now().isoformat())
                completes_task = True
            elif action == "cancel":
                clean_changes["status"] = "cancelled"
            elif action == "archive":
                clean_changes["status"] = "archived"
            elif action == "reschedule" and not any(key in clean_changes for key in ("start_at", "due_at")):
                raise ValueError("Une nouvelle date est obligatoire pour reporter.")

            if "status" in clean_changes:
                clean_changes["status"] = normalize(clean_changes["status"])
                if clean_changes["status"] not in STATUSES:
                    raise ValueError("Statut de mise à jour invalide.")
                completes_task = completes_task or (
                    before["status"] != "done" and clean_changes["status"] == "done"
                )
            for key in ("start_at", "end_at", "due_at", "completed_at"):
                if key in clean_changes:
                    clean_changes[key] = parse_user_date(
                        clean_changes[key], reference=self.now()
                    )
            if "task_bucket" in clean_changes:
                clean_changes["task_bucket"] = TASK_BUCKET_ALIASES.get(
                    normalize(clean_changes["task_bucket"]),
                    normalize(clean_changes["task_bucket"]),
                )
                if clean_changes["task_bucket"] not in TASK_BUCKETS:
                    raise ValueError("Catégorie de tâche invalide.")
            if before["kind"] == "task" and "due_at" in clean_changes:
                clean_changes["task_bucket"] = (
                    "daily" if clean_changes["due_at"] else "backlog"
                )
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
            after = self._record(db.execute("SELECT * FROM records WHERE id=?", (row["id"],)).fetchone())
            observation = None
            if completes_task:
                observation = self._append_observation(
                    db,
                    record_id=row["id"],
                    observation_kind="completion",
                    title=after["title"],
                    source_text=clean(reason) or "Tâche terminée",
                    occurred_at=after.get("completed_at") or self.now().isoformat(),
                    context_id=context_id,
                    metadata={"via": "life_update"},
                )
            self._audit(db, row["id"], action, before, after, reason=reason, context_id=context_id)
            self._remember_state(db, context_id, action, {}, [row["id"]])
            result = {"operation": action, "record": after}
            if observation:
                result["observation"] = observation
            return result

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
                row, ambiguous = self._resolve_record(db, query=query, context_id=context_id)
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
                db.execute(
                    "UPDATE records SET active=0,status='archived',updated_at=? WHERE id=?",
                    (self.now().isoformat(), record_id),
                )
                db.execute(
                    "UPDATE facts SET current=0,valid_to=?,updated_at=? WHERE source_record_id=? AND current=1",
                    (self.now().isoformat(), self.now().isoformat(), record_id),
                )
                after = self._record(db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone())
                self._audit(db, record_id, "forget", before, after, reason=reason, context_id=context_id)
                removed.append(record_id)
            return {"operation": "forgotten", "record_ids": removed, "count": len(removed)}

    def rollover(self, *, target_date: str | None = None) -> dict[str, Any]:
        target = (parse_user_date(target_date, reference=self.now()) or self.now().isoformat())[:10]
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
                metadata = dict(before.get("metadata", {}))
                metadata["reschedule_count"] = int(metadata.get("reschedule_count", 0)) + 1
                metadata.setdefault("original_due_at", row["due_at"])
                metadata["last_due_at"] = row["due_at"]
                metadata.setdefault("overdue_since", target)
                db.execute(
                    """UPDATE records
                       SET due_at=NULL,task_bucket='backlog',metadata_json=?,updated_at=?
                       WHERE id=?""",
                    (self._json(metadata), self.now().isoformat(), row["id"]),
                )
                after = self._record(db.execute("SELECT * FROM records WHERE id=?", (row["id"],)).fetchone())
                self._append_observation(
                    db,
                    record_id=row["id"],
                    observation_kind="rollover",
                    title=after["title"],
                    source_text=(
                        f"Tâche non réalisée prévue le {row['due_at'][:10]}"
                    ),
                    occurred_at=self.now().isoformat(),
                    metadata={"previous_due_at": row["due_at"], "target_date": target},
                )
                self._audit(db, row["id"], "rollover", before, after,
                            reason="Tâche datée non terminée")
                moved.append(after)
        return {"operation": "rollover", "target_date": target, "moved": moved, "count": len(moved)}

    def history(self, record_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM record_history WHERE record_id=? ORDER BY id", (clean(record_id),)
            ).fetchall()]

    def register_migration(self, key: str, details: dict[str, Any]) -> bool:
        with self.connect() as db:
            if db.execute("SELECT 1 FROM migrations WHERE migration_key=?", (key,)).fetchone():
                return False
            db.execute(
                "INSERT INTO migrations VALUES(?,?,?)",
                (key, self.now().isoformat(), self._json(details)),
            )
            return True

    def migration_applied(self, key: str) -> bool:
        with self.connect() as db:
            return db.execute(
                "SELECT 1 FROM migrations WHERE migration_key=?", (clean(key),)
            ).fetchone() is not None
