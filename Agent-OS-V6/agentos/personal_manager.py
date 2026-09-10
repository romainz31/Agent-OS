from __future__ import annotations

import re

from typing import Any

from agentos.conversation import ConversationTracker
from agentos.llm import LLMError
from agentos.manager import Manager as CoreManager
from agentos.research import ResearchGateway, ReliableResearcherWorker


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

    CONVERSATION_STATUS_COMMANDS = {
        "conversation status",
        "conversation statut",
        "statut conversation",
        "fil status",
        "fil conversation",
        "conversation debug",
    }

    CONVERSATION_HISTORY_COMMANDS = {
        "conversation history",
        "historique conversation",
        "historique conversations",
        "anciens fils",
    }

    CONVERSATION_NEW_COMMANDS = {
        "nouvelle conversation",
        "nouveau fil",
        "nouvelle discussion",
        "conversation reset",
        "reset conversation",
    }

    CONVERSATION_RESUME_COMMANDS = {
        "on en était où",
        "on en etait ou",
        "on en étais où",
        "on en etais ou",
        "où en était on",
        "ou en etait on",
        "où en étions nous",
        "ou en etions nous",
        "de quoi on parlait",
        "de quoi parlait on",
        "on parlait de quoi",
        "rappelle moi où on en était",
        "rappelle moi ou on en etait",
        "reprends la conversation",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.conversation_tracker = ConversationTracker()
        # Première installation : récupère le tampon V4.7 afin de conserver
        # immédiatement une continuité après la mise à jour.
        try:
            self.conversation_tracker.bootstrap_from_session(
                self.memory.data.get("session", [])
            )
        except Exception:
            # Le suivi de conversation ne doit jamais empêcher Paul de démarrer.
            pass

        self.research_gateway = ResearchGateway(
            llm=self.llm,
            permissions=self.permissions,
            conversation_tracker=self.conversation_tracker,
        )

        # Remplace le Researcher historique par la variante robuste qui teste
        # plusieurs backends DDGS séparément. Un backend défaillant ne doit
        # plus faire échouer toute une mission de recherche.
        self.engine.register(
            ReliableResearcherWorker(
                self.llm,
                self.permissions,
            )
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

    def _scrub_conversation_for_memory_action(
        self,
        action: dict[str, Any] | None,
    ) -> None:
        if not isinstance(action, dict):
            return
        if str(action.get("type", "")) != "forget":
            return
        values = action.get("forgotten_values", [])
        if not isinstance(values, (list, tuple, set)):
            return
        try:
            self.conversation_tracker.forget_values(values)
        except Exception:
            pass

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
            self._scrub_conversation_for_memory_action(action)
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
            self._scrub_conversation_for_memory_action(action)
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
    # PERSISTENT CONVERSATION THREAD V4.8
    # =========================================================

    def _conversation_command_response(
        self,
        message: str,
    ) -> str | None:
        normalized = self._normalize(message)

        if normalized in self.CONVERSATION_STATUS_COMMANDS:
            return self.conversation_tracker.status_summary()

        if normalized in self.CONVERSATION_HISTORY_COMMANDS:
            return self.conversation_tracker.history_summary()

        if normalized in self.CONVERSATION_NEW_COMMANDS:
            self.conversation_tracker.new_thread()
            try:
                self.memory.clear_session()
            except Exception:
                pass
            return (
                "Nouveau fil de conversation créé. "
                "Les souvenirs personnels restent conservés, mais l'ancien "
                "contexte de discussion n'est plus injecté dans les réponses."
            )

        if (
            normalized in self.CONVERSATION_RESUME_COMMANDS
            or self.conversation_tracker.is_resume_query(message)
        ):
            return self.conversation_tracker.resume_response()

        return None

    def _track_exchange(
        self,
        user_message: str,
        assistant_message: str,
    ) -> None:
        try:
            self.conversation_tracker.add_exchange(
                user_message,
                assistant_message,
            )
        except Exception:
            # Une panne du journal conversationnel ne doit jamais casser Paul.
            pass

    # =========================================================
    # FACTUAL RESEARCH V4.9
    # =========================================================

    def _research_command_response(
        self,
        message: str,
    ) -> str | None:
        gateway = getattr(
            self,
            "research_gateway",
            None,
        )
        if gateway is None:
            return None
        return gateway.command_response(message)

    def _research_response(
        self,
        message: str,
    ) -> str | None:
        gateway = getattr(
            self,
            "research_gateway",
            None,
        )
        if gateway is None:
            return None

        command = gateway.command_response(message)
        if command is not None:
            return command

        if not gateway.should_research(message):
            return None

        return gateway.answer(message)

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

    @classmethod
    def _is_personal_state_message(cls, message: str) -> bool:
        if ConversationTracker.transient_state_kind(message) is not None:
            return True

        normalized = cls._normalize(message)
        return any(
            marker in normalized
            for marker in (
                "comment je vais",
                "comment je me sens",
                "mon humeur",
                "mon moral",
                "mon stress",
                "ma motivation",
                "mon énergie",
                "mon energie",
                "est ce que je t avais dit que j etais fatigue",
                "est-ce que je t'avais dit que j'étais fatigué",
            )
        )

    @classmethod
    def _sanitize_response_for_user(
        cls,
        message: str,
        response: str,
    ) -> str:
        """Nettoie les tics de soutien hors sujet avant affichage.

        Le prompt reste la première protection, mais un petit modèle local peut
        ignorer une instruction de style. Cette barrière empêche qu'un ancien
        état émotionnel soit recyclé dans une réponse factuelle sans lien.
        """
        raw = str(response or "").strip()
        if not raw:
            return raw

        state_relevant = cls._is_personal_state_message(message)
        parts = re.split(r"(?<=[.!?])\s+|\n+", raw)

        generic_closings = (
            "n hesite pas",
            "si tu as besoin",
            "si tu as d autres questions",
            "si tu veux approfondir",
            "si tu veux en savoir plus",
            "fais moi savoir",
            "ton bien etre",
            "ton confort",
            "reviens quand tu es pret",
            "reviens quand tu seras pret",
        )

        irrelevant_state_markers = (
            "ton energie",
            "tu as de l energie",
            "tu n as pas d energie",
            "ta fatigue",
            "tu es fatigue",
            "tu es creve",
            "repose toi",
            "besoin de repos",
            "ton repos",
            "ton moral",
            "ton humeur",
            "ton stress",
            "ta motivation",
            "ton bien etre",
            "ton confort",
        )

        kept: list[str] = []
        for part in parts:
            part = " ".join(str(part or "").split()).strip()
            if not part:
                continue
            normalized = ConversationTracker._normalized_words(part)

            if any(marker in normalized for marker in generic_closings):
                continue

            if (
                not state_relevant
                and any(
                    marker in normalized
                    for marker in irrelevant_state_markers
                )
            ):
                continue

            kept.append(part)

        cleaned = " ".join(kept).strip()
        return cleaned or raw

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
- Le bloc FIL DE CONVERSATION ACTIF décrit la continuité de la discussion.
  Utilise-le pour comprendre les pronoms, les références comme « ça »,
  « celui-là », « comme on disait », et les questions de suivi.
- Ne prétends jamais qu'un détail figure dans le fil s'il n'y figure pas.
- Réponds directement à ce que l'utilisateur vient de dire ou demander.
- N'ouvre pas un ancien sujet juste parce qu'il apparaît dans la conversation
  récente.
- Ne reparle pas d'une ancienne mission dans une conversation personnelle si
  l'utilisateur ne l'a pas demandée.
- Ne propose pas de mission ou de travail supplémentaire sans besoin réel.
- Ne termine pas par « n'hésite pas », « si tu as besoin », « ton bien-être
  reste ma priorité », « ton confort reste ma priorité » ou une relance
  générique équivalente. Réponds puis arrête-toi.
- Pour une question simple, fais court. Pour une demande complexe, développe
  seulement ce qui est utile.
- Réponds naturellement en français et tutoie toujours l'utilisateur.

MÉMOIRE ÉMOTIONNELLE
- L'état émotionnel est temporaire et incertain. Une observation ancienne
  appartient à l'historique et ne décrit pas forcément l'état actuel.
- Si le message courant ne parle pas explicitement de l'état de l'utilisateur,
  ne mentionne absolument pas sa fatigue, son repos, son énergie, son stress,
  sa motivation, son confort ou son bien-être.
- Si l'utilisateur a ensuite indiqué que l'état temporaire est terminé ou
  inversé, ne répète plus l'ancien conseil (« repose-toi », etc.).
- Adapte légèrement la densité ou le ton seulement si l'estimation est assez
  fiable et pertinente pour la demande actuelle.
- Ne diagnostique jamais et ne transforme jamais une humeur en trait durable.

FIABILITÉ FACTUELLE
- N'affirme pas comme certain un fait externe précis si le bloc de recherche
  n'en fournit pas la preuve.
- Les questions factuelles vérifiables sont normalement prises en charge par
  le Researcher avant d'arriver ici. Si un détail manque encore, dis que tu ne
  peux pas le confirmer au lieu de l'inventer.
- Une ancienne réponse de Paul n'est jamais une source fiable à elle seule.

AGENT-OS / MISSIONS
- Si le bloc ÉTAT AGENT-OS indique qu'il n'est pas fourni, ne parle pas des
  missions, workers ou approbations et n'en invente aucun.
- S'il est fourni, utilise uniquement ces données factuelles pour parler de
  l'état du système.
- Les missions restent séparées de la mémoire personnelle.
"""

        prompt = f"""
MÉMOIRE PERSONNELLE PERTINENTE :

{self.memory.personal_conversation_context(message, include_session=False)}

FIL DE CONVERSATION ACTIF :

{self.conversation_tracker.context_for(message, limit=10)}

ÉTAT AGENT-OS :

{operational_context}

MESSAGE COURANT :

{message}
"""

        try:
            response = self.llm.chat(
                prompt,
                system=system,
            )
            return self._sanitize_response_for_user(
                message,
                response,
            )

        except LLMError as exc:
            return (
                "Ollama inaccessible : "
                f"{exc}"
            )

    # =========================================================
    # AUTONOMOUS MANAGER V4.8
    # =========================================================

    def set_autonomy_controller(
        self,
        controller,
    ) -> None:
        self.autonomy_controller = controller

    def _autonomy(self):
        return getattr(
            self,
            "autonomy_controller",
            None,
        )

    def notify(
        self,
        text: str,
    ) -> None:
        controller = self._autonomy()

        if controller is not None:
            try:
                controller.on_worker_event(
                    text
                )
            except Exception as exc:
                controller.record(
                    "event_recovery_error",
                    level="warning",
                    detail=str(exc),
                )

        # Le moteur historique reste la source de vérité pour les statuts,
        # notifications et la mémoire opérationnelle. Si l'autonomie a déjà
        # réinitialisé la tâche, _refresh_mission verra simplement la mission
        # redevenue active au lieu de la figer en échec.
        super().notify(
            text
        )

    def _autonomy_command_response(
        self,
        message: str,
    ) -> str | None:
        controller = self._autonomy()
        if controller is None:
            return None
        return controller.command_response(
            message
        )

    def _new_missions_since(
        self,
        previous_ids: set[str],
    ) -> list:
        return [
            mission
            for mission in self.missions.list()
            if mission.id not in previous_ids
        ]

    def _apply_new_mission_policy(
        self,
        mission,
        message: str,
    ) -> str:
        controller = self._autonomy()
        if controller is None:
            return ""

        result = controller.apply_creation_policy(
            mission,
            message,
        )

        bits = []
        priority = result.get(
            "priority"
        )
        deadline = result.get(
            "deadline"
        )

        if priority is not None:
            bits.append(
                "priorité "
                + controller.PRIORITY_LABELS[
                    priority
                ]
            )

        if deadline is not None:
            bits.append(
                "échéance "
                + deadline.isoformat(
                    timespec="minutes"
                )
            )

        if not bits:
            return ""

        return (
            "\n\nPilotage Manager : "
            + " | ".join(bits)
            + " | autonomie active."
        )

    def handle(
        self,
        message: str,
    ) -> str:
        value = str(
            message
            or ""
        ).strip()

        if not value:
            return ""

        conversation_response = (
            self._conversation_command_response(value)
        )
        if conversation_response is not None:
            return conversation_response

        autonomy_response = (
            self._autonomy_command_response(
                value
            )
        )

        if autonomy_response is not None:
            self.memory.add_session(
                "user",
                value,
            )
            self.memory.add_session(
                "assistant",
                autonomy_response,
            )
            self._track_exchange(value, autonomy_response)
            return autonomy_response

        research_response = self._research_response(value)
        if research_response is not None:
            research_response = self._sanitize_response_for_user(
                value,
                research_response,
            )
            self.memory.add_session(
                "user",
                value,
            )
            self.memory.add_session(
                "assistant",
                research_response,
            )
            self._track_exchange(value, research_response)
            return research_response

        previous_ids = set(
            self.missions.missions
        )

        response = super().handle(
            value
        )
        response = self._sanitize_response_for_user(
            value,
            response,
        )

        controller = self._autonomy()
        if controller is None:
            self._track_exchange(value, response)
            return response

        new_missions = self._new_missions_since(
            previous_ids
        )

        final_response = response

        if new_missions:
            # Une interaction utilisateur ne crée normalement qu'une mission.
            # En cas de changement futur du routeur, on applique néanmoins la
            # politique à toutes les nouvelles missions détectées.
            suffixes = []

            for mission in reversed(
                new_missions
            ):
                suffix = self._apply_new_mission_policy(
                    mission,
                    value,
                )
                if suffix:
                    suffixes.append(suffix)

            if suffixes:
                final_response = response + "".join(suffixes)

        self._track_exchange(value, final_response)
        return final_response

    def _operational_context(
        self,
    ) -> str:
        base = super()._operational_context()
        controller = self._autonomy()
        if controller is None:
            return base
        return (
            base
            + "\n\n"
            + controller.status_summary()
        )
