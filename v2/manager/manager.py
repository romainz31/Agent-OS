"""
Manager principal Agent-OS V2.

Le Manager est l'interlocuteur principal de l'utilisateur.

Responsabilités :

    - comprendre les demandes
    - maintenir le contexte
    - décider de l'action
    - créer des tâches
    - créer des missions
    - déléguer aux workers
    - suivre les résultats
    - gérer les événements
"""

from __future__ import annotations

from typing import Any, Optional

from v2.brain.llm import (
    LLM,
    LLMError,
)

from v2.config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
)

from v2.events.event_bus import (
    Event,
    EventBus,
)

from v2.memory.memory import (
    MemoryStore,
)

from v2.missions.mission_manager import (
    MissionManager,
    MissionStatus,
)

from v2.permissions.permissions import (
    PermissionEngine,
)

from v2.tasks.task_manager import (
    TaskManager,
    TaskStatus,
)

from v2.workers.worker import (
    Worker,
)

from v2.workers.worker_engine import (
    WorkerEngine,
)

from v2.manager.decision import (
    ManagerDecision,
)


class Manager:
    """
    Manager principal d'Agent-OS.

    Le Manager ne réalise pas directement le travail technique.

    Il :

        1. comprend la demande
        2. décide quoi faire
        3. crée une tâche ou une mission
        4. choisit un worker
        5. lance le travail
        6. récupère les résultats
        7. informe l'utilisateur
    """

    # ============================================================
    # INITIALISATION
    # ============================================================

    def __init__(
        self,
        llm: Optional[LLM] = None,
        memory: Optional[MemoryStore] = None,
        tasks: Optional[TaskManager] = None,
        missions: Optional[MissionManager] = None,
        permissions: Optional[PermissionEngine] = None,
        event_bus: Optional[EventBus] = None,
        worker_engine: Optional[WorkerEngine] = None,
    ):
        self.llm = llm or LLM(
            host=OLLAMA_HOST,
            model=OLLAMA_MODEL,
        )

        self.memory = memory or MemoryStore()

        self.tasks = tasks or TaskManager()

        # MissionManager ne prend actuellement
        # que storage_path en argument.
        self.missions = missions or MissionManager()

        self.permissions = permissions or PermissionEngine()

        self.event_bus = event_bus or EventBus()

        self.worker_engine = worker_engine or WorkerEngine(
            task_manager=self.tasks,
            event_bus=self.event_bus,
        )

        # ========================================================
        # ÉVÉNEMENTS
        # ========================================================

        self.event_bus.subscribe(
            "task.created",
            self._on_task_created,
        )

        self.event_bus.subscribe(
            "task.started",
            self._on_task_started,
        )

        self.event_bus.subscribe(
            "task.completed",
            self._on_task_completed,
        )

        self.event_bus.subscribe(
            "task.failed",
            self._on_task_failed,
        )

    # ============================================================
    # WORKERS
    # ============================================================

    def register_worker(
        self,
        worker: Worker,
    ) -> None:
        """
        Enregistre un worker.
        """

        self.worker_engine.register(
            worker
        )

    def list_workers(
        self,
    ) -> list[dict[str, str]]:
        """
        Retourne la liste des workers disponibles.
        """

        workers = []

        for name, worker in self.worker_engine.workers.items():

            workers.append(
                {
                    "name": name,
                    "description": getattr(
                        worker,
                        "description",
                        "",
                    ),
                }
            )

        return workers

    def get_worker_names(
        self,
    ) -> list[str]:
        """
        Retourne uniquement les noms des workers.
        """

        return list(
            self.worker_engine.workers.keys()
        )

    # ============================================================
    # CHAT
    # ============================================================

    def chat(
        self,
        message: str,
    ) -> str:
        """
        Point d'entrée principal du Manager.
        """

        message = message.strip()

        if not message:
            return "Je n'ai reçu aucun message."

        # --------------------------------------------------------
        # MÉMOIRE DE CONVERSATION
        # --------------------------------------------------------

        self.memory.add(
            "conversation",
            message,
            metadata={
                "role": "user",
            },
        )

        # --------------------------------------------------------
        # CONTEXTE
        # --------------------------------------------------------

        context = self.memory.build_manager_context()

        # --------------------------------------------------------
        # DÉCISION
        # --------------------------------------------------------

        try:

            decision = self._decide(
                message=message,
                context=context,
            )

        except LLMError as exc:

            return (
                "Je n'arrive pas à contacter le modèle local.\n"
                f"Détail : {exc}"
            )

        except Exception as exc:

            return (
                "Une erreur est survenue pendant "
                "l'analyse de ta demande.\n"
                f"Détail : {exc}"
            )

        # --------------------------------------------------------
        # EXÉCUTION
        # --------------------------------------------------------

        try:

            response = self._execute_decision(
                decision=decision,
                original_message=message,
            )

        except Exception as exc:

            response = (
                "Je n'ai pas pu exécuter la décision.\n"
                f"Détail : {exc}"
            )

        # --------------------------------------------------------
        # MÉMOIRE
        # --------------------------------------------------------

        self.memory.add(
            "conversation",
            response,
            metadata={
                "role": "manager",
                "action": decision.action,
            },
        )

        return response

    # ============================================================
    # DÉCISION
    # ============================================================

    def _decide(
        self,
        message: str,
        context: str,
    ) -> ManagerDecision:
        """
        Demande au LLM de déterminer l'action à effectuer.
        """

        prompt = self._build_decision_prompt(
            message=message,
            context=context,
        )

        raw = self.llm.simple_chat(
            prompt=prompt,
            system_prompt=(
                "Tu es le Manager principal d'Agent-OS. "
                "Tu dois analyser les demandes de l'utilisateur "
                "et produire une décision JSON valide."
            ),
        )

        return self._parse_decision(
            raw=raw,
            original_message=message,
        )

    # ============================================================
    # PROMPT DÉCISION
    # ============================================================

    def _build_decision_prompt(
        self,
        message: str,
        context: str,
    ) -> str:
        """
        Construit le prompt utilisé pour décider de l'action.
        """

        workers = self.list_workers()

        workers_text = "\n".join(
            (
                f"- {worker['name']} : "
                f"{worker['description']}"
            )
            for worker in workers
        )

        return f"""
Tu es le Manager principal d'un système d'agents IA.

Tu es l'interlocuteur direct de l'utilisateur.

Tu dois décider ce qu'il faut faire.

============================================================
WORKERS DISPONIBLES
============================================================

{workers_text}

============================================================
RÈGLES DE ROUTAGE
============================================================

researcher :
    Recherche web, documentation, comparaison,
    collecte d'informations, analyse de sources.

developer :
    Python, programmation, architecture logicielle,
    création ou modification de code.

tester :
    Tests, vérification, validation, reproduction
    de bugs et contrôle du fonctionnement.

demo :
    Tests simples du système.

ai_worker :
    Tâches générales qui ne correspondent pas clairement
    à un worker spécialisé.

IMPORTANT :
Tu dois privilégier un worker spécialisé lorsqu'il correspond
à la demande.

N'utilise PAS ai_worker simplement parce que la demande
est générale.

============================================================
ACTIONS POSSIBLES
============================================================

conversation
create_task
create_mission
approval_required
blocked

============================================================
QUAND UTILISER create_task
============================================================

Utilise create_task lorsqu'une seule tâche doit être exécutée.

Exemples :

    "Recherche comment fonctionne MQTT"
    "Écris un script Python"
    "Teste ce système"

============================================================
QUAND UTILISER create_mission
============================================================

Utilise create_mission lorsqu'une demande contient plusieurs
étapes qui doivent être exécutées dans un ordre logique.

Exemples :

    "Recherche d'abord les solutions puis crée l'architecture
     et enfin teste-la."

    "Analyse le problème, développe une solution puis vérifie
     qu'elle fonctionne."

Une mission doit être décomposée en plusieurs étapes.

============================================================
CONVERSATION
============================================================

Utilise conversation lorsqu'aucun travail externe
n'est nécessaire.

Exemples :

    "Bonjour"
    "Explique-moi ce qu'est un agent IA"
    "Tu penses quoi de cette architecture ?"

============================================================
APPROBATION
============================================================

Utilise approval_required lorsqu'une action nécessite
l'autorisation explicite de l'utilisateur.

============================================================
BLOCAGE
============================================================

Utilise blocked lorsqu'une action ne doit pas être exécutée.

============================================================
PRIORITÉS
============================================================

low
normal
high
critical

============================================================
CONTEXTE MÉMOIRE
============================================================

{context}

============================================================
MESSAGE UTILISATEUR
============================================================

{message}

============================================================
FORMAT DE RÉPONSE
============================================================

Réponds UNIQUEMENT avec un objet JSON.

Pour conversation :

{{
    "action": "conversation",
    "response": "réponse à l'utilisateur"
}}

Pour une tâche :

{{
    "action": "create_task",
    "response": "courte explication",
    "title": "titre",
    "description": "description complète",
    "priority": "normal",
    "assigned_agent": "researcher"
}}

Pour une mission :

{{
    "action": "create_mission",
    "response": "courte explication",
    "title": "titre",
    "objective": "objectif complet",
    "description": "description de la mission",
    "priority": "normal"
}}

Pour une approbation :

{{
    "action": "approval_required",
    "response": "explication",
    "required_approval": "action nécessitant une autorisation"
}}

Pour un blocage :

{{
    "action": "blocked",
    "response": "explication"
}}
"""

    # ============================================================
    # PARSING DÉCISION
    # ============================================================

    def _parse_decision(
        self,
        raw: str,
        original_message: str,
    ) -> ManagerDecision:
        """
        Convertit la réponse du LLM en ManagerDecision.
        """

        import json

        text = raw.strip()

        try:

            data = json.loads(text)

        except json.JSONDecodeError:

            start = text.find("{")
            end = text.rfind("}")

            if start != -1 and end != -1 and end > start:

                try:

                    data = json.loads(
                        text[start:end + 1]
                    )

                except json.JSONDecodeError:

                    data = {}

            else:

                data = {}

        # --------------------------------------------------------
        # RÉPARATION DES ALIAS
        # --------------------------------------------------------

        action = str(
            data.get(
                "action",
                "",
            )
        ).strip().lower()

        aliases = {
            "response": "conversation",
            "answer": "conversation",
            "chat": "conversation",
            "analysis": "conversation",
            "respond": "conversation",
            "task": "create_task",
            "mission": "create_mission",
            "approval": "approval_required",
            "approve": "approval_required",
            "deny": "blocked",
            "block": "blocked",
        }

        action = aliases.get(
            action,
            action,
        )

        # --------------------------------------------------------
        # DÉTECTION DE MISSION
        # --------------------------------------------------------

        lower_message = original_message.lower()

        mission_indicators = [
            "d'abord",
            "ensuite",
            "puis",
            "enfin",
            "après",
            "après ça",
            "et ensuite",
            "première étape",
            "deuxième étape",
            "troisième étape",
            "plusieurs étapes",
            "étapes",
            "puis teste",
            "puis vérifie",
            "ensuite teste",
            "ensuite vérifie",
            "recherche puis",
            "analyse puis",
            "développe puis",
        ]

        if (
            action in {
                "",
                "conversation",
                "create_task",
            }
            and any(
                indicator in lower_message
                for indicator in mission_indicators
            )
        ):
            action = "create_mission"

        # --------------------------------------------------------
        # ACTION INVALIDE
        # --------------------------------------------------------

        if action not in {
            "conversation",
            "create_task",
            "create_mission",
            "approval_required",
            "blocked",
        }:

            action = "conversation"

            data = {
                "action": "conversation",
                "response": raw,
            }

        # --------------------------------------------------------
        # WORKER
        # --------------------------------------------------------

        assigned_agent = data.get(
            "assigned_agent"
        )

        if isinstance(
            assigned_agent,
            str,
        ):

            assigned_agent = assigned_agent.strip()

        else:

            assigned_agent = None

        available_workers = set(
            self.get_worker_names()
        )

        if (
            assigned_agent
            and assigned_agent not in available_workers
        ):
            assigned_agent = None

        # --------------------------------------------------------
        # ROUTAGE DÉTERMINISTE
        # --------------------------------------------------------

        if action == "create_task":

            inferred_worker = self._infer_worker(
                original_message
            )

            if inferred_worker:
                assigned_agent = inferred_worker

        # --------------------------------------------------------
        # DÉCISION
        # --------------------------------------------------------

        data["action"] = action

        if assigned_agent:
            data["assigned_agent"] = assigned_agent

        try:

            decision = ManagerDecision.from_dict(
                data
            )

        except Exception:

            decision = ManagerDecision(
                action="conversation",
                response=(
                    data.get(
                        "response"
                    )
                    or raw
                ),
            )

        return decision

    # ============================================================
    # ROUTAGE WORKER
    # ============================================================

    def _infer_worker(
        self,
        text: str,
    ) -> Optional[str]:
        """
        Détermine automatiquement le worker adapté.
        """

        lower = text.lower()

        available = set(
            self.get_worker_names()
        )

        # --------------------------------------------------------
        # TESTEUR
        # --------------------------------------------------------

        tester_keywords = [
            "teste",
            "tester",
            "test",
            "tests",
            "tester le",
            "tester la",
            "vérifie",
            "vérifier",
            "validation",
            "valider",
            "bug",
            "bugs",
            "erreur",
            "erreurs",
            "fonctionne",
            "fonctionnement",
            "reproduire",
            "reproduis",
        ]

        if (
            "tester" in available
            and any(
                keyword in lower
                for keyword in tester_keywords
            )
        ):
            return "tester"

        # --------------------------------------------------------
        # DEVELOPER
        # --------------------------------------------------------

        developer_keywords = [
            "python",
            "code",
            "coder",
            "développe",
            "développer",
            "développement",
            "programme",
            "programmer",
            "programmation",
            "script",
            "classe",
            "fonction",
            "api",
            "architecture logicielle",
            "architecture python",
            "module",
            "refactor",
            "refactoriser",
            "implémente",
            "implémenter",
            "créé le fichier",
            "crée le fichier",
            "modifier le code",
            "modifie le code",
        ]

        if (
            "developer" in available
            and any(
                keyword in lower
                for keyword in developer_keywords
            )
        ):
            return "developer"

        # --------------------------------------------------------
        # RESEARCHER
        # --------------------------------------------------------

        researcher_keywords = [
            "recherche",
            "rechercher",
            "cherche",
            "chercher",
            "documentation",
            "documente",
            "documenter",
            "web",
            "internet",
            "source",
            "sources",
            "compare",
            "comparer",
            "comparaison",
            "informations",
            "information",
            "étude",
            "étudier",
            "analyse documentaire",
        ]

        if (
            "researcher" in available
            and any(
                keyword in lower
                for keyword in researcher_keywords
            )
        ):
            return "researcher"

        # --------------------------------------------------------
        # DEMO
        # --------------------------------------------------------

        if "demo" in available:

            if any(
                keyword in lower
                for keyword in [
                    "démo",
                    "demo",
                    "démonstration",
                    "démontrer",
                ]
            ):
                return "demo"

        # --------------------------------------------------------
        # AI WORKER
        # --------------------------------------------------------

        if "ai_worker" in available:
            return "ai_worker"

        return None

    # ============================================================
    # EXÉCUTION DÉCISION
    # ============================================================

    def _execute_decision(
        self,
        decision: ManagerDecision,
        original_message: str,
    ) -> str:
        """
        Exécute la décision du Manager.
        """

        if decision.action == "conversation":

            return decision.response

        if decision.action == "create_task":

            return self._execute_create_task(
                decision=decision,
                original_message=original_message,
            )

        if decision.action == "create_mission":

            return self._execute_create_mission(
                decision=decision,
                original_message=original_message,
            )

        if decision.action == "approval_required":

            return (
                decision.response
                or (
                    "Cette action nécessite "
                    "ton approbation."
                )
            )

        if decision.action == "blocked":

            return (
                decision.response
                or (
                    "Cette action est bloquée "
                    "par les règles de sécurité."
                )
            )

        return (
            "Je n'ai pas pu déterminer quoi faire."
        )

    # ============================================================
    # CRÉATION TÂCHE
    # ============================================================

    def _execute_create_task(
        self,
        decision: ManagerDecision,
        original_message: str,
    ) -> str:
        """
        Crée puis lance une tâche.
        """

        assigned_agent = (
            decision.assigned_agent
        )

        if not assigned_agent:

            assigned_agent = self._infer_worker(
                original_message
            )

        if not assigned_agent:

            return (
                "Je n'ai trouvé aucun worker adapté "
                "à cette tâche."
            )

        if (
            assigned_agent
            not in self.get_worker_names()
        ):

            return (
                f"Le worker '{assigned_agent}' "
                "n'est pas disponible."
            )

        task = self.tasks.create(
            title=decision.title,
            description=decision.description,
            priority=decision.priority,
            deadline=decision.deadline,
            assigned_agent=assigned_agent,
            metadata=decision.metadata,
        )

        self.event_bus.publish(
            "task.created",
            {
                "task_id": task.id,
                "title": task.title,
                "assigned_agent": assigned_agent,
            },
        )

        submitted = self.worker_engine.submit(
            task.id
        )

        if not submitted:

            return (
                f"Tâche créée ({task.id}), "
                "mais je n'ai pas réussi à la lancer."
            )

        return (
            decision.response
            or (
                f"Tâche créée et confiée à "
                f"{assigned_agent}."
            )
        )

    # ============================================================
    # CRÉATION MISSION
    # ============================================================

    def _execute_create_mission(
        self,
        decision: ManagerDecision,
        original_message: str,
    ) -> str:
        """
        Crée une mission et lance sa première étape.
        """

        mission = self.missions.create(
            title=decision.title,
            objective=(
                decision.objective
                or decision.description
            ),
            priority=decision.priority,
            deadline=decision.deadline,
            metadata=decision.metadata,
        )

        # --------------------------------------------------------
        # PREMIER WORKER
        # --------------------------------------------------------

        assigned_agent = decision.assigned_agent

        available = set(
            self.get_worker_names()
        )

        if (
            not assigned_agent
            or assigned_agent not in available
        ):
            assigned_agent = self._infer_first_mission_worker(
                original_message
            )

        if not assigned_agent:

            assigned_agent = self._infer_worker(
                decision.objective
                or decision.description
                or original_message
            )

        if not assigned_agent:

            return (
                f"Mission créée ({mission.id}), "
                "mais aucun worker n'a pu être sélectionné."
            )

        # --------------------------------------------------------
        # PREMIÈRE TÂCHE
        # --------------------------------------------------------

        task = self.tasks.create(
            title=decision.title,
            description=(
                decision.objective
                or decision.description
            ),
            priority=decision.priority,
            deadline=decision.deadline,
            assigned_agent=assigned_agent,
            parent_task_id=None,
            metadata={
                "mission_id": mission.id,
                "mission_step": 1,
            },
        )

        self.missions.add_task(
            mission.id,
            task.id,
        )

        self.event_bus.publish(
            "task.created",
            {
                "task_id": task.id,
                "title": task.title,
                "assigned_agent": assigned_agent,
                "mission_id": mission.id,
            },
        )

        submitted = self.worker_engine.submit(
            task.id
        )

        if not submitted:

            self.missions.fail(
                mission.id,
                (
                    "Impossible de lancer "
                    "la première tâche."
                ),
            )

            return (
                f"Mission {mission.id} créée, "
                "mais la première tâche n'a pas pu démarrer."
            )

        return (
            decision.response
            or (
                f"Mission {mission.id} créée. "
                f"Première étape confiée à "
                f"{assigned_agent}."
            )
        )

    # ============================================================
    # ROUTAGE PREMIÈRE ÉTAPE D'UNE MISSION
    # ============================================================

    def _infer_first_mission_worker(
        self,
        text: str,
    ) -> Optional[str]:
        """
        Détermine le worker correspondant à la première
        étape d'une mission.
        """

        lower = text.lower()

        separators = [
            " ensuite ",
            " puis ",
            " enfin ",
            ", puis ",
            ", ensuite ",
            " après ",
            " après ça ",
        ]

        first_part = lower

        for separator in separators:

            if separator in lower:

                first_part = lower.split(
                    separator,
                    1,
                )[0]

        return self._infer_worker(
            first_part
        )

    # ============================================================
    # ÉVÉNEMENTS
    # ============================================================

    def _on_task_created(
        self,
        event: Event,
    ) -> None:
        """
        Réagit à la création d'une tâche.
        """

        # L'EventBus transmet un objet Event.
        # Pour l'instant aucun traitement lourd.
        pass

    def _on_task_started(
        self,
        event: Event,
    ) -> None:
        """
        Réagit au démarrage d'une tâche.
        """

        # L'EventBus transmet un objet Event.
        pass

    def _on_task_completed(
        self,
        event: Event,
    ) -> None:
        """
        Réagit à la fin d'une tâche.

        Si la tâche appartient à une mission,
        on tente de lancer l'étape suivante.
        """

        # IMPORTANT :
        # EventBus transmet Event, pas dict.
        data = event.data

        task_id = data.get(
            "task_id"
        )

        if not task_id:
            return

        task = self.tasks.get(
            task_id
        )

        if task is None:
            return

        mission_id = task.metadata.get(
            "mission_id"
        )

        if not mission_id:
            return

        self._continue_mission(
            mission_id=mission_id,
            completed_task=task,
        )

    def _on_task_failed(
        self,
        event: Event,
    ) -> None:
        """
        Réagit à l'échec d'une tâche.
        """

        # IMPORTANT :
        # EventBus transmet Event, pas dict.
        data = event.data

        task_id = data.get(
            "task_id"
        )

        if not task_id:
            return

        task = self.tasks.get(
            task_id
        )

        if task is None:
            return

        mission_id = task.metadata.get(
            "mission_id"
        )

        if not mission_id:
            return

        error = data.get(
            "error"
        ) or task.error

        self.missions.fail(
            mission_id,
            error or "Une étape de la mission a échoué.",
        )

    # ============================================================
    # CONTINUER UNE MISSION
    # ============================================================

    def _continue_mission(
        self,
        mission_id: str,
        completed_task,
    ) -> None:
        """
        Demande au LLM quelle doit être la prochaine étape
        d'une mission.
        """

        mission = self.missions.get(
            mission_id
        )

        if mission is None:
            return

        # --------------------------------------------------------
        # RÉCUPÉRATION DES TÂCHES
        # --------------------------------------------------------

        mission_tasks = []

        for task_id in mission.task_ids:

            task = self.tasks.get(
                task_id
            )

            if task is not None:

                mission_tasks.append(
                    task
                )

        # --------------------------------------------------------
        # CONSTRUCTION DU CONTEXTE
        # --------------------------------------------------------

        previous_result = (
            completed_task.result
            or "Aucun résultat."
        )

        prompt = f"""
Une mission Agent-OS est en cours.

MISSION :
{mission.title}

OBJECTIF :
{mission.objective}

ÉTAT :
{mission.status}

DERNIÈRE ÉTAPE TERMINÉE :
{completed_task.title}

RÉSULTAT :
{previous_result}

TÂCHES DÉJÀ RÉALISÉES :

"""

        for task in mission_tasks:

            prompt += (
                f"- {task.title} : "
                f"{task.status}\n"
            )

        prompt += """

Décide maintenant s'il reste une étape.

Si la mission est terminée :

{
    "next": "complete",
    "result": "résultat final"
}

S'il faut une nouvelle étape :

{
    "next": "task",
    "title": "titre",
    "description": "description précise",
    "assigned_agent": "researcher|developer|tester|ai_worker",
    "priority": "normal"
}

Réponds uniquement avec du JSON.
"""

        try:

            raw = self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Tu es le planificateur de missions "
                    "d'Agent-OS. Réponds uniquement en JSON."
                ),
            )

        except Exception as exc:

            self.missions.fail(
                mission_id,
                str(exc),
            )

            return

        decision = self._parse_mission_decision(
            raw
        )

        if decision is None:

            self.missions.fail(
                mission_id,
                "Décision de mission invalide.",
            )

            return

        # --------------------------------------------------------
        # MISSION TERMINÉE
        # --------------------------------------------------------

        if decision.get(
            "next"
        ) == "complete":

            result = decision.get(
                "result"
            )

            self.missions.complete(
                mission_id,
                result=result,
            )

            return

        # --------------------------------------------------------
        # NOUVELLE TÂCHE
        # --------------------------------------------------------

        if decision.get(
            "next"
        ) != "task":

            self.missions.fail(
                mission_id,
                "Action de mission inconnue.",
            )

            return

        title = decision.get(
            "title"
        )

        description = decision.get(
            "description"
        )

        assigned_agent = decision.get(
            "assigned_agent"
        )

        priority = decision.get(
            "priority",
            mission.priority,
        )

        if not title or not description:

            self.missions.fail(
                mission_id,
                "Étape de mission incomplète.",
            )

            return

        # --------------------------------------------------------
        # ROUTAGE
        # --------------------------------------------------------

        available = set(
            self.get_worker_names()
        )

        if assigned_agent not in available:

            assigned_agent = self._infer_worker(
                f"{title}\n{description}"
            )

        if not assigned_agent:

            self.missions.fail(
                mission_id,
                "Aucun worker adapté à l'étape suivante.",
            )

            return

        # --------------------------------------------------------
        # NUMÉRO D'ÉTAPE
        # --------------------------------------------------------

        step_number = (
            len(mission.task_ids)
            + 1
        )

        task = self.tasks.create(
            title=title,
            description=description,
            priority=priority,
            deadline=mission.deadline,
            assigned_agent=assigned_agent,
            parent_task_id=completed_task.id,
            metadata={
                "mission_id": mission_id,
                "mission_step": step_number,
                "previous_task_id": completed_task.id,
                "previous_result": previous_result,
            },
        )

        self.missions.add_task(
            mission_id,
            task.id,
        )

        self.event_bus.publish(
            "task.created",
            {
                "task_id": task.id,
                "title": task.title,
                "assigned_agent": assigned_agent,
                "mission_id": mission_id,
            },
        )

        self.worker_engine.submit(
            task.id
        )

    # ============================================================
    # PARSING MISSION
    # ============================================================

    def _parse_mission_decision(
        self,
        raw: str,
    ) -> Optional[dict[str, Any]]:
        """
        Parse une décision de mission.
        """

        import json

        text = raw.strip()

        try:

            data = json.loads(
                text
            )

        except json.JSONDecodeError:

            start = text.find("{")
            end = text.rfind("}")

            if (
                start == -1
                or end == -1
                or end <= start
            ):
                return None

            try:

                data = json.loads(
                    text[start:end + 1]
                )

            except json.JSONDecodeError:

                return None

        if not isinstance(
            data,
            dict,
        ):
            return None

        return data

    # ============================================================
    # STATUS
    # ============================================================

    def status(
        self,
    ) -> dict[str, Any]:
        """
        Retourne l'état global du système.
        """

        tasks = self.tasks.list()

        missions = self.missions.list()

        return {
            "workers": self.get_worker_names(),

            "tasks": {
                "total": len(tasks),

                "pending": len(
                    [
                        task
                        for task in tasks
                        if task.status
                        == TaskStatus.PENDING
                    ]
                ),

                "running": len(
                    [
                        task
                        for task in tasks
                        if task.status
                        == TaskStatus.RUNNING
                    ]
                ),

                "waiting_approval": len(
                    [
                        task
                        for task in tasks
                        if task.status
                        == TaskStatus.WAITING_APPROVAL
                    ]
                ),

                "blocked": len(
                    [
                        task
                        for task in tasks
                        if task.status
                        == TaskStatus.BLOCKED
                    ]
                ),

                "completed": len(
                    [
                        task
                        for task in tasks
                        if task.status
                        == TaskStatus.COMPLETED
                    ]
                ),

                "failed": len(
                    [
                        task
                        for task in tasks
                        if task.status
                        == TaskStatus.FAILED
                    ]
                ),
            },

            "missions": {
                "total": len(
                    missions
                ),

                "pending": len(
                    [
                        mission
                        for mission in missions
                        if mission.status
                        == MissionStatus.PENDING
                    ]
                ),

                "running": len(
                    [
                        mission
                        for mission in missions
                        if mission.status
                        == MissionStatus.RUNNING
                    ]
                ),

                "completed": len(
                    [
                        mission
                        for mission in missions
                        if mission.status
                        == MissionStatus.COMPLETED
                    ]
                ),

                "failed": len(
                    [
                        mission
                        for mission in missions
                        if mission.status
                        == MissionStatus.FAILED
                    ]
                ),
            },

            "running_workers": list(
                self.worker_engine.running.keys()
            ),
        }

    # ============================================================
    # ARRÊT
    # ============================================================

    def shutdown(
        self,
    ) -> None:
        """
        Arrête proprement le WorkerEngine.
        """

        self.worker_engine.shutdown(
            wait=True
        )