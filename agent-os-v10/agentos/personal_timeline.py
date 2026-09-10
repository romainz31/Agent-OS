"""Personal Timeline V10.2.

Single chronological source for personal planning and lived actions.

The authoritative storage is ``agenda_items``:
- todo: task to do / completed task;
- appointment: appointment;
- event: planned personal event;
- action: action reported as completed;
- mood: dated mood/feeling reported by the user.

V10.1 ``life_events`` rows are migrated once and kept only as a legacy backup.
"""
from __future__ import annotations

import calendar
import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Any


def norm(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or "").lower())
        if not unicodedata.combining(char)
    )


def canon(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", norm(value)))


class PersonalTimeline:
    """Unified personal timeline backed by ``PersonalAgenda.agenda_items``."""

    VERSION = "10.2"

    # Deliberately explicit: this keeps statements such as "j'ai faim" or
    # "j'ai un chat" out of the completed-action history.
    COMPLETED_VERBS = {
        "achete", "accompagne", "appele", "apporte", "arrose", "aspire",
        "bricole", "change", "charge", "cherche", "commande", "coupe",
        "debranche", "deplace", "depose", "desherbe", "donne", "dormi",
        "emmene", "envoye", "ete", "fait", "fais", "ferme", "fini",
        "installe", "lance", "lave", "livre", "mange", "mis", "monte",
        "nettoye", "ouvert", "passe", "paye", "plante", "pris", "prepare",
        "ramene", "range", "recu", "repare", "remplace", "rempli",
        "reserve", "retire", "rince", "sorti", "termine", "teste", "tondu",
        "trie", "verifie", "vide",
    }

    NON_ACTION_STARTS = (
        "besoin ", "envie ", "faim", "soif", "peur", "mal ", "chaud",
        "froid", "raison", "tort", "un rdv", "un rendez vous", "rendez vous",
        "dentiste", "medecin", "docteur", "une question", "une idee",
    )

    QUERY_STOPWORDS = {
        "les", "des", "une", "que", "quoi", "fait", "faite", "faites",
        "fais", "fois", "dans", "pour", "mon", "mes", "sur", "trois",
        "derniers", "dernier", "mois", "depuis", "est", "quand", "combien",
        "jai", "aujourdhui", "aujourd", "hui", "hier", "tache", "taches",
        "termine", "terminees", "terminee", "comme", "quelles", "quelle",
    }

    def __init__(self, agenda) -> None:
        self.agenda = agenda
        self._ensure_support_tables()
        self._migrate_legacy_life_events()

    # =========================================================
    # STORAGE / MIGRATION
    # =========================================================

    def _ensure_support_tables(self) -> None:
        with self.agenda._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS life_notices(key TEXT PRIMARY KEY)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_kind_day "
                "ON agenda_items(kind,due_date,status)"
            )

    def _legacy_table_exists(self) -> bool:
        with self.agenda._connect() as db:
            row = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_events'"
            ).fetchone()
        return row is not None

    def _migrate_legacy_life_events(self) -> None:
        if not self._legacy_table_exists():
            return

        with self.agenda._connect() as db:
            done = db.execute(
                "SELECT value FROM agenda_meta WHERE key='timeline_v102_life_events_migrated'"
            ).fetchone()
            if done:
                return

            rows = db.execute(
                "SELECT id,day,title,kind,source,created FROM life_events ORDER BY id"
            ).fetchall()

            for row in rows:
                mapped_kind = "mood" if str(row["kind"]) == "humeur" else "action"
                title = str(row["title"] or "").strip()
                if mapped_kind == "action":
                    title = re.sub(r"^j\s*[’']?\s*ai\s+", "", title, flags=re.I).strip()
                day = str(row["day"] or "").strip()
                if not title or not day:
                    continue
                try:
                    date.fromisoformat(day)
                except ValueError:
                    continue

                normalized = self._normalize_title(title)
                existing = db.execute(
                    """
                    SELECT id FROM agenda_items
                    WHERE kind=? AND due_date=? AND normalized_title=?
                    LIMIT 1
                    """,
                    (mapped_kind, day, normalized),
                ).fetchone()
                if existing:
                    continue

                created = str(row["created"] or self.agenda._now().isoformat())
                metadata = {
                    "timeline_version": self.VERSION,
                    "origin": "legacy_life_events",
                    "legacy_life_event_id": int(row["id"]),
                }
                completed_at = self._occurred_iso(day) if mapped_kind == "action" else None
                status = "done" if mapped_kind == "action" else "logged"

                db.execute(
                    """
                    INSERT INTO agenda_items(
                        kind,title,normalized_title,due_date,start_time,end_time,
                        status,source_text,metadata_json,created_at,updated_at,completed_at
                    ) VALUES(?,?,?,?,NULL,NULL,?,?,?,?,?,?)
                    """,
                    (
                        mapped_kind,
                        title,
                        normalized,
                        day,
                        status,
                        str(row["source"] or title),
                        json.dumps(metadata, ensure_ascii=False),
                        created,
                        created,
                        completed_at,
                    ),
                )

            db.execute(
                "INSERT OR REPLACE INTO agenda_meta(key,value) VALUES(?,?)",
                ("timeline_v102_life_events_migrated", self.agenda._now().isoformat()),
            )

    def _normalize_title(self, title: str) -> str:
        normalize = getattr(self.agenda, "normalize", None)
        if callable(normalize):
            return str(normalize(title))
        return canon(title)

    def _occurred_iso(self, day: str) -> str:
        target = date.fromisoformat(day)
        now = self.agenda._now()
        if target == now.date():
            return now.isoformat()
        tz = now.tzinfo
        return datetime.combine(target, time(hour=12), tzinfo=tz).isoformat()

    @staticmethod
    def _metadata(row: dict[str, Any]) -> dict[str, Any]:
        try:
            data = json.loads(str(row.get("metadata_json") or "{}"))
        except Exception:
            data = {}
        return data if isinstance(data, dict) else {}

    # =========================================================
    # FRIENDLY TEXT
    # =========================================================

    @staticmethod
    def _natural_list(values: list[str]) -> str:
        values = [str(value).strip() for value in values if str(value).strip()]
        if len(values) < 2:
            return values[0] if values else ""
        return ", ".join(values[:-1]) + " et " + values[-1]

    @staticmethod
    def _friendly_day(value: str, today: date) -> str:
        day = date.fromisoformat(value)
        if day == today:
            return "aujourd'hui"
        if day == today - timedelta(days=1):
            return "hier"
        if day == today + timedelta(days=1):
            return "demain"
        return day.strftime("le %d/%m/%Y")

    @staticmethod
    def _as_user_action(value: str) -> str:
        value = str(value or "").strip(" .")
        value = re.sub(r"^j\s*[’']?\s*ai\s+", "", value, flags=re.I)
        return "tu as " + value

    # =========================================================
    # ACTION CAPTURE
    # =========================================================

    @classmethod
    def _strip_relative_prefix(cls, value: str) -> str:
        return re.sub(
            r"^(?:aujourd(?:['’]?hui)|aujourdhui|hier|ce\s+matin|cet\s+apres[- ]?midi|cet\s+après[- ]?midi|ce\s+soir)\s*[,;:\-]?\s*",
            "",
            str(value or "").strip(),
            count=1,
            flags=re.I,
        )

    @classmethod
    def _completed_payload(cls, text: str) -> str | None:
        if "?" in str(text or ""):
            return None

        raw = cls._strip_relative_prefix(str(text or "").strip())
        match = re.match(r"^j\s*[’']?\s*ai\s+(.+)$", raw, flags=re.I)
        if not match:
            return None

        payload = match.group(1).strip()
        normalized = canon(payload)
        if not normalized:
            return None
        if any(normalized.startswith(start) for start in cls.NON_ACTION_STARTS):
            return None
        if re.search(r"\b(?:pas|jamais|peut etre|peut-etre|si)\b", normalized):
            return None

        first = normalized.split()[0]
        if first not in cls.COMPLETED_VERBS:
            return None
        return payload

    @classmethod
    def _starts_with_completed_verb(cls, value: str) -> bool:
        normalized = canon(value)
        return bool(normalized) and normalized.split()[0] in cls.COMPLETED_VERBS

    @classmethod
    def _split_completed_payload(cls, payload: str) -> list[str]:
        value = str(payload or "").strip(" .")
        value = re.sub(r"\n\s*[-*•]\s*", ";", value)

        # Commas/semicolons always separate actions. "et" is also accepted so
        # "nettoyé la cuisine et le salon" becomes two useful timeline facts.
        chunks = [
            part.strip(" .,:;-")
            for part in re.split(r"\s*(?:;|,|\n|\bet\b)\s*", value, flags=re.I)
            if part.strip(" .,:;-")
        ]
        if not chunks:
            return []

        first_words = chunks[0].split()
        inherited_verb = first_words[0] if first_words else ""
        inherited_norm = canon(inherited_verb)
        if inherited_norm not in cls.COMPLETED_VERBS:
            inherited_verb = ""

        result: list[str] = []
        for index, chunk in enumerate(chunks):
            chunk = re.sub(r"^j\s*[’']?\s*ai\s+", "", chunk, flags=re.I).strip()
            if not chunk:
                continue
            if index > 0 and inherited_verb and not cls._starts_with_completed_verb(chunk):
                chunk = inherited_verb + " " + chunk
            if chunk not in result:
                result.append(chunk)
        return result[:30]

    @classmethod
    def _split_explicit_journal(cls, payload: str) -> list[str]:
        value = str(payload or "").strip()
        value = re.sub(r"\n\s*[-*•]\s*", ";", value)
        if cls._starts_with_completed_verb(value):
            return cls._split_completed_payload(value)
        parts = [p.strip(" .,:;-") for p in re.split(r"[;,\n]+", value) if p.strip()]
        return parts[:30]

    def _same_completed_todo(self, title: str, day: str) -> dict[str, Any] | None:
        with self.agenda._connect() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM agenda_items
                    WHERE kind='todo' AND status='done'
                      AND substr(COALESCE(completed_at,''),1,10)=?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (day,),
                ).fetchall()
            ]
        for item in rows:
            try:
                if self.agenda._todo_match_score(title, item) >= 0.90:
                    return item
            except Exception:
                if canon(title) == canon(item.get("title", "")):
                    return item
        return None

    def add(self, title: str, day: str, kind: str = "action", source: str = ""):
        date.fromisoformat(day)
        mapped_kind = "mood" if kind in {"humeur", "mood"} else kind
        if mapped_kind not in {"action", "mood"}:
            raise ValueError("Type Timeline inconnu")

        title = str(title or "").strip(" .")
        if not title:
            raise ValueError("Action vide")

        if mapped_kind == "action":
            done_todo = self._same_completed_todo(title, day)
            if done_todo is not None:
                return int(done_todo["id"]), False

        normalized = self._normalize_title(title)
        now = self.agenda._now().isoformat()
        status = "done" if mapped_kind == "action" else "logged"
        completed_at = self._occurred_iso(day) if mapped_kind == "action" else None
        metadata = {
            "timeline_version": self.VERSION,
            "origin": "conversation",
        }

        with self.agenda._connect() as db:
            old = db.execute(
                """
                SELECT id FROM agenda_items
                WHERE kind=? AND due_date=? AND normalized_title=?
                LIMIT 1
                """,
                (mapped_kind, day, normalized),
            ).fetchone()
            if old:
                return int(old["id"]), False

            cursor = db.execute(
                """
                INSERT INTO agenda_items(
                    kind,title,normalized_title,due_date,start_time,end_time,
                    status,source_text,metadata_json,created_at,updated_at,completed_at
                ) VALUES(?,?,?,?,NULL,NULL,?,?,?,?,?,?)
                """,
                (
                    mapped_kind,
                    title,
                    normalized,
                    day,
                    status,
                    str(source or title).strip(),
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    now,
                    completed_at,
                ),
            )
            return int(cursor.lastrowid), True

    # =========================================================
    # ROLLOVER
    # =========================================================

    def rollover(self) -> None:
        today = self.agenda._now().date().isoformat()
        with self.agenda._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM agenda_items
                WHERE kind='todo' AND status='pending' AND due_date<?
                """,
                (today,),
            ).fetchall()
            for row in rows:
                try:
                    metadata = json.loads(row["metadata_json"] or "{}")
                except Exception:
                    metadata = {}
                source_key = canon(row["source_text"] or "")
                explicit_date_in_source = bool(
                    re.search(r"\b(?:aujourdhui|demain|hier|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b", source_key)
                    or re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", str(row["source_text"] or ""))
                )
                looks_explicitly_undated = (
                    source_key.startswith("a faire")
                    and not explicit_date_in_source
                )
                if metadata.get("backlog_undated") or looks_explicitly_undated:
                    continue
                metadata.setdefault("first_due_date", row["due_date"])
                metadata["previous_due_date"] = row["due_date"]
                metadata["reschedule_count"] = int(metadata.get("reschedule_count", 0)) + 1
                db.execute(
                    """
                    UPDATE agenda_items
                    SET due_date=?,metadata_json=?,updated_at=?
                    WHERE id=?
                    """,
                    (
                        today,
                        json.dumps(metadata, ensure_ascii=False),
                        self.agenda._now().isoformat(),
                        row["id"],
                    ),
                )

    # =========================================================
    # UNIFIED READS
    # =========================================================

    @classmethod
    def _query_words(cls, query: str) -> list[str]:
        return [
            word
            for word in re.findall(r"[a-z0-9]+", canon(query))
            if len(word) > 2 and word not in cls.QUERY_STOPWORDS
        ]

    @classmethod
    def _matches_query(cls, title: str, query: str) -> bool:
        words = cls._query_words(query)
        searchable = canon(title)
        return not words or all(word in searchable for word in words)

    def completed_rows(self, start: str, end: str, query: str = "") -> list[dict[str, Any]]:
        with self.agenda._connect() as db:
            action_rows = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM agenda_items
                    WHERE kind='action' AND due_date BETWEEN ? AND ?
                    ORDER BY due_date,id
                    """,
                    (start, end),
                ).fetchall()
            ]
            todo_rows = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM agenda_items
                    WHERE kind='todo' AND status='done'
                      AND substr(COALESCE(completed_at,''),1,10) BETWEEN ? AND ?
                    ORDER BY completed_at,id
                    """,
                    (start, end),
                ).fetchall()
            ]

        result: list[dict[str, Any]] = []
        for row in action_rows:
            if not self._matches_query(row["title"], query):
                continue
            result.append(
                {
                    "id": row["id"],
                    "day": row["due_date"],
                    "title": row["title"],
                    "kind": "action",
                    "status": "done",
                    "source": row["source_text"],
                    "planned_for": None,
                    "completed_at": row.get("completed_at"),
                }
            )

        for row in todo_rows:
            day = str(row.get("completed_at") or "")[:10]
            if not day or not self._matches_query(row["title"], query):
                continue
            # If the same real-world action was already explicitly logged, do
            # not display/count it twice.
            duplicate = False
            for existing in result:
                if existing["day"] != day:
                    continue
                try:
                    if self.agenda._todo_match_score(existing["title"], row) >= 0.90:
                        duplicate = True
                        break
                except Exception:
                    if canon(existing["title"]) == canon(row["title"]):
                        duplicate = True
                        break
            if duplicate:
                continue
            result.append(
                {
                    "id": "T-" + str(row["id"]),
                    "day": day,
                    "title": row["title"],
                    "kind": "todo",
                    "status": "done",
                    "source": row["source_text"],
                    "planned_for": row["due_date"],
                    "completed_at": row.get("completed_at"),
                }
            )

        return sorted(result, key=lambda item: (item["day"], str(item["id"])))

    def rows(self, start: str, end: str, query: str = "") -> list[dict[str, Any]]:
        """Legacy journal read: completed actions + moods.

        The method name stays for API/test compatibility, but data now comes
        from the unified ``agenda_items`` Timeline.
        """
        result = self.completed_rows(start, end, query)
        with self.agenda._connect() as db:
            moods = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM agenda_items
                    WHERE kind='mood' AND due_date BETWEEN ? AND ?
                    ORDER BY due_date,id
                    """,
                    (start, end),
                ).fetchall()
            ]
        for row in moods:
            if not self._matches_query(row["title"], query):
                continue
            result.append(
                {
                    "id": row["id"],
                    "day": row["due_date"],
                    "title": row["title"],
                    "kind": "humeur",
                    "status": "logged",
                    "source": row["source_text"],
                    "planned_for": None,
                    "completed_at": None,
                }
            )
        return sorted(result, key=lambda item: (item["day"], str(item["id"])))

    def timeline_rows(self, start: str, end: str, query: str = "") -> list[dict[str, Any]]:
        """Return every personal Timeline item in one normalized shape."""
        with self.agenda._connect() as db:
            raw_rows = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM agenda_items
                    WHERE due_date BETWEEN ? AND ?
                       OR substr(COALESCE(completed_at,''),1,10) BETWEEN ? AND ?
                    ORDER BY due_date,start_time,id
                    """,
                    (start, end, start, end),
                ).fetchall()
            ]

        result: list[dict[str, Any]] = []
        for row in raw_rows:
            if not self._matches_query(row.get("title", ""), query):
                continue
            kind = str(row.get("kind") or "event")
            status = str(row.get("status") or "pending")
            completed_day = str(row.get("completed_at") or "")[:10] or None
            display_day = completed_day if kind == "todo" and status == "done" else row["due_date"]
            result.append(
                {
                    "id": row["id"],
                    "day": display_day,
                    "planned_for": row["due_date"],
                    "start_time": row.get("start_time"),
                    "title": row["title"],
                    "kind": kind,
                    "status": status,
                    "completed_at": row.get("completed_at"),
                    "source": row.get("source_text", ""),
                }
            )
        return sorted(
            result,
            key=lambda item: (
                item.get("day") or "9999-12-31",
                item.get("start_time") or "99:99",
                int(item["id"]) if str(item["id"]).isdigit() else 0,
            ),
        )

    def day_summary(self, target: date) -> str:
        day = target.isoformat()
        today = self.agenda._now().date()
        label = self._friendly_day(day, today)

        with self.agenda._connect() as db:
            scheduled = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM agenda_items
                    WHERE due_date=? AND kind IN ('todo','appointment','event')
                    ORDER BY CASE WHEN start_time IS NULL THEN 1 ELSE 0 END,start_time,id
                    """,
                    (day,),
                ).fetchall()
            ]
            moods = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM agenda_items WHERE due_date=? AND kind='mood' ORDER BY id",
                    (day,),
                ).fetchall()
            ]

        completed = self.completed_rows(day, day)
        pending_todos = [row for row in scheduled if row["kind"] == "todo" and row["status"] == "pending"]
        appointments = [row for row in scheduled if row["kind"] == "appointment" and row["status"] == "pending"]
        events = [row for row in scheduled if row["kind"] == "event" and row["status"] == "pending"]

        lines = [f"Timeline pour {label} :"]
        if appointments:
            lines.append("Rendez-vous :")
            for item in appointments:
                prefix = f"{item['start_time']} — " if item.get("start_time") else ""
                lines.append(f"- {prefix}{item['title']}")
        if pending_todos:
            lines.append("À faire :")
            for item in pending_todos:
                lines.append(f"- {item['title']}")
        if events:
            lines.append("Événements :")
            for item in events:
                prefix = f"{item['start_time']} — " if item.get("start_time") else ""
                lines.append(f"- {prefix}{item['title']}")
        if completed:
            lines.append("Fait :")
            for item in completed:
                suffix = " (tâche terminée)" if item["kind"] == "todo" else ""
                lines.append(f"- {item['title']}{suffix}")
        if moods:
            lines.append("Ressenti :")
            lines.extend(f"- {item['title']}" for item in moods)

        if len(lines) == 1:
            lines.append("Rien de noté pour le moment.")
        return "\n".join(lines)

    # =========================================================
    # QUERY PARSING
    # =========================================================

    def _period(
        self,
        text: str,
        *,
        default_all_time: bool = False,
    ) -> tuple[date, date, re.Match[str] | None]:
        today = self.agenda._now().date()
        normalized = canon(text)
        match = re.search(r"(\d+|trois|six|deux)\s+(?:derniers?\s+)?mois", normalized)
        if match:
            raw_count = match.group(1)
            count = {"deux": 2, "trois": 3, "six": 6}.get(
                raw_count,
                int(raw_count) if raw_count.isdigit() else 3,
            )
            if count > 1200:
                raise ValueError("Choisis une période de 1 à 1200 mois.")
            idx = today.year * 12 + today.month - 1 - count
            year, month0 = divmod(idx, 12)
            start = date(year, month0 + 1, min(today.day, calendar.monthrange(year, month0 + 1)[1]))
            return start, today, match

        resolved = self.agenda.resolve_date(text, reference=self.agenda._now())
        if resolved:
            return resolved.value, resolved.value, None
        if default_all_time:
            return date(1970, 1, 1), today, None
        return today, today, None

    @staticmethod
    def _looks_like_completed_query(text: str) -> bool:
        n = canon(text)
        markers = (
            "qu est ce que j ai fait",
            "qu ai je fait",
            "qu est ce que jai fait",
            "j ai fait quoi",
            "jai fait quoi",
            "quoi comme taches",
            "taches terminees",
            "taches que j ai faites",
            "taches que jai faites",
            "quelles taches j ai faites",
            "quelles taches ai je faites",
            "quelles taches jai faites",
            "ce que j ai fait",
            "ce que jai fait",
        )
        return any(marker in n for marker in markers)

    @staticmethod
    def _looks_like_timeline_query(text: str) -> bool:
        n = canon(text)
        return "timeline" in n or "chronologie de ma journee" in n

    def _query_subject(self, text: str) -> str:
        raw = str(text or "").strip()
        if ":" in raw:
            return raw.split(":", 1)[1].strip()
        n = canon(raw)
        if "combien de fois" in n or "quand est ce" in n:
            match = re.search(r"j\s*[’']?\s*ai\s+(.+)", raw, flags=re.I)
            if match:
                value = match.group(1)
                value = re.split(r"\s+(?:sur|dans|depuis|ces)\s+", value, flags=re.I)[0]
                return value.strip(" ?")
        return ""

    def _friendly_completed_detail(self, row: dict[str, Any], today: date) -> str:
        prefix = self._friendly_day(row["day"], today)
        if row.get("kind") == "todo":
            return f"{prefix}, tu as terminé « {row['title']} »"
        return f"{prefix}, {self._as_user_action(row['title'])}"

    def _format_completed_query(self, start: date, end: date, query: str = "") -> str:
        rows = self.completed_rows(start.isoformat(), end.isoformat(), query)
        today = self.agenda._now().date()

        if start == end:
            label = self._friendly_day(start.isoformat(), today)
            period = label
        else:
            period = f"du {start:%d/%m/%Y} au {end:%d/%m/%Y}"

        if not rows:
            if query.strip():
                return f"Je n'ai rien retrouvé pour « {query.strip()} » {period}."
            return f"Je n'ai rien de noté comme fait {period}."

        if query.strip():
            count = len(rows)
            intro = "Je l'ai retrouvé une fois" if count == 1 else f"Je l'ai retrouvé {count} fois"
            details = self._natural_list(
                [
                    self._friendly_completed_detail(row, today)
                    for row in rows[-10:]
                ]
            )
            suffix = " Je te montre seulement les 10 plus récentes." if count > 10 else ""
            return f"{intro} {period} : {details}.{suffix}"

        intro = (
            f"{period.capitalize()}, tu as fait une chose :"
            if len(rows) == 1
            else f"{period.capitalize()}, tu as fait {len(rows)} choses :"
        )
        details = "\n".join(f"- {row['title']}" for row in rows[-100:])
        suffix = "\nJe te montre les 100 plus récentes." if len(rows) > 100 else ""
        return f"{intro}\n{details}{suffix}"

    def _format_timeline_query(self, start: date, end: date, query: str = "") -> str:
        if start == end and not query.strip():
            return self.day_summary(start)

        rows = self.timeline_rows(start.isoformat(), end.isoformat(), query)
        if not rows:
            return "Je n'ai rien retrouvé dans ta Timeline sur cette période."
        labels = {
            "todo": "tâche",
            "appointment": "rendez-vous",
            "event": "événement",
            "action": "fait",
            "mood": "ressenti",
        }
        lines = []
        for row in rows[-100:]:
            time_part = f" {row['start_time']}" if row.get("start_time") else ""
            lines.append(
                f"- {row['day']}{time_part} · {labels.get(row['kind'], row['kind'])} · {row['title']}"
            )
        suffix = "\nJe te montre les 100 plus récentes." if len(rows) > 100 else ""
        return "Ta Timeline :\n" + "\n".join(lines) + suffix

    # =========================================================
    # MAIN HANDLER
    # =========================================================

    def handle(self, text: str) -> str | None:
        self.rollover()
        raw = str(text or "").strip()
        n = canon(raw)
        today = self.agenda._now().date()

        # Deletion kept for backward compatibility with V10.1.
        match = re.fullmatch(r"(?:journal|timeline)\s+supprimer\s+(?:j-)?(\d+)", n)
        if match:
            ident = int(match.group(1))
            with self.agenda._connect() as db:
                cursor = db.execute(
                    "DELETE FROM agenda_items WHERE id=? AND kind IN ('action','mood')",
                    (ident,),
                )
                if not cursor.rowcount and self._legacy_table_exists():
                    # A V10.1 J-id may have been migrated to a different agenda id.
                    rows = db.execute(
                        "SELECT id,metadata_json FROM agenda_items WHERE kind IN ('action','mood')"
                    ).fetchall()
                    for row in rows:
                        try:
                            metadata = json.loads(row["metadata_json"] or "{}")
                        except Exception:
                            metadata = {}
                        if int(metadata.get("legacy_life_event_id", -1)) == ident:
                            cursor = db.execute("DELETE FROM agenda_items WHERE id=?", (row["id"],))
                            break
            return "C'est supprimé de ta Timeline." if cursor.rowcount else "Je n'ai pas retrouvé cet élément."

        # Questions about what was actually done must win over Agenda queries.
        if self._looks_like_completed_query(raw):
            try:
                start, end, _ = self._period(raw)
            except ValueError as exc:
                return str(exc)
            return self._format_completed_query(start, end)

        # Explicit Timeline query = planned + completed + appointments + events.
        if self._looks_like_timeline_query(raw):
            try:
                start, end, _ = self._period(raw)
            except ValueError as exc:
                return str(exc)
            query = raw.split(":", 1)[1].strip() if ":" in raw else ""
            return self._format_timeline_query(start, end, query)

        # Explicit mood.
        if n.startswith("humeur ") or n.startswith("humeur:") or n.startswith("humeur :"):
            payload = raw.split(":", 1)[1].strip() if ":" in raw else re.sub(r"^humeur\s+", "", raw, flags=re.I).strip()
            _, created = self.add(payload, today.isoformat(), "mood", raw)
            if not created:
                return "Oui, je l'avais déjà gardé pour aujourd'hui."
            return f"Je vois : {payload}. Je garde ça comme ton ressenti d'aujourd'hui."

        # Explicit legacy journal syntax.
        if re.match(r"^journal\s*:", raw, flags=re.I):
            resolved = self.agenda.resolve_date(raw, reference=self.agenda._now())
            day = resolved.value if resolved else today
            if day > today:
                return "Cette date est future : ajoute plutôt une tâche ou un rendez-vous à ta Timeline."
            payload = raw.split(":", 1)[1].strip()
            parts = self._split_explicit_journal(payload)
            return self._record_actions(parts, day, raw)

        # Natural completed statement: accepts j'ai / jai / j ai and inherits the
        # verb across an object list ("nettoyé X, Y, Z").
        payload = self._completed_payload(raw)
        if payload is not None:
            resolved = self.agenda.resolve_date(raw, reference=self.agenda._now())
            day = resolved.value if resolved else today
            if day > today:
                return "Cette date est future : je la traiterais plutôt comme quelque chose à prévoir."
            parts = self._split_completed_payload(payload)
            return self._record_actions(parts, day, raw)

        # Legacy journal search/count/date query.
        if n.startswith("journal") or "combien de fois" in n or "quand est ce que" in n:
            try:
                start, end, match = self._period(
                    raw,
                    default_all_time=(
                        n == "journal"
                        or "combien de fois" in n
                        or "quand est ce" in n
                    ),
                )
            except ValueError as exc:
                return str(exc)
            query = self._query_subject(raw)
            if n.startswith("journal") and not query:
                rows = self.rows(start.isoformat(), end.isoformat(), "")
                if not rows:
                    return "Je n'ai rien retrouvé dans ta Timeline sur cette période."
                details = "\n".join(
                    f"- {self._friendly_day(row['day'], today)} : {row['title']}"
                    for row in rows[-100:]
                )
                return f"J'ai retrouvé {len(rows)} élément{'s' if len(rows) > 1 else ''} :\n{details}"
            return self._format_completed_query(start, end, query)

        return None

    def _record_actions(self, parts: list[str], day: date, source: str) -> str:
        today = self.agenda._now().date()
        recorded: list[str] = []
        duplicates: list[str] = []
        completed_now: list[str] = []

        for part in parts:
            action = str(part or "").strip(" .")
            if not action:
                continue

            # If a matching pending TODO exists today, close it instead of
            # creating a second record. The TODO itself remains the timeline row.
            completion = None
            if day == today:
                try:
                    completion = self.agenda.complete_todo("c'est fait pour " + action)
                except Exception:
                    completion = None
            if completion and "est fait" in completion:
                completed_now.append(action)
                continue

            if self._same_completed_todo(action, day.isoformat()) is not None:
                duplicates.append(action)
                continue

            _, created = self.add(action, day.isoformat(), "action", source)
            if created:
                recorded.append(action)
            else:
                duplicates.append(action)

        new_items = recorded + completed_now
        answers: list[str] = []
        if new_items:
            friendly = self._natural_list([self._as_user_action(item) for item in new_items])
            answers.append(
                f"D'accord, pour {self._friendly_day(day.isoformat(), today)} : {friendly}."
            )
        if completed_now:
            answers.append(
                "J'ai aussi marqué comme faite "
                + ("la tâche correspondante." if len(completed_now) == 1 else "les tâches correspondantes.")
            )
        if duplicates:
            answers.append(
                "Je l'avais déjà dans ta Timeline, donc je ne l'ai pas compté deux fois."
                if len(duplicates) == 1
                else "Je les avais déjà dans ta Timeline, donc je ne les ai pas comptés deux fois."
            )
        return " ".join(answers) if answers else "D'accord."

    # =========================================================
    # CONVERSATION CONTEXT / NOTIFICATIONS
    # =========================================================

    def context_for(self, message: str) -> str:
        n = canon(message)
        relevant = any(
            marker in n
            for marker in (
                "timeline", "agenda", "programme", "tache", "rdv", "rendez vous",
                "aujourdhui", "demain", "hier", "fait", "termine", "journal",
            )
        )
        if not relevant:
            return "(Timeline non nécessaire pour ce message)"
        resolved = self.agenda.resolve_date(message, reference=self.agenda._now())
        target = resolved.value if resolved else self.agenda._now().date()
        return self.day_summary(target)

    def notifications(self) -> list[str]:
        self.rollover()
        now = self.agenda._now()
        today = now.date()
        notices: list[str] = []
        candidates: list[tuple[str, str]] = []

        if now.hour >= 8:
            candidates.append((f"daily:{today}", self.agenda.program_for_date(today)))

        for item in self.agenda.items_for_date(today, kind="appointment"):
            if item.get("status") != "pending" or not item.get("start_time"):
                continue
            try:
                hour, minute = map(int, item["start_time"].split(":")[:2])
                at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:
                continue
            if timedelta(0) <= at - now <= timedelta(minutes=30):
                candidates.append(
                    (
                        f"rdv:{item['id']}:{today}:{item['start_time']}",
                        f"Rappel : {item['title']} à {item['start_time']}.",
                    )
                )

        with self.agenda._connect() as db:
            for key, message in candidates:
                if db.execute("INSERT OR IGNORE INTO life_notices VALUES(?)", (key,)).rowcount:
                    notices.append(message)
        return notices
