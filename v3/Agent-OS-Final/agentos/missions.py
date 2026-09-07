from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore
from agentos.tasks import TaskManager, TaskStatus


@dataclass
class Mission:
    id: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str

    task_ids: list[str] = field(default_factory=list)
    plan: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MissionManager:

    def __init__(self) -> None:

        self.store = JsonStore(
            DATA_DIR / "missions.json",
            [],
        )

        self.lock = threading.RLock()

        self.missions: dict[str, Mission] = {}

        self._load()

    # =========================================================
    # INTERNAL
    # =========================================================

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _load(self) -> None:

        for item in self.store.load():

            try:

                mission = Mission(
                    **item
                )

                self.missions[
                    mission.id
                ] = mission

            except TypeError:

                pass

    def _save(self) -> None:

        self.store.save(
            [
                mission.to_dict()
                for mission
                in self.missions.values()
            ]
        )

    # =========================================================
    # CREATE
    # =========================================================

    def create(
        self,
        *,
        title: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> Mission:

        with self.lock:

            now = self._now()

            mission = Mission(
                id=(
                    "mission_"
                    + uuid.uuid4().hex[:10]
                ),
                title=title,
                description=description,
                status="planning",
                created_at=now,
                updated_at=now,
                metadata=metadata or {},
            )

            self.missions[
                mission.id
            ] = mission

            self._save()

            return mission

    # =========================================================
    # ACCESS
    # =========================================================

    def get(
        self,
        mission_id: str,
    ) -> Mission | None:

        return self.missions.get(
            mission_id
        )

    def list(
        self,
    ) -> list[Mission]:

        return sorted(
            self.missions.values(),
            key=lambda mission: (
                mission.created_at
            ),
            reverse=True,
        )

    # =========================================================
    # PLAN
    # =========================================================

    def attach_plan(
        self,
        mission_id: str,
        *,
        plan: list[dict[str, Any]],
        task_ids: list[str],
    ) -> Mission:

        with self.lock:

            mission = self.missions[
                mission_id
            ]

            mission.plan = plan

            mission.task_ids = (
                task_ids
            )

            mission.status = (
                "running"
                if task_ids
                else "failed"
            )

            mission.updated_at = (
                self._now()
            )

            self._save()

            return mission

    # =========================================================
    # STATUS
    # =========================================================

    def refresh(
        self,
        mission: Mission,
        tasks: TaskManager,
    ) -> Mission:

        if not mission.task_ids:

            return mission

        linked = [
            tasks.get(task_id)
            for task_id
            in mission.task_ids
        ]

        linked = [
            task
            for task
            in linked
            if task is not None
        ]

        if not linked:

            status = "failed"

        elif any(
            task.status
            == TaskStatus.FAILED.value
            for task
            in linked
        ):

            status = "failed"

        elif any(
            task.status
            == TaskStatus.CANCELLED.value
            for task
            in linked
        ):

            status = "cancelled"

        elif all(
            task.status
            == TaskStatus.COMPLETED.value
            for task
            in linked
        ):

            status = "completed"

        elif any(
            task.status
            == TaskStatus.WAITING_APPROVAL.value
            for task
            in linked
        ):

            status = (
                "waiting_approval"
            )

        elif any(
            task.status
            == TaskStatus.RUNNING.value
            for task
            in linked
        ):

            status = "running"

        else:

            status = "queued"

        if mission.status != status:

            with self.lock:

                mission.status = status

                mission.updated_at = (
                    self._now()
                )

                self._save()

        return mission

    # =========================================================
    # DISPLAY
    # =========================================================

    def format(
        self,
        tasks: TaskManager,
    ) -> str:

        if not self.missions:

            return "Aucune mission."

        sections: list[str] = []

        for mission in self.list():

            self.refresh(
                mission,
                tasks,
            )

            lines = [
                (
                    f"{mission.id} | "
                    f"{mission.status} | "
                    f"{mission.title}"
                )
            ]

            for index, task_id in enumerate(
                mission.task_ids,
                1,
            ):

                task = tasks.get(
                    task_id
                )

                if task is None:

                    lines.append(
                        (
                            f"  {index}. "
                            f"{task_id} | "
                            "introuvable"
                        )
                    )

                    continue

                lines.append(
                    (
                        f"  {index}. "
                        f"{task.status} | "
                        f"{task.worker} | "
                        f"{task.title}"
                    )
                )

            sections.append(
                "\n".join(lines)
            )

        return "\n\n".join(
            sections
        )