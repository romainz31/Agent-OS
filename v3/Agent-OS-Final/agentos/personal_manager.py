from __future__ import annotations

import re

from typing import Any

from agentos.llm import LLMError
from agentos.manager import Manager as CoreManager


class PersonalManager(CoreManager):
    """Surcouche conversationnelle de Paul.

    Le moteur historique de ``agentos.manager.Manager`` reste responsable des
    missions, workers, approbations et notifications. Cette classe ne remplace
    que la couche relationnelle/conversationnelle afin de limiter les risques
    de régression sur l'orchestration existante.
    """

    RELATIONAL_COMMANDS = {
        "memory relations",
        "memory relationnelle",
        "mémoire relationnelle",
        "memoire relationnelle",
        "/memoryrelations",
        "/relations",
    }

    RELATIONAL_HISTORY_COMMANDS = {
        "memory history",
        "memory relation history",
        "historique relationnel",
        "historique mémoire",
        "historique memoire",
        "/memoryhistory",
        "/relationhistory",
    }

    MEMORY_STATS_COMMANDS = {
        "memory stats",
        "stats mémoire",
        "stats memoire",
        "/memorystats",
    }

    MEMORY_MAINTENANCE_COMMANDS = {
        "memory cleanup",
        "memory clean",
        "memory maintenance",
        "nettoie la mémoire",
        "nettoie la memoire",
        "maintenance mémoire",
        "maintenance memoire",
        "/memorycleanup",
        "/memorymaintenance",
    }

    MEMORY_FORGET_PREFIXES = (
        "memory forget ",
        "memory oublie ",
        "mémoire oublie ",
        "memoire oublie ",
        "/memoryforget ",
    )

    MEMORY_CORRECT_PREFIXES = (
        "memory correct ",
        "memory corrige ",
        "mémoire corrige ",
        "memoire corrige ",
        "/memorycorrect ",
    )

    # =========================================================
    # MEMORY ACTIONS
    # =========================================================

    @staticmethod
    def _first_change(
        changes: list[dict[str, Any]],
        status: str,
    ) -> dict[str, Any] | None:
        for change in changes:
            if str(change.get("status", "")) == status:
                return change
        return None

    def _memory_action_response(
        self,
        action: dict[str, Any],
    ) -> str | None:
        action_type = str(
            action.get(
                "type",
                "",
            )
        )

        if action_type == "forget":
            count = int(
                action.get(
                    "count",
                    0,
                )
                or 0
            )
            target = str(
                action.get(
                    "target",
                    "",
                )
                or ""
            ).strip()

            if count <= 0:
                if target:
                    return (
                        "Je n'ai trouvé aucun souvenir personnel actif "
                        f"correspondant à « {target} »."
                    )
                return (
                    "Je n'ai trouvé aucun souvenir personnel actif "
                    "à oublier."
                )

            if target:
                return f"C'est oublié : {target}."

            return "C'est oublié."

        if action_type != "relational_update":
            return None

        raw_changes = action.get(
            "changes",
            [],
        )
        changes = [
            change
            for change in raw_changes
            if isinstance(
                change,
                dict,
            )
        ]

        if not changes:
            return None

        replaced = self._first_change(
            changes,
            "replaced",
        )
        if replaced is not None:
            content = str(
                replaced.get(
                    "content",
                    "",
                )
                or ""
            ).strip()
            return (
                f"Mis à jour : {content}."
                if content
                else "C'est mis à jour."
            )

        categories = {
            str(change.get("category", ""))
            for change in changes
        }

        if categories == {"communication"}:
            return "Compris. J'appliquerai ça à mes réponses."

        if all(
            str(change.get("status", "")) == "unchanged"
            for change in changes
        ):
            return "Déjà pris en compte."

        if all(
            str(change.get("status", "")) in {"reinforced", "unchanged"}
            for change in changes
        ):
            return "C'est confirmé."

        return "C'est retenu."

    @staticmethod
    def _strip_command_prefix(
        message: str,
        prefixes: tuple[str, ...],
    ) -> str | None:
        clean = str(message or "").strip()
        lower = clean.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                return clean[len(prefix):].strip(" :.-")
        return None

    def _maintenance_response(self) -> str:
        result = self.memory.run_maintenance(
            persist=True
        )
        changes = (
            int(result.get("reclassified", 0))
            + int(result.get("merged", 0))
            + int(result.get("stale_emotions_removed", 0))
            + int(result.get("working_removed", 0))
        )

        if changes <= 0:
            return "Mémoire vérifiée : rien à nettoyer."

        parts = []
        if int(result.get("reclassified", 0)):
            parts.append(
                f"{int(result['reclassified'])} souvenir(s) reclassé(s)"
            )
        if int(result.get("merged", 0)):
            parts.append(
                f"{int(result['merged'])} doublon(s) fusionné(s)"
            )
        if int(result.get("stale_emotions_removed", 0)):
            parts.append(
                f"{int(result['stale_emotions_removed'])} état(s) émotionnel(s) périmé(s) archivé(s)"
            )
        if int(result.get("working_removed", 0)):
            parts.append(
                f"{int(result['working_removed'])} ancien(s) travail/travaux retiré(s)"
            )

        return "Mémoire nettoyée : " + ", ".join(parts) + "."

    def _explicit_memory_command_response(
        self,
        message: str,
    ) -> str | None:
        forget_target = self._strip_command_prefix(
            message,
            self.MEMORY_FORGET_PREFIXES,
        )
        if forget_target is not None:
            action = self.memory.forget_personal(
                forget_target,
                source="user_explicit",
                persist=True,
                track_action=False,
            )
            return self._memory_action_response(action)

        correction = self._strip_command_prefix(
            message,
            self.MEMORY_CORRECT_PREFIXES,
        )
        if correction is not None:
            if not correction:
                return (
                    "Précise le souvenir corrigé, par exemple : "
                    "memory correct Ma copine s'appelle Coralie."
                )

            self.memory.maybe_remember(correction)
            action = self.memory.consume_memory_action()
            if action is None:
                return (
                    "Je n'ai pas reconnu une information personnelle structurée "
                    "dans cette correction."
                )
            response = self._memory_action_response(action)
            return response or "C'est corrigé."

        return None

    def _category_memory_query_response(
        self,
        message: str,
    ) -> str | None:
        value = self._normalize(message)

        categories: tuple[tuple[str, tuple[str, ...]], ...] = (
            (
                "communication",
                (
                    "mes préférences de communication",
                    "mes preferences de communication",
                    "ma façon de communiquer",
                    "ma facon de communiquer",
                    "comment je préfère que tu me répondes",
                    "comment je prefere que tu me repondes",
                    "comment je veux que tu me répondes",
                    "comment je veux que tu me repondes",
                ),
            ),
            (
                "habits",
                (
                    "mes habitudes",
                    "mes routines",
                    "mes habitudes de travail",
                    "mes habitudes personnelles",
                ),
            ),
            (
                "interests",
                (
                    "mes centres d'intérêt",
                    "mes centres d interet",
                    "mes centres d’intérêt",
                    "mes intérêts",
                    "mes interets",
                ),
            ),
            (
                "relations",
                (
                    "mes relations",
                    "les personnes importantes",
                    "mes proches",
                ),
            ),
            (
                "preferences",
                (
                    "mes préférences personnelles",
                    "mes preferences personnelles",
                    "mes goûts personnels",
                    "mes gouts personnels",
                ),
            ),
        )

        for category, markers in categories:
            if any(marker in value for marker in markers):
                return self.memory.relational_category_summary(category)

        return None

    def _specific_personal_fact_response(
        self,
        message: str,
    ) -> str | None:
        raw = str(message or "").strip()
        value = self.memory._ascii(raw)

        relation_roles = {
            "copine": "ta copine",
            "compagne": "ta compagne",
            "compagnon": "ton compagnon",
            "femme": "ta femme",
            "mari": "ton mari",
            "frere": "ton frère",
            "soeur": "ta sœur",
            "mere": "ta mère",
            "pere": "ton père",
            "ami": "ton ami",
            "amie": "ton amie",
        }

        asks_name = any(
            marker in value
            for marker in (
                "comment s'appelle",
                "comment s appelle",
                "quel est le prenom",
                "quelle est le prenom",
                "le prenom de ma",
                "le prenom de mon",
                "tu sais comment s'appelle",
                "tu sais comment s appelle",
            )
        )

        if asks_name:
            for role, display in relation_roles.items():
                if re.search(rf"\b{re.escape(role)}\b", value):
                    remembered = self.memory.relation_value(role)
                    if remembered:
                        return f"{display.capitalize()} s'appelle {remembered}."
                    return f"Je n'ai pas le prénom de {display} en mémoire."

        favorite_match = re.search(
            r"(?:quel est|quelle est|c'est quoi|c est quoi)\s+mon\s+(.{2,60}?)\s+prefere",
            value,
        )
        if favorite_match:
            subject = favorite_match.group(1).strip()
            remembered = self.memory.favorite_value(subject)
            if remembered:
                return f"Ton {subject} préféré est {remembered}."
            return f"Je n'ai pas ton {subject} préféré en mémoire."

        return None

    def _direct_memory_response(
        self,
        message: str,
    ) -> str | None:
        # ``maybe_remember`` vient juste d'être appelé par le Manager historique.
        # On consomme ici l'action transitoire pour éviter de laisser le LLM
        # transformer une simple préférence en long discours ou en mission.
        action = self.memory.consume_memory_action()
        if action is not None:
            response = self._memory_action_response(
                action
            )
            if response is not None:
                return response

        explicit_command = self._explicit_memory_command_response(
            message
        )
        if explicit_command is not None:
            return explicit_command

        command = self._normalize(
            message
        )

        if command in self.MEMORY_MAINTENANCE_COMMANDS:
            return self._maintenance_response()

        if command in self.RELATIONAL_COMMANDS:
            return self.memory.relational_full_context()

        if command in self.RELATIONAL_HISTORY_COMMANDS:
            return self.memory.relational_history_summary()

        if command in self.MEMORY_STATS_COMMANDS:
            stats = self.memory.stats()
            return (
                "Mémoire : "
                f"profil {stats['profile']} | "
                f"relationnel {stats['relational']} | "
                f"historique relationnel {stats['relational_history']} | "
                f"durable {stats['long_term']} | "
                f"épisodique {stats['episodic']} | "
                f"émotionnel {stats['emotional_current']}."
            )

        specific_fact = self._specific_personal_fact_response(
            message
        )
        if specific_fact is not None:
            return specific_fact

        category_response = self._category_memory_query_response(
            message
        )
        if category_response is not None:
            return category_response

        return super()._direct_memory_response(
            message
        )

    # =========================================================
    # CONVERSATION POLICY
    # =========================================================

    def _message_needs_operational_context(
        self,
        message: str,
    ) -> bool:
        if self._extract_mission_reference(
            message
        ) is not None:
            return True

        if self._looks_like_operational_question(
            message
        ):
            return True

        normalized = self._normalize(
            message
        )

        return any(
            marker in normalized
            for marker in (
                "agent-os",
                "agent os",
                "mission",
                "missions",
                "worker",
                "workers",
                "researcher",
                "developer",
                "tester",
                "planner",
                "approbation",
                "autorisation",
                "équipe agent",
                "equipe agent",
            )
        )

    def _conversation(
        self,
        message: str,
    ) -> str:
        operational_needed = (
            self._message_needs_operational_context(
                message
            )
        )

        operational_context = (
            self._operational_context()
            if operational_needed
            else (
                "(non fourni : le message courant n'est pas "
                "une question opérationnelle)"
            )
        )

        system = """
Tu es Paul, le Manager personnel et opérationnel d'Agent-OS.

TA PRIORITÉ EST LE MESSAGE COURANT.
La mémoire est une aide silencieuse. Elle ne doit jamais devenir le sujet de
la réponse simplement parce qu'elle contient des informations intéressantes.

RÈGLES RELATIONNELLES
- Applique réellement les préférences de communication présentes dans la
  mémoire relationnelle, sans annoncer que tu les appliques.
- Ne récite pas les souvenirs de l'utilisateur pour montrer que tu t'en
  souviens.
- Mentionne un souvenir personnel uniquement lorsqu'il améliore directement
  la réponse au message courant.
- N'invente jamais une habitude, une expérience vécue, une émotion, une
  préférence, une relation ou un comportement probable.
- N'écris jamais « tu passes probablement beaucoup de temps à... » ou une
  variante si ce fait n'est pas explicitement présent dans la mémoire.
- Le message courant est prioritaire sur un souvenir ancien en cas de conflit.
- Ne dis pas spontanément « c'est enregistré dans ma mémoire » sauf si
  l'utilisateur parle explicitement de mémoire.

RÈGLES DE CONVERSATION
- Réponds directement à ce que l'utilisateur vient de dire ou demander.
- N'ouvre pas un ancien sujet juste parce qu'il apparaît dans la conversation
  récente.
- Ne reparle pas d'une ancienne mission dans une conversation personnelle si
  l'utilisateur ne l'a pas demandée.
- Ne propose pas de mission ou de travail supplémentaire sans besoin réel.
- Ne termine pas systématiquement par une question, « n'hésite pas », une
  proposition générique ou une relance artificielle.
- Pour une question simple, fais court. Pour une demande complexe, développe
  seulement ce qui est utile.
- Réponds naturellement en français et tutoie toujours l'utilisateur.

MÉMOIRE ÉMOTIONNELLE
- L'état émotionnel est temporaire et incertain. Une observation ancienne
  appartient à l'historique et ne décrit pas forcément l'état actuel.
- Adapte légèrement la densité ou le ton seulement si l'estimation est assez
  fiable.
- Ne diagnostique jamais et ne transforme jamais une humeur en trait durable.

AGENT-OS / MISSIONS
- Si le bloc ÉTAT AGENT-OS indique qu'il n'est pas fourni, ne parle pas des
  missions, workers ou approbations et n'en invente aucun.
- S'il est fourni, utilise uniquement ces données factuelles pour parler de
  l'état du système.
- Les missions restent séparées de la mémoire personnelle.
"""

        prompt = f"""
MÉMOIRE PERSONNELLE PERTINENTE :

{self.memory.personal_conversation_context(message)}

ÉTAT AGENT-OS :

{operational_context}

MESSAGE COURANT :

{message}
"""

        try:
            return self.llm.chat(
                prompt,
                system=system,
            )

        except LLMError as exc:
            return (
                "Ollama inaccessible : "
                f"{exc}"
            )
