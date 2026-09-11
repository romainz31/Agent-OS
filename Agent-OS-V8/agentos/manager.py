from __future__ import annotations

import re
from datetime import date
from typing import Any

from agentos.agenda import AgendaStore, parse_date_reference
from agentos.config import DB_PATH, OLLAMA_HOST, OLLAMA_MODEL
from agentos.conversation import ConversationStore
from agentos.db import Database
from agentos.integrations.registry import IntegrationRegistry
from agentos.llm import LLMError, OllamaLLM
from agentos.memory import MemoryStore
from agentos.missions import MissionRunner, MissionStore


MISSION_REF_RE = re.compile(r"\bM-(\d{1,6})\b", flags=re.IGNORECASE)


class PersonalManager:
    """Paul: stable Agent-OS identity above interchangeable execution engines."""

    def __init__(
        self,
        db: Database | None = None,
        llm: OllamaLLM | None = None,
        integrations: IntegrationRegistry | None = None,
    ) -> None:
        self.db = db or Database(DB_PATH)
        self.memory = MemoryStore(self.db)
        self.conversation = ConversationStore(self.db)
        self.agenda = AgendaStore(self.db)
        self.missions = MissionStore(self.db)
        self.llm = llm or OllamaLLM(OLLAMA_HOST, OLLAMA_MODEL)
        self.integrations = integrations or IntegrationRegistry()
        self.runner = MissionRunner(self.missions, self.llm, self.integrations)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().strip().split())

    @staticmethod
    def _mission_action(text: str) -> tuple[str, str] | None:
        value = PersonalManager._normalize(text)
        match = MISSION_REF_RE.search(value)
        if not match:
            return None
        ref = f"M-{int(match.group(1)):03d}"
        if any(x in value for x in ("pause", "mets en pause", "met en pause", "suspends")):
            return "pause", ref
        if any(x in value for x in ("reprends", "reprend", "resume", "relance", "continue")):
            return "resume", ref
        if any(x in value for x in ("annule", "annuler", "arrête", "arrete", "stop")):
            return "cancel", ref
        return None

    @staticmethod
    def _mission_request(text: str) -> str | None:
        value = text.strip()
        patterns = (
            r"^\s*mission\s*:\s*(.+)$",
            r"^\s*lance\s+(?:une\s+)?mission\s*[:\-]?\s*(.+)$",
            r"^\s*cr[eé]e\s+(?:une\s+)?mission\s*[:\-]?\s*(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, value, flags=re.IGNORECASE | re.DOTALL)
            if match and match.group(1).strip():
                return match.group(1).strip()
        return None

    def reset_personal(self) -> None:
        self.memory.reset()
        self.conversation.reset()
        self.agenda.reset()

    def reset_all(self) -> None:
        self.reset_personal()
        self.missions.reset()

    def status(self, remote_checks: bool = False) -> dict[str, Any]:
        try:
            ollama = self.llm.health()
        except Exception as exc:
            ollama = {"ok": False, "error": str(exc), "model": OLLAMA_MODEL}
        return {
            "name": "Paul",
            "version": "8.0.0",
            "memory_count": self.memory.count(),
            "mission_count": self.missions.count(),
            "ollama": ollama,
            "integrations": self.integrations.status(remote_checks=remote_checks),
        }

    def _record(self, user: str, response: str, intent: str, meta: dict[str, Any] | None = None) -> str:
        self.conversation.add("user", user, intent=intent, meta=meta)
        self.conversation.add("assistant", response, intent=intent, meta=meta)
        return response

    def _memory_summary(self) -> str:
        items = self.memory.list_active(limit=100)
        if not items:
            return "Je ne sais encore rien de personnel sur toi. La mémoire V8 est vide."
        labels = {
            "identity.first_name": "Prénom",
            "relations.partner_name": "Partenaire",
            "profile.location": "Lieu de vie",
        }
        lines = ["Voici ce que j'ai actuellement en mémoire :"]
        for item in reversed(items):
            key = str(item["key"])
            lines.append(f"- {labels.get(key, key)} : {item['value']}")
        return "\n".join(lines)

    def _system_prompt(self) -> str:
        recent = self.conversation.recent(limit=10)
        transcript = "\n".join(
            f"{row['role'].upper()}: {row['content']}" for row in recent
        ) or "Aucun historique."
        missions = self.missions.format()
        return (
            "Tu es Paul, le Manager personnel d'Agent-OS V8. Réponds en français sauf demande contraire. "
            "Tu restes l'interlocuteur principal : les moteurs externes sont des workers, jamais l'identité utilisateur. "
            "Sois direct, concret, et n'invente pas de souvenirs.\n\n"
            f"MÉMOIRE ACTIVE:\n{self.memory.prompt_context()}\n\n"
            f"MISSIONS:\n{missions}\n\n"
            f"CONVERSATION RÉCENTE:\n{transcript}"
        )

    def chat(self, message: str) -> str:
        text = " ".join(str(message or "").strip().split())
        if not text:
            return "Écris-moi une demande."
        lower = self._normalize(text)
        previous = self.conversation.previous_user()

        # Mission Control stays deterministic and above every external engine.
        action = self._mission_action(text)
        if action:
            verb, ref = action
            mission = self.missions.control(ref, verb)
            if not mission:
                return self._record(text, f"Mission {ref} introuvable.", "mission_control")
            labels = {"pause": "mise en pause", "resume": "reprise", "cancel": "annulée"}
            return self._record(text, f"{ref} {labels[verb]}. État : {mission['status']}.", "mission_control")

        objective = self._mission_request(text)
        if objective:
            mission = self.runner.launch(objective)
            response = (
                f"{mission['human_id']} créée et lancée en arrière-plan.\n"
                f"Objectif : {objective}\n"
                "Tu peux continuer à discuter avec moi pendant son exécution."
            )
            return self._record(text, response, "mission_launch", {"mission": mission["human_id"]})

        if lower in {"missions", "mes missions", "mission control", "liste des missions"}:
            return self._record(text, self.missions.format(), "missions_list")

        if lower in {"status", "statut", "état", "etat", "system status"}:
            status = self.status(remote_checks=False)
            integrations = status["integrations"]
            response = (
                "Agent-OS V8.0.0 — Paul\n"
                f"Ollama : {'OK' if status['ollama'].get('ok') else 'indisponible'} ({OLLAMA_MODEL})\n"
                f"Mémoire : {status['memory_count']} souvenir(s) actif(s)\n"
                f"Missions : {status['mission_count']}\n"
                f"LangGraph : {'actif' if integrations['langgraph'].get('ok') else 'fallback local'}\n"
                f"MAF : {'disponible' if integrations['maf'].get('ok') else 'optionnel/non installé'}\n"
                f"Agent Zero : {'configuré' if integrations['agent_zero'].get('configured') else 'non configuré'}\n"
                f"OpenHands : {'configuré' if integrations['openhands'].get('configured') else 'non configuré'}"
            )
            return self._record(text, response, "status")

        if any(marker in lower for marker in (
            "qu'est-ce que tu sais de moi", "qu est ce que tu sais de moi",
            "que sais-tu de moi", "que sais tu de moi", "ma mémoire", "ma memoire",
        )):
            return self._record(text, self._memory_summary(), "memory_query")

        if any(marker in lower for marker in (
            "comment je m'appelle", "comment je m appelle", "quel est mon prénom", "quel est mon prenom",
        )):
            first_name = self.memory.get("identity.first_name")
            response = (
                f"Tu t'appelles {first_name}." if first_name
                else "Je ne connais pas encore ton prénom. La mémoire V8 est vide au départ."
            )
            return self._record(text, response, "memory_query")

        learned = self.memory.extract_heuristic(text)
        if learned:
            if any(key == "identity.first_name" for key, _ in learned):
                first_name = self.memory.get("identity.first_name") or ""
                return self._record(text, f"D'accord, je retiens que tu t'appelles {first_name}.", "memory_write")
            response = "D'accord, je le garde en mémoire."
            return self._record(text, response, "memory_write")

        # Agenda write before generic interpretation.
        event = self.agenda.extract_event(text)
        if event:
            event_date, title = event
            created = self.agenda.add(event_date, title, source_text=text)
            response = (
                f"Ajouté au {event_date.strftime('%d/%m/%Y')} : {title}."
                if created else
                f"C'était déjà enregistré pour le {event_date.strftime('%d/%m/%Y')} : {title}."
            )
            return self._record(text, response, "agenda_write", {"date": event_date.isoformat()})

        # Agenda explicit query, including short contextual follow-up: “et le 12/10/2026 ?”
        target_date = parse_date_reference(text)
        contextual_agenda = bool(
            target_date
            and previous
            and previous.get("intent") == "agenda_query"
            and len(text.split()) <= 8
        )
        if (self.agenda.is_query(text) and target_date) or contextual_agenda:
            response = self.agenda.format_for(target_date)
            return self._record(text, response, "agenda_query", {"date": target_date.isoformat()})

        # Generic Paul conversation. The local LLM receives memory + recent context.
        try:
            response = self.llm.ask(text, system=self._system_prompt())
        except LLMError as exc:
            response = (
                "Je peux gérer la mémoire, l'agenda et Mission Control, mais Ollama n'est pas joignable "
                f"pour cette réponse générale. Détail : {exc}"
            )
        return self._record(text, response, "chat")
