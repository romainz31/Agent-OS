"""
Manager principal Agent-OS V2.2.

Ajoute :
- dépendances entre tâches ;
- référence au dernier travail de la session ;
- notifications de fin ;
- transmission automatique du résultat entre étapes ;
- affichage explicite task/worker/status.
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

    SESSION_HISTORY_LIMIT = 12

    REFERENCE_MARKERS = (
        "ce script",
        "ce code",
        "cette solution",
        "ce résultat",
        "ce resultat",
        "ça",
        "ca",
        "celui-ci",
        "celle-ci",
        "le précédent",
        "la précédente",
        "le precedent",
        "la precedente",
        "ce qu'il a fait",
        "ce qu’elle a fait",
    )

    def __init__(
        self,
        llm: Optional[
            LLM
        ] = None,
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

        self.llm = (
            llm
            or LLM(
                host=OLLAMA_HOST,
                model=OLLAMA_MODEL,
            )
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
                task_manager=(
                    self.tasks
                ),
                event_bus=(
                    self.event_bus
                ),
            )
        )

        self.router = (
            router
            or ManagerRouter()
        )

        self.session_messages: list[
            dict[str, str]
        ] = []

        self.last_task_id: Optional[
            str
        ] = None

        self.notifications: list[
            str
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
            "task.waiting_dependency",
            self._on_task_waiting_dependency,
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

    def get_worker_names(
        self,
    ) -> list[str]:

        return list(
            self.worker_engine
            .workers
            .keys()
        )

    def list_workers(
        self,
    ) -> list[
        dict[str, str]
    ]:

        return [
            {
                "name": name,
                "description": (
                    getattr(
                        worker,
                        "description",
                        "",
                    )
                ),
            }
            for (
                name,
                worker,
            )
            in self.worker_engine
            .workers
            .items()
        ]

    # ========================================================
    # CHAT
    # ========================================================

    def chat(
        self,
        message: str,
    ) -> str:

        message = (
            message.strip()
        )

        if not message:

            return (
                "Je n'ai reçu "
                "aucun message."
            )

        route = (
            self.router.route(
                message=message,
                available_workers=(
                    self.get_worker_names()
                ),
            )
        )

        long_term_context = (
            self.memory
            .build_manager_context(
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
                        message,
                        session_context,
                        long_term_context,
                    )
                )

            else:

                decision = (
                    self._build_work_decision(
                        message,
                        route,
                        session_context,
                        long_term_context,
                    )
                )

                response = (
                    self._execute_decision(
                        decision,
                        message,
                    )
                )

        except LLMError as exc:

            response = (
                "Je n'arrive pas à "
                "contacter le modèle local.\n"
                f"Détail : {exc}"
            )

        except Exception as exc:

            response = (
                "Une erreur est survenue.\n"
                f"Détail : {exc}"
            )

        self._append_session(
            "user",
            message,
        )

        self._append_session(
            "manager",
            response,
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

SESSION :
{session_context}

MÉMOIRE LONGUE DURÉE PERTINENTE :
{long_term_context}

MESSAGE :
{message}

Réponds naturellement en français.
"""

        return self.llm.simple_chat(
            prompt=prompt,
            system_prompt=(
                "Tu es le Manager personnel "
                "d'Agent-OS."
            ),
        )

    # ========================================================
    # DECISION
    # ========================================================

    def _build_work_decision(
        self,
        message: str,
        route: RouteDecision,
        session_context: str,
        long_term_context: str,
    ) -> ManagerDecision:

        prompt = f"""
Python a déjà décidé :

ACTION = {route.action}
WORKER = {route.worker or "non déterminé"}

Tu n'as pas le droit de changer
l'action ni le worker.

MESSAGE :
{message}

SESSION :
{session_context}

MÉMOIRE :
{long_term_context}

Si create_task :

{{
    "title": "titre clair",
    "description": "description complète",
    "priority": "normal",
    "deadline": null
}}

Si create_mission :

{{
    "title": "titre clair",
    "objective": "objectif global",
    "description": "description précise de la première étape",
    "priority": "normal",
    "deadline": null
}}

JSON uniquement.
"""

        raw = self.llm.simple_chat(
            prompt=prompt,
            system_prompt=(
                "Tu structures des tâches "
                "Agent-OS. JSON uniquement."
            ),
        )

        data = self._parse_json(
            raw
        )

        if (
            route.action
            == "create_task"
        ):

            return ManagerDecision(
                action=(
                    "create_task"
                ),
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
                priority=(
                    self._safe_priority(
                        data.get(
                            "priority"
                        )
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
            action=(
                "create_mission"
            ),
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
            priority=(
                self._safe_priority(
                    data.get(
                        "priority"
                    )
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
    # EXECUTION
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

            return (
                self._execute_create_task(
                    decision,
                    original_message,
                )
            )

        if (
            decision.action
            == "create_mission"
        ):

            return (
                self._execute_create_mission(
                    decision,
                    original_message,
                )
            )

        return (
            decision.response
            or (
                "Décision "
                "non exécutable."
            )
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
                "Aucun worker "
                "n'est disponible."
            )

        dependencies = (
            self._resolve_dependencies(
                original_message
            )
        )

        task = (
            self.tasks.create(
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
                depends_on=(
                    dependencies
                ),
                metadata=(
                    decision.metadata
                ),
            )
        )

        self.last_task_id = (
            task.id
        )

        self.event_bus.publish(
            "task.created",
            {
                "task_id": (
                    task.id
                ),
                "title": (
                    task.title
                ),
                "assigned_agent": (
                    assigned_agent
                ),
            },
        )

        accepted = (
            self.worker_engine.submit(
                task.id
            )
        )

        task = (
            self.tasks.get(
                task.id
            )
            or task
        )

        if not accepted:

            return (
                f"Tâche {task.id} créée "
                "mais impossible à lancer.\n"
                f"Worker : "
                f"{assigned_agent}\n"
                f"Statut : "
                f"{task.status}"
            )

        dependency_line = ""

        if task.depends_on:

            dependency_line = (
                "\nDépend de : "
                + ", ".join(
                    task.depends_on
                )
            )

        return (
            f"Tâche créée : "
            f"{task.id}\n"
            f"Worker : "
            f"{assigned_agent}\n"
            f"Statut : "
            f"{task.status}"
            f"{dependency_line}"
        )

    # ========================================================
    # MISSION
    # ========================================================

    def _execute_create_mission(
        self,
        decision: ManagerDecision,
        original_message: str,
    ) -> str:

        mission = (
            self.missions.create(
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
                    decision.description
                    or original_message,
                    self.get_worker_names(),
                )
            )

            assigned_agent = (
                first_route.worker
                or self._fallback_worker()
            )

        if not assigned_agent:

            self.missions.fail(
                mission.id,
                (
                    "Aucun worker "
                    "disponible."
                ),
            )

            return (
                f"Mission {mission.id} "
                "créée mais aucun "
                "worker n'est disponible."
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

        self.last_task_id = (
            task.id
        )

        self.event_bus.publish(
            "task.created",
            {
                "task_id": (
                    task.id
                ),
                "mission_id": (
                    mission.id
                ),
                "title": (
                    task.title
                ),
                "assigned_agent": (
                    assigned_agent
                ),
            },
        )

        self.worker_engine.submit(
            task.id
        )

        task = (
            self.tasks.get(
                task.id
            )
            or task
        )

        return (
            f"Mission créée : "
            f"{mission.id}\n"
            f"Première tâche : "
            f"{task.id}\n"
            f"Worker : "
            f"{assigned_agent}\n"
            f"Statut : "
            f"{task.status}"
        )

    # ========================================================
    # REFERENCES
    # ========================================================

    def _resolve_dependencies(
        self,
        message: str,
    ) -> list[str]:

        if not self.last_task_id:

            return []

        lower = (
            message.lower()
        )

        if any(
            marker in lower
            for marker
            in self.REFERENCE_MARKERS
        ):

            if self.tasks.get(
                self.last_task_id
            ):

                return [
                    self.last_task_id
                ]

        return []

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

    def _on_task_waiting_dependency(
        self,
        event: Event,
    ) -> None:

        task_id = (
            event.data.get(
                "task_id"
            )
        )

        if task_id:

            self.notifications.append(
                f"⏳ {task_id} attend "
                "la fin de ses dépendances."
            )

    def _on_task_completed(
        self,
        event: Event,
    ) -> None:

        task_id = (
            event.data.get(
                "task_id"
            )
        )

        if not task_id:
            return

        task = self.tasks.get(
            task_id
        )

        if task is None:
            return

        self.notifications.append(
            f"✓ {task.id} terminée "
            f"par {task.assigned_agent} : "
            f"{task.title}"
        )

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
                        "worker": (
                            task
                            .assigned_agent
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

        if mission_id:

            self._continue_mission(
                mission_id,
                task,
            )

    def _on_task_failed(
        self,
        event: Event,
    ) -> None:

        task_id = (
            event.data.get(
                "task_id"
            )
        )

        if not task_id:
            return

        task = self.tasks.get(
            task_id
        )

        if task:

            self.notifications.append(
                f"✗ {task.id} a échoué : "
                f"{task.error or event.data.get('error')}"
            )

            mission_id = (
                task.metadata.get(
                    "mission_id"
                )
            )

            if mission_id:

                self.missions.fail(
                    mission_id,
                    (
                        task.error
                        or (
                            "Une étape "
                            "de la mission "
                            "a échoué."
                        )
                    ),
                )

    def drain_notifications(
        self,
    ) -> list[str]:

        notifications = list(
            self.notifications
        )

        self.notifications.clear()

        return notifications

    # ========================================================
    # MISSION CONTINUATION
    # ========================================================

    def _continue_mission(
        self,
        mission_id: str,
        completed_task,
    ) -> None:

        mission = (
            self.missions.get(
                mission_id
            )
        )

        if mission is None:
            return

        previous_result = (
            completed_task.result
            or "Aucun résultat."
        )

        workers = ", ".join(
            self.get_worker_names()
        )

        prompt = f"""
MISSION :
{mission.title}

OBJECTIF :
{mission.objective}

WORKERS :
{workers}

DERNIÈRE ÉTAPE :
{completed_task.title}

RÉSULTAT :
{previous_result}

Décide si la mission est terminée.

Si terminée :

{{
    "next": "complete",
    "result": "résultat final"
}}

Sinon :

{{
    "next": "task",
    "title": "titre",
    "description": "étape précise",
    "priority": "normal"
}}

Ne choisis pas le worker.
JSON uniquement.
"""

        try:

            raw = (
                self.llm.simple_chat(
                    prompt=prompt,
                    system_prompt=(
                        "Tu planifies "
                        "une mission Agent-OS. "
                        "JSON uniquement."
                    ),
                )
            )

            data = (
                self._parse_json(
                    raw
                )
            )

        except Exception as exc:

            self.missions.fail(
                mission_id,
                str(exc),
            )

            return

        if (
            data.get("next")
            == "complete"
        ):

            self.missions.complete(
                mission_id,
                result=str(
                    data.get(
                        "result",
                        previous_result,
                    )
                ),
            )

            self.notifications.append(
                f"✓ Mission "
                f"{mission_id} terminée."
            )

            return

        if (
            data.get("next")
            != "task"
        ):

            self.missions.fail(
                mission_id,
                (
                    "Décision de mission "
                    "invalide."
                ),
            )

            return

        title = str(
            data.get(
                "title",
                "",
            )
        ).strip()

        description = str(
            data.get(
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
            description,
            self.get_worker_names(),
        )

        assigned_agent = (
            route.worker
            or self._fallback_worker()
        )

        if not assigned_agent:

            self.missions.fail(
                mission_id,
                (
                    "Aucun worker "
                    "disponible."
                ),
            )

            return

        step_number = (
            len(
                mission.task_ids
            )
            + 1
        )

        task = (
            self.tasks.create(
                title=title,
                description=description,
                priority=(
                    self._safe_priority(
                        data.get(
                            "priority"
                        )
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
                depends_on=[
                    completed_task.id
                ],
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
                },
            )
        )

        self.missions.add_task(
            mission_id,
            task.id,
        )

        self.last_task_id = (
            task.id
        )

        self.worker_engine.submit(
            task.id
        )

        self.notifications.append(
            f"→ Mission {mission_id}, "
            f"étape {step_number} : "
            f"{task.id} confiée à "
            f"{assigned_agent}."
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
            len(
                self.session_messages
            )
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

        if not (
            self.session_messages
        ):

            return (
                "(début d'une "
                "nouvelle session)"
            )

        return "\n".join(
            (
                f"{item['role'].upper()} : "
                f"{item['content']}"
            )
            for item
            in self.session_messages[
                -self.SESSION_HISTORY_LIMIT:
            ]
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _parse_json(
        raw: str,
    ) -> dict[
        str,
        Any,
    ]:

        text = (
            raw.strip()
        )

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

        return (
            data
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    @staticmethod
    def _safe_priority(
        value: Any,
    ) -> str:

        priority = str(
            value
            or "normal"
        ).lower().strip()

        if (
            priority
            in {
                "low",
                "normal",
                "high",
                "critical",
            }
        ):

            return priority

        return "normal"

    @staticmethod
    def _fallback_title(
        message: str,
    ) -> str:

        title = " ".join(
            message.split()
        )

        if len(title) <= 80:
            return title

        return (
            title[:77]
            + "..."
        )

    def _fallback_worker(
        self,
    ) -> Optional[str]:

        names = (
            self.get_worker_names()
        )

        if (
            "ai_worker"
            in names
        ):

            return "ai_worker"

        if names:

            return names[0]

        return None

    # ========================================================
    # INSPECTION
    # ========================================================

    def format_tasks(
        self,
        limit: int = 20,
    ) -> str:

        tasks = (
            self.tasks.list()[
                -limit:
            ]
        )

        if not tasks:

            return (
                "Aucune tâche."
            )

        lines = []

        for task in reversed(
            tasks
        ):

            dependency = ""

            if task.depends_on:

                dependency = (
                    " | dépend de "
                    + ", ".join(
                        task.depends_on
                    )
                )

            lines.append(
                f"{task.id} | "
                f"{task.status} | "
                f"{task.assigned_agent or '-'} | "
                f"{task.title}"
                f"{dependency}"
            )

        return "\n".join(
            lines
        )

    def format_missions(
        self,
        limit: int = 20,
    ) -> str:

        missions = (
            self.missions.list()[
                -limit:
            ]
        )

        if not missions:

            return (
                "Aucune mission."
            )

        return "\n".join(
            (
                f"{mission.id} | "
                f"{mission.status} | "
                f"{mission.title} | "
                f"{len(mission.task_ids)} "
                "étape(s)"
            )
            for mission
            in reversed(
                missions
            )
        )

    def status(
        self,
    ) -> dict[
        str,
        Any,
    ]:

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
                    for task
                    in tasks
                    if (
                        task.status
                        == status
                    )
                ]
            )

        def count_missions(
            status,
        ) -> int:

            return len(
                [
                    mission
                    for mission
                    in missions
                    if (
                        mission.status
                        == status
                    )
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
            "last_task_id": (
                self.last_task_id
            ),
            "tasks": {
                "total": (
                    len(tasks)
                ),
                "pending": (
                    count_tasks(
                        TaskStatus
                        .PENDING
                        .value
                    )
                ),
                "waiting_dependency": (
                    count_tasks(
                        TaskStatus
                        .WAITING_DEPENDENCY
                        .value
                    )
                ),
                "running": (
                    count_tasks(
                        TaskStatus
                        .RUNNING
                        .value
                    )
                ),
                "waiting_approval": (
                    count_tasks(
                        TaskStatus
                        .WAITING_APPROVAL
                        .value
                    )
                ),
                "blocked": (
                    count_tasks(
                        TaskStatus
                        .BLOCKED
                        .value
                    )
                ),
                "completed": (
                    count_tasks(
                        TaskStatus
                        .COMPLETED
                        .value
                    )
                ),
                "failed": (
                    count_tasks(
                        TaskStatus
                        .FAILED
                        .value
                    )
                ),
            },
            "missions": {
                "total": (
                    len(
                        missions
                    )
                ),
                "pending": (
                    count_missions(
                        MissionStatus
                        .PENDING
                    )
                ),
                "running": (
                    count_missions(
                        MissionStatus
                        .RUNNING
                    )
                ),
                "completed": (
                    count_missions(
                        MissionStatus
                        .COMPLETED
                    )
                ),
                "failed": (
                    count_missions(
                        MissionStatus
                        .FAILED
                    )
                ),
            },
            "running_workers": (
                list(
                    self.worker_engine
                    .running
                    .keys()
                )
            ),
        }

    def shutdown(
        self,
    ) -> None:

        self.worker_engine.shutdown(
            wait=True
        )