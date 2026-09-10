from __future__ import annotations

import re
from datetime import datetime

from typing import Any

from agentos.agenda import PersonalAgenda
from agentos.config import DATA_DIR

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

        # V6.4 : agenda distinct de la mémoire personnelle et des missions.
        # Une panne de l'agenda ne doit jamais empêcher Paul de démarrer.
        self.agenda = None
        try:
            self.agenda = PersonalAgenda(
                DATA_DIR / "agenda.db",
                personal_memory_provider=lambda: getattr(
                    self.memory,
                    "personal_v2",
                    None,
                ),
            )
        except Exception:
            self.agenda = None

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
    # PERSONAL AGENDA / TODO V6.4
    # =========================================================

    def _v64_agenda_response(
        self,
        message: str,
    ) -> str | None:
        agenda = getattr(self, "agenda", None)
        if agenda is None:
            return None
        try:
            return agenda.handle_message(message)
        except Exception:
            return None

    def _v64_agenda_context(
        self,
        message: str,
    ) -> str:
        agenda = getattr(self, "agenda", None)
        if agenda is None:
            return "(agenda personnel indisponible)"
        try:
            return agenda.context_for(message)
        except Exception:
            return "(agenda personnel indisponible)"

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
    # MEMORY-FIRST RECALL V6.2.1
    # =========================================================

    @classmethod
    def _v621_question_like(
        cls,
        message: str,
    ) -> bool:
        raw = str(message or "").strip()
        if not raw:
            return False

        normalized = cls._normalize(raw)
        if raw.endswith("?"):
            return True

        return normalized.startswith(
            (
                "qui ",
                "que ",
                "quoi ",
                "quel ",
                "quelle ",
                "quels ",
                "quelles ",
                "ou ",
                "où ",
                "quand ",
                "jusqu a quand ",
                "comment ",
                "pourquoi ",
                "combien ",
                "est ce que ",
                "est-ce que ",
                "tu te souviens ",
                "rappelle moi ",
                "rappelle-moi ",
            )
        )

    @classmethod
    def _v621_explicit_web_request(
        cls,
        message: str,
    ) -> bool:
        normalized = cls._normalize(message)
        return any(
            marker in normalized
            for marker in (
                "cherche sur internet",
                "recherche sur internet",
                "cherche sur le web",
                "recherche sur le web",
                "va voir sur internet",
                "verifie sur internet",
                "vérifie sur internet",
                "verifie sur le web",
                "vérifie sur le web",
                "google ",
                "sur internet pour moi",
            )
        )

    def _v621_known_person_names(self) -> set[str]:
        names: set[str] = set()

        try:
            items = self.memory.relational_active_items(
                "relations"
            )
        except Exception:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            value = self._normalize(
                str(item.get("value", "") or "")
            )
            if len(value) < 2:
                continue

            names.add(value)
            for token in value.split():
                token = token.strip(" .,!?:;()[]{}'\"")
                if len(token) >= 3:
                    names.add(token)

        return names

    def _v621_is_personal_memory_query(
        self,
        message: str,
    ) -> bool:
        """Détermine si la réponse doit venir de la mémoire privée.

        Une question sur la vie de l'utilisateur ou sur une personne connue
        ne doit jamais déclencher une recherche Web par défaut. L'utilisateur
        peut explicitement demander une recherche Internet pour lever ce garde.
        """
        if not self._v621_question_like(message):
            return False

        if self._v621_explicit_web_request(message):
            return False

        # V6.2.3 : l'utilisateur écrit souvent naturellement sans apostrophe
        # (jai, javais, jsuis, jusqua). On normalise seulement pour l'intention.
        normalized = self._v623_chat_normalize(message)

        explicit_recall = any(
            marker in normalized
            for marker in (
                "tu te souviens",
                "te souviens tu",
                "je t ai dit",
                "je t avais dit",
                "je t ai raconte",
                "je t avais raconte",
                "qu est ce que je t ai dit",
                "qu est-ce que je t ai dit",
                "rappelle moi ce que",
                "rappelle-moi ce que",
                "d apres ce que je t ai dit",
                "d'après ce que je t'ai dit",
            )
        )
        if explicit_recall:
            return True

        first_person_past = bool(
            re.search(
                r"\b(?:j ai|j avais|j etais|je suis alle|je suis allee|"
                r"je t ai|je t avais|je faisais|on a|nous avons)\b",
                normalized,
            )
        )

        temporal = any(
            marker in normalized
            for marker in (
                "hier",
                "avant hier",
                "avant-hier",
                "aujourd hui",
                "aujourd'hui",
                "ce matin",
                "hier soir",
                "la semaine derniere",
                "la semaine dernière",
                "le mois dernier",
                "jusqu a quand",
                "jusqu'à quand",
            )
        )

        relation_anchor = any(
            marker in normalized
            for marker in (
                "ma copine",
                "mon copain",
                "ma compagne",
                "mon compagnon",
                "ma femme",
                "mon mari",
                "ma mere",
                "ma mère",
                "mon pere",
                "mon père",
                "mon frere",
                "mon frère",
                "ma soeur",
                "ma sœur",
                "mon ami",
                "mon amie",
                "mes parents",
            )
        )

        known_person = any(
            name and re.search(
                rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])",
                normalized,
            )
            for name in self._v621_known_person_names()
        )

        try:
            memory_evidence = (
                self.memory.relevant_personal_summary(
                    message,
                    limit=8,
                )
                is not None
            )
        except Exception:
            memory_evidence = False

        possessive = bool(
            re.search(
                r"\b(?:mon|ma|mes|notre|nos)\b",
                normalized,
            )
        )

        if first_person_past:
            return True
        if relation_anchor:
            return True
        if known_person:
            return True
        if memory_evidence and (temporal or possessive):
            return True

        # V6.2.2 : une relance comme "comment est-elle partie ?" peut ne plus
        # contenir le prénom. Si le fil utilisateur récent parle d'un proche,
        # on reste en mémoire privée au lieu d'envoyer le pronom sur le Web.
        if self._v622_private_followup_from_context(
            message
        ):
            return True

        return False

    def _v621_personal_recall_context(
        self,
        message: str,
    ) -> str:
        if not self._v621_is_personal_memory_query(message):
            return (
                "NON — réponse normale. La recherche externe reste possible "
                "si elle est réellement nécessaire."
            )

        try:
            focused = self.memory.relevant_personal_summary(
                message,
                limit=8,
            )
        except Exception:
            focused = None

        if focused:
            return (
                "OUI — QUESTION SUR LA MÉMOIRE PERSONNELLE.\n"
                "Réponds d'abord avec les souvenirs ci-dessous. N'utilise "
                "aucune identité homonyme trouvée sur Internet.\n\n"
                "RAPPEL CIBLÉ :\n"
                + focused
            )

        return (
            "OUI — QUESTION SUR LA MÉMOIRE PERSONNELLE.\n"
            "Aucun souvenir ciblé n'a été retrouvé par l'index. Vérifie le "
            "fil actif et la mémoire personnelle fournis plus bas. Si la "
            "réponse n'y figure pas, dis simplement que tu ne t'en souviens pas."
        )


    # =========================================================
    # PERSONAL MEMORY REASONING V6.2.2
    # =========================================================

    @classmethod
    def _v622_reference_followup(
        cls,
        message: str,
    ) -> bool:
        normalized = cls._normalize(message)
        return bool(
            re.search(
                r"\b(?:elle|il|lui|elles|ils|son|sa|ses|leur|leurs)\b",
                normalized,
            )
            or normalized.startswith(
                (
                    "comment est elle ",
                    "comment est il ",
                    "ou est elle ",
                    "ou est il ",
                    "où est elle ",
                    "où est il ",
                    "quand est elle ",
                    "quand est il ",
                    "avec quoi est elle ",
                    "avec quoi est il ",
                )
            )
        )

    def _v622_recent_user_context(
        self,
        message: str,
        *,
        limit: int = 8,
    ) -> str:
        tracker = getattr(
            self,
            "conversation_tracker",
            None,
        )
        if tracker is None:
            return "(aucun fil utilisateur disponible)"

        try:
            return tracker.user_context_for(
                message,
                limit=limit,
            )
        except Exception:
            return "(fil utilisateur indisponible)"

    def _v622_private_followup_from_context(
        self,
        message: str,
    ) -> bool:
        """Relie 'elle/il/lui' au dernier contexte personnel utilisateur.

        Cette vérification a lieu avant toute recherche Web. Elle ne tente pas
        de résoudre le pronom : elle décide seulement que le Web est le mauvais
        outil tant que le contexte privé peut contenir le référent.
        """
        if not self._v621_question_like(message):
            return False
        if self._v621_explicit_web_request(message):
            return False
        if not self._v622_reference_followup(message):
            return False

        recent = self._normalize(
            self._v622_recent_user_context(
                message,
                limit=8,
            )
        )
        if not recent:
            return False

        relation_markers = (
            "ma copine",
            "mon copain",
            "ma compagne",
            "mon compagnon",
            "ma femme",
            "mon mari",
            "ma mere",
            "ma mère",
            "mon pere",
            "mon père",
            "mon frere",
            "mon frère",
            "ma soeur",
            "ma sœur",
            "mon ami",
            "mon amie",
            "mes parents",
        )

        if any(marker in recent for marker in relation_markers):
            return True

        for name in self._v621_known_person_names():
            if name and re.search(
                rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])",
                recent,
            ):
                return True

        return False

    def _v622_personal_reasoning_context(
        self,
        message: str,
    ) -> str:
        if not self._v621_is_personal_memory_query(message):
            return (
                "NON — ce tour n'est pas un rappel personnel."
            )

        try:
            focused = self.memory.relevant_personal_summary(
                message,
                limit=10,
            )
        except Exception:
            focused = None

        user_context = self._v622_recent_user_context(
            message,
            limit=10,
        )

        return (
            "OUI — RAISONNEMENT SUR MÉMOIRE PERSONNELLE.\n"
            "Règle de preuve : seules les déclarations utilisateur et les "
            "souvenirs personnels structurés peuvent servir de faits. Les "
            "anciennes réponses de Paul ne sont jamais des souvenirs vécus.\n\n"
            "SOUVENIRS CIBLÉS :\n"
            + (focused or "(aucun souvenir structuré ciblé)")
            + "\n\nFIL UTILISATEUR UNIQUEMENT :\n"
            + user_context
        )


    # =========================================================
    # MEMORY COHERENCE / CHAT FRENCH V6.2.3
    # =========================================================

    @classmethod
    def _v623_chat_normalize(
        cls,
        message: str,
    ) -> str:
        """Normalise quelques formes naturelles/SMS sans corriger le message."""
        value = cls._normalize(message)
        replacements = (
            (r"\bjai\b", "j ai"),
            (r"\bjavais\b", "j avais"),
            (r"\bjetais\b", "j etais"),
            (r"\bjsuis\b", "je suis"),
            (r"\bjusqua\b", "jusqu a"),
            (r"\bcest\b", "c est"),
            (r"\bquest ce\b", "qu est ce"),
        )
        for pattern, replacement in replacements:
            value = re.sub(pattern, replacement, value)
        return " ".join(value.split())

    @classmethod
    def _v623_personal_statement(
        cls,
        message: str,
    ) -> bool:
        """Détecte une déclaration sur la vie de l'utilisateur.

        Une déclaration personnelle n'a aucune raison de déclencher une
        recherche Web automatique : le Web ne peut pas savoir ce que vient de
        vivre l'utilisateur.
        """
        if cls._v621_question_like(message):
            return False
        if cls._v621_explicit_web_request(message):
            return False

        normalized = cls._v623_chat_normalize(message)
        if not normalized:
            return False

        first_person = bool(
            re.search(
                r"\b(?:j ai|j avais|j etais|je suis|je vais|je viens|je pars|"
                r"je rentre|je retourne|je fais|je travaille|on a|nous avons)\b",
                normalized,
            )
        )
        relation = any(
            marker in normalized
            for marker in (
                "ma copine", "mon copain", "ma compagne", "mon compagnon",
                "ma femme", "mon mari", "ma mere", "mon pere", "ma soeur",
                "mon frere", "mon ami", "mon amie", "mes parents",
            )
        )
        temporal = bool(
            re.search(
                r"\b(?:aujourd hui|hier|avant hier|demain|ce matin|ce soir|"
                r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
                r"semaine derniere|mois dernier|il y a)\b",
                normalized,
            )
        )

        return first_person or (relation and temporal)

    def _v623_personal_statement_has_explicit_anchor(
        self,
        message: str,
    ) -> bool:
        normalized = self._v623_chat_normalize(message)
        relation = any(
            marker in normalized
            for marker in (
                "ma copine", "mon copain", "ma compagne", "mon compagnon",
                "ma femme", "mon mari", "ma mere", "mon pere", "ma soeur",
                "mon frere", "mon ami", "mon amie", "mes parents",
            )
        )
        if relation:
            return True

        for name in self._v621_known_person_names():
            if name and re.search(
                rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])",
                normalized,
            ):
                return True
        return False

    def _v623_timeline_context(
        self,
        message: str,
    ) -> str:
        normalized = self._v623_chat_normalize(message)
        asks_latest = any(
            marker in normalized
            for marker in (
                "derniere fois",
                "dernier fois",
                "la derniere fois",
                "pour la derniere fois",
            )
        )
        if not asks_latest:
            return "(aucune comparaison chronologique demandée)"

        try:
            item = self.memory.latest_episodic_match(message)
        except Exception:
            item = None

        if not isinstance(item, dict):
            return (
                "Aucun événement personnel correspondant n'a été retrouvé. "
                "Ne cherche pas sur le Web : demande à l'utilisateur si besoin."
            )

        content = str(item.get("content", "") or "").strip()
        event_date = str(item.get("event_date", "") or "").strip()
        return (
            "DERNIER ÉVÉNEMENT PERSONNEL CORRESPONDANT\n"
            f"- date de l'événement : {event_date or '(date exacte inconnue)'}\n"
            f"- souvenir utilisateur : {content}\n"
            "Cette date décrit quand l'événement s'est produit, pas quand il a "
            "été raconté. Utilise ce bloc comme source prioritaire."
        )


    # =========================================================
    # PERSONAL MEMORY V2 ROUTING V6.3
    # =========================================================

    def _v63_memory_store(self):
        return getattr(self.memory, "personal_v2", None)

    def _v63_last_user_statement(self) -> str | None:
        try:
            context = self._v622_recent_user_context(
                "",
                limit=10,
            )
        except Exception:
            return None

        lines = []
        for line in str(context or "").splitlines():
            line = line.strip()
            if line.lower().startswith("user:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    lines.append(value)
        return lines[-1] if lines else None

    def _v63_enriched_private_query(
        self,
        message: str,
    ) -> str:
        value = str(message or "").strip()
        try:
            followup = self._v622_reference_followup(value)
        except Exception:
            followup = False

        if not followup:
            return value

        last_user = self._v63_last_user_statement()
        if not last_user:
            return value

        return (
            value
            + "\nContexte utilisateur précédent : "
            + last_user
        )

    def _v63_personal_memory_owns(
        self,
        message: str,
    ) -> bool:
        try:
            if self.memory.personal_memory_v2_should_own(message):
                return True
        except Exception:
            pass

        try:
            if self._v622_private_followup_from_context(message):
                return True
        except Exception:
            pass

        try:
            if self._v621_is_personal_memory_query(message):
                return True
        except Exception:
            pass

        return False

    def _v63_personal_statement(
        self,
        message: str,
    ) -> bool:
        store = self._v63_memory_store()
        if store is None:
            try:
                return self._v623_personal_statement(message)
            except Exception:
                return False
        try:
            return bool(store.looks_personal_statement(message))
        except Exception:
            return False

    def _v63_personal_memory_context(
        self,
        message: str,
    ) -> str:
        query = self._v63_enriched_private_query(message)
        try:
            return self.memory.personal_memory_v2_context(
                query,
                limit=8,
            )
        except Exception:
            return "(mémoire personnelle V2 indisponible)"

    def _v63_direct_personal_answer(
        self,
        message: str,
    ) -> str | None:
        if not self._v63_personal_memory_owns(message):
            return None
        query = self._v63_enriched_private_query(message)
        store = self._v63_memory_store()
        if store is None:
            return None
        try:
            # L'enrichissement par le dernier message utilisateur permet à une
            # relance « comment est-elle partie ? » de retrouver Coralie sans
            # réintroduire les anciennes réponses de Paul.
            return store.direct_answer(query)
        except Exception:
            return None

    def _v63_memory_command_response(
        self,
        message: str,
    ) -> str | None:
        normalized = self._v623_chat_normalize(message)
        if normalized in {
            "memory v2",
            "memory v2 status",
            "memoire v2",
            "memoire v2 status",
            "personal memory v2",
        }:
            return self.memory.personal_memory_v2_status()

        prefixes = (
            "memory v2 search ",
            "memoire v2 cherche ",
            "memoire v2 recherche ",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                raw = str(message or "").strip()
                target = raw[len(prefix):].strip() if len(raw) >= len(prefix) else ""
                if not target:
                    return "Précise ce que tu veux rechercher dans la mémoire V2."
                return self.memory.personal_memory_v2_context(
                    target,
                    limit=12,
                )
        return None


    # =========================================================
    # PERSONAL ACTOR IDENTITY / PRIVATE QUERY GUARD V6.3.1
    # =========================================================

    def _v631_private_query_guard(
        self,
        message: str,
    ) -> bool:
        """Protège les questions sur la vie privée avant toute recherche Web."""
        store = self._v63_memory_store()

        if store is not None:
            try:
                if store.explicit_web_request(message):
                    return False
            except Exception:
                pass

            try:
                if store.looks_personal_query(message):
                    return True
            except Exception:
                pass

        try:
            if self._v63_personal_memory_owns(message):
                return True
        except Exception:
            pass

        try:
            if self._v621_is_personal_memory_query(message):
                return True
        except Exception:
            pass

        normalized = self._v623_chat_normalize(message)
        question_like = bool(
            normalized.startswith(
                (
                    "qui ",
                    "avec qui ",
                    "comment ",
                    "quand ",
                    "ou ",
                    "jusqu a quand ",
                )
            )
        )
        if not question_like:
            return False

        try:
            relations = self.memory.relational_active_items("relations")
        except Exception:
            relations = []

        for item in relations:
            if not isinstance(item, dict):
                continue
            person = str(item.get("value", "") or "").strip()
            if not person:
                continue
            wanted = self._v623_chat_normalize(person)
            if wanted and wanted in normalized:
                return True

        return False

    def _v631_private_fallback(
        self,
        message: str,
    ) -> str:
        """Répond sans Web quand la mémoire privée ne suffit pas."""
        normalized = self._v623_chat_normalize(message)

        if normalized.startswith("avec qui "):
            return (
                "Tu ne me l'as pas dit, ou je ne l'ai pas retrouvé "
                "dans ta mémoire personnelle. Avec qui est-elle partie ?"
            )

        return self._conversation(message)

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
        # V6.2.1 — une question sur la vie privée de l'utilisateur ou sur une
        # personne mémorisée ne part jamais sur le Web par défaut.
        if (
            self._v631_private_query_guard(message)
            or self._v63_personal_memory_owns(message)
            or self._v63_personal_statement(message)
            or self._v621_is_personal_memory_query(message)
            or self._v623_personal_statement(message)
        ):
            # V6.3 : une information sur la vie privée reste strictement dans
            # Personal Memory V2 / conversation utilisateur. Le Web n'est
            # autorisé que sur demande explicite.
            return None

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


    # =========================================================
    # NATURAL MANAGER V6.2
    # =========================================================

    def _v62_understanding_context(self) -> str:
        understanding = getattr(
            self,
            "_current_understanding",
            None,
        )
        if understanding is None:
            return "(compréhension V6.2 non disponible pour ce tour)"

        topic = str(
            getattr(understanding, "topic", "")
            or ""
        ).strip()
        continuity = getattr(
            understanding,
            "continues_previous_topic",
            None,
        )
        goal = str(
            getattr(understanding, "conversation_goal", "")
            or ""
        ).strip()
        primary = str(
            getattr(understanding, "primary_intent", "")
            or ""
        ).strip()

        if continuity is True:
            continuity_text = "oui"
        elif continuity is False:
            continuity_text = "non — nouveau sujet"
        else:
            continuity_text = "indéterminée"

        lines = [
            f"- intention : {primary or 'conversation'}",
            f"- but conversationnel : {goal or 'casual_chat'}",
            f"- sujet actuel : {topic or '(non identifié)'}",
            f"- continue le sujet précédent : {continuity_text}",
        ]

        learning_requested = bool(
            getattr(
                understanding,
                "learning_requested",
                False,
            )
        )
        if learning_requested:
            subject = str(
                getattr(
                    understanding,
                    "learning_subject",
                    "",
                )
                or ""
            ).strip()
            lines.append(
                "- apprentissage demandé : "
                + (subject or "oui")
            )

        return "\n".join(lines)

    def _v62_thread_context(
        self,
        message: str,
    ) -> str:
        # V6.2.2+ — un rappel personnel utilise uniquement les paroles de
        # l'utilisateur comme preuve factuelle.
        if (
            hasattr(self, "_v621_is_personal_memory_query")
            and self._v621_is_personal_memory_query(message)
        ):
            return self._v622_recent_user_context(
                message,
                limit=12,
            )

        # V6.2.3 — une nouvelle déclaration personnelle autonome ne doit pas
        # réactiver une ancienne demande (ex. Londres/YAML). Si elle ne contient
        # qu'un pronom sans référent explicite, on garde le fil utilisateur seul.
        if self._v623_personal_statement(message):
            if (
                self._v622_reference_followup(message)
                and not self._v623_personal_statement_has_explicit_anchor(message)
            ):
                return self._v622_recent_user_context(
                    message,
                    limit=8,
                )
            return (
                "(NOUVELLE DÉCLARATION PERSONNELLE : ancien sujet masqué. "
                "Réponds uniquement au message courant et mémorise-le si utile.)"
            )

        understanding = getattr(
            self,
            "_current_understanding",
            None,
        )

        if (
            understanding is not None
            and getattr(
                understanding,
                "continues_previous_topic",
                None,
            ) is False
        ):
            topic = str(
                getattr(
                    understanding,
                    "topic",
                    "",
                )
                or ""
            ).strip()
            suffix = (
                f" Sujet actuel : {topic}."
                if topic
                else ""
            )
            return (
                "(NOUVEAU SUJET : l'ancien fil est volontairement masqué "
                "pour cette réponse. Ne reprends aucune ancienne discussion "
                "sans référence explicite de l'utilisateur.)"
                + suffix
            )

        return self.conversation_tracker.context_for(
            message,
            limit=10,
        )

    def _v62_communication_preferences(self) -> str:
        lines: list[str] = []

        try:
            structured = self.memory.relational_category_summary(
                "communication"
            )
        except Exception:
            structured = ""

        if structured:
            normalized = structured.lower()
            if not any(
                marker in normalized
                for marker in (
                    "aucune",
                    "vide",
                    "non renseign",
                )
            ):
                lines.append(structured)

        # V6.1 sait déjà stocker une préférence non reconnue par l'ancien
        # parseur relationnel dans long_term. V6.2 récupère aussi ces règles
        # de communication pour qu'elles s'appliquent à tous les sujets.
        communication_markers = (
            "répond",
            "repond",
            "parle",
            "ton ",
            "enjou",
            "direct",
            "blabla",
            "bla bla",
            "demande si ça va",
            "demande si ca va",
            "demander si ça va",
            "demander si ca va",
            "plus calme",
            "plus court",
            "moins enthousiaste",
            "enthousias",
        )

        extras: list[str] = []
        try:
            candidates = list(
                self.memory.data.get(
                    "long_term",
                    [],
                )
            )
        except Exception:
            candidates = []

        for item in reversed(candidates[-250:]):
            if not isinstance(item, dict):
                continue
            kind = str(
                item.get("kind", "")
                or ""
            ).lower()
            if kind not in {
                "preference",
                "communication",
                "communication_preference",
            }:
                continue
            content = str(
                item.get("content", "")
                or ""
            ).strip()
            normalized = content.lower()
            if not content or not any(
                marker in normalized
                for marker in communication_markers
            ):
                continue
            if content not in extras:
                extras.append(content)
            if len(extras) >= 8:
                break

        if extras:
            lines.append(
                "Préférences conversationnelles mémorisées :\n- "
                + "\n- ".join(extras)
            )

        return (
            "\n\n".join(lines)
            if lines
            else "(aucune préférence de communication spécifique)"
        )

    def _v62_response_style_context(self) -> str:
        now = datetime.now().astimezone()
        hour = now.hour

        if 0 <= hour < 6:
            daypart = "nuit"
            default_tone = "calme"
            default_length = "plutôt courte"
        elif 6 <= hour < 12:
            daypart = "matin"
            default_tone = "neutre"
            default_length = "normale"
        elif 12 <= hour < 18:
            daypart = "après-midi"
            default_tone = "neutre"
            default_length = "normale"
        else:
            daypart = "soir"
            default_tone = "calme"
            default_length = "normale à courte"

        understanding = getattr(
            self,
            "_current_understanding",
            None,
        )
        state = (
            getattr(understanding, "user_state", {})
            if understanding is not None
            else {}
        )
        style = (
            getattr(understanding, "response_style", {})
            if understanding is not None
            else {}
        )
        if not isinstance(state, dict):
            state = {}
        if not isinstance(style, dict):
            style = {}

        tone_map = {
            "calm": "calme",
            "neutral": "neutre",
            "dynamic": "dynamique",
        }
        verbosity_map = {
            "short": "courte",
            "normal": "normale",
            "detailed": "détaillée",
        }

        requested_tone = tone_map.get(
            str(style.get("tone", "")),
            default_tone,
        )
        requested_length = verbosity_map.get(
            str(style.get("verbosity", "")),
            default_length,
        )

        # La fatigue influence seulement le style. Elle ne devient jamais un
        # sujet de conversation sauf demande explicite du message courant.
        if state.get("energy") == "low":
            requested_tone = "calme"
            if str(style.get("verbosity", "")) != "detailed":
                requested_length = "courte"

        mention_state = bool(
            style.get(
                "mention_state",
                False,
            )
        )

        return (
            f"- heure locale : {now.strftime('%H:%M')} ({daypart})\n"
            f"- ton conseillé : {requested_tone}\n"
            f"- longueur conseillée : {requested_length}\n"
            f"- mentionner explicitement l'état émotionnel : "
            f"{'oui' if mention_state else 'non'}\n"
            "- règle : l'état adapte la forme, jamais le sujet\n\n"
            "PRÉFÉRENCES DURABLES DE COMMUNICATION :\n"
            + self._v62_communication_preferences()
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
- Le bloc FIL DE CONVERSATION ACTIF décrit la continuité de la discussion.
  Utilise-le pour comprendre les pronoms, les références comme « ça »,
  « celui-là », « comme on disait », et les questions de suivi.
- Ne prétends jamais qu'un détail figure dans le fil s'il n'y figure pas.
- Réponds directement à ce que l'utilisateur vient de dire ou demander.
- N'ouvre pas un ancien sujet juste parce qu'il apparaît dans la conversation
  récente.
- Si COMPRÉHENSION DU MESSAGE COURANT indique « nouveau sujet », ignore le
  contenu de l'ancien sujet. Ne complète jamais spontanément la réponse avec
  YAML, Agent-OS, une mission ou tout autre thème précédent.
- Le message courant et son sujet sont toujours prioritaires sur le fil.
- Ne reparle pas d'une ancienne mission dans une conversation personnelle si
  l'utilisateur ne l'a pas demandée.
- Ne propose pas de mission ou de travail supplémentaire sans besoin réel.
- Ne termine pas par « n'hésite pas », « si tu as besoin », « ton bien-être
  reste ma priorité », « ton confort reste ma priorité » ou une relance
  générique équivalente. Réponds puis arrête-toi.
- Pour une question simple, fais court. Pour une demande complexe, développe
  seulement ce qui est utile.
- Réponds uniquement en français, sauf si l'utilisateur demande explicitement
  une autre langue. Ne mélange jamais spontanément plusieurs langues.
- Tutoie toujours l'utilisateur.
- Évite l'enthousiasme forcé, les compliments automatiques et les réactions
  surjouées. Par défaut, parle comme un collègue calme, direct et naturel.
- Les préférences durables de communication priment sur ce style par défaut.

MÉMOIRE ÉMOTIONNELLE
- L'état émotionnel est temporaire et incertain. Une observation ancienne
  appartient à l'historique et ne décrit pas forcément l'état actuel.
- Si le message courant ne parle pas explicitement de l'état de l'utilisateur,
  ne mentionne absolument pas sa fatigue, son repos, son énergie, son stress,
  sa motivation, son confort ou son bien-être.
- Une fatigue mémorisée peut rendre le ton plus calme et la réponse plus courte,
  mais ne justifie jamais une question spontanée sur le sommeil, le repos ou
  « est-ce que ça va ? ».
- STYLE DE RÉPONSE V6.2 indique explicitement si l'état peut être mentionné.
- Si l'utilisateur a ensuite indiqué que l'état temporaire est terminé ou
  inversé, ne répète plus l'ancien conseil (« repose-toi », etc.).
- Adapte légèrement la densité ou le ton seulement si l'estimation est assez
  fiable et pertinente pour la demande actuelle.
- Ne diagnostique jamais et ne transforme jamais une humeur en trait durable.

RAPPEL PERSONNEL / VIE PRIVÉE
- Si MODE DE RAPPEL PERSONNEL V6.2.1 indique OUI, la question porte sur ce que
  l'utilisateur t'a raconté ou sur une personne de sa vie déjà mémorisée.
- Dans ce mode, MÉMOIRE PERSONNELLE et RAISONNEMENT PERSONNEL V6.2.2 sont les
  seules sources factuelles autorisées. Ne cherche jamais un homonyme public et
  ne cite jamais Wikipédia, Google, un article ou une autre source Web pour
  répondre sur un proche, sauf demande Web explicite de l'utilisateur.
- Une ancienne réponse de Paul n'est PAS un souvenir de l'utilisateur. Paul est
  un logiciel : il ne peut pas avoir vu un canard, accompagné Coralie, conduit,
  voyagé ou vécu physiquement un événement avec l'utilisateur.
- Réponds uniquement à l'information demandée. Si la question demande un lieu,
  donne le lieu pertinent ; ne récite pas tous les souvenirs du même jour.
- Tu peux faire une inférence simple lorsque les souvenirs la rendent très
  probable, mais indique clairement qu'il s'agit d'une déduction. Exemple :
  "tu l'as emmenée à l'aéroport pour partir en voyage" permet de répondre
  "probablement en avion" à "comment est-elle partie ?".
- Ne transforme jamais une déduction en certitude si le moyen exact n'a pas été
  dit explicitement.
- Si plusieurs souvenirs sont compatibles, choisis celui qui répond
  sémantiquement à la propriété demandée au lieu de tous les énumérer.
- Pour « la dernière fois », utilise en priorité CHRONOLOGIE PERSONNELLE V6.2.3.
  Compare la date à laquelle les événements ont eu lieu, PAS l'ordre dans lequel
  l'utilisateur les a racontés.
- Les expressions « dimanche dernier », « mardi dernier », « il y a 3 jours »,
  etc. sont de vraies informations temporelles et doivent être mémorisées.
- Si la mémoire et le fil utilisateur ne suffisent pas pour répondre ou déduire
  raisonnablement, pose UNE question courte à l'utilisateur. Ne lance pas de
  recherche Internet pour combler une information privée manquante.
- Une date relative enregistrée dans un souvenir (hier, samedi, etc.) fait
  partie du souvenir et peut être utilisée pour répondre à une relance liée.
- Une nouvelle déclaration personnelle n'est jamais une invitation à reprendre
  une ancienne demande sans rapport. Réponds au nouveau message, puis arrête-toi.

AGENDA PERSONNEL / V6.4
- Une liste de choses que l'utilisateur dit devoir faire est une TODO LIST,
  pas une demande de mission Agent-OS et pas une recherche Internet.
- Les tâches, rendez-vous et événements planifiés sont trois catégories
  distinctes. Ne les mélange pas.
- « mon programme aujourd'hui/demain » doit réunir les rendez-vous, les tâches
  ouvertes et les événements notables du jour.
- Une tâche terminée ne doit plus apparaître dans « ce qu'il me reste à faire ».
- Une tâche personnelle (« je dois nettoyer le filtre ») concerne l'utilisateur.
  Une demande adressée à Paul (« refais-moi mon dashboard ») reste une mission.
- N'utilise jamais le Web pour expliquer une tâche que l'utilisateur est
  simplement en train d'ajouter à son agenda.

MÉMOIRE PERSONNELLE V2 / V6.3
- Pour les événements personnels, MÉMOIRE PERSONNELLE V2 / SQLITE V6.3 est la
  source structurée prioritaire. Elle sépare la date vécue de la date où le
  souvenir a été raconté.
- Les personnes, lieux, sujets et bornes temporelles sont des index de recherche
  complémentaires : n'utilise jamais un seul mot-clé comme unique preuve.
- Les anciennes réponses de Paul ne sont jamais une source d'événements vécus.
- Les phrases en « je / j'ai / je suis » présentes dans les souvenirs ont été
  écrites par l'utilisateur. Elles décrivent donc L'UTILISATEUR, jamais Paul.
  Quand tu les reformules, utilise « tu / tu as / tu es ». Ne dis jamais
  « j'ai emmené », « j'ai vu », « je suis allé » pour une action de l'utilisateur.
- Les faits structurés suivent la forme sujet -> action -> objet. Si le sujet
  vaut « toi », l'acteur est l'utilisateur.
- Si une question personnelle n'a pas de réponse dans cette mémoire ni dans les
  déclarations utilisateur du fil, pose une question courte à l'utilisateur.
  N'utilise pas le Web pour remplir un trou de mémoire privée.
- Une déduction structurée peut être utilisée si elle est explicitement marquée
  comme déduite (ex. aéroport + départ en voyage => probablement avion).
- Ne mélange jamais une ancienne demande de travail/recherche avec un nouveau
  souvenir personnel simplement parce qu'ils partagent un lieu ou un mot.

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

COMPRÉHENSION DU MESSAGE COURANT :

{self._v62_understanding_context()}

STYLE DE RÉPONSE V6.2 :

{self._v62_response_style_context()}

MODE DE RAPPEL PERSONNEL V6.2.1 :

{self._v621_personal_recall_context(message)}

RAISONNEMENT PERSONNEL V6.2.2 :

{self._v622_personal_reasoning_context(message)}

CHRONOLOGIE PERSONNELLE V6.2.3 :

{self._v623_timeline_context(message)}

MÉMOIRE PERSONNELLE V2 / SQLITE V6.3 :

{self._v63_personal_memory_context(message)}

AGENDA PERSONNEL V6.4 :

{self._v64_agenda_context(message)}

FIL DE CONVERSATION ACTIF :

{self._v62_thread_context(message)}

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

        # V6.4 — agenda AVANT mémoire personnelle, Researcher et missions.
        # Ainsi « aujourd'hui il faut que je fasse... » devient une liste de
        # tâches personnelle et ne peut pas être interprété comme une recherche.
        agenda_response = self._v64_agenda_response(value)
        if agenda_response is not None:
            self.memory.add_session("user", value)
            self.memory.add_session("assistant", agenda_response)
            self._track_exchange(value, agenda_response)
            return agenda_response

        # V6.3 — commandes et journal personnel avant toute recherche Web.
        memory_v2_command = self._v63_memory_command_response(value)
        if memory_v2_command is not None:
            self.memory.add_session("user", value)
            self.memory.add_session("assistant", memory_v2_command)
            self._track_exchange(value, memory_v2_command)
            return memory_v2_command

        if self._v63_personal_statement(value):
            try:
                self.memory.personal_memory_v2_observe(value)
            except Exception:
                pass

        # Les questions personnelles simples dont la réponse est structurée
        # peuvent être résolues sans LLM ni Web : date, lieu, fin de période,
        # transport explicite/déduit.
        direct_personal = self._v63_direct_personal_answer(value)
        if direct_personal is not None:
            self.memory.add_session("user", value)
            self.memory.add_session("assistant", direct_personal)
            self._track_exchange(value, direct_personal)
            return direct_personal

        # V6.3.1 : une question privée ne part jamais chez Researcher juste
        # parce que la réponse structurée exacte manque.
        if self._v631_private_query_guard(value):
            private_response = self._v631_private_fallback(value)
            self.memory.add_session("user", value)
            self.memory.add_session("assistant", private_response)
            self._track_exchange(value, private_response)
            return private_response

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
