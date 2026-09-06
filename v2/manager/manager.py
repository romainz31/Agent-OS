"""
Manager principal Agent-OS V2.1.

Architecture :

Utilisateur
    ↓
Manager
    ↓
ManagerRouter
    ↓
conversation / tâche / mission
    ↓
WorkerEngine
    ↓
Workers
    ↓
EventBus
    ↓
Manager

Principe V2.1 :

Le LLM ne décide plus seul du routage.
Python choisit l'action générale et le worker.

La conversation courante reste en RAM.
La mémoire longue durée est séparée.
"""

from __future__ import annotations

import json

from typing import (
    Any,
    Optional,
)

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

from v2.manager.decision import (
    ManagerDecision,
)

from v2.manager.router import (
    ManagerRouter,
    RouteDecision,
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


class Manager:
    """
    Manager principal Agent-OS.
    """

    SESSION_HISTORY_LIMIT = 12

    def __init__(
        self,
        llm: Optional[LLM] = None,
        memory: Optional[
            MemoryStore
        ] = None,
        tasks: Optional[
            TaskManager
        ] = None,
        missions: Optional[
            MissionManager
        ] = None,
        permissions: Optional[
            PermissionEngine
        ] = None,
        event_bus: Optional[
            EventBus
        ] = None,
        worker_engine: Optional[
            WorkerEngine
        ] = None,
        router: Optional[
            ManagerRouter
        ] = None,
    ) -> None:

        self.llm = llm or LLM(
            host=OLLAMA_HOST,
            model=OLLAMA_MODEL,
        )

        self.memory = (
            memory
            or MemoryStore()
        )

        self.tasks = (
            tasks
            or TaskManager()
        )

        self.missions = (
            missions
            or MissionManager()
        )

        self.permissions = (
            permissions
            or PermissionEngine()
        )

        self.event_bus = (
            event_bus
            or EventBus()
        )

        self.worker_engine = (
            worker_engine
            or WorkerEngine(
                task_manager=self.tasks,
                event_bus=self.event_bus,
            )
        )

        self.router = (
            router
            or ManagerRouter()
        )

        # Conversation de la session actuelle.
        # Elle n'est PAS persistée.
        self.session_messages: list[
            dict[str, str]
        ] = []

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

    # ========================================================
    # WORKERS
    # ========================================================

    def register_worker(
        self,
        worker: Worker,
    ) -> None:

        self.worker_engine.register(
            worker
        )

    def list_workers(
        self,
    ) -> list[dict[str, str]]:

        return [
            {
                "name": name,
                "description": getattr(
                    worker,
                    "description",
                    "",
                ),
            }
            for (
                name,
                worker,
            )
            in self.worker_engine.workers.items()
        ]

    def get_worker_names(
        self,
    ) -> list[str]:

        return list(
            self.worker_engine.workers.keys()
        )

    # ========================================================
    # CHAT
    # ========================================================

    def chat(
        self,
        message: str,
    ) -> str:

        message = message.strip()

        if not message:

            return (
                "Je n'ai reçu aucun message."
            )

        route = self.router.route(
            message=message,
            available_workers=(
                self.get_worker_names()
            ),
        )

        long_term_context = (
            self.memory.build_manager_context(
                query=message
            )
        )

        session_context = (
            self._build_session_context()
        )

        try:

            if (
                route.action
                == "conversation"
            ):

                response = (
                    self._conversation_reply(
                        message=message,
                        session_context=(
                            session_context
                        ),
                        long_term_context=(
                            long_term_context
                        ),
                    )
                )

            else:

                decision = (
                    self._build_work_decision(
                        message=message,
                        route=route,
                        session_context=(
                            session_context
                        ),
                        long_term_context=(
                            long_term_context
                        ),
                    )
                )

                response = (
                    self._execute_decision(
                        decision=decision,
                        original_message=(
                            message
                        ),
                    )
                )

        except LLMError as exc:

            response = (
                "Je n'arrive pas à contacter "
                "le modèle local.\n"
                f"Détail : {exc}"
            )

        except Exception as exc:

            response = (
                "Une erreur est survenue.\n"
                f"Détail : {exc}"
            )

        self._append_session(
            role="user",
            content=message,
        )

        self._append_session(
            role="manager",
            content=response,
        )

        return response

    # ========================================================
    # CONVERSATION
    # ========================================================

    def _conversation_reply(
        self,
        message: str,
        session_context: str,
        long_term_context: str,
    ) -> str:

        prompt = f"""
Tu es le Manager personnel de l'utilisateur.

Tu es son interlocuteur principal.

Tu peux discuter naturellement et répondre
directement aux questions qui ne nécessitent pas
de travail délégué.

============================================================
CONVERSATION DE CETTE SESSION
============================================================

{session_context}

============================================================
MÉMOIRE LONGUE DURÉE PERTINENTE
============================================================

{long_term_context}

============================================================
MESSAGE ACTUEL
============================================================

{message}

Réponds naturellement en français.

Ne parle pas de workers, de routage ou
d'architecture interne sauf si l'utilisateur
pose explicitement une question à ce sujet.
"""

        return self.llm.simple_chat(
            prompt=prompt,
            system_prompt=(
                "Tu es le Manager personnel "
                "d'Agent-OS."
            ),
        )

    # ========================================================
    # WORK DECISION
    # ========================================================

    def _build_work_decision(
        self,
        message: str,
        route: RouteDecision,
        session_context: str,
        long_term_context: str,
    ) -> ManagerDecision:
        """
        Le routeur Python a déjà décidé l'action.

        Le LLM ne fait ici que structurer
        proprement la tâche ou mission.
        """

        prompt = f"""
Tu travailles pour le Manager Agent-OS.

Python a déjà décidé le routage suivant :

ACTION :
{route.action}

WORKER :
{route.worker or "non déterminé"}

RAISON :
{route.reason}

Tu n'as PAS le droit de changer cette action.

============================================================
MESSAGE UTILISATEUR
============================================================

{message}

============================================================
SESSION ACTUELLE
============================================================

{session_context}

============================================================
MÉMOIRE PERTINENTE
============================================================

{long_term_context}

============================================================
FORMAT
============================================================

Si ACTION = create_task :

{{
    "response": "courte confirmation naturelle",
    "title": "titre clair",
    "description": "description complète de la tâche",
    "priority": "normal",
    "deadline": null
}}

Si ACTION = create_mission :

{{
    "response": "courte confirmation naturelle",
    "title": "titre clair",
    "objective": "objectif global",
    "description": "description précise de la première étape",
    "priority": "normal",
    "deadline": null
}}

Réponds UNIQUEMENT avec le JSON.
"""

        raw = self.llm.simple_chat(
            prompt=prompt,
            system_prompt=(
                "Tu structures des tâches "
                "pour Agent-OS. "
                "Tu réponds uniquement en JSON."
            ),
        )

        data = self._parse_json(
            raw
        )

        if route.action == "create_task":

            return ManagerDecision(
                action="create_task",
                response=str(
                    data.get(
                        "response",
                        "",
                    )
                ).strip(),
                title=(
                    str(
                        data.get(
                            "title",
                            "",
                        )
                    ).strip()
                    or self._fallback_title(
                        message
                    )
                ),
                description=(
                    str(
                        data.get(
                            "description",
                            "",
                        )
                    ).strip()
                    or message
                ),
                priority=self._safe_priority(
                    data.get(
                        "priority"
                    )
                ),
                deadline=(
                    data.get(
                        "deadline"
                    )
                    or None
                ),
                assigned_agent=(
                    route.worker
                    or self._fallback_worker()
                ),
                metadata={
                    "router_reason": (
                        route.reason
                    ),
                    "original_message": (
                        message
                    ),
                },
            )

        return ManagerDecision(
            action="create_mission",
            response=str(
                data.get(
                    "response",
                    "",
                )
            ).strip(),
            title=(
                str(
                    data.get(
                        "title",
                        "",
                    )
                ).strip()
                or self._fallback_title(
                    message
                )
            ),
            objective=(
                str(
                    data.get(
                        "objective",
                        "",
                    )
                ).strip()
                or message
            ),
            description=(
                str(
                    data.get(
                        "description",
                        "",
                    )
                ).strip()
                or message
            ),
            priority=self._safe_priority(
                data.get(
                    "priority"
                )
            ),
            deadline=(
                data.get(
                    "deadline"
                )
                or None
            ),
            assigned_agent=(
                route.worker
            ),
            metadata={
                "router_reason": (
                    route.reason
                ),
                "original_message": (
                    message
                ),
            },
        )

    # ========================================================
    # EXECUTE
    # ========================================================

    def _execute_decision(
        self,
        decision: ManagerDecision,
        original_message: str,
    ) -> str:

        decision.validate()

        if (
            decision.action
            == "create_task"
        ):

            return self._execute_create_task(
                decision=decision,
                original_message=(
                    original_message
                ),
            )

        if (
            decision.action
            == "create_mission"
        ):

            return self._execute_create_mission(
                decision=decision,
                original_message=(
                    original_message
                ),
            )

        return (
            decision.response
            or "Décision non exécutable."
        )

    # ========================================================
    # TASK
    # ========================================================

    def _execute_create_task(
        self,
        decision: ManagerDecision,
        original_message: str,
    ) -> str:

        assigned_agent = (
            decision.assigned_agent
            or self._fallback_worker()
        )

        if not assigned_agent:

            return (
                "Aucun worker n'est disponible."
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
            title=(
                decision.title
                or self._fallback_title(
                    original_message
                )
            ),
            description=(
                decision.description
                or original_message
            ),
            priority=(
                decision.priority
            ),
            deadline=(
                decision.deadline
            ),
            assigned_agent=(
                assigned_agent
            ),
            metadata=(
                decision.metadata
            ),
        )

        self.event_bus.publish(
            "task.created",
            {
                "task_id": task.id,
                "title": task.title,
                "assigned_agent": (
                    assigned_agent
                ),
            },
        )

        submitted = (
            self.worker_engine.submit(
                task.id
            )
        )

        if not submitted:

            return (
                f"Tâche {task.id} créée, "
                "mais son lancement a échoué."
            )

        return (
            decision.response
            or (
                "C'est lancé. "
                f"Je l'ai confié à "
                f"{assigned_agent}."
            )
        )

    # ========================================================
    # MISSION
    # ========================================================

    def _execute_create_mission(
        self,
        decision: ManagerDecision,
        original_message: str,
    ) -> str:

        mission = self.missions.create(
            title=(
                decision.title
                or self._fallback_title(
                    original_message
                )
            ),
            objective=(
                decision.objective
                or original_message
            ),
            priority=(
                decision.priority
            ),
            deadline=(
                decision.deadline
            ),
            metadata=(
                decision.metadata
            ),
        )

        assigned_agent = (
            decision.assigned_agent
        )

        if (
            not assigned_agent
            or assigned_agent
            not in self.get_worker_names()
        ):

            first_route = (
                self.router.route(
                    message=(
                        decision.description
                        or original_message
                    ),
                    available_workers=(
                        self.get_worker_names()
                    ),
                )
            )

            assigned_agent = (
                first_route.worker
                or self._fallback_worker()
            )

        if not assigned_agent:

            self.missions.fail(
                mission.id,
                "Aucun worker disponible.",
            )

            return (
                f"Mission {mission.id} créée, "
                "mais aucun worker n'est disponible."
            )

        task = self.tasks.create(
            title=(
                decision.title
                or "Première étape"
            ),
            description=(
                decision.description
                or original_message
            ),
            priority=(
                decision.priority
            ),
            deadline=(
                decision.deadline
            ),
            assigned_agent=(
                assigned_agent
            ),
            metadata={
                "mission_id": (
                    mission.id
                ),
                "mission_step": 1,
                "mission_objective": (
                    mission.objective
                ),
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
                "mission_id": (
                    mission.id
                ),
                "title": task.title,
                "assigned_agent": (
                    assigned_agent
                ),
            },
        )

        submitted = (
            self.worker_engine.submit(
                task.id
            )
        )

        if not submitted:

            self.missions.fail(
                mission.id,
                (
                    "Impossible de lancer "
                    "la première étape."
                ),
            )

            return (
                f"Mission {mission.id} créée, "
                "mais elle n'a pas pu démarrer."
            )

        return (
            decision.response
            or (
                "Mission lancée. "
                "Je commence par "
                f"{assigned_agent}."
            )
        )

    # ========================================================
    # EVENTS
    # ========================================================

    def _on_task_created(
        self,
        event: Event,
    ) -> None:

        pass

    def _on_task_started(
        self,
        event: Event,
    ) -> None:

        pass

    def _on_task_completed(
        self,
        event: Event,
    ) -> None:

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

        # Mémoire de travail persistante.
        if task.result:

            try:

                self.memory.add(
                    "tasks",
                    (
                        f"Tâche terminée : "
                        f"{task.title}\n"
                        f"Résultat : "
                        f"{task.result}"
                    ),
                    metadata={
                        "task_id": (
                            task.id
                        ),
                        "status": (
                            "completed"
                        ),
                        "worker": (
                            task.assigned_agent
                        ),
                    },
                )

            except Exception:

                pass

        mission_id = (
            task.metadata.get(
                "mission_id"
            )
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

        mission_id = (
            task.metadata.get(
                "mission_id"
            )
        )

        if not mission_id:
            return

        self.missions.fail(
            mission_id,
            (
                data.get("error")
                or task.error
                or (
                    "Une étape de la "
                    "mission a échoué."
                )
            ),
        )

    # ========================================================
    # MISSION CONTINUATION
    # ========================================================

    def _continue_mission(
        self,
        mission_id: str,
        completed_task,
    ) -> None:

        mission = self.missions.get(
            mission_id
        )

        if mission is None:
            return

        mission_tasks = []

        for task_id in mission.task_ids:

            task = self.tasks.get(
                task_id
            )

            if task:
                mission_tasks.append(
                    task
                )

        previous_result = (
            completed_task.result
            or "Aucun résultat."
        )

        history = "\n".join(
            (
                f"- Étape "
                f"{task.metadata.get('mission_step', '?')} : "
                f"{task.title} "
                f"[{task.status}]"
            )
            for task in mission_tasks
        )

        workers = ", ".join(
            self.get_worker_names()
        )

        prompt = f"""
MISSION :
{mission.title}

OBJECTIF :
{mission.objective}

WORKERS DISPONIBLES :
{workers}

DERNIÈRE ÉTAPE :
{completed_task.title}

RÉSULTAT :
{previous_result}

HISTORIQUE :
{history}

Décide si la mission est terminée.

Si elle est terminée :

{{
    "next": "complete",
    "result": "résultat final synthétique"
}}

Sinon :

{{
    "next": "task",
    "title": "titre de l'étape",
    "description": "travail précis à effectuer",
    "priority": "normal"
}}

Ne choisis PAS le worker.
Python le fera.

Réponds uniquement en JSON.
"""

        try:

            raw = self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Tu planifies la suite "
                    "d'une mission Agent-OS."
                ),
            )

            decision = self._parse_json(
                raw
            )

        except Exception as exc:

            self.missions.fail(
                mission_id,
                str(exc),
            )

            return

        next_action = decision.get(
            "next"
        )

        if next_action == "complete":

            self.missions.complete(
                mission_id,
                result=str(
                    decision.get(
                        "result",
                        previous_result,
                    )
                ),
            )

            return

        if next_action != "task":

            self.missions.fail(
                mission_id,
                (
                    "Décision de mission "
                    "invalide."
                ),
            )

            return

        title = str(
            decision.get(
                "title",
                "",
            )
        ).strip()

        description = str(
            decision.get(
                "description",
                "",
            )
        ).strip()

        if (
            not title
            or not description
        ):

            self.missions.fail(
                mission_id,
                (
                    "Étape suivante "
                    "incomplète."
                ),
            )

            return

        route = self.router.route(
            message=description,
            available_workers=(
                self.get_worker_names()
            ),
        )

        assigned_agent = (
            route.worker
            or self._fallback_worker()
        )

        if not assigned_agent:

            self.missions.fail(
                mission_id,
                (
                    "Aucun worker disponible "
                    "pour l'étape suivante."
                ),
            )

            return

        step_number = (
            len(
                mission.task_ids
            )
            + 1
        )

        task = self.tasks.create(
            title=title,
            description=description,
            priority=self._safe_priority(
                decision.get(
                    "priority"
                )
            ),
            deadline=(
                mission.deadline
            ),
            assigned_agent=(
                assigned_agent
            ),
            parent_task_id=(
                completed_task.id
            ),
            metadata={
                "mission_id": (
                    mission_id
                ),
                "mission_step": (
                    step_number
                ),
                "previous_task_id": (
                    completed_task.id
                ),
                "previous_result": (
                    previous_result
                ),
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
                "mission_id": (
                    mission_id
                ),
                "title": task.title,
                "assigned_agent": (
                    assigned_agent
                ),
            },
        )

        submitted = (
            self.worker_engine.submit(
                task.id
            )
        )

        if not submitted:

            self.missions.fail(
                mission_id,
                (
                    "Impossible de lancer "
                    "l'étape suivante."
                ),
            )

    # ========================================================
    # SESSION
    # ========================================================

    def _append_session(
        self,
        role: str,
        content: str,
    ) -> None:

        self.session_messages.append(
            {
                "role": role,
                "content": content,
            }
        )

        max_messages = (
            self.SESSION_HISTORY_LIMIT
            * 2
        )

        if (
            len(self.session_messages)
            > max_messages
        ):

            self.session_messages = (
                self.session_messages[
                    -max_messages:
                ]
            )

    def _build_session_context(
        self,
    ) -> str:

        if not self.session_messages:

            return (
                "(début d'une nouvelle session)"
            )

        lines = []

        for message in (
            self.session_messages[
                -self.SESSION_HISTORY_LIMIT:
            ]
        ):

            role = message.get(
                "role",
                "unknown",
            )

            content = message.get(
                "content",
                "",
            )

            lines.append(
                f"{role.upper()} : "
                f"{content}"
            )

        return "\n".join(
            lines
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _parse_json(
        raw: str,
    ) -> dict[str, Any]:

        text = raw.strip()

        try:

            data = json.loads(
                text
            )

        except json.JSONDecodeError:

            start = text.find(
                "{"
            )

            end = text.rfind(
                "}"
            )

            if (
                start == -1
                or end == -1
                or end <= start
            ):

                return {}

            try:

                data = json.loads(
                    text[
                        start:end + 1
                    ]
                )

            except json.JSONDecodeError:

                return {}

        if not isinstance(
            data,
            dict,
        ):

            return {}

        return data

    @staticmethod
    def _safe_priority(
        value: Any,
    ) -> str:

        priority = str(
            value
            or "normal"
        ).lower().strip()

        if priority not in {
            "low",
            "normal",
            "high",
            "critical",
        }:

            return "normal"

        return priority

    @staticmethod
    def _fallback_title(
        message: str,
    ) -> str:

        title = " ".join(
            message.split()
        )

        if len(title) > 80:

            title = (
                title[:77]
                + "..."
            )

        return title

    def _fallback_worker(
        self,
    ) -> Optional[str]:

        available = (
            self.get_worker_names()
        )

        if "ai_worker" in available:
            return "ai_worker"

        if available:
            return available[0]

        return None

    # ========================================================
    # STATUS
    # ========================================================

    def status(
        self,
    ) -> dict[str, Any]:

        tasks = (
            self.tasks.list()
        )

        missions = (
            self.missions.list()
        )

        def count_tasks(
            status: str,
        ) -> int:

            return len(
                [
                    task
                    for task in tasks
                    if task.status
                    == status
                ]
            )

        def count_missions(
            status: str,
        ) -> int:

            return len(
                [
                    mission
                    for mission
                    in missions
                    if mission.status
                    == status
                ]
            )

        return {
            "workers": (
                self.get_worker_names()
            ),
            "session_messages": (
                len(
                    self.session_messages
                )
            ),
            "tasks": {
                "total": len(
                    tasks
                ),
                "pending": count_tasks(
                    TaskStatus.PENDING
                ),
                "running": count_tasks(
                    TaskStatus.RUNNING
                ),
                "waiting_approval": (
                    count_tasks(
                        TaskStatus.WAITING_APPROVAL
                    )
                ),
                "blocked": count_tasks(
                    TaskStatus.BLOCKED
                ),
                "completed": count_tasks(
                    TaskStatus.COMPLETED
                ),
                "failed": count_tasks(
                    TaskStatus.FAILED
                ),
            },
            "missions": {
                "total": len(
                    missions
                ),
                "pending": (
                    count_missions(
                        MissionStatus.PENDING
                    )
                ),
                "running": (
                    count_missions(
                        MissionStatus.RUNNING
                    )
                ),
                "completed": (
                    count_missions(
                        MissionStatus.COMPLETED
                    )
                ),
                "failed": (
                    count_missions(
                        MissionStatus.FAILED
                    )
                ),
            },
            "running_workers": list(
                self.worker_engine.running.keys()
            ),
        }

    # ========================================================
    # SHUTDOWN
    # ========================================================

    def shutdown(
        self,
    ) -> None:

        self.worker_engine.shutdown(
            wait=True
        )