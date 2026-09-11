from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from agentos.db import Database


WEEKDAYS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


def parse_date_reference(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    value = text.lower()
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", value)
    if match:
        d, m, y = map(int, match.groups())
        if y < 100:
            y += 2000
        try:
            return date(y, m, d)
        except ValueError:
            return None
    if "après-demain" in value or "apres-demain" in value:
        return today + timedelta(days=2)
    if "demain" in value:
        return today + timedelta(days=1)
    if "aujourd'hui" in value or "aujourdhui" in value:
        return today
    for label, weekday in WEEKDAYS.items():
        if re.search(rf"\b{label}\b", value):
            delta = (weekday - today.weekday()) % 7
            if delta == 0:
                delta = 7
            return today + timedelta(days=delta)
    return None


class AgendaStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def reset(self) -> None:
        self.db.execute("DELETE FROM agenda")

    def list_for(self, event_date: date) -> list[dict]:
        return self.db.query(
            "SELECT id,event_date,title,created_at FROM agenda WHERE event_date=? ORDER BY id",
            (event_date.isoformat(),),
        )

    def add(self, event_date: date, title: str, source_text: str = "") -> bool:
        title = " ".join(title.strip().split()).strip(" .")
        if not title:
            return False
        existing = self.db.one(
            "SELECT id FROM agenda WHERE event_date=? AND lower(title)=lower(?) LIMIT 1",
            (event_date.isoformat(), title),
        )
        if existing:
            return False
        self.db.execute(
            "INSERT INTO agenda(event_date,title,source_text) VALUES(?,?,?)",
            (event_date.isoformat(), title, source_text),
        )
        return True

    def extract_event(self, message: str, today: date | None = None) -> tuple[date, str] | None:
        if "?" in message:
            return None
        event_date = parse_date_reference(message, today=today)
        if not event_date:
            return None
        value = " ".join(message.strip().split())
        lower = value.lower()
        if not any(marker in lower for marker in ("je dois", "j'ai", "jai ", "à faire", "a faire", "prévu", "prevu")):
            return None
        cleaned = re.sub(r"\b(le\s+)?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", "", value, count=1, flags=re.IGNORECASE)
        for wd in WEEKDAYS:
            cleaned = re.sub(rf"\b{wd}\b", "", cleaned, count=1, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(aujourd'hui|aujourdhui|demain|après-demain|apres-demain)\b", "", cleaned, count=1, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*(je dois|j'ai|jai|à faire|a faire|j'ai prévu|jai prevu|j’ai prévu)\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" ,.-")
        if not cleaned:
            return None
        return event_date, cleaned

    @staticmethod
    def is_query(message: str) -> bool:
        value = message.lower()
        markers = (
            "qu'ai-je prévu", "qu ai je prévu", "qu'ai je prévu", "qu est ce que j'ai prévu",
            "qu'est-ce que j'ai prévu", "programme", "prévu", "prevu", "à faire", "a faire",
        )
        return "?" in message and any(marker in value for marker in markers)

    def format_for(self, event_date: date) -> str:
        items = self.list_for(event_date)
        label = event_date.strftime("%d/%m/%Y")
        if not items:
            return f"Rien de prévu enregistré pour le {label}."
        lines = [f"Pour le {label} :"]
        lines.extend(f"- {item['title']}" for item in items)
        return "\n".join(lines)
