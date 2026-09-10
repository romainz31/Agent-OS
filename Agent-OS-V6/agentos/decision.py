from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionDecision:
    owner: str = "unknown"
    action: str = "none"
    view: str = "none"
    target: str = ""
    subject: str = ""
    field: str = "none"
    confidence: float = 0.0
    allow_web: bool = True
    reason: str = ""
    source: str = "fallback"


class ActionDecisionEngine:
    """Arbitrage court entre les capacités de Paul.

    V6.4.2.1 ne remplace pas UnderstandingEngine. Il utilise d'abord son
    analyse riche. Si cette analyse n'identifie pas clairement le propriétaire
    de la demande, un second appel LLM très court choisit seulement la capacité
    qui doit agir. L'exécution reste déterministe.
    """

    OWNERS = {
        "agenda",
        "personal_memory",
        "external",
        "agent_work",
        "conversation",
        "operational",
        "unknown",
    }
    ACTIONS = {
        "add",
        "query",
        "complete",
        "remember",
        "research",
        "delegate",
        "chat",
        "status",
        "none",
    }
    VIEWS = {"todo", "appointment", "event", "program", "none"}
    FIELDS = {"what", "where", "when", "who", "none"}

    SYSTEM = r"""
Tu es le sélecteur d'action interne d'Agent-OS.
Tu ne réponds jamais à l'utilisateur. Tu choisis seulement QUI doit traiter le
message et QUELLE action doit être exécutée.

Capacités disponibles :
- agenda : tâches personnelles futures, rendez-vous, événements personnels
  planifiés, consultation du planning ;
- personal_memory : faits/souvenirs sur la vie de l'utilisateur déjà vécus ou
  questions sur ce qu'il a raconté ;
- external : information publique/externe nécessitant Internet ;
- agent_work : travail réellement délégué à Paul/aux agents ;
- conversation : discussion, conseil, explication sans action externe ;
- operational : état des missions/workers/Agent-OS.

Règle fondamentale : comprends le SENS, pas une phrase-clé.

Exemples :
"je dois faire quoi samedi ?"
=> agenda / query / todo / samedi / what

"qu'est-ce que j'ai de prévu samedi ?"
=> agenda / query / program / samedi / what

"les événements prévus pour samedi ?" après une discussion sur l'agenda
=> agenda / query / event / samedi / what

"où je dois aller samedi ?"
=> agenda / query / program / samedi / where

"samedi je dois aller chercher Coralie à l'aéroport"
=> agenda / add / todo / samedi

"j'ai rendez-vous chez le dentiste demain à 15h"
=> agenda / add / appointment / demain

"hier j'ai emmené Coralie à l'aéroport"
=> personal_memory / remember

"qui a emmené Coralie à l'aéroport ?"
=> personal_memory / query

"quels événements sont prévus samedi à Toulouse ?"
=> external / research

"que faire samedi à Toulouse ?"
=> external / research

"refais mon dashboard Home Assistant"
=> agent_work / delegate

"explique-moi le cisaillement du vent"
=> conversation / chat

Une formulation à la première personne sur ce que l'utilisateur DOIT faire,
a de prévu, a comme rendez-vous ou programme est normalement son agenda.
Une formulation qui demande des événements/sorties DANS UNE VILLE ou dans le
monde extérieur est external.

Le MESSAGE PRÉCÉDENT sert uniquement à résoudre une relance courte. Ne transforme
pas une question externe en agenda seulement parce qu'un ancien message parlait
d'agenda.

Réponds avec UN JSON exactement :
{
  "owner": "agenda|personal_memory|external|agent_work|conversation|operational|unknown",
  "action": "add|query|complete|remember|research|delegate|chat|status|none",
  "view": "todo|appointment|event|program|none",
  "target": "",
  "subject": "",
  "field": "what|where|when|who|none",
  "confidence": 0.0,
  "reason": ""
}
""".strip()

    def __init__(self, llm) -> None:
        self.llm = llm

    @staticmethod
    def _clean(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, number))

    @classmethod
    def _json_object(cls, raw: str) -> dict[str, Any] | None:
        text = str(raw or "").strip()
        if not text:
            return None
        text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```\s*$", "", text).strip()
        start = text.find("{")
        if start < 0:
            return None
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    @classmethod
    def _from_understanding(cls, understanding: Any) -> ActionDecision | None:
        if understanding is None:
            return None

        try:
            agenda_conf = float(getattr(understanding, "agenda_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            agenda_conf = 0.0
        if bool(getattr(understanding, "agenda_requested", False)) and agenda_conf >= 0.58:
            return ActionDecision(
                owner="agenda",
                action=cls._clean(getattr(understanding, "agenda_action", "query")).lower() or "query",
                view=cls._clean(getattr(understanding, "agenda_view", "program")).lower() or "program",
                target=cls._clean(getattr(understanding, "agenda_target", "")),
                subject=cls._clean(getattr(understanding, "agenda_subject", "")),
                field=cls._clean(getattr(understanding, "agenda_field", "none")).lower() or "none",
                confidence=agenda_conf,
                allow_web=False,
                reason="UnderstandingEngine a identifié l'agenda.",
                source="understanding",
            )

        primary = cls._clean(getattr(understanding, "primary_intent", "")).lower()
        conf = cls._clamp(getattr(understanding, "confidence", 0.0))
        # Les domaines ambigus (mémoire/conversation/externe) passent par
        # l'arbitre court : le gros prompt Understanding peut comprendre le
        # sujet tout en choisissant un mauvais propriétaire.
        if primary == "operational" and conf >= 0.58:
            return ActionDecision(
                owner="operational",
                action="status",
                confidence=conf,
                allow_web=False,
                reason="UnderstandingEngine a identifié une question opérationnelle.",
                source="understanding",
            )
        if (
            bool(getattr(understanding, "work_requested", False))
            and bool(getattr(understanding, "work_explicit", False))
        ):
            try:
                work_conf = float(getattr(understanding, "work_confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                work_conf = 0.0
            if work_conf >= 0.72:
                return ActionDecision(
                    owner="agent_work",
                    action="delegate",
                    confidence=work_conf,
                    allow_web=False,
                    reason="UnderstandingEngine a identifié un travail délégué.",
                    source="understanding",
                )
        return None

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> ActionDecision:
        owner = cls._clean(payload.get("owner", "unknown")).lower()
        action = cls._clean(payload.get("action", "none")).lower()
        view = cls._clean(payload.get("view", "none")).lower()
        field = cls._clean(payload.get("field", "none")).lower()
        if owner not in cls.OWNERS:
            owner = "unknown"
        if action not in cls.ACTIONS:
            action = "none"
        if view not in cls.VIEWS:
            view = "none"
        if field not in cls.FIELDS:
            field = "none"
        confidence = cls._clamp(payload.get("confidence", 0.0))
        allow_web = owner == "external"
        return ActionDecision(
            owner=owner,
            action=action,
            view=view,
            target=cls._clean(payload.get("target", ""))[:120],
            subject=cls._clean(payload.get("subject", ""))[:240],
            field=field,
            confidence=confidence,
            allow_web=allow_web,
            reason=cls._clean(payload.get("reason", ""))[:300],
            source="arbiter_llm",
        )

    @classmethod
    def _fallback(cls, message: str) -> ActionDecision:
        # Filet de sécurité volontairement petit. Il ne sert pas de routeur
        # principal : il protège surtout la vie privée si les deux analyses LLM
        # échouent complètement.
        n = cls._clean(message).lower()
        personal_future = bool(
            re.search(r"\b(?:je|j['’]?|mon|ma|mes|moi)\b", n)
            and re.search(r"\b(?:dois|prévu|prevu|rendez|rdv|programme|planning)\b", n)
        )
        if personal_future:
            return ActionDecision(
                owner="agenda",
                action="query" if ("?" in message or "quoi" in n or "qu est" in n) else "add",
                view=(
                    "todo"
                    if re.search(r"\b(?:dois|tache|taches|todo)\b", n)
                    else "program"
                ),
                confidence=0.56,
                allow_web=False,
                reason="Filet de sécurité : formulation personnelle de planning.",
                source="fallback",
            )
        return ActionDecision()

    def decide(
        self,
        message: str,
        understanding: Any = None,
        *,
        previous_user_message: str = "",
    ) -> ActionDecision:
        inherited = self._from_understanding(understanding)
        if inherited is not None:
            return inherited

        broad = ""
        if understanding is not None:
            broad = (
                "intention="
                + self._clean(getattr(understanding, "primary_intent", ""))
                + "; sujet="
                + self._clean(getattr(understanding, "topic", ""))
                + "; travail="
                + str(bool(getattr(understanding, "work_requested", False)))
            )

        prompt = (
            "ANALYSE LARGE EXISTANTE (indice, pas décision finale) :\n"
            + (broad or "(aucune)")
            + "\n\nMESSAGE PRÉCÉDENT UTILISATEUR :\n"
            + (self._clean(previous_user_message) or "(aucun)")[-500:]
            + "\n\nMESSAGE ACTUEL :\n"
            + self._clean(message)
        )
        try:
            raw = self.llm.chat(prompt, system=self.SYSTEM)
            payload = self._json_object(raw)
            if payload is not None:
                result = self._from_payload(payload)
                if result.confidence >= 0.55 and result.owner != "unknown":
                    return result
        except Exception:
            pass
        return self._fallback(message)
