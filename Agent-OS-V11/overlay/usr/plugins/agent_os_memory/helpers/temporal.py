from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


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


def normalize_fr(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9:/+\-\s']+", " ", text)
    return " ".join(text.split())


def ensure_reference(reference: datetime | None, timezone: str = "Europe/Paris") -> datetime:
    tz = ZoneInfo(timezone)
    current = reference or datetime.now(tz)
    if current.tzinfo is None:
        return current.replace(tzinfo=tz)
    return current.astimezone(tz)


def extract_clock(value: str) -> tuple[int, int] | None:
    text = normalize_fr(value)
    match = re.search(r"(?:^|\b(?:a|vers)\s+)([01]?\d|2[0-3])(?:\s*(?:h|:)\s*([0-5]\d))?\b", text)
    if not match:
        match = re.search(r"\b([01]?\d|2[0-3])\s*h\s*([0-5]\d)?\b", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def _with_clock(day: date, clock: tuple[int, int] | None, tz: ZoneInfo) -> datetime:
    hour, minute = clock or (12, 0)
    return datetime.combine(day, time(hour=hour, minute=minute), tzinfo=tz)


def _resolve_weekday(target: int, reference: datetime, prefer: str, text: str) -> date:
    today = reference.date()
    current = today.weekday()
    normalized = normalize_fr(text)

    if "prochain" in normalized or "prochaine" in normalized:
        delta = (target - current) % 7
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)

    if "dernier" in normalized or "derniere" in normalized:
        delta = (current - target) % 7
        if delta == 0:
            delta = 7
        return today - timedelta(days=delta)

    if prefer == "past":
        delta = (current - target) % 7
        return today - timedelta(days=delta)

    delta = (target - current) % 7
    return today + timedelta(days=delta)


def resolve_temporal_expression(
    expression: str,
    *,
    reference: datetime | None = None,
    timezone: str = "Europe/Paris",
    prefer: str = "future",
    clock_source: str = "",
) -> datetime | None:
    """Resolve a French natural time expression without semantic guessing.

    ``prefer`` controls an unqualified weekday: ``past`` for completed actions,
    ``future`` for tasks/appointments/events. The model only supplies the
    original expression; calendar arithmetic remains deterministic here.
    """

    reference = ensure_reference(reference, timezone)
    tz = ZoneInfo(timezone)
    raw = str(expression or "").strip()
    text = normalize_fr(raw)
    if not text:
        return None

    clock = extract_clock(f"{raw} {clock_source}".strip())

    # ISO date or datetime.
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})(?:[t\s](\d{1,2}):(\d{2}))?\b", text)
    if iso_match:
        day = date.fromisoformat(iso_match.group(1))
        if iso_match.group(2):
            clock = (int(iso_match.group(2)), int(iso_match.group(3)))
        return _with_clock(day, clock, tz)

    # dd/mm/yyyy or dd-mm-yyyy; two-digit years are accepted as 20xx.
    numeric = re.search(r"\b(0?[1-9]|[12]\d|3[01])[/\-](0?[1-9]|1[0-2])(?:[/\-](\d{2}|\d{4}))?\b", text)
    if numeric:
        day_num = int(numeric.group(1))
        month_num = int(numeric.group(2))
        year_raw = numeric.group(3)
        year = reference.year if not year_raw else int(year_raw)
        if year < 100:
            year += 2000
        candidate = date(year, month_num, day_num)
        if not year_raw:
            if prefer == "future" and candidate < reference.date():
                candidate = date(year + 1, month_num, day_num)
            elif prefer == "past" and candidate > reference.date():
                candidate = date(year - 1, month_num, day_num)
        return _with_clock(candidate, clock, tz)

    # 12 septembre [2026]
    month_names = "|".join(MONTHS)
    named = re.search(rf"\b(0?[1-9]|[12]\d|3[01])\s+({month_names})(?:\s+(\d{{4}}))?\b", text)
    if named:
        year = int(named.group(3) or reference.year)
        candidate = date(year, MONTHS[named.group(2)], int(named.group(1)))
        if not named.group(3):
            if prefer == "future" and candidate < reference.date():
                candidate = date(year + 1, candidate.month, candidate.day)
            elif prefer == "past" and candidate > reference.date():
                candidate = date(year - 1, candidate.month, candidate.day)
        return _with_clock(candidate, clock, tz)

    # Longest expressions first so ``avant hier`` is not swallowed by ``hier``
    # and ``après demain`` is not swallowed by ``demain``.
    relatives = {
        "avant hier": -2,
        "avant-hier": -2,
        "apres demain": 2,
        "apres-demain": 2,
        "aujourd'hui": 0,
        "aujourdhui": 0,
        "aujourd hui": 0,
        "hier": -1,
        "demain": 1,
    }
    for marker, offset in relatives.items():
        if marker in text:
            return _with_clock(reference.date() + timedelta(days=offset), clock, tz)

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text):
            return _with_clock(_resolve_weekday(weekday, reference, prefer, text), clock, tz)

    return None




NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
    "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9,
    "dix": 10, "onze": 11, "douze": 12,
}


def _number_token(value: str) -> int | None:
    token = normalize_fr(value)
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _subtract_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) - months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    # Clamp the day to the last valid day in the target month.
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def resolve_period_expression(
    expression: str,
    *,
    reference: datetime | None = None,
    timezone: str = "Europe/Paris",
) -> tuple[date, date] | None:
    reference = ensure_reference(reference, timezone)
    today = reference.date()
    text = normalize_fr(expression)
    if not text:
        return None

    if "cette semaine" in text:
        start = today - timedelta(days=today.weekday())
        return start, today
    if "semaine derniere" in text or "la semaine derniere" in text:
        current_start = today - timedelta(days=today.weekday())
        end = current_start - timedelta(days=1)
        return end - timedelta(days=6), end
    if "ce mois" in text or "ce mois ci" in text:
        return date(today.year, today.month, 1), today
    if "mois dernier" in text or "le mois dernier" in text:
        start_current = date(today.year, today.month, 1)
        end = start_current - timedelta(days=1)
        return date(end.year, end.month, 1), end
    if "cette annee" in text:
        return date(today.year, 1, 1), today
    if "annee derniere" in text or "l annee derniere" in text:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)

    match = re.search(
        r"(?:ces?|les?|sur|depuis)\s+([a-z0-9]+)\s+derniers?\s+(jours?|semaines?|mois|annees?)",
        text,
    )
    if not match:
        match = re.search(r"depuis\s+([a-z0-9]+)\s+(jours?|semaines?|mois|annees?)", text)
    if match:
        amount = _number_token(match.group(1))
        unit = match.group(2)
        if not amount or amount < 1 or amount > 120:
            return None
        if unit.startswith("jour"):
            return today - timedelta(days=amount), today
        if unit.startswith("semaine"):
            return today - timedelta(weeks=amount), today
        if unit == "mois":
            return _subtract_months(today, amount), today
        if unit.startswith("annee"):
            try:
                start = today.replace(year=today.year - amount)
            except ValueError:
                start = today.replace(year=today.year - amount, day=28)
            return start, today
    return None

def day_expression_to_iso_bounds(
    expression: str,
    *,
    reference: datetime | None = None,
    timezone: str = "Europe/Paris",
    prefer: str = "past",
) -> tuple[str | None, str | None]:
    period = resolve_period_expression(
        expression, reference=reference, timezone=timezone
    )
    if period is not None:
        return period[0].isoformat(), period[1].isoformat()
    moment = resolve_temporal_expression(
        expression,
        reference=reference,
        timezone=timezone,
        prefer=prefer,
    )
    if moment is None:
        return None, None
    day = moment.date().isoformat()
    return day, day
