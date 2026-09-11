from __future__ import annotations

from typing import Any

from agentos.db import Database


class ConversationStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, role: str, content: str, intent: str | None = None, meta: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "INSERT INTO conversation(role,content,intent,meta_json) VALUES(?,?,?,?)",
            (role, content, intent, self.db.dumps(meta or {})),
        )

    def recent(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT role,content,intent,meta_json,created_at FROM conversation ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows.reverse()
        for row in rows:
            row["meta"] = self.db.loads(row.pop("meta_json", "{}"), {})
        return rows

    def previous_user(self) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT role,content,intent,meta_json,created_at FROM conversation WHERE role='user' ORDER BY id DESC LIMIT 1"
        )
        if not row:
            return None
        row["meta"] = self.db.loads(row.pop("meta_json", "{}"), {})
        return row

    def reset(self) -> None:
        self.db.execute("DELETE FROM conversation")
