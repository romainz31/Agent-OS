from __future__ import annotations

from agentos.engine import (
    WorkerEngine,
)

from agentos.missions import (
    MissionManager,
)

from agentos.planner import (
    Planner,
)

from agentos.tasks import (
    TaskManager,
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

    # =========================================================
    # CREATE
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

        # Toutes les tâches sont proposées au moteur.
        # Les dépendances bloquent automatiquement
        # celles qui doivent attendre.

        for task_id in created_task_ids:

            self.engine.submit(
                task_id
            )

        return self.missions.get(
            mission.id
        )

    # =========================================================
    # USER DISPLAY
    # =========================================================

    def format_created(
        self,
        mission,
    ) -> str:

        lines = [
            "D'accord, je m'en occupe.",
            "",
            "Plan de travail :",
        ]

        for index, task_id in enumerate(
            mission.task_ids,
            1,
        ):

            task = self.tasks.get(
                task_id
            )

            if task is None:

                continue

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
            "Je te tiens au courant "
            "de l'avancement."
        )

        return "\n".join(
            lines
        )