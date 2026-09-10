from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class AgendaDate:
    value: date
    label: str


class PersonalAgenda:
    """Agenda personnel local de Paul.

    V6.4 sépare explicitement :
    - les tâches à accomplir (todo) ;
    - les rendez-vous (appointment) ;
    - les événements notables planifiés (event).

    La mémoire personnelle reste une mémoire de vie. L'agenda décrit ce qui est
    prévu / à faire. Les réponses de Paul ne sont jamais importées ici.
    """

    SCHEMA_VERSION = 4

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

    TODO_MARKERS = (
        "il faut que je fasse",
        "je dois faire",
        "je dois",
        "j ai a faire",
        "j ai des choses a faire",
        "j ai des trucs a faire",
        "j ai des taches a faire",
        "ma liste de choses a faire",
        "ma liste de taches",
        "todo",
        "to do",
        "ajoute a ma liste",
        "ajoute a ma todo",
        "note que je dois",
    )

    APPOINTMENT_MARKERS = (
        "rendez vous",
        "rdv",
    )

    EVENT_MARKERS = (
        "anniversaire",
        "concert",
        "livraison",
        "retour",
        "revient",
        "rentre",
        "arrive",
        "arrivee",
        "depart",
        "part en voyage",
        "vacances",
        "voyage jusqu",
        "match",
        "fete",
        "vol ",
        "train ",
    )

    PROGRAM_MARKERS = (
        "programme",
        "planning",
        "j ai quoi",
        "qu est ce que j ai de prevu",
        "qu est ce qui est prevu",
        "quoi de prevu",
        "ma journee",
        "mon agenda",
        "donne moi mon programme",
        "affiche mon programme",
        "rappelle moi mon programme",
        "qu est ce que je fais",
    )

    TODO_QUERY_MARKERS = (
        "mes taches",
        "mes taches a faire",
        "ma todo",
        "ma to do",
        "qu est ce que j ai a faire",
        "qu est ce qu il me reste a faire",
        "que dois je faire",
        "ce que je dois faire",
        "liste de ce que j ai a faire",
        "rappelle moi ce que j ai a faire",
    )

    APPOINTMENT_QUERY_MARKERS = (
        "mes rendez vous",
        "mes rdv",
        "quel rendez vous",
        "quels rendez vous",
        "quel rdv",
        "quels rdv",
    )

    COMPLETION_MARKERS = (
        "c est fait",
        "je l ai fait",
        "j ai fait",
        "j ai termine",
        "j ai fini",
        "marque comme fait",
        "marque comme faite",
        "marque comme terminee",
        "marque comme termine",
    )

    def __init__(
        self,
        db_path: str | Path,
        *,
        personal_memory_provider: Callable[[], Any] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.personal_memory_provider = personal_memory_provider
        self.now_provider = now_provider
        self._last_view: tuple[str, date] | None = None
        self._ensure_schema()
        self._deduplicate_items()

    # =========================================================
    # BASIC HELPERS
    # =========================================================

    def _now(self) -> datetime:
        if self.now_provider is not None:
            value = self.now_provider()
        else:
            value = datetime.now().astimezone()
        if value.tzinfo is None:
            return value.astimezone()
        return value

    @staticmethod
    def _clean(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _ascii(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        return "".join(char for char in text if not unicodedata.combining(char))

    @classmethod
    def normalize(cls, value: Any) -> str:
        text = cls._ascii(cls._clean(value))
        replacements = (
            (r"\baujourdhui\b", "aujourd hui"),
            (r"\baujd\b", "aujourd hui"),
            (r"\bajd\b", "aujourd hui"),
            (r"\bjai\b", "j ai"),
            (r"\bjavais\b", "j avais"),
            (r"\bjsuis\b", "je suis"),
            (r"\bcest\b", "c est"),
            (r"\bquest\b", "qu est"),
            (r"\bjusqua\b", "jusqu a"),
            (r"\bsamdi\b", "samedi"),
            (r"\baujoudhui\b", "aujourd hui"),
        )
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    @classmethod
    def _tokens(cls, value: Any) -> set[str]:
        ignored = {
            "avec", "dans", "pour", "faire", "fait", "faite", "fais",
            "j", "je", "ai", "le", "la", "les", "un", "une", "des",
            "de", "du", "au", "aux", "a", "et", "est", "c", "que",
            "mon", "ma", "mes", "comme", "termine", "terminee", "fini",
        }
        return {
            token
            for token in cls.normalize(value).split()
            if len(token) >= 2 and token not in ignored
        }

    @classmethod
    def _question_like(cls, message: str) -> bool:
        n = cls.normalize(message)
        return n.startswith(
            (
                "qu est ce",
                "est ce",
                "quoi ",
                "quand ",
                "ou ",
                "comment ",
                "quel ",
                "quelle ",
                "quels ",
                "quelles ",
                "qui ",
                "que dois je",
            )
        ) or str(message or "").strip().endswith("?")


    # =========================================================
    # AGENDA IDENTITY / DEDUP V6.4.2.1
    # =========================================================

    @classmethod
    def _canonical_identity(cls, value: Any) -> str:
        """Identité stable pour comparer deux formulations équivalentes."""
        n = cls.normalize(value)
        # l'aéroport -> l aeroport ; laeroport -> laeroport.
        # On compacte les élisions françaises pour que les deux soient égales.
        n = re.sub(
            r"\b([ldjtmnsc])\s+([aeiouyh])",
            r"\1\2",
            n,
        )
        return " ".join(n.split())

    @staticmethod
    def _display_quality(value: str) -> tuple[int, int]:
        raw = str(value or "")
        score = 0
        if "'" in raw or "’" in raw:
            score += 3
        if any(ch in raw for ch in "àâäéèêëîïôöùûüç"):
            score += 2
        if any(ch.isupper() for ch in raw[1:]):
            score += 1
        return score, len(raw)

    def _deduplicate_items(self) -> None:
        """Masque les doublons historiques sans perdre l'entrée la plus propre."""
        try:
            with self._connect() as db:
                rows = db.execute(
                    """
                    SELECT * FROM agenda_items
                    WHERE status='pending'
                    ORDER BY id
                    """
                ).fetchall()

                groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
                for row in rows:
                    item = dict(row)
                    key = (
                        str(item.get("kind", "")),
                        str(item.get("due_date", "")),
                        str(item.get("start_time") or ""),
                        self._canonical_identity(item.get("title", "")),
                    )
                    groups.setdefault(key, []).append(item)

                now = self._now().isoformat()
                for key, items in groups.items():
                    if not key[3]:
                        continue
                    best = max(
                        items,
                        key=lambda item: self._display_quality(
                            str(item.get("title", ""))
                        ),
                    )
                    best_id = int(best["id"])
                    best_title = self._clean(best.get("title", ""))
                    db.execute(
                        """
                        UPDATE agenda_items
                        SET title=?, normalized_title=?, updated_at=?
                        WHERE id=?
                        """,
                        (best_title, key[3], now, best_id),
                    )
                    for item in items:
                        item_id = int(item["id"])
                        if item_id == best_id:
                            continue
                        db.execute(
                            """
                            UPDATE agenda_items
                            SET status='cancelled', updated_at=?
                            WHERE id=?
                            """,
                            (now, item_id),
                        )
        except Exception:
            # La déduplication ne doit jamais empêcher Paul de démarrer.
            return

    def _existing_equivalent_item(
        self,
        *,
        kind: str,
        title: str,
        due_date: date,
        start_time: str | None,
    ) -> dict[str, Any] | None:
        wanted = self._canonical_identity(title)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM agenda_items
                WHERE kind=? AND due_date=?
                  AND COALESCE(start_time, '') = COALESCE(?, '')
                  AND status != 'cancelled'
                ORDER BY id
                """,
                (kind, due_date.isoformat(), start_time),
            ).fetchall()
        for row in rows:
            item = dict(row)
            if self._canonical_identity(item.get("title", "")) == wanted:
                return item
        return None

    @staticmethod
    def _memory_people(item: dict[str, Any]) -> list[str]:
        raw = item.get("people")
        if isinstance(raw, list):
            return [str(v).strip() for v in raw if str(v).strip()]
        raw = item.get("people_json")
        if isinstance(raw, str) and raw.strip():
            try:
                value = json.loads(raw)
                if isinstance(value, list):
                    return [str(v).strip() for v in value if str(v).strip()]
            except Exception:
                pass
        return []

    def _memory_notable_label(
        self,
        item: dict[str, Any],
        wanted: str,
    ) -> str:
        content = self._clean(item.get("content", ""))
        n = self.normalize(content)
        start = str(item.get("event_start") or "")[:10]
        end = str(item.get("event_end") or "")[:10]
        people = self._memory_people(item)
        person = people[0] if people else ""

        if end == wanted and start and start != end and "voyage" in n:
            return (
                f"Fin du voyage de {person}"
                if person
                else "Fin d'un voyage personnel"
            )
        if start == wanted and "voyage" in n and person:
            return f"Départ en voyage de {person}"
        return content

    @classmethod
    def _unique_labels(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = cls._canonical_identity(value)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    def handle_decision(
        self,
        message: str,
        decision: Any,
    ) -> str | None:
        """Exécute une décision centrale sans refaire de classification."""
        if decision is None:
            return None
        if str(getattr(decision, "owner", "")) != "agenda":
            return None
        try:
            confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.50:
            return None

        class Adapter:
            pass

        adapted = Adapter()
        adapted.agenda_requested = True
        adapted.agenda_confidence = max(0.60, confidence)
        adapted.agenda_action = str(getattr(decision, "action", "query") or "query")
        adapted.agenda_view = str(getattr(decision, "view", "program") or "program")
        if adapted.agenda_view == "none":
            adapted.agenda_view = "program"
        adapted.agenda_target = str(getattr(decision, "target", "") or "")
        adapted.agenda_subject = str(getattr(decision, "subject", "") or "")
        adapted.agenda_field = str(getattr(decision, "field", "none") or "none")
        adapted.agenda_time = ""

        return self.handle_understanding(message, adapted)

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
                CREATE TABLE IF NOT EXISTS agenda_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    source_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            # SQLite n'autorise pas toujours une expression dans UNIQUE selon
            # la version : on ajoute un index fonctionnel séparé si possible.
            # Si la table ci-dessus existe déjà, ce bloc est sans effet.
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_agenda_due ON agenda_items(due_date, status, kind)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_agenda_title ON agenda_items(normalized_title)"
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS agenda_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            db.execute(
                "INSERT OR REPLACE INTO agenda_meta(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )

    # =========================================================
    # DATE / TIME PARSING
    # =========================================================

    @classmethod
    def resolve_date(
        cls,
        message: str,
        *,
        reference: datetime | None = None,
    ) -> AgendaDate | None:
        ref = reference or datetime.now().astimezone()
        today = ref.date()
        n = cls.normalize(message)

        # Explicit numeric date: 15/09, 15/09/2026, 15-09-2026.
        m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", n)
        if m:
            day = int(m.group(1))
            month = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else today.year
            if year < 100:
                year += 2000
            try:
                result = date(year, month, day)
                return AgendaDate(result, result.strftime("%d/%m/%Y"))
            except ValueError:
                pass

        # Written date: 15 septembre [2026].
        month_names = "|".join(cls.MONTHS)
        m = re.search(
            rf"\b(\d{{1,2}})\s+({month_names})(?:\s+(\d{{4}}))?\b",
            n,
        )
        if m:
            day = int(m.group(1))
            month = cls.MONTHS[m.group(2)]
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                result = date(year, month, day)
                if not m.group(3) and result < today - timedelta(days=1):
                    result = date(year + 1, month, day)
                return AgendaDate(result, result.strftime("%d/%m/%Y"))
            except ValueError:
                pass

        m = re.search(r"\bdans\s+(\d{1,3})\s+jours?\b", n)
        if m:
            delta = int(m.group(1))
            result = today + timedelta(days=delta)
            return AgendaDate(result, f"dans {delta} jour" + ("s" if delta != 1 else ""))

        if "apres demain" in n:
            return AgendaDate(today + timedelta(days=2), "après-demain")
        if "demain" in n:
            return AgendaDate(today + timedelta(days=1), "demain")
        if "aujourd hui" in n or re.search(r"\bauj\b", n):
            return AgendaDate(today, "aujourd'hui")

        for name, weekday in cls.WEEKDAYS.items():
            if not re.search(rf"\b{name}\b", n):
                continue
            delta = (weekday - today.weekday()) % 7
            if f"{name} prochain" in n and delta == 0:
                delta = 7
            result = today + timedelta(days=delta)
            return AgendaDate(result, name)

        return None

    @classmethod
    def resolve_time(cls, message: str) -> str | None:
        n = cls.normalize(message)
        # 15h, 15h30, 15:30. Exclut les années 2026, etc.
        m = re.search(r"(?<!\d)([01]?\d|2[0-3])\s*h\s*([0-5]?\d)?(?!\d)", n)
        if not m:
            m = re.search(r"(?<!\d)([01]?\d|2[0-3])\s*[:]\s*([0-5]\d)(?!\d)", str(message or ""))
        if not m:
            return None
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        return f"{hour:02d}:{minute:02d}"

    def _target_date(self, message: str) -> AgendaDate:
        resolved = self.resolve_date(message, reference=self._now())
        if resolved is not None:
            return resolved
        return AgendaDate(self._now().date(), "aujourd'hui")

    @classmethod
    def _strip_date_time_words(cls, text: str) -> str:
        value = cls._clean(text)
        # Enlève seulement les marqueurs les plus fréquents de la description.
        patterns = (
            r"\baujourd['’ ]?hui\b",
            r"\baujourdhui\b",
            r"\bdemain\b",
            r"\bapres[- ]?demain\b",
            r"\bdans\s+\d{1,3}\s+jours?\b",
            r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\s+prochain)?\b",
            r"\ble\s+\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
            r"\b\d{1,2}\s+(?:janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre)(?:\s+\d{4})?\b",
            r"\b(?:a|à)\s+([01]?\d|2[0-3])\s*h\s*[0-5]?\d?\b",
            r"\b(?:a|à)\s+([01]?\d|2[0-3]):[0-5]\d\b",
        )
        for pattern in patterns:
            value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
        return cls._clean(value).strip(" ,;:-")

    # =========================================================
    # ITEM STORAGE
    # =========================================================

    def _add_item(
        self,
        *,
        kind: str,
        title: str,
        due_date: date,
        start_time: str | None,
        source_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[int, bool]:
        title = self._clean(title).strip(" .,:;-")
        if not title:
            raise ValueError("Titre d'agenda vide")
        normalized = self._canonical_identity(title)
        now = self._now().isoformat()

        equivalent = self._existing_equivalent_item(
            kind=kind,
            title=title,
            due_date=due_date,
            start_time=start_time,
        )
        if equivalent is not None:
            existing_id = int(equivalent["id"])
            existing_title = str(equivalent.get("title", "") or "")
            # Garde la formulation la plus lisible sans créer un doublon.
            if self._display_quality(title) > self._display_quality(existing_title):
                with self._connect() as db:
                    db.execute(
                        """
                        UPDATE agenda_items
                        SET title=?, normalized_title=?, source_text=?, updated_at=?
                        WHERE id=?
                        """,
                        (title, normalized, self._clean(source_text), now, existing_id),
                    )
            return existing_id, False

        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO agenda_items(
                    kind, title, normalized_title, due_date, start_time,
                    status, source_text, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    kind,
                    title,
                    normalized,
                    due_date.isoformat(),
                    start_time,
                    self._clean(source_text),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid), True

    def items_for_date(
        self,
        target: date,
        *,
        kind: str | None = None,
        status: str = "pending",
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM agenda_items WHERE due_date=?"
        params: list[Any] = [target.isoformat()]
        if kind is not None:
            sql += " AND kind=?"
            params.append(kind)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY CASE WHEN start_time IS NULL THEN 1 ELSE 0 END, start_time, id"
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def overdue_todos(self) -> list[dict[str, Any]]:
        today = self._now().date().isoformat()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM agenda_items
                WHERE kind='todo' AND status='pending' AND due_date < ?
                ORDER BY due_date, id
                LIMIT 20
                """,
                (today,),
            ).fetchall()
        return [dict(row) for row in rows]

    # =========================================================
    # NATURAL CAPTURE
    # =========================================================

    @classmethod
    def looks_like_todo_capture(cls, message: str) -> bool:
        if cls._question_like(message):
            return False
        n = cls.normalize(message)
        if "je dois te " in n or "je dois que tu " in n:
            return False
        return any(marker in n for marker in cls.TODO_MARKERS)

    @classmethod
    def looks_like_appointment_capture(cls, message: str) -> bool:
        if cls._question_like(message):
            return False
        n = cls.normalize(message)
        return any(re.search(rf"\b{re.escape(marker)}\b", n) for marker in cls.APPOINTMENT_MARKERS)

    @classmethod
    def looks_like_event_capture(cls, message: str) -> bool:
        if cls._question_like(message):
            return False
        n = cls.normalize(message)
        has_date = cls.resolve_date(message) is not None
        if not has_date:
            return False
        return any(marker in n for marker in cls.EVENT_MARKERS)

    @classmethod
    def _todo_payload(cls, message: str) -> str:
        raw = str(message or "").strip()
        if ":" in raw:
            before, after = raw.split(":", 1)
            if any(marker in cls.normalize(before) for marker in cls.TODO_MARKERS):
                return after.strip()

        patterns = (
            r"il\s+faut\s+que\s+je\s+fasse\s+(.+)$",
            r"je\s+dois\s+faire\s+(.+)$",
            r"je\s+dois\s+(.+)$",
            r"j['’ ]?ai\s+(?:des\s+)?(?:choses|trucs|t[aâ]ches?)\s+[aà]\s+faire\s+(.+)$",
            r"(?:todo|to[- ]?do)\s*[:\-]?\s*(.+)$",
            r"(?:ajoute\s+)(.+?)\s+(?:a|à)\s+ma\s+(?:liste|todo)(?:\s+.*)?$",
            r"(?:note\s+que\s+je\s+dois)\s+(.+)$",
        )
        for pattern in patterns:
            m = re.search(pattern, raw, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()

        # Fallback normalisé pour les formes "jai".
        n = cls.normalize(raw)
        for marker in cls.TODO_MARKERS:
            pos = n.find(marker)
            if pos >= 0:
                return n[pos + len(marker):].strip(" :-")
        return raw

    @classmethod
    def _split_todos(cls, payload: str) -> list[str]:
        value = str(payload or "").strip()
        value = re.sub(r"\n\s*[-*•]\s*", ";", value)
        parts = [part.strip() for part in re.split(r"[;,]+", value) if part.strip()]
        if len(parts) == 1 and " et " in cls.normalize(parts[0]):
            # Pour une phrase de liste sans virgule : "courses et appeler X".
            raw_parts = re.split(r"\s+et\s+", parts[0], flags=re.IGNORECASE)
            if 1 < len(raw_parts) <= 5:
                parts = [part.strip() for part in raw_parts if part.strip()]
        result: list[str] = []
        for part in parts:
            cleaned = cls._strip_date_time_words(part)
            cleaned = re.sub(r"^(?:et|puis)\s+", "", cleaned, flags=re.IGNORECASE)
            cleaned = cls._clean(cleaned).strip(" .,:;-")
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result[:30]

    def capture_todos(self, message: str) -> str | None:
        if not self.looks_like_todo_capture(message):
            return None
        target = self._target_date(message)
        titles = self._split_todos(self._todo_payload(message))
        if not titles:
            return "Je vois que tu veux ajouter des tâches, mais je n'ai pas identifié lesquelles."

        added: list[str] = []
        existing: list[str] = []
        for title in titles:
            _, created = self._add_item(
                kind="todo",
                title=title,
                due_date=target.value,
                start_time=None,
                source_text=message,
            )
            (added if created else existing).append(title)

        self._last_view = ("todo", target.value)
        if added:
            return (
                f"C'est noté pour {target.label} : {len(added)} tâche"
                + ("s" if len(added) > 1 else "")
                + " — "
                + "; ".join(added)
                + "."
            )
        return f"Ces tâches étaient déjà notées pour {target.label}."

    @classmethod
    def _appointment_title(cls, message: str) -> str:
        raw = str(message or "").strip()
        raw = re.sub(
            r"^.*?\b(?:rendez[- ]?vous|rdv)\b\s*(?:avec|chez|pour)?\s*",
            "",
            raw,
            count=1,
            flags=re.IGNORECASE,
        )
        title = cls._strip_date_time_words(raw)
        title = re.sub(r"^(?:avec|chez|pour)\s+", "", title, flags=re.IGNORECASE)
        title = cls._clean(title).strip(" .,:;-")
        return title or "rendez-vous"

    def capture_appointment(self, message: str) -> str | None:
        if not self.looks_like_appointment_capture(message):
            return None
        target = self._target_date(message)
        start_time = self.resolve_time(message)
        title = self._appointment_title(message)
        _, created = self._add_item(
            kind="appointment",
            title=title,
            due_date=target.value,
            start_time=start_time,
            source_text=message,
        )
        self._last_view = ("appointment", target.value)
        when = target.label + (f" à {start_time}" if start_time else "")
        if created:
            return f"Rendez-vous noté pour {when} : {title}."
        return f"Ce rendez-vous est déjà noté pour {when}."

    def capture_event(self, message: str) -> str | None:
        if not self.looks_like_event_capture(message):
            return None
        target = self._target_date(message)
        start_time = self.resolve_time(message)
        title = self._strip_date_time_words(message)
        title = re.sub(r"^(?:note|rappelle moi que)\s+", "", title, flags=re.IGNORECASE)
        title = self._clean(title).strip(" .,:;-")
        if not title:
            return None
        _, created = self._add_item(
            kind="event",
            title=title,
            due_date=target.value,
            start_time=start_time,
            source_text=message,
        )

        # Un événement personnel planifié reste aussi un fait de vie utile à
        # Personal Memory V2. Les tâches et rendez-vous, eux, restent dans
        # l'agenda pour éviter de polluer la mémoire épisodique.
        if created and self.personal_memory_provider is not None:
            try:
                store = self.personal_memory_provider()
                if store is not None:
                    store.remember_event(
                        message,
                        kind="planned_event",
                        source="user",
                        confidence=0.95,
                    )
            except Exception:
                pass

        self._last_view = ("event", target.value)
        when = target.label + (f" à {start_time}" if start_time else "")
        if created:
            return f"Événement noté pour {when} : {title}."
        return f"Cet événement est déjà noté pour {when}."

    # =========================================================
    # COMPLETION
    # =========================================================

    @classmethod
    def _completion_payload(cls, message: str) -> str | None:
        n = cls.normalize(message)
        if not any(marker in n for marker in cls.COMPLETION_MARKERS):
            return None
        raw = str(message or "").strip()
        patterns = (
            r"(?:c['’ ]?est\s+fait\s+(?:pour\s+)?)\s*(.+)$",
            r"(?:j['’ ]?ai\s+(?:fait|termine|terminé|fini))\s+(.+)$",
            r"(?:marque\s+(.+?)\s+comme\s+(?:fait|faite|termine|terminé|terminee|terminée))$",
        )
        for pattern in patterns:
            m = re.search(pattern, raw, flags=re.IGNORECASE)
            if m:
                return cls._strip_date_time_words(m.group(1)).strip(" .,:;-")
        return None

    def _pending_todos_near(self, target: date) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM agenda_items
                WHERE kind='todo' AND status='pending' AND due_date <= ?
                ORDER BY due_date DESC, id DESC
                LIMIT 50
                """,
                (target.isoformat(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_todo(self, message: str) -> str | None:
        payload = self._completion_payload(message)
        if not payload:
            return None
        target_date = self._target_date(message).value
        candidates = self._pending_todos_near(target_date)
        if not candidates:
            return None

        wanted_tokens = self._tokens(payload)
        wanted_norm = self.normalize(payload)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in candidates:
            title = str(item.get("title", ""))
            title_tokens = self._tokens(title)
            overlap = len(wanted_tokens & title_tokens)
            union = max(1, len(wanted_tokens | title_tokens))
            jaccard = overlap / union
            seq = SequenceMatcher(None, wanted_norm, self.normalize(title)).ratio()
            score = max(jaccard, seq * 0.85)
            if wanted_norm and wanted_norm in self.normalize(title):
                score += 0.35
            ranked.append((score, item))

        ranked.sort(key=lambda row: row[0], reverse=True)
        if not ranked or ranked[0][0] < 0.45:
            return None
        if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] - 0.06 and ranked[1][0] > 0.55:
            return (
                "J'ai trouvé plusieurs tâches possibles : "
                + " / ".join(str(row[1]["title"]) for row in ranked[:3])
                + ". Laquelle est terminée ?"
            )

        item = ranked[0][1]
        now = self._now().isoformat()
        with self._connect() as db:
            db.execute(
                """
                UPDATE agenda_items
                SET status='done', completed_at=?, updated_at=?
                WHERE id=?
                """,
                (now, now, int(item["id"])),
            )
        return f"C'est noté : « {item['title']} » est fait."

    # =========================================================
    # QUERIES / PROGRAM
    # =========================================================

    @classmethod
    def _view_kind(cls, message: str) -> str | None:
        n = cls.normalize(message)
        if any(marker in n for marker in cls.APPOINTMENT_QUERY_MARKERS):
            return "appointment"
        if any(marker in n for marker in cls.TODO_QUERY_MARKERS):
            return "todo"
        if any(marker in n for marker in cls.PROGRAM_MARKERS):
            return "program"
        if n in {"et demain", "demain alors", "et aujourd hui", "et ce soir"}:
            return "followup"
        return None

    @staticmethod
    def _date_label(target: date, today: date) -> str:
        if target == today:
            return "aujourd'hui"
        if target == today + timedelta(days=1):
            return "demain"
        return target.strftime("%d/%m/%Y")

    @staticmethod
    def _format_item(item: dict[str, Any]) -> str:
        title = str(item.get("title", ""))
        time = str(item.get("start_time") or "")
        return (f"{time} — " if time else "") + title

    def _memory_notable_events(self, target: date) -> list[str]:
        provider = self.personal_memory_provider
        if provider is None:
            return []
        try:
            store = provider()
        except Exception:
            return []
        if store is None:
            return []

        # Lecture structurée de la base personnelle : uniquement les bornes de
        # date (début/fin) qui correspondent au jour demandé et qui ressemblent
        # à un événement de calendrier. Cela évite d'afficher chaque anecdote.
        try:
            connect = getattr(store, "_connect")
            row_to_dict = getattr(store, "_row_to_dict")
        except Exception:
            return []

        wanted = target.isoformat()
        try:
            with connect() as db:
                rows = db.execute(
                    """
                    SELECT * FROM personal_events
                    WHERE substr(COALESCE(event_start, ''), 1, 10)=?
                       OR substr(COALESCE(event_end, ''), 1, 10)=?
                    ORDER BY recorded_at DESC
                    LIMIT 30
                    """,
                    (wanted, wanted),
                ).fetchall()
        except Exception:
            return []

        result: list[str] = []
        for row in rows:
            try:
                item = row_to_dict(row)
            except Exception:
                item = dict(row)
            content = self._clean(item.get("content", ""))
            n = self.normalize(content)
            if not content:
                continue
            if not any(marker in n for marker in self.EVENT_MARKERS):
                continue
            label = self._memory_notable_label(item, wanted)
            if label:
                result.append(label)
        return self._unique_labels(result)[:5]

    def program_for_date(
        self,
        target: date,
        *,
        view: str = "program",
    ) -> str:
        todos = self.items_for_date(target, kind="todo")
        appointments = self.items_for_date(target, kind="appointment")
        events = self.items_for_date(target, kind="event")
        memory_events = self._memory_notable_events(target) if view == "program" else []

        today = self._now().date()
        label = self._date_label(target, today)
        lines = [f"Programme pour {label} :"] if view == "program" else []

        if view in {"program", "appointment"}:
            if appointments:
                lines.append("Rendez-vous :")
                lines.extend(f"- {self._format_item(item)}" for item in appointments)
            elif view == "appointment":
                lines.append(f"Aucun rendez-vous noté pour {label}.")

        if view in {"program", "todo"}:
            if todos:
                lines.append("À faire :")
                lines.extend(f"- {self._format_item(item)}" for item in todos)
            elif view == "todo":
                lines.append(f"Aucune tâche à faire notée pour {label}.")

        if view == "program":
            combined_events = [self._format_item(item) for item in events]
            combined_events.extend(event for event in memory_events if event not in combined_events)
            if combined_events:
                lines.append("Événements notables :")
                lines.extend(f"- {event}" for event in combined_events[:8])

            if target == today:
                overdue = self.overdue_todos()
                if overdue:
                    lines.append("En retard :")
                    lines.extend(
                        f"- {item['title']} ({item['due_date']})"
                        for item in overdue[:10]
                    )

        if view == "program" and len(lines) == 1:
            lines.append("Rien de planifié pour le moment.")

        return "\n".join(lines)

    # =========================================================
    # NATURAL AGENDA PROPERTY QUERIES V6.4.1
    # =========================================================

    @classmethod
    def _agenda_property_kind(cls, message: str) -> str | None:
        # Détecte les questions naturelles portant sur l'agenda personnel.
        if not cls._question_like(message):
            return None

        n = cls.normalize(message)

        schedule_anchor = any(
            marker in n
            for marker in (
                "je dois",
                "dois je",
                "j ai rendez vous",
                "j ai rdv",
                "mon rendez vous",
                "mon rdv",
                "mes rendez vous",
                "mes rdv",
                "j ai de prevu",
                "je vais",
                "il faut que j aille",
                "il faut que je sois",
                "ou je dois",
                "ou dois je",
                "quand je dois",
                "quand dois je",
            )
        )

        if not schedule_anchor:
            return None

        if n.startswith(
            (
                "ou ",
                "a quel endroit ",
                "a quelle adresse ",
                "quel endroit ",
                "quelle adresse ",
            )
        ):
            return "where"

        if n.startswith(
            (
                "a quelle heure ",
                "quelle heure ",
                "quand ",
            )
        ):
            return "when"

        return None

    @classmethod
    def _extract_location_from_item(
        cls,
        item: dict[str, Any],
    ) -> str | None:
        # Extrait prudemment un lieu explicite d'une entrée d'agenda.
        candidates = [
            str(item.get("title", "") or ""),
            str(item.get("source_text", "") or ""),
        ]

        for raw in candidates:
            raw = cls._clean(raw)
            if not raw:
                continue

            airport = re.search(
                r"\b(?:a|à)\s+(?:l['’]?\s*)?(?:aeroport|aéroport)\b",
                raw,
                flags=re.IGNORECASE,
            )
            if airport:
                return "à l'aéroport"

            m = re.search(
                r"\bchez\s+([^,;.!?]+)",
                raw,
                flags=re.IGNORECASE,
            )
            if m:
                value = cls._clean(m.group(1)).strip(" ,;:-")
                if value:
                    return "chez " + value

            m = re.search(
                r"\b(au|aux)\s+([^,;.!?]+)",
                raw,
                flags=re.IGNORECASE,
            )
            if m:
                value = cls._clean(m.group(2)).strip(" ,;:-")
                if value:
                    return m.group(1).lower() + " " + value

            m = re.search(
                r"\b(?:a|à)\s+([^,;.!?]+)",
                raw,
                flags=re.IGNORECASE,
            )
            if m:
                value = cls._clean(m.group(1)).strip(" ,;:-")
                normalized = cls.normalize(value)
                if (
                    value
                    and not re.fullmatch(
                        r"\d{1,2}(?:h\d{0,2}|:\d{2})?",
                        normalized,
                    )
                ):
                    return "à " + value

        return None

    def _agenda_property_answer(
        self,
        message: str,
    ) -> str | None:
        # Répond à où/quand depuis agenda.db, sans Researcher.
        kind = self._agenda_property_kind(message)
        if kind is None:
            return None

        resolved = self.resolve_date(
            message,
            reference=self._now(),
        )
        target = (
            resolved.value
            if resolved is not None
            else self._now().date()
        )
        today = self._now().date()
        label = self._date_label(target, today)

        items = self.items_for_date(
            target,
            status="pending",
        )

        if not items:
            return f"Tu n'as rien de noté dans ton agenda pour {label}."

        if kind == "where":
            locations: list[str] = []
            for item in items:
                location = self._extract_location_from_item(item)
                if location and location not in locations:
                    locations.append(location)

            self._last_view = ("program", target)

            if len(locations) == 1:
                return (
                    f"{label.capitalize()}, tu dois aller "
                    f"{locations[0]}."
                )

            if len(locations) > 1:
                return (
                    f"Pour {label}, tu as plusieurs lieux prévus : "
                    + "; ".join(locations)
                    + "."
                )

            titles = [
                self._format_item(item)
                for item in items
            ]
            return (
                f"Pour {label}, tu as "
                + "; ".join(titles[:5])
                + " de noté, mais aucun lieu précis n'est indiqué."
            )

        if kind == "when":
            timed = [
                item
                for item in items
                if str(item.get("start_time") or "").strip()
            ]

            self._last_view = ("program", target)

            if len(timed) == 1:
                item = timed[0]
                return (
                    f"{label.capitalize()} à "
                    f"{item['start_time']} : {item['title']}."
                )

            if len(timed) > 1:
                return (
                    f"Pour {label} : "
                    + "; ".join(
                        self._format_item(item)
                        for item in timed[:8]
                    )
                    + "."
                )

            return (
                f"C'est prévu pour {label}, "
                "mais tu n'as pas indiqué d'heure."
            )

        return None

    def query(self, message: str) -> str | None:
        # V6.4.1 : les questions naturelles sur le lieu/l'heure d'une
        # obligation planifiée sont résolues par agenda.db avant le Web.
        property_answer = self._agenda_property_answer(message)
        if property_answer is not None:
            return property_answer

        view = self._view_kind(message)
        if view is None:
            return None

        if view == "followup":
            if self._last_view is None:
                return None
            previous_view, _ = self._last_view
            view = previous_view

        target = self._target_date(message).value
        self._last_view = (view, target)
        return self.program_for_date(target, view=view)


    # =========================================================
    # SEMANTIC AGENDA INTENT V6.4.2
    # =========================================================

    @staticmethod
    def _semantic_value(
        understanding: Any,
        name: str,
        default: Any = None,
    ) -> Any:
        if understanding is None:
            return default
        return getattr(understanding, name, default)

    def _semantic_agenda_owned(
        self,
        understanding: Any,
    ) -> bool:
        if understanding is None:
            return False
        requested = bool(
            self._semantic_value(
                understanding,
                "agenda_requested",
                False,
            )
        )
        try:
            confidence = float(
                self._semantic_value(
                    understanding,
                    "agenda_confidence",
                    0.0,
                )
                or 0.0
            )
        except (TypeError, ValueError):
            confidence = 0.0
        return requested and confidence >= 0.58

    def _semantic_target_date(
        self,
        message: str,
        understanding: Any,
    ) -> tuple[date, str, bool]:
        target_text = self._clean(
            self._semantic_value(
                understanding,
                "agenda_target",
                "",
            )
        )
        resolved = None
        if target_text:
            resolved = self.resolve_date(
                target_text,
                reference=self._now(),
            )
        if resolved is None:
            resolved = self.resolve_date(
                message,
                reference=self._now(),
            )

        today = self._now().date()
        if resolved is None:
            return today, self._date_label(today, today), False
        return (
            resolved.value,
            self._date_label(resolved.value, today),
            True,
        )

    def _semantic_upcoming_items(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        today = self._now().date().isoformat()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM agenda_items
                WHERE status='pending' AND due_date >= ?
                ORDER BY due_date,
                         CASE WHEN start_time IS NULL THEN 1 ELSE 0 END,
                         start_time,
                         id
                LIMIT ?
                """,
                (today, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def _semantic_filter_subject(
        self,
        items: list[dict[str, Any]],
        subject: str,
    ) -> list[dict[str, Any]]:
        wanted = self.normalize(subject)
        if not wanted:
            return items

        generic = {
            "tache",
            "taches",
            "todo",
            "rendez vous",
            "rdv",
            "evenement",
            "evenements",
            "programme",
            "planning",
        }
        if wanted in generic:
            return items

        wanted_tokens = self._tokens(wanted)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in items:
            haystack = " ".join(
                (
                    str(item.get("title", "") or ""),
                    str(item.get("source_text", "") or ""),
                )
            )
            normalized = self.normalize(haystack)
            tokens = self._tokens(normalized)
            overlap = len(wanted_tokens & tokens)
            union = max(1, len(wanted_tokens | tokens))
            score = overlap / union
            if wanted and wanted in normalized:
                score += 0.65
            if normalized and normalized in wanted:
                score += 0.35
            if score > 0:
                ranked.append((score, item))

        ranked.sort(key=lambda row: row[0], reverse=True)
        if not ranked:
            return []
        best = ranked[0][0]
        return [
            item
            for score, item in ranked
            if score >= max(0.18, best - 0.15)
        ][:12]

    def _semantic_location_from_item(
        self,
        item: dict[str, Any],
    ) -> str | None:
        extractor = getattr(
            self,
            "_extract_location_from_item",
            None,
        )
        if callable(extractor):
            try:
                value = extractor(item)
                if value:
                    return str(value)
            except Exception:
                pass

        for raw in (
            str(item.get("title", "") or ""),
            str(item.get("source_text", "") or ""),
        ):
            clean = self._clean(raw)
            if not clean:
                continue
            m = re.search(
                r"\b(?:a|à|au|aux|chez)\s+([^,;.!?]+)",
                clean,
                flags=re.IGNORECASE,
            )
            if m:
                prefix_match = re.search(
                    r"\b(a|à|au|aux|chez)\s+",
                    clean[m.start():],
                    flags=re.IGNORECASE,
                )
                prefix = (
                    prefix_match.group(1).lower()
                    if prefix_match
                    else "à"
                )
                value = self._clean(m.group(1)).strip(" ,;:-")
                if value:
                    return prefix + " " + value
        return None

    def _semantic_event_program(
        self,
        target: date,
    ) -> str:
        today = self._now().date()
        label = self._date_label(target, today)
        events = self.items_for_date(
            target,
            kind="event",
        )
        memory_events = self._memory_notable_events(target)
        values = [
            self._format_item(item)
            for item in events
        ]
        values.extend(
            event
            for event in memory_events
            if event not in values
        )
        self._last_view = ("event", target)
        if values:
            return (
                f"Événements prévus pour {label} :\n- "
                + "\n- ".join(values[:12])
            )

        # On garde les catégories distinctes, mais on signale les autres
        # obligations du jour pour éviter une réponse inutilement vide.
        todos = self.items_for_date(target, kind="todo")
        appointments = self.items_for_date(
            target,
            kind="appointment",
        )
        if todos or appointments:
            extras: list[str] = []
            if appointments:
                extras.append(
                    "Rendez-vous : "
                    + "; ".join(
                        self._format_item(item)
                        for item in appointments[:6]
                    )
                )
            if todos:
                extras.append(
                    "À faire : "
                    + "; ".join(
                        self._format_item(item)
                        for item in todos[:8]
                    )
                )
            return (
                f"Aucun événement notable distinct n'est noté pour {label}. "
                + " ".join(extras)
            )
        return f"Aucun événement notable n'est noté pour {label}."

    def _semantic_query_answer(
        self,
        message: str,
        understanding: Any,
    ) -> str:
        view = str(
            self._semantic_value(
                understanding,
                "agenda_view",
                "program",
            )
            or "program"
        ).strip().lower()
        field = str(
            self._semantic_value(
                understanding,
                "agenda_field",
                "none",
            )
            or "none"
        ).strip().lower()
        subject = self._clean(
            self._semantic_value(
                understanding,
                "agenda_subject",
                "",
            )
        )

        target, label, explicit_target = self._semantic_target_date(
            message,
            understanding,
        )

        if field in {"where", "when", "who"}:
            if explicit_target:
                items = self.items_for_date(
                    target,
                    status="pending",
                )
            else:
                items = self._semantic_upcoming_items()

            filtered = self._semantic_filter_subject(
                items,
                subject,
            )
            if filtered:
                items = filtered

            if not items:
                if explicit_target:
                    return (
                        f"Tu n'as rien de correspondant dans ton agenda "
                        f"pour {label}."
                    )
                return "Je n'ai rien de correspondant dans ton agenda."

            if field == "where":
                locations: list[str] = []
                for item in items:
                    location = self._semantic_location_from_item(item)
                    if location and location not in locations:
                        locations.append(location)
                if len(locations) == 1:
                    return f"Tu dois aller {locations[0]}."
                if locations:
                    return (
                        "Tu as plusieurs lieux prévus : "
                        + "; ".join(locations[:8])
                        + "."
                    )
                return (
                    "J'ai retrouvé ce qui est prévu, mais tu n'as pas "
                    "indiqué le lieu."
                )

            if field == "when":
                timed = [
                    item
                    for item in items
                    if str(item.get("start_time") or "").strip()
                ]
                if len(timed) == 1:
                    item = timed[0]
                    return (
                        f"{item['due_date']} à {item['start_time']} : "
                        f"{item['title']}."
                    )
                if timed:
                    return (
                        "Horaires prévus : "
                        + "; ".join(
                            f"{item['due_date']} {item['start_time']} — "
                            f"{item['title']}"
                            for item in timed[:8]
                        )
                        + "."
                    )
                if explicit_target:
                    return (
                        f"C'est prévu pour {label}, mais tu n'as pas "
                        "indiqué d'heure."
                    )
                if len(items) == 1:
                    return (
                        f"C'est prévu le {items[0]['due_date']}, mais sans "
                        "heure précise."
                    )
                return (
                    "J'ai retrouvé plusieurs éléments, mais aucun n'a "
                    "d'heure précise."
                )

            # who : on ne déduit pas une personne absente. Le titre/source
            # reste la seule preuve, donc on renvoie l'élément plutôt que
            # d'inventer un accompagnant.
            return (
                "Dans ton agenda, j'ai : "
                + "; ".join(
                    self._format_item(item)
                    for item in items[:8]
                )
                + "."
            )

        if view == "todo":
            self._last_view = ("todo", target)
            return self.program_for_date(
                target,
                view="todo",
            )
        if view == "appointment":
            self._last_view = ("appointment", target)
            return self.program_for_date(
                target,
                view="appointment",
            )
        if view == "event":
            return self._semantic_event_program(target)

        self._last_view = ("program", target)
        return self.program_for_date(
            target,
            view="program",
        )

    def _semantic_add(
        self,
        message: str,
        understanding: Any,
    ) -> str:
        view = str(
            self._semantic_value(
                understanding,
                "agenda_view",
                "todo",
            )
            or "todo"
        ).strip().lower()
        subject = self._clean(
            self._semantic_value(
                understanding,
                "agenda_subject",
                "",
            )
        ).strip(" .,:;-")
        if not subject:
            return (
                "J'ai compris que tu veux ajouter quelque chose à ton "
                "agenda, mais il me manque ce que je dois noter."
            )

        target, label, _ = self._semantic_target_date(
            message,
            understanding,
        )
        raw_time = self._clean(
            self._semantic_value(
                understanding,
                "agenda_time",
                "",
            )
        )
        start_time = self.resolve_time(raw_time) if raw_time else None
        if start_time is None:
            start_time = self.resolve_time(message)

        if view == "appointment":
            _, created = self._add_item(
                kind="appointment",
                title=subject,
                due_date=target,
                start_time=start_time,
                source_text=message,
            )
            self._last_view = ("appointment", target)
            when = label + (f" à {start_time}" if start_time else "")
            return (
                f"Rendez-vous noté pour {when} : {subject}."
                if created
                else f"Ce rendez-vous était déjà noté pour {when}."
            )

        if view == "event":
            _, created = self._add_item(
                kind="event",
                title=subject,
                due_date=target,
                start_time=start_time,
                source_text=message,
            )
            self._last_view = ("event", target)
            when = label + (f" à {start_time}" if start_time else "")
            return (
                f"Événement noté pour {when} : {subject}."
                if created
                else f"Cet événement était déjà noté pour {when}."
            )

        _, created = self._add_item(
            kind="todo",
            title=subject,
            due_date=target,
            start_time=start_time,
            source_text=message,
        )
        self._last_view = ("todo", target)
        return (
            f"C'est noté pour {label} : {subject}."
            if created
            else f"Cette tâche était déjà notée pour {label}."
        )

    def _semantic_complete(
        self,
        understanding: Any,
    ) -> str:
        subject = self._clean(
            self._semantic_value(
                understanding,
                "agenda_subject",
                "",
            )
        )
        if not subject:
            return "Quelle tâche est terminée ?"

        candidates = self._pending_todos_near(
            self._now().date()
        )
        matched = self._semantic_filter_subject(
            candidates,
            subject,
        )
        if not matched:
            return (
                f"Je n'ai pas retrouvé de tâche ouverte correspondant à "
                f"« {subject} »."
            )
        if len(matched) > 1:
            return (
                "J'ai plusieurs tâches possibles : "
                + " / ".join(
                    str(item.get("title", ""))
                    for item in matched[:5]
                )
                + ". Laquelle est terminée ?"
            )

        item = matched[0]
        now = self._now().isoformat()
        with self._connect() as db:
            db.execute(
                """
                UPDATE agenda_items
                SET status='done', completed_at=?, updated_at=?
                WHERE id=?
                """,
                (now, now, int(item["id"])),
            )
        return f"C'est noté : « {item['title']} » est fait."

    def handle_understanding(
        self,
        message: str,
        understanding: Any,
    ) -> str | None:
        if not self._semantic_agenda_owned(understanding):
            return None

        action = str(
            self._semantic_value(
                understanding,
                "agenda_action",
                "query",
            )
            or "query"
        ).strip().lower()

        if action == "query":
            return self._semantic_query_answer(
                message,
                understanding,
            )
        if action == "add":
            return self._semantic_add(
                message,
                understanding,
            )
        if action == "complete":
            return self._semantic_complete(understanding)

        return (
            "J'ai compris que ta demande concerne ton agenda, mais je n'ai "
            "pas identifié l'action à effectuer. Reformule simplement ce que "
            "tu veux ajouter, consulter ou terminer."
        )

    # =========================================================
    # COMMANDS / ROUTER
    # =========================================================

    def status_summary(self) -> str:
        today = self._now().date()
        with self._connect() as db:
            total_pending = int(
                db.execute("SELECT COUNT(*) FROM agenda_items WHERE status='pending'").fetchone()[0]
            )
            todos = int(
                db.execute("SELECT COUNT(*) FROM agenda_items WHERE kind='todo' AND status='pending'").fetchone()[0]
            )
            appointments = int(
                db.execute("SELECT COUNT(*) FROM agenda_items WHERE kind='appointment' AND status='pending'").fetchone()[0]
            )
            events = int(
                db.execute("SELECT COUNT(*) FROM agenda_items WHERE kind='event' AND status='pending'").fetchone()[0]
            )
        return "\n".join(
            [
                "AGENDA PERSONNEL V6.4",
                f"Base : {self.db_path}",
                f"Éléments actifs : {total_pending}",
                f"Tâches : {todos}",
                f"Rendez-vous : {appointments}",
                f"Événements : {events}",
                f"Aujourd'hui : {len(self.items_for_date(today, status='pending'))} élément(s)",
            ]
        )

    def is_agenda_intent(self, message: str) -> bool:
        n = self.normalize(message)
        if n in {"agenda status", "agenda statut", "mon agenda"}:
            return True
        return bool(
            self.looks_like_todo_capture(message)
            or self.looks_like_appointment_capture(message)
            or self.looks_like_event_capture(message)
            or self._agenda_property_kind(message)
            or self._view_kind(message)
            or self._completion_payload(message)
        )

    def handle_message(
        self,
        message: str,
        understanding: Any | None = None,
    ) -> str | None:
        n = self.normalize(message)
        if n in {"agenda status", "agenda statut"}:
            return self.status_summary()

        # Une vraie question reconnue déterministement garde la priorité.
        queried = self.query(message)
        if queried is not None:
            return queried

        # V6.4.2 — sinon on exploite l'intention comprise par le LLM central.
        # C'est ce chemin qui rend l'agenda souple sans multiplier les regex.
        semantic = self.handle_understanding(
            message,
            understanding,
        )
        if semantic is not None:
            return semantic

        completed = self.complete_todo(message)
        if completed is not None:
            return completed

        appointment = self.capture_appointment(message)
        if appointment is not None:
            return appointment

        todos = self.capture_todos(message)
        if todos is not None:
            return todos

        event = self.capture_event(message)
        if event is not None:
            return event

        return None

    def context_for(self, message: str) -> str:
        if not self.is_agenda_intent(message):
            return "(agenda non pertinent pour ce message)"
        target = self._target_date(message).value
        return self.program_for_date(target, view="program")
