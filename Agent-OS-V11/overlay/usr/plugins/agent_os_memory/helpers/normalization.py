from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time
from typing import Any


STOPWORDS = {
    "a", "ai", "au", "aux", "avec", "ce", "ces", "cette", "dans",
    "de", "des", "du", "elle", "en", "et", "fait", "faire", "il",
    "j", "je", "la", "le", "les", "ma", "mes", "mon", "nous",
    "on", "ou", "pour", "que", "qui", "sur", "tu", "un", "une",
}


def clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value).casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    replacements = (
        (r"\baujourdhui\b", "aujourd hui"),
        (r"\bjai\b", "j ai"),
        (r"\bcest\b", "c est"),
        (r"\bquest\b", "qu est"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def tokens(value: Any) -> set[str]:
    return {
        token for token in normalize(value).split()
        if len(token) > 1 and token not in STOPWORDS
    }


def parse_iso(value: Any, *, end_of_day: bool = False) -> str | None:
    """Validate and normalize an ISO date or datetime without guessing."""
    raw = clean(value)
    if not raw:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            day = date.fromisoformat(raw)
            clock = time.max.replace(microsecond=0) if end_of_day else time.min
            return datetime.combine(day, clock).isoformat()
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError as exc:
        raise ValueError(f"Date ISO invalide : {raw}") from exc


def date_key(value: str | None, fallback: datetime) -> str:
    if not value:
        return fallback.date().isoformat()
    return str(value)[:10]
