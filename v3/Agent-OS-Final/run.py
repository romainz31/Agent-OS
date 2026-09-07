from __future__ import annotations

import re
import threading

from agentos.approvals import (
    ApprovalManager,
)

from agentos.engine import (
    WorkerEngine,
)

from agentos.llm import (
    LLM,
    LLMError,
)

from agentos.memory import (
    Memory,
)

from agentos.missions import (
    MissionManager,
)

from agentos.permissions import (
    PermissionEngine,
)

from agentos.project_files import (
    ProjectFiles,
)

from agentos.python_runner import (
    PythonRunner,
)

from agentos.router import (
    Router,
)

from agentos.tasks import (
    TaskManager,
)

from agentos.workers import (
    AIWorker,
    DeveloperWorker,
    ResearcherWorker,
    TesterWorker,
)


class Manager:

    MISSION_SPLIT_PATTERN = (
        r"\s*(?:,|\bet\b)?\s*"
        r"(?:ensuite|puis|enfin|"
        r"après|apres)"
        r"\s+"
    )

    MISSION_START_MARKERS = (
        "d'abord",
        "d’abord",
        "commence par",
        "premièrement",
        "premierement",
    )

    def __init__(
        self,
    ) -> None:

        self.llm = (
            LLM()
        )

        self.memory = (
            Memory()
        )

        self.permissions = (
            PermissionEngine()
        )

        self.tasks = (
            TaskManager()
        )

        self.router = (
            Router()
        )

        self.files = (
            ProjectFiles(
                self.permissions
            )
        )

        self.runner = (
            PythonRunner(
                self.permissions
            )
        )

        self.missions = (
            MissionManager(
                self.tasks
            )
        )

        self._lock = (
            threading.RLock()
        )

        self._notifications: list[
            str
        ] = []

        self._mission_terminal_cache: dict[
            str,
            str,
        ] = {}

        # ====================================================
        # ENGINE
        # ====================================================

        self.engine = (
            WorkerEngine(
                self.tasks,
                self.notify,
            )
        )

        self.engine.register(
            AIWorker(
                self.llm
            )
        )

        self.engine.register(
            ResearcherWorker(
                self.llm,
                self.permissions,
            )
        )

        self.engine.register(
            DeveloperWorker(
                self.llm,
                self.files,
                self.runner,
            )
        )

        self.engine.register(
            TesterWorker(
                self.llm,
                self.files,
                self.runner,
            )
        )

        # ====================================================
        # APPROVALS
        # ====================================================

        self.approvals = (
            ApprovalManager(
                self.tasks,
                self.files,
                self.runner,
                self.engine.resume_dependents,
            )
        )

    # ========================================================
    # NOTIFICATIONS
    # ========================================================

    def notify(
        self,
        text: str,
    ) -> None:

        with self._lock:

            self._notifications.append(
                text
            )

        self._refresh_missions()

    def drain_notifications(
        self,
    ) -> list[str]:

        self._refresh_missions()

        with self._lock:

            values = list(
                self._notifications
            )

            self._notifications.clear()

            return values

    # ========================================================
    # MISSION NOTIFICATION
    # ========================================================

    def _refresh_missions(
        self,
    ) -> None:

        self.missions.refresh_all()

        for mission in (
            self.missions.missions.values()
        ):

            previous = (
                self._mission_terminal_cache
                .get(
                    mission.id
                )
            )

            current = (
                mission.status
            )

            if (
                current
                not in {
                    "completed",
                    "failed",
                    "cancelled",
                }
            ):

                continue

            if (
                previous
                == current
            ):

                continue

            self._mission_terminal_cache[
                mission.id
            ] = current

            if (
                current
                == "completed"
            ):

                notification = (
                    f"✓ Mission {mission.id} "
                    "terminée."
                )

            elif (
                current
                == "cancelled"
            ):

                notification = (
                    f"✗ Mission {mission.id} "
                    "annulée."
                )

            else:

                notification = (
                    f"✗ Mission {mission.id} "
                    f"échouée : "
                    f"{mission.error or 'erreur inconnue'}"
                )

            with self._lock:

                self._notifications.append(
                    notification
                )

    # ========================================================
    # TITLES
    # ========================================================

    @staticmethod
    def _task_title(
        message: str,
    ) -> str:

        clean = " ".join(
            message
            .strip()
            .split()
        )

        if (
            len(clean)
            <= 90
        ):

            return clean

        return (
            clean[
                :87
            ].rstrip()
            + "..."
        )

    # ========================================================
    # CONVERSATION
    # ========================================================

    def _conversation(
        self,
        message: str,
    ) -> str:

        try:

            return self.llm.chat(
                (
                    "Tu es le Manager "
                    "d'Agent-OS, interlocuteur "
                    "principal de l'utilisateur.\n\n"
                    "CONTEXTE MÉMOIRE:\n"
                    f"{self.memory.context()}\n\n"
                    "MESSAGE COURANT:\n"
                    f"{message}\n\n"
                    "Réponds naturellement "
                    "en français. "
                    "Ne prétends pas qu'un worker "
                    "a travaillé si aucune tâche "
                    "ne l'a fait."
                )
            )

        except LLMError as exc:

            return (
                "Ollama inaccessible : "
                f"{exc}"
            )

    # ========================================================
    # MISSION DETECTION
    # ========================================================

    @classmethod
    def _looks_like_mission(
        cls,
        message: str,
    ) -> bool:

        lower = (
            message.lower()
        )

        if re.search(
            cls.MISSION_SPLIT_PATTERN,
            lower,
            flags=re.IGNORECASE,
        ):

            return True

        if any(
            marker in lower
            for marker
            in cls.MISSION_START_MARKERS
        ):

            return True

        return False

    # ========================================================
    # NORMALIZE FIRST STEP
    # ========================================================

    @classmethod
    def _clean_first_step(
        cls,
        text: str,
    ) -> str:

        value = (
            text.strip()
        )

        lower = (
            value.lower()
        )

        for marker in (
            cls.MISSION_START_MARKERS
        ):

            if lower.startswith(
                marker
            ):

                value = (
                    value[
                        len(marker):
                    ]
                    .lstrip(
                        " ,:-"
                    )
                )

                break

        return value.strip()

    # ========================================================
    # SPLIT MISSION
    # ========================================================

    @classmethod
    def _split_mission(
        cls,
        message: str,
    ) -> list[str]:

        parts = re.split(
            cls.MISSION_SPLIT_PATTERN,
            message.strip(),
            flags=re.IGNORECASE,
        )

        cleaned = []

        for index, part in enumerate(
            parts
        ):

            value = (
                part
                .strip()
                .strip(
                    " ,.;"
                )
            )

            if (
                index == 0
            ):

                value = (
                    cls._clean_first_step(
                        value
                    )
                )

            if value:

                cleaned.append(
                    value
                )

        return cleaned

    # ========================================================
    # CREATE SIMPLE TASK
    # ========================================================

    def _create_task(
        self,
        *,
        message: str,
        depends_on: list[str]
        | None = None,
        mission_id: str
        | None = None,
        step_index: int
        | None = None,
    ):

        route = (
            self.router.route(
                message
            )
        )

        if (
            route.kind
            == "conversation"
        ):

            worker = (
                "ai_worker"
            )

        else:

            worker = (
                route.worker
                or "ai_worker"
            )

        metadata = {
            "original_message": (
                message
            ),
            "router_reason": (
                route.reason
            ),
        }

        if mission_id:

            metadata[
                "mission_id"
            ] = mission_id

        if step_index is not None:

            metadata[
                "mission_step"
            ] = step_index

        task = (
            self.tasks.create(
                title=(
                    self._task_title(
                        message
                    )
                ),
                description=message,
                worker=worker,
                depends_on=(
                    depends_on
                    or []
                ),
                metadata=metadata,
            )
        )

        return task

    # ========================================================
    # CREATE MISSION
    # ========================================================

    def _create_mission(
        self,
        message: str,
    ) -> str:

        steps = (
            self._split_mission(
                message
            )
        )

        if (
            len(steps)
            < 2
        ):

            # Faux positif :
            # revient au mode simple.
            task = (
                self._create_task(
                    message=message
                )
            )

            self.engine.submit(
                task.id
            )

            return (
                f"Tâche créée : {task.id}\n"
                f"Worker : {task.worker}\n"
                f"Statut : "
                f"{self.tasks.get(task.id).status}"
            )

        # ----------------------------------------------------
        # Mission créée avant les tâches
        # ----------------------------------------------------

        mission = (
            self.missions.create(
                title=(
                    self._task_title(
                        message
                    )
                ),
                original_message=message,
                task_ids=[],
                metadata={
                    "steps": steps,
                },
            )
        )

        task_ids = []

        previous_task_id = (
            None
        )

        for index, step in enumerate(
            steps,
            start=1,
        ):

            dependencies = []

            if (
                previous_task_id
                is not None
            ):

                dependencies.append(
                    previous_task_id
                )

            task = (
                self._create_task(
                    message=step,
                    depends_on=dependencies,
                    mission_id=mission.id,
                    step_index=index,
                )
            )

            task_ids.append(
                task.id
            )

            previous_task_id = (
                task.id
            )

        mission.task_ids = (
            task_ids
        )

        mission.updated_at = (
            self.missions._now()
        )

        self.missions._save()

        # ----------------------------------------------------
        # On lance seulement la première tâche.
        # Les suivantes seront réveillées automatiquement.
        # ----------------------------------------------------

        self.engine.submit(
            task_ids[0]
        )

        self.missions.refresh(
            mission.id
        )

        lines = [
            (
                f"Mission créée : "
                f"{mission.id}"
            ),
            (
                f"Étapes : "
                f"{len(task_ids)}"
            ),
        ]

        for index, task_id in enumerate(
            task_ids,
            start=1,
        ):

            task = (
                self.tasks.get(
                    task_id
                )
            )

            lines.append(
                (
                    f"{index}. "
                    f"{task.worker} | "
                    f"{task.status} | "
                    f"{task.title}"
                )
            )

        return "\n".join(
            lines
        )

    # ========================================================
    # HANDLE
    # ========================================================

    def handle(
        self,
        message: str,
    ) -> str:

        value = (
            message.strip()
        )

        cmd = (
            value.lower()
        )

        if not value:

            return ""

        # ====================================================
        # COMMANDS
        # ====================================================

        if (
            cmd
            == "tasks"
        ):

            return (
                self.tasks.format()
            )

        if (
            cmd
            == "missions"
        ):

            return (
                self.missions.format()
            )

        if (
            cmd
            == "approvals"
        ):

            return (
                self.approvals.format()
            )

        if (
            cmd
            == "memory"
        ):

            return (
                self.memory.format()
            )

        if (
            cmd
            == "status"
        ):

            self._refresh_missions()

            running_missions = len(
                [
                    mission
                    for mission
                    in self.missions
                    .missions
                    .values()
                    if (
                        mission.status
                        not in {
                            "completed",
                            "failed",
                            "cancelled",
                        }
                    )
                ]
            )

            return (
                "Workers : "
                f"{', '.join(self.engine.workers)}\n"
                "Tâches en cours : "
                f"{len(self.engine.running)}\n"
                "Missions actives : "
                f"{running_missions}\n"
                "Approbations : "
                f"{len(self.approvals.pending())}"
            )

        # ====================================================
        # APPROVAL
        # ====================================================

        if cmd in {
            "oui",
            "yes",
            "y",
            "approve",
            "autorise",
        }:

            response = (
                self.approvals
                .approve_latest()
            )

            self._refresh_missions()

            return response

        if cmd in {
            "non",
            "no",
            "n",
            "reject",
            "refuse",
        }:

            response = (
                self.approvals
                .reject_latest()
            )

            self._refresh_missions()

            return response

        # ====================================================
        # MEMORY
        # ====================================================

        self.memory.add_session(
            "user",
            value,
        )

        self.memory.maybe_remember(
            value
        )

        # ====================================================
        # MISSION
        # ====================================================

        if (
            self._looks_like_mission(
                value
            )
        ):

            return (
                self._create_mission(
                    value
                )
            )

        # ====================================================
        # SIMPLE ROUTING
        # ====================================================

        route = (
            self.router.route(
                value
            )
        )

        if (
            route.kind
            == "conversation"
        ):

            answer = (
                self._conversation(
                    value
                )
            )

            self.memory.add_session(
                "assistant",
                answer,
            )

            return answer

        task = (
            self._create_task(
                message=value
            )
        )

        self.engine.submit(
            task.id
        )

        return (
            f"Tâche créée : {task.id}\n"
            f"Worker : {task.worker}\n"
            f"Statut : "
            f"{self.tasks.get(task.id).status}"
        )

    # ========================================================
    # SHUTDOWN
    # ========================================================

    def shutdown(
        self,
    ) -> None:

        self.engine.shutdown()