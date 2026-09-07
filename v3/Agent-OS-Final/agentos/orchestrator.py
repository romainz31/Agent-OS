from __future__ import annotations

from typing import Any

from agentos.engine import (
    WorkerEngine,
)

from agentos.missions import (
    Mission,
    MissionManager,
)

from agentos.planner import (
    Planner,
)

from agentos.tasks import (
    TaskManager,
    TaskStatus,
)


class Orchestrator:

    def __init__(
        self,
        *,
        planner: Planner,
        missions: MissionManager,
        tasks: TaskManager,
        engine: WorkerEngine,
    ) -> None:
        self.planner = planner
        self.missions = missions
        self.tasks = tasks
        self.engine = engine

    # =========================================================
    # TITLE
    # =========================================================

    @staticmethod
    def _mission_title(
        message: str,
    ) -> str:
        clean = " ".join(
            message
            .strip()
            .split()
        )

        if len(clean) <= 90:
            return clean

        return (
            clean[:87]
            .rstrip()
            + "..."
        )

    @staticmethod
    def _normalize_message(
        message: str,
    ) -> str:
        return " ".join(
            message
            .lower()
            .strip()
            .split()
        )

    # =========================================================
    # CREATE TASKS
    # =========================================================

    def _create_tasks_from_plan(
        self,
        *,
        mission: Mission,
        message: str,
        initial_worker: str,
        router_reason: str,
    ) -> Mission:
        plan = self.planner.plan(
            message=message,
            initial_worker=(
                initial_worker
            ),
        )

        created_task_ids = []

        plan_dicts = [
            step.to_dict()
            for step
            in plan
        ]

        for step_index, step in enumerate(
            plan
        ):
            dependency_ids = []

            for dependency_index in (
                step.depends_on
            ):
                if (
                    0
                    <= dependency_index
                    < len(
                        created_task_ids
                    )
                ):
                    dependency_ids.append(
                        created_task_ids[
                            dependency_index
                        ]
                    )

            task = self.tasks.create(
                title=step.title,
                description=(
                    step.description
                ),
                worker=step.worker,
                depends_on=(
                    dependency_ids
                ),
                metadata={
                    "mission_id": (
                        mission.id
                    ),
                    "plan_step": (
                        step_index
                    ),
                    "original_message": (
                        message
                    ),
                    "router_reason": (
                        router_reason
                    ),
                },
            )

            created_task_ids.append(
                task.id
            )

        self.missions.attach_plan(
            mission.id,
            plan=plan_dicts,
            task_ids=created_task_ids,
        )

        for task_id in (
            created_task_ids
        ):
            self.engine.submit(
                task_id
            )

        return self.missions.get(
            mission.id
        )

    # =========================================================
    # CREATE MISSION
    # =========================================================

    def create_mission(
        self,
        *,
        message: str,
        initial_worker: str,
        router_reason: str,
    ):
        mission = (
            self.missions.create(
                title=(
                    self._mission_title(
                        message
                    )
                ),
                description=message,
                metadata={
                    "router_reason": (
                        router_reason
                    ),
                    "initial_worker": (
                        initial_worker
                    ),
                },
            )
        )

        try:
            return (
                self._create_tasks_from_plan(
                    mission=mission,
                    message=message,
                    initial_worker=(
                        initial_worker
                    ),
                    router_reason=(
                        router_reason
                    ),
                )
            )

        except Exception as exc:
            self.missions.set_status(
                mission.id,
                "failed",
                metadata_patch={
                    "planning_error": (
                        str(exc)
                    ),
                },
            )

            return None

    # =========================================================
    # MISSION TASK DISCOVERY
    # =========================================================

    def _tasks_for_mission(
        self,
        mission_id: str,
    ) -> list:
        result = []

        for task in (
            self.tasks.list()
        ):
            metadata = (
                task.metadata
                if isinstance(
                    task.metadata,
                    dict,
                )
                else {}
            )

            if (
                metadata.get(
                    "mission_id"
                )
                == mission_id
            ):
                result.append(
                    task
                )

        return result

    # =========================================================
    # DUPLICATE DETECTION
    # =========================================================

    def _duplicate_for_planning_mission(
        self,
        mission: Mission,
    ) -> Mission | None:
        wanted = (
            self._normalize_message(
                mission.description
            )
        )

        for other in (
            self.missions.list()
        ):
            if (
                other.id
                == mission.id
            ):
                continue

            # On regarde uniquement
            # les missions plus anciennes.
            if (
                other.created_at
                >= mission.created_at
            ):
                continue

            if (
                self._normalize_message(
                    other.description
                )
                != wanted
            ):
                continue

            self.missions.refresh(
                other,
                self.tasks,
            )

            if other.status in {
                "completed",
                "queued",
                "running",
                "waiting_approval",
            }:
                return other

        return None

    # =========================================================
    # PLANNING RECOVERY
    # =========================================================

    def recover_planning_missions(
        self,
    ) -> dict[str, Any]:
        resumed = []

        cancelled_duplicates = []

        cancelled_orphan_tasks = []

        failed = []

        planning = [
            mission
            for mission
            in self.missions.list()
            if (
                mission.status
                == "planning"
                and not mission.task_ids
            )
        ]

        # Les plus anciennes d'abord.
        for mission in reversed(
            planning
        ):
            duplicate = (
                self
                ._duplicate_for_planning_mission(
                    mission
                )
            )

            # Exemple actuel :
            # M-009 est la répétition de M-008.
            if duplicate is not None:
                self.missions.set_status(
                    mission.id,
                    "cancelled",
                    metadata_patch={
                        "recovery_reason": (
                            "duplicate_interrupted_planning"
                        ),
                        "duplicate_of": (
                            duplicate.human_id
                        ),
                    },
                )

                cancelled_duplicates.append(
                    {
                        "mission": (
                            mission.human_id
                        ),
                        "duplicate_of": (
                            duplicate.human_id
                        ),
                    }
                )

                continue

            # Cas plus rare :
            # le crash a eu lieu au milieu
            # de la création des tâches.
            orphan_tasks = (
                self._tasks_for_mission(
                    mission.id
                )
            )

            for task in (
                orphan_tasks
            ):
                if task.status not in {
                    TaskStatus.COMPLETED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                }:
                    self.tasks.update(
                        task.id,
                        status=(
                            TaskStatus
                            .CANCELLED
                            .value
                        ),
                        error=(
                            "Tâche abandonnée "
                            "pendant la planification "
                            "interrompue."
                        ),
                    )

                    cancelled_orphan_tasks.append(
                        task.id
                    )

            metadata = (
                mission.metadata
                if isinstance(
                    mission.metadata,
                    dict,
                )
                else {}
            )

            initial_worker = str(
                metadata.get(
                    "initial_worker",
                    "ai_worker",
                )
            )

            router_reason = str(
                metadata.get(
                    "router_reason",
                    "recovery",
                )
            )

            try:
                recovered = (
                    self
                    ._create_tasks_from_plan(
                        mission=mission,
                        message=(
                            mission.description
                        ),
                        initial_worker=(
                            initial_worker
                        ),
                        router_reason=(
                            router_reason
                        ),
                    )
                )

                if recovered is None:
                    raise RuntimeError(
                        (
                            "Mission introuvable "
                            "après reprise."
                        )
                    )

                resumed.append(
                    mission.human_id
                )

            except Exception as exc:
                self.missions.set_status(
                    mission.id,
                    "failed",
                    metadata_patch={
                        "recovery_error": (
                            str(exc)
                        ),
                    },
                )

                failed.append(
                    {
                        "mission": (
                            mission.human_id
                        ),
                        "error": (
                            str(exc)
                        ),
                    }
                )

        return {
            "resumed": resumed,
            "cancelled_duplicates": (
                cancelled_duplicates
            ),
            "cancelled_orphan_tasks": (
                cancelled_orphan_tasks
            ),
            "failed": failed,
        }

    # =========================================================
    # DISPLAY
    # =========================================================

    def format_created(
        self,
        mission,
    ) -> str:
        if mission is None:
            return (
                "Je n'ai pas pu "
                "préparer la mission."
            )

        if not mission.task_ids:
            return (
                "La mission a été créée, "
                "mais aucun travail exécutable "
                "n'a été préparé."
            )

        lines = [
            "D'accord, je m'en occupe.",
            "",
            "Plan de travail :",
        ]

        worker_names = {
            "researcher": (
                "Recherche"
            ),
            "developer": (
                "Développement"
            ),
            "tester": (
                "Vérification"
            ),
            "ai_worker": (
                "Analyse"
            ),
        }

        for index, task_id in enumerate(
            mission.task_ids,
            1,
        ):
            task = (
                self.tasks.get(
                    task_id
                )
            )

            if task is None:
                continue

            worker_name = (
                worker_names.get(
                    task.worker,
                    task.worker,
                )
            )

            lines.append(
                (
                    f"{index}. "
                    f"{worker_name} — "
                    f"{task.title}"
                )
            )

        lines.append(
            ""
        )

        lines.append(
            (
                "Je te tiens au courant "
                "de l'avancement."
            )
        )

        return "\n".join(
            lines
        )