"""
Manager principal Agent-OS V2.2.1.

Ajoute :
- dépendances entre tâches ;
- référence au dernier travail de la session ;
- notifications de fin ;
- transmission automatique du résultat entre étapes ;
- affichage explicite task/worker/status ;
- plan déterministe pour les missions multi-agents.
"""

from __future__ import annotations

import json
import re

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
        llm: Optional[LLM] = None,
        memory: Optional[MemoryStore] = None,
        tasks: Optional[TaskManager] = None,
        missions: Optional[MissionManager] = None,
        permissions: Optional[PermissionEngine] = None,
        event_bus: Optional[EventBus] = None,
        worker_engine: Optional[WorkerEngine] = None,
        router: Optional[ManagerRouter] = None,
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
                task_manager=self.tasks,
                event_bus=self.event_bus,
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
            self.worker_engine.workers.keys()
        )

    def list_workers(
        self,
    ) -> list[
        dict[str, str]
    ]:

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
                action="create_task",
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
            action="create_mission",
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

        dependencies = (
            self._resolve_dependencies(
                original_message
            )
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
            depends_on=(
                dependencies
            ),
            metadata=(
                decision.metadata
            ),
        )

        self.last_task_id = (
            task.id
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
                f"Worker : {assigned_agent}\n"
                f"Statut : {task.status}"
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
            f"Tâche créée : {task.id}\n"
            f"Worker : {assigned_agent}\n"
            f"Statut : {task.status}"
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

        planned_steps = (
            self._build_mission_plan(
                original_message
            )
        )

        if not planned_steps:

            planned_steps = [
                {
                    "description": (
                        decision.description
                        or original_message
                    ),
                    "worker": (
                        decision.assigned_agent
                        or self._fallback_worker()
                    ),
                }
            ]

        metadata = dict(
            decision.metadata
            or {}
        )

        metadata[
            "planned_steps"
        ] = planned_steps

        metadata[
            "current_step_index"
        ] = 0

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
                metadata=metadata,
            )
        )

        first_step = (
            planned_steps[0]
        )

        assigned_agent = (
            first_step.get(
                "worker"
            )
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
                "créée mais aucun worker "
                "n'est disponible."
            )

        first_description = (
            first_step.get(
                "description"
            )
            or original_message
        )

        task = (
            self.tasks.create(
                title=(
                    self._fallback_title(
                        first_description
                    )
                ),
                description=(
                    first_description
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
                    "mission_step_index": 0,
                    "mission_objective": (
                        mission.objective
                    ),
                },
            )
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
            f"Mission créée : {mission.id}\n"
            f"Étapes prévues : "
            f"{len(planned_steps)}\n"
            f"Première tâche : {task.id}\n"
            f"Worker : {assigned_agent}\n"
            f"Statut : {task.status}"
        )

    def _build_mission_plan(
        self,
        message: str,
    ) -> list[
        dict[str, str]
    ]:

        cleaned = (
            " ".join(
                message.split()
            )
        )

        if not cleaned:

            return []

        # "d'abord" appartient à la première étape.
        # On ne découpe qu'à partir des transitions suivantes.
        split_pattern = (
            r"\s*(?:,|\bet\b)?\s*"
            r"(?:ensuite|puis|enfin|après|apres)"
            r"\s+"
        )

        parts = re.split(
            split_pattern,
            cleaned,
            flags=re.IGNORECASE,
        )

        parts = [
            part.strip(
                " ,.;:"
            )
            for part
            in parts
            if part.strip(
                " ,.;:"
            )
        ]

        if len(parts) < 2:

            return []

        steps = []

        for part in parts:

            route = (
                self.router.route(
                    message=part,
                    available_workers=(
                        self.get_worker_names()
                    ),
                )
            )

            worker = (
                route.worker
            )

            if not worker:

                worker = (
                    self._infer_worker_for_step(
                        part
                    )
                )

            if not worker:

                worker = (
                    self._fallback_worker()
                )

            if not worker:
                continue

            steps.append(
                {
                    "description": (
                        part
                    ),
                    "worker": (
                        worker
                    ),
                }
            )

        return steps

    def _infer_worker_for_step(
        self,
        text: str,
    ) -> Optional[str]:

        lower = (
            text.lower()
        )

        available = set(
            self.get_worker_names()
        )

        researcher_words = (
            "recherche",
            "chercher",
            "cherche",
            "trouve",
            "documentation",
            "documente",
            "analyse les sources",
            "bonnes pratiques",
        )

        developer_words = (
            "crée",
            "cree",
            "code",
            "développe",
            "developpe",
            "implémente",
            "implemente",
            "architecture",
            "conçois",
            "concois",
            "script",
            "programme",
        )

        tester_words = (
            "teste",
            "test",
            "vérifie",
            "verifie",
            "valide",
            "bugs",
            "bug",
            "contrôle",
            "controle",
        )

        if (
            "tester" in available
            and any(
                word in lower
                for word
                in tester_words
            )
        ):

            return "tester"

        if (
            "developer" in available
            and any(
                word in lower
                for word
                in developer_words
            )
        ):

            return "developer"

        if (
            "researcher" in available
            and any(
                word in lower
                for word
                in researcher_words
            )
        ):

            return "researcher"

        return None

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

        task = (
            self.tasks.get(
                task_id
            )
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

        task = (
            self.tasks.get(
                task_id
            )
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

        if (
            mission.status
            in {
                MissionStatus.COMPLETED,
                MissionStatus.FAILED,
                MissionStatus.CANCELLED,
            }
        ):
            return

        planned_steps = (
            mission.metadata.get(
                "planned_steps",
                [],
            )
        )

        if not isinstance(
            planned_steps,
            list,
        ):

            planned_steps = []

        current_step_index = (
            completed_task.metadata.get(
                "mission_step_index",
                0,
            )
        )

        try:

            current_step_index = int(
                current_step_index
            )

        except (
            TypeError,
            ValueError,
        ):

            current_step_index = 0

        next_step_index = (
            current_step_index
            + 1
        )

        if (
            next_step_index
            >= len(
                planned_steps
            )
        ):

            final_result = (
                completed_task.result
                or (
                    "Toutes les étapes "
                    "de la mission "
                    "ont été terminées."
                )
            )

            self.missions.complete(
                mission_id,
                result=(
                    final_result
                ),
            )

            self.notifications.append(
                f"✓ Mission "
                f"{mission_id} terminée."
            )

            return

        next_step = (
            planned_steps[
                next_step_index
            ]
        )

        if not isinstance(
            next_step,
            dict,
        ):

            self.missions.fail(
                mission_id,
                (
                    "Étape de mission "
                    "invalide."
                ),
            )

            return

        description = str(
            next_step.get(
                "description",
                "",
            )
        ).strip()

        assigned_agent = str(
            next_step.get(
                "worker",
                "",
            )
        ).strip()

        if (
            not description
            or not assigned_agent
        ):

            self.missions.fail(
                mission_id,
                (
                    "Étape suivante "
                    "incomplète."
                ),
            )

            return

        if (
            assigned_agent
            not in self.get_worker_names()
        ):

            assigned_agent = (
                self._infer_worker_for_step(
                    description
                )
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

        task = (
            self.tasks.create(
                title=(
                    self._fallback_title(
                        description
                    )
                ),
                description=(
                    description
                ),
                priority=(
                    mission.priority
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
                        next_step_index
                        + 1
                    ),
                    "mission_step_index": (
                        next_step_index
                    ),
                    "previous_task_id": (
                        completed_task.id
                    ),
                    "mission_objective": (
                        mission.objective
                    ),
                },
            )
        )

        mission.metadata[
            "current_step_index"
        ] = next_step_index

        self.missions.add_task(
            mission_id,
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
                    mission_id
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

        self.notifications.append(
            f"→ Mission {mission_id}, "
            f"étape "
            f"{next_step_index + 1}/"
            f"{len(planned_steps)} : "
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

        if not self.session_messages:

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

            start = (
                text.find(
                    "{"
                )
            )

            end = (
                text.rfind(
                    "}"
                )
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

        title = (
            " ".join(
                message.split()
            )
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

        lines = []

        for mission in reversed(
            missions
        ):

            planned_steps = (
                mission.metadata.get(
                    "planned_steps",
                    [],
                )
            )

            planned_count = (
                len(planned_steps)
                if isinstance(
                    planned_steps,
                    list,
                )
                else 0
            )

            lines.append(
                f"{mission.id} | "
                f"{mission.status} | "
                f"{mission.title} | "
                f"{len(mission.task_ids)}/"
                f"{planned_count or len(mission.task_ids)} "
                "étape(s)"
            )

        return "\n".join(
            lines
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
                    if task.status == status
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