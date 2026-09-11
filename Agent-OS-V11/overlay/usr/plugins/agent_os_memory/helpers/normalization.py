from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta
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


FRENCH_WEEKDAYS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


def parse_user_date(
    value: Any,
    *,
    reference: datetime | None = None,
    end_of_day: bool = False,
) -> str | None:
    """Parse ISO dates plus common unambiguous French date expressions.

    The language model remains responsible for understanding the user's
    sentence. This helper only resolves a small, deterministic vocabulary after
    extraction and rejects unknown expressions instead of guessing.
    """
    raw = clean(value)
    if not raw:
        return None
    reference = reference or datetime.now().astimezone()
    try:
        return parse_iso(raw, end_of_day=end_of_day)
    except ValueError as iso_error:
        folded = normalize(raw)
        relative_days = {
            "aujourd hui": 0,
            "today": 0,
            "maintenant": 0,
            "now": 0,
            "demain": 1,
            "tomorrow": 1,
            "apres demain": 2,
            "apres-demain": 2,
            "hier": -1,
            "yesterday": -1,
        }
        if folded in relative_days:
            target = reference.date() + timedelta(days=relative_days[folded])
            clock = time.max.replace(microsecond=0) if end_of_day else time.min
            return datetime.combine(target, clock).isoformat()

        if folded in FRENCH_WEEKDAYS:
            target_weekday = FRENCH_WEEKDAYS[folded]
            days_ahead = (target_weekday - reference.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target = reference.date() + timedelta(days=days_ahead)
            clock = time.max.replace(microsecond=0) if end_of_day else time.min
            return datetime.combine(target, clock).isoformat()

        match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})", raw)
        if match:
            day_number, month_number, year_text = match.groups()
            year_number = int(year_text)
            if len(year_text) == 2:
                year_number += 2000 if year_number < 70 else 1900
            try:
                target = date(year_number, int(month_number), int(day_number))
            except ValueError as exc:
                raise ValueError(f"Date française invalide : {raw}") from exc
            clock = time.max.replace(microsecond=0) if end_of_day else time.min
            return datetime.combine(target, clock).isoformat()

        raise iso_error


def date_key(value: str | None, fallback: datetime) -> str:
    if not value:
        return fallback.date().isoformat()
    return str(value)[:10]
