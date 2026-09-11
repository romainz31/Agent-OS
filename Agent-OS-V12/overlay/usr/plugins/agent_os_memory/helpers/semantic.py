from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any

from .local_ai import LocalSemanticAI
from .normalization import clean, normalize
from .store import FACT_KINDS, PersonalMemoryStore


EXTRACTOR_PROMPT = """
Tu es l'extracteur sémantique de la mémoire personnelle de Paul.
Analyse uniquement le message utilisateur fourni après cette instruction.
Retourne un objet JSON, sans texte autour, avec:
route (capture, query, update, forget, clarify ou noop), type,
title, semantic_state, action_verb, object_text, location_text,
date_expression, start_at, due_at, completed_at, date_precision,
occurrences, entities (liste type/name/role), entity_attributes
(liste entity/attribute/value/type), subject, predicate, value,
query_text, aggregate, states, start, end, sort.
Si le message contient plusieurs faits personnels, retourne route=capture
avec captures=[...] et une entrée complète par fait. Ne fusionne pas deux
faits indépendants dans un seul titre.
Les dates déjà résolues doivent être ISO. Ne complète jamais une donnée
absente et ne transforme pas une hypothèse en fait. Le texte source complet
sera conservé séparément.
"""

QUERY_PROMPT = """
Tu es le planificateur d'une requête sur la mémoire personnelle SQLite.
À partir de la question, retourne uniquement un JSON contenant text, kinds,
statuses, states, semantic_state, start, end, subject, predicate, entity,
entity_type, aggregate, sort, limit. La base locale est la seule source de
vérité. Ne réponds pas à la place de la base.
"""

SYNTHESIS_PROMPT = """
Réponds en français à la question utilisateur en utilisant exclusivement les
preuves JSON fournies. N'invente aucun détail absent. Si les preuves sont
vides, dis que l'information n'est pas dans la mémoire personnelle. Pour une
question de quantité, additionne occurrences et non le nombre de lignes.
Réponds en une ou deux phrases naturelles, sans mentionner JSON, SQL ou
modèle.
"""

MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "décembre": 12,
}
NUMBER_WORDS = {
    "une": 1, "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
}
PLACEHOLDERS = {"", "unknown", "inconnu", "null", "none", "n/a", "?", "??"}


def _iso_day(value: datetime) -> str:
    return value.date().isoformat()


def _french_date(value: str | None) -> str:
    if not value:
        return "cette date"
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10]
    return f"{date.day:02d}/{date.month:02d}/{date.year:04d}"


def _resolve_date(text: str, now: datetime) -> tuple[str | None, str]:
    raw = clean(text).casefold()
    if re.search(r"\baujourd'?hui\b", raw):
        return _iso_day(now), "day"
    if re.search(r"\bdemain\b", raw):
        return _iso_day(now + timedelta(days=1)), "day"
    if re.search(r"\baprès[- ]demain\b", raw):
        return _iso_day(now + timedelta(days=2)), "day"
    if re.search(r"\bhier\b", raw):
        return _iso_day(now - timedelta(days=1)), "day"

    match = re.search(r"\b(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{2,4})\b", raw)
    if match:
        day, month, year = (int(item) for item in match.groups())
        if year < 100:
            year += 2000
        try:
            return f"{year:04d}-{month:02d}-{day:02d}", "exact"
        except ValueError:
            return None, "unknown"

    match = re.search(
        r"\b(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|"
        r"juillet|août|aout|septembre|octobre|novembre|décembre|decembre)"
        r"(?:\s+(\d{4}))?\b",
        raw,
    )
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2)]
        year = int(match.group(3) or now.year)
        try:
            return f"{year:04d}-{month:02d}-{day:02d}", "exact"
        except ValueError:
            return None, "unknown"
    return None, "unknown"


def _month_window(now: datetime, previous: bool = False) -> tuple[str, str]:
    year, month = now.year, now.month
    if previous:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def _extract_occurrences(text: str) -> int:
    match = re.search(
        r"\b(\d+|une|un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix)\s+fois\b",
        text.casefold(),
    )
    if not match:
        return 1
    token = match.group(1)
    return int(token) if token.isdigit() else NUMBER_WORDS[token]


def _title_after(text: str, markers: tuple[str, ...]) -> str:
    lowered = text.casefold()
    positions = [(lowered.find(marker), marker) for marker in markers]
    positions = [(pos, marker) for pos, marker in positions if pos >= 0]
    if not positions:
        return ""
    pos, marker = min(positions)
    result = text[pos + len(marker):].strip(" .,:;!?")
    result = re.split(
        r"\b(?:demain|aujourd'hui|aujourd’hui|hier|le\s+\d{1,2}[\/.-])\b",
        result,
        maxsplit=1,
        flags=re.I,
    )[0]
    result = re.sub(r"^(?:je|j['’])\s+", "", result, flags=re.I)
    if re.match(r"^range\b", result, flags=re.I):
        result = "ranger" + result[5:]
    return clean(result)


def _entity(name: str, entity_type: str, role: str) -> dict[str, str]:
    return {"type": entity_type, "name": clean(name), "role": role}


def _fallback_plan(text: str, now: datetime) -> dict[str, Any]:
    source = clean(text)
    low = source.casefold()
    name_match = re.search(r"\bje\s+m['’]appelle\s+([A-Za-zÀ-ÿ'-]+)", source, re.I)
    residence_match = re.search(
        r"\bj['’]habite\s+(?:à|a|dans)\s+([^,.!?]+)", source, re.I
    )
    relation_match = re.search(
        r"\b([A-ZÀ-Ý][A-Za-zÀ-ÿ'-]+)\s+est\s+(?:ma|mon)\s+([^,.!?]+)",
        source,
    )
    like_match = re.search(
        r"\bj['’]aime\s+(?:bien\s+)?(?:le|la|les|l['’])?\s*([^,.!?]+)",
        source,
        re.I,
    )
    query_words = (
        "combien", "quand", "quelle", "quelles", "quels", "qui", "où",
        "comment", "est-ce que", "dernière fois", "derniere fois",
        "rappelle-moi", "montre", "liste",
    )
    is_question = low.startswith(query_words) or "combien de fois" in low

    if name_match and residence_match and not is_question:
        place = clean(residence_match.group(1))
        return {
            "route": "capture",
            "captures": [
                {
                    "type": "fact", "title": "nom", "subject": "user",
                    "predicate": "nom", "value": name_match.group(1),
                },
                {
                    "type": "fact", "title": "domicile", "subject": "user",
                    "predicate": "domicile", "value": place,
                    "entities": [_entity(place, "place", "location")],
                },
            ],
        }
    if name_match and not is_question:
        return {
            "route": "capture", "type": "fact", "title": "nom",
            "subject": "user", "predicate": "nom", "value": name_match.group(1),
            "semantic_state": "unknown",
        }
    if residence_match and not is_question:
        place = clean(residence_match.group(1))
        return {
            "route": "capture", "type": "fact", "title": "domicile",
            "subject": "user", "predicate": "domicile", "value": place,
            "entities": [_entity(place, "place", "location")],
        }
    if relation_match and not is_question:
        person, relation = relation_match.groups()
        return {
            "route": "capture", "type": "relation",
            "title": f"{person} est {relation}",
            "subject": "user", "predicate": f"relation avec {person}",
            "value": clean(relation), "entities": [_entity(person, "person", "subject")],
        }
    if like_match and not is_question:
        value = clean(like_match.group(1))
        return {
            "route": "capture", "type": "preference", "title": value,
            "subject": "user", "predicate": "goût", "value": value,
        }
    work_match = re.search(
        r"\bje\s+travaille\s+(?:dans|chez|comme)\s+([^,.!?]+)",
        source,
        re.I,
    )
    if work_match and not is_question:
        value = clean(work_match.group(0))
        return {
            "route": "capture", "type": "fact", "title": "emploi",
            "subject": "user", "predicate": "emploi", "value": value,
        }

    if is_question:
        query_text = source
        if ("appelle" in low or "m'appelle" in low) and "habite" in low:
            return {"route": "query", "query_text": "", "kinds": ["fact"],
                    "subject": "user", "predicate": "", "aggregate": "list"}
        if "nom" in low and ("appelle" in low or "m'appelle" in low):
            return {"route": "query", "query_text": "", "kinds": ["fact"],
                    "subject": "user", "predicate": "nom", "aggregate": "list"}
        if "habite" in low or "domicile" in low:
            return {"route": "query", "query_text": "", "kinds": ["fact"],
                    "subject": "user", "predicate": "domicile", "aggregate": "list"}
        person = re.search(
            r"\b(?:avec|de|sur)\s+([A-ZÀ-Ý][A-Za-zÀ-ÿ'-]+)", source
        )
        if "relation" in low and person:
            return {
                "route": "query", "query_text": "", "kinds": ["relation"],
                "subject": "user", "predicate": f"relation avec {person.group(1)}",
                "aggregate": "list",
            }
        target = ""
        for candidate in ("courses", "cuisine", "chambre", "ménage", "menage"):
            if candidate in low:
                target = candidate
                break
        start = end = None
        if "ce mois" in low or "ce mois-ci" in low:
            start, end = _month_window(now)
        elif "mois dernier" in low:
            start, end = _month_window(now, previous=True)
        exact, _ = _resolve_date(source, now)
        if exact:
            start = end = exact
        return {
            "route": "query", "query_text": target or query_text,
            "kinds": ["action"] if target else [],
            "states": ["completed"] if target else [],
            "aggregate": "count" if "combien" in low else "list",
            "start": start, "end": end,
            "sort": "latest" if "derni" in low else "recent",
        }

    date, precision = _resolve_date(source, now)
    if "aller à la mer" in low or "vais à la mer" in low:
        return {
            "route": "capture", "type": "event", "title": "aller à la mer",
            "semantic_state": "planned", "start_at": date, "date_precision": precision,
            "entities": [_entity("mer", "place", "location")],
        }

    if re.search(r"\b(?:demain|aujourd'hui|aujourd’hui)\b", low) and re.search(
        r"\b(?:dois|faut|faudra|il faut que)\b", low
    ):
        title = _title_after(source, ("que", "dois", "faut", "faudra"))
        return {
            "route": "capture", "type": "task", "title": title,
            "semantic_state": "planned", "due_at": date, "date_precision": precision,
        }

    if re.search(r"\b(?:j['’]ai|je suis allé|je suis alle|je vais)\b", low):
        location = ""
        if "magasin" in low:
            location = "magasin"
        if "nettoy" in low:
            title = "nettoyer la cuisine" if "cuisine" in low else _title_after(
                source, ("j'ai", "j’ai")
            )
        elif "courses" in low:
            title = "faire des courses"
        else:
            title = _title_after(source, ("j'ai", "j’ai", "je suis allé", "je vais"))
        return {
            "route": "capture", "type": "action", "title": title or source,
            "semantic_state": "completed", "completed_at": date or _iso_day(now),
            "date_precision": precision if date else "day",
            "location_text": location,
            "occurrences": _extract_occurrences(source),
            "entities": [_entity(location, "place", "location")] if location else [],
        }

    if re.search(r"\b(?:dois|faut que|il faut)\b", low):
        title = _title_after(source, ("que", "dois", "faut"))
        return {
            "route": "capture", "type": "task", "title": title or source,
            "semantic_state": "planned", "due_at": date,
            "date_precision": precision,
        }
    return {"route": "noop"}


class SemanticMemoryPipeline:
    """Interpret user text, validate it, then call the transactional store."""

    def __init__(
        self,
        store: PersonalMemoryStore,
        *,
        config: dict[str, Any] | None = None,
        ai: Any | None = None,
    ) -> None:
        self.store = store
        self.config = dict(config or {})
        self.ai = ai or LocalSemanticAI(self.config)

    @staticmethod
    def _valid_plan(plan: Any) -> bool:
        return isinstance(plan, dict) and clean(
            plan.get("route") or plan.get("intent")
        ) in {"capture", "query", "update", "forget", "clarify", "noop"}

    async def _interpret(self, text: str, now: datetime) -> dict[str, Any]:
        prompt = EXTRACTOR_PROMPT + "\nDate actuelle: " + _iso_day(now)
        prompt += "\nMessage utilisateur:\n" + text
        try:
            plan = await self.ai.generate_json(prompt)
        except Exception:
            plan = None
        if self._valid_plan(plan):
            plan = dict(plan)
            plan["route"] = clean(plan.get("route") or plan.get("intent"))
            return plan
        return _fallback_plan(text, now)

    def _capture_kwargs(
        self, plan: dict[str, Any], source: str, now: datetime
    ) -> dict[str, Any]:
        kind = clean(plan.get("type") or plan.get("kind") or "note")
        title = clean(plan.get("title") or plan.get("object_text") or source)
        date_expression = clean(plan.get("date_expression"))
        resolved, precision = _resolve_date(date_expression or source, now)
        start_at = plan.get("start_at") or plan.get("start")
        due_at = plan.get("due_at") or plan.get("due")
        completed_at = plan.get("completed_at")
        if start_at and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(start_at)):
            start_at = str(start_at)
        elif start_at and not re.match(r"\d{4}-", str(start_at)):
            start_at, _ = _resolve_date(str(start_at), now)
        if due_at and not re.match(r"\d{4}-", str(due_at)):
            due_at, _ = _resolve_date(str(due_at), now)
        if completed_at and not re.match(r"\d{4}-", str(completed_at)):
            completed_at, _ = _resolve_date(str(completed_at), now)
        if not start_at and kind in {"event", "appointment"}:
            start_at = resolved
        if not due_at and kind == "task":
            due_at = resolved
        if not completed_at and kind == "action":
            completed_at = resolved or _iso_day(now)
        if plan.get("date_precision"):
            precision = clean(plan["date_precision"])

        entities = list(plan.get("entities") or [])
        attrs = list(plan.get("entity_attributes") or [])
        metadata = dict(plan.get("metadata") or {})
        metadata["date_expression"] = date_expression
        metadata["semantic_source"] = "qwen" if self.ai else "fallback"
        kwargs = {
            "kind": kind,
            "title": title,
            "status": plan.get("status") or "",
            "semantic_state": plan.get("semantic_state") or "",
            "action_verb": plan.get("action_verb") or "",
            "object_text": plan.get("object_text") or "",
            "location_text": plan.get("location_text") or "",
            "start_at": start_at,
            "due_at": due_at,
            "completed_at": completed_at,
            "date_precision": precision or "unknown",
            "time_expression": plan.get("time_expression") or date_expression,
            "recurrence_rule": plan.get("recurrence_rule") or "",
            "priority": plan.get("priority") or "",
            "importance": plan.get("importance", 0.5),
            "confidence": plan.get("confidence", 1.0),
            "inferred": bool(plan.get("inferred", False)),
            "source_text": source,
            "metadata": metadata,
            "entities": entities,
            "entity_attributes": attrs,
            "subject": plan.get("subject") or "user",
            "predicate": plan.get("predicate") or "",
            "value": plan.get("value") or title,
            "occurrences": plan.get("occurrences") or 1,
        }
        return kwargs

    @staticmethod
    def _validate_capture(kwargs: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if clean(kwargs.get("title")).casefold() in PLACEHOLDERS:
            errors.append("un titre précis")
        kind = clean(kwargs.get("kind")).casefold()
        if kind in {"event", "appointment"} and not (
            kwargs.get("start_at") or kwargs.get("due_at")
        ):
            errors.append("une date pour cet événement")
        for key in ("title", "value", "subject"):
            value = clean(kwargs.get(key))
            if value.casefold() in PLACEHOLDERS and key == "title":
                errors.append(key)
        return list(dict.fromkeys(errors))

    async def _query_plan(self, text: str, now: datetime) -> dict[str, Any]:
        prompt = QUERY_PROMPT + "\nDate actuelle: " + _iso_day(now)
        prompt += "\nQuestion:\n" + text
        try:
            plan = await self.ai.generate_json(prompt)
        except Exception:
            plan = None
        if isinstance(plan, dict):
            return dict(plan)
        return _fallback_plan(text, now)

    @staticmethod
    def _deterministic_reply(question: str, result: dict[str, Any]) -> str:
        records = list(result.get("records") or [])
        facts = list(result.get("facts") or [])
        low = question.casefold()
        if not records and not facts:
            return "Je n'ai pas cette information dans ma mémoire personnelle."
        if result.get("query", {}).get("aggregate") == "count" or "combien" in low:
            count = result.get("count", result.get("observation_count", 0))
            unit = "fois" if int(count) != 1 else "fois"
            return f"Tu l'as fait {count} {unit}."
        if facts:
            if "appelle" in low and "habite" in low:
                by_predicate = {
                    item.get("predicate"): item.get("value") for item in facts
                }
                name = by_predicate.get("nom")
                place = by_predicate.get("domicile")
                if name and place:
                    return f"Tu t'appelles {name} et tu habites à {place}."
            if "relation" in low and len(facts) == 1:
                fact = facts[0]
                person = str(fact.get("predicate", "")).split("avec", 1)[-1].strip()
                return f"{person or 'Cette personne'} est ta {fact.get('value')}."
            parts = []
            for fact in reversed(facts[:5]):
                parts.append(f"{fact.get('predicate')} : {fact.get('value')}")
            return " ; ".join(parts) + "."
        latest = records[0]
        if "derni" in low or "quand" in low or "date" in low:
            moment = latest.get("completed_at") or latest.get("start_at") or latest.get("due_at")
            return f"La dernière fois, c'était le {_french_date(moment)}."
        titles = [str(item.get("title")) for item in records[:5]]
        return " ".join(titles) + "."

    async def _answer_query(
        self, question: str, plan: dict[str, Any], context_id: str, now: datetime
    ) -> str:
        if not plan.get("kinds") and plan.get("type"):
            plan["kinds"] = [plan["type"]]
        result = self.store.query(
            text=plan.get("text") or plan.get("query_text") or "",
            kinds=plan.get("kinds") or [],
            statuses=plan.get("statuses") or [],
            states=plan.get("states") or [],
            semantic_state=plan.get("semantic_state") or "",
            start=plan.get("start"),
            end=plan.get("end"),
            subject=plan.get("subject") or "",
            predicate=plan.get("predicate") or "",
            entity=plan.get("entity") or "",
            entity_type=plan.get("entity_type") or "",
            aggregate=plan.get("aggregate") or "list",
            context_id=context_id,
            follow_up=bool(plan.get("follow_up")),
            limit=int(plan.get("limit") or 20),
        )
        evidence = {
            "records": result.get("records", []),
            "facts": result.get("facts", []),
            "count": result.get("count", result.get("observation_count", 0)),
        }
        try:
            prompt = SYNTHESIS_PROMPT + "\nQuestion:\n" + question
            prompt += "\nPreuves locales:\n" + str(evidence)
            answer = await self.ai.generate_text(prompt)
        except Exception:
            answer = None
        return clean(answer) if answer else self._deterministic_reply(question, result)

    async def handle(self, text: str, *, context_id: str = "") -> dict[str, Any]:
        text = clean(text)
        if not text:
            return {"handled": False, "reply": ""}
        now = self.store.now()
        pending = self.store.pending_clarification(context_id)
        source = text
        if pending and _resolve_date(text, now)[0]:
            source = clean(pending["source_text"] + " " + text)
            self.store.clear_pending_clarification(context_id)

        plan = await self._interpret(source, now)
        route = clean(plan.get("route"))
        if route == "capture":
            capture_plans = list(plan.get("captures") or [plan])
            operations = []
            replies = []
            for capture_plan in capture_plans:
                kwargs = self._capture_kwargs(capture_plan, source, now)
                errors = self._validate_capture(kwargs)
                if errors:
                    self.store.save_pending_clarification(
                        context_id=context_id, source_text=source, missing=errors
                    )
                    return {
                        "handled": True,
                        "reply": "Pour que je le note correctement, il me manque "
                        + " et ".join(errors) + ".",
                        "pending": True,
                    }
                result = self.store.capture(context_id=context_id, **kwargs)
                operations.append(result)
                record = result.get("record", {})
                if result.get("operation") == "completed_existing_task":
                    replies.append(f"« {record.get('title')} » est terminé")
                elif record.get("kind") == "task":
                    replies.append(f"la tâche « {record.get('title')} »")
                elif record.get("kind") in {"fact", "preference", "relation"}:
                    fact = result.get("fact", {})
                    value = fact.get("value") or kwargs.get("value")
                    if record.get("kind") == "relation":
                        person = (kwargs.get("entities") or [{}])[0].get("name", "")
                        replies.append(f"que {person} est ta {value}")
                    elif record.get("kind") == "preference":
                        replies.append(f"que tu aimes {value}")
                    else:
                        replies.append(
                            f"que ton {fact.get('predicate') or kwargs.get('predicate')} "
                            f"est {value}"
                        )
                else:
                    replies.append(f"« {record.get('title')} »")
            if len(replies) == 1:
                reply = ("Je retiens " if capture_plans[0].get("type") in FACT_KINDS
                         else "C'est noté : ") + replies[0] + "."
            else:
                reply = "Je retiens " + " et ".join(replies) + "."
            operation = operations[0] if len(operations) == 1 else operations
            return {"handled": True, "reply": reply, "operation": operation}
        if route == "query":
            reply = await self._answer_query(text, plan, context_id, now)
            return {"handled": True, "reply": reply, "query": plan}
        if route == "update":
            result = self.store.update(
                record_id=plan.get("record_id") or "",
                query=plan.get("query_text") or plan.get("title") or "",
                context_id=context_id,
                action=plan.get("action") or "update",
                changes=plan.get("changes") or {},
                reason="demande utilisateur",
            )
            if result.get("requires_user_choice"):
                return {"handled": True, "reply": "Lequel veux-tu modifier ?", "operation": result}
            return {
                "handled": True,
                "reply": "C'est mis à jour.",
                "operation": result,
            }
        if route == "forget":
            result = self.store.forget(
                record_ids=plan.get("record_ids") or [],
                query=plan.get("query_text") or plan.get("title") or "",
                context_id=context_id,
            )
            return {
                "handled": True,
                "reply": "C'est oublié." if result.get("count") else
                "Je n'ai rien trouvé à oublier.",
                "operation": result,
            }
        if route == "clarify":
            missing = plan.get("missing") or ["une précision"]
            self.store.save_pending_clarification(
                context_id=context_id, source_text=source, missing=missing
            )
            return {"handled": True, "reply": "Il me manque " + " et ".join(missing) + ".", "pending": True}
        return {"handled": False, "reply": ""}
