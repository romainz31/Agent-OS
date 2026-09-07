from __future__ import annotations

import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)

from datetime import (
    datetime,
    timezone,
)

from typing import (
    Any,
)

from agentos.config import (
    DATA_DIR,
)

from agentos.storage import (
    JsonStore,
)

from agentos.tasks import (
    TaskManager,
    TaskStatus,
)


@dataclass
class Mission:

    id: str

    title: str

    original_message: str

    created_at: str

    updated_at: str

    task_ids: list[str] = field(
        default_factory=list
    )

    status: str = "pending"

    result: str | None = None

    error: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return asdict(
            self
        )


class MissionManager:

    TERMINAL = {
        "completed",
        "failed",
        "cancelled",
    }

    def __init__(
        self,
        tasks: TaskManager,
    ) -> None:

        self.tasks = tasks

        self.store = JsonStore(
            DATA_DIR / "missions.json",
            [],
        )

        self.missions: dict[
            str,
            Mission,
        ] = {}

        self._load()

    # ========================================================
    # TIME
    # ========================================================

    @staticmethod
    def _now(
    ) -> str:

        return datetime.now(
            timezone.utc
        ).isoformat()

    # ========================================================
    # STORAGE
    # ========================================================

    def _load(
        self,
    ) -> None:

        self.missions = {}

        for item in (
            self.store.load()
        ):

            try:

                mission = Mission(
                    **item
                )

            except TypeError:

                continue

            self.missions[
                mission.id
            ] = mission

    def _save(
        self,
    ) -> None:

        self.store.save(
            [
                mission.to_dict()
                for mission
                in self.missions.values()
            ]
        )

    # ========================================================
    # CREATE
    # ========================================================

    def create(
        self,
        *,
        title: str,
        original_message: str,
        task_ids: list[str],
        metadata: dict[str, Any]
        | None = None,
    ) -> Mission:

        now = (
            self._now()
        )

        mission = Mission(
            id=(
                "mission_"
                + uuid.uuid4().hex[
                    :12
                ]
            ),
            title=title,
            original_message=(
                original_message
            ),
            created_at=now,
            updated_at=now,
            task_ids=list(
                task_ids
            ),
            status="pending",
            metadata=(
                metadata
                or {}
            ),
        )

        self.missions[
            mission.id
        ] = mission

        self._save()

        return mission

    # ========================================================
    # READ
    # ========================================================

    def get(
        self,
        mission_id: str,
    ) -> Mission | None:

        return (
            self.missions.get(
                mission_id
            )
        )

    def list(
        self,
    ) -> list[Mission]:

        self.refresh_all()

        return sorted(
            self.missions.values(),
            key=lambda mission:
            mission.created_at,
            reverse=True,
        )

    # ========================================================
    # STATUS
    # ========================================================

    def refresh(
        self,
        mission_id: str,
    ) -> Mission | None:

        mission = (
            self.get(
                mission_id
            )
        )

        if mission is None:

            return None

        task_objects = []

        for task_id in (
            mission.task_ids
        ):

            task = (
                self.tasks.get(
                    task_id
                )
            )

            if task is not None:

                task_objects.append(
                    task
                )

        if not task_objects:

            mission.status = (
                "failed"
            )

            mission.error = (
                "La mission ne contient "
                "aucune tâche valide."
            )

            mission.updated_at = (
                self._now()
            )

            self._save()

            return mission

        statuses = [
            task.status
            for task
            in task_objects
        ]

        # ----------------------------------------------------
        # FAILED
        # ----------------------------------------------------

        if any(
            status
            == TaskStatus.FAILED.value
            for status
            in statuses
        ):

            mission.status = (
                "failed"
            )

            failed = next(
                (
                    task
                    for task
                    in task_objects
                    if (
                        task.status
                        == TaskStatus
                        .FAILED
                        .value
                    )
                ),
                None,
            )

            mission.error = (
                failed.error
                if failed
                else (
                    "Une tâche "
                    "de la mission a échoué."
                )
            )

        # ----------------------------------------------------
        # CANCELLED
        # ----------------------------------------------------

        elif any(
            status
            == TaskStatus.CANCELLED.value
            for status
            in statuses
        ):

            mission.status = (
                "cancelled"
            )

            mission.error = (
                "Une tâche de la mission "
                "a été annulée."
            )

        # ----------------------------------------------------
        # COMPLETED
        # ----------------------------------------------------

        elif all(
            status
            == TaskStatus.COMPLETED.value
            for status
            in statuses
        ):

            mission.status = (
                "completed"
            )

            final_task = (
                task_objects[-1]
            )

            mission.result = (
                final_task.result
            )

            mission.error = None

        # ----------------------------------------------------
        # WAITING APPROVAL
        # ----------------------------------------------------

        elif any(
            status
            == TaskStatus
            .WAITING_APPROVAL
            .value
            for status
            in statuses
        ):

            mission.status = (
                "waiting_approval"
            )

        # ----------------------------------------------------
        # RUNNING
        # ----------------------------------------------------

        elif any(
            status
            == TaskStatus.RUNNING.value
            for status
            in statuses
        ):

            mission.status = (
                "running"
            )

        # ----------------------------------------------------
        # WAITING DEPENDENCY
        # ----------------------------------------------------

        elif any(
            status
            == TaskStatus
            .WAITING_DEPENDENCY
            .value
            for status
            in statuses
        ):

            mission.status = (
                "running"
            )

        else:

            mission.status = (
                "pending"
            )

        mission.updated_at = (
            self._now()
        )

        self._save()

        return mission

    def refresh_all(
        self,
    ) -> None:

        for mission_id in list(
            self.missions
        ):

            self.refresh(
                mission_id
            )

    # ========================================================
    # TASK LOOKUP
    # ========================================================

    def mission_for_task(
        self,
        task_id: str,
    ) -> Mission | None:

        for mission in (
            self.missions.values()
        ):

            if (
                task_id
                in mission.task_ids
            ):

                return mission

        return None

    # ========================================================
    # FORMAT
    # ========================================================

    def format(
        self,
    ) -> str:

        missions = (
            self.list()
        )

        if not missions:

            return (
                "Aucune mission."
            )

        lines = []

        for mission in missions:

            lines.append(
                (
                    f"{mission.id} | "
                    f"{mission.status} | "
                    f"{mission.title}"
                )
            )

            for index, task_id in enumerate(
                mission.task_ids,
                start=1,
            ):

                task = (
                    self.tasks.get(
                        task_id
                    )
                )

                if task is None:

                    lines.append(
                        (
                            f"  {index}. "
                            f"{task_id} | introuvable"
                        )
                    )

                    continue

                lines.append(
                    (
                        f"  {index}. "
                        f"{task.id} | "
                        f"{task.status} | "
                        f"{task.worker} | "
                        f"{task.title}"
                    )
                )

        return "\n".join(
            lines
        )