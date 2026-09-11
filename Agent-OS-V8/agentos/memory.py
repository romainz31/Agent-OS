from __future__ import annotations

import re
from typing import Iterable

from agentos.db import Database


class MemoryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def count(self) -> int:
        row = self.db.one("SELECT COUNT(*) AS n FROM memories WHERE active=1")
        return int(row["n"] if row else 0)

    def list_active(self, limit: int = 100) -> list[dict]:
        return self.db.query(
            "SELECT id,key,value,confidence,created_at,updated_at FROM memories "
            "WHERE active=1 ORDER BY updated_at DESC,id DESC LIMIT ?",
            (limit,),
        )

    def get(self, key: str) -> str | None:
        row = self.db.one(
            "SELECT value FROM memories WHERE key=? AND active=1 ORDER BY id DESC LIMIT 1",
            (key.strip().lower(),),
        )
        return str(row["value"]) if row else None

    def remember(self, key: str, value: str, source_text: str = "", confidence: float = 1.0) -> bool:
        key = key.strip().lower()
        value = value.strip()
        if not key or not value:
            return False
        current = self.db.one(
            "SELECT id,value FROM memories WHERE key=? AND active=1 ORDER BY id DESC LIMIT 1",
            (key,),
        )
        if current and str(current["value"]).strip().casefold() == value.casefold():
            self.db.execute(
                "UPDATE memories SET updated_at=CURRENT_TIMESTAMP, confidence=MAX(confidence,?) WHERE id=?",
                (float(confidence), int(current["id"])),
            )
            return False
        if current:
            self.db.execute("UPDATE memories SET active=0,updated_at=CURRENT_TIMESTAMP WHERE key=? AND active=1", (key,))
        self.db.execute(
            "INSERT INTO memories(key,value,source_text,confidence,active) VALUES(?,?,?,?,1)",
            (key, value, source_text, float(confidence)),
        )
        return True

    def forget(self, key: str) -> int:
        rows = self.db.query("SELECT id FROM memories WHERE key=? AND active=1", (key.strip().lower(),))
        for row in rows:
            self.db.execute("UPDATE memories SET active=0,updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(row["id"]),))
        return len(rows)

    def reset(self) -> None:
        self.db.execute("DELETE FROM memories")

    def prompt_context(self, limit: int = 30) -> str:
        items = self.list_active(limit=limit)
        if not items:
            return "Aucun souvenir personnel enregistré."
        return "\n".join(f"- {item['key']}: {item['value']}" for item in reversed(items))

    def extract_heuristic(self, message: str) -> list[tuple[str, str]]:
        text = " ".join(message.strip().split())
        patterns: Iterable[tuple[str, str]] = (
            (r"\b(?:je m['’]appelle|mon pr[eé]nom est)\s+([A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,40})", "identity.first_name"),
            (r"\bma copine s['’]appelle\s+([A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,40})", "relations.partner_name"),
            (r"\bmon copain s['’]appelle\s+([A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,40})", "relations.partner_name"),
            (r"\bj['’]habite (?:[àa] |a )?([^,.!?]{2,80})", "profile.location"),
        )
        found: list[tuple[str, str]] = []
        for pattern, key in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip(" .,!?")
                if value:
                    self.remember(key, value, source_text=message)
                    found.append((key, value))
        return found
