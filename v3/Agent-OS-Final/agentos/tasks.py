from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore


class TaskStatus(str, Enum):
    PENDING = "pending"
    WAITING_DEPENDENCY = "waiting_dependency"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str
    title: str
    description: str
    worker: str
    status: str
    created_at: str
    updated_at: str
    result: str | None = None
    result_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskManager:
    def __init__(self) -> None:
        self.store = JsonStore(
            DATA_DIR / "tasks.json",
            [],
        )
        self.lock = threading.RLock()
        self.tasks: dict[str, Task] = {}
        self._load()

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _load(self) -> None:
        loaded = self.store.load()

        if not isinstance(loaded, list):
            loaded = []

        for item in loaded:
            if not isinstance(item, dict):
                continue

            try:
                task = Task(**item)
            except TypeError:
                continue

            self.tasks[task.id] = task

    def _save(self) -> None:
        self.store.save(
            [
                task.to_dict()
                for task in self.tasks.values()
            ]
        )

    def create(
        self,
        *,
        title: str,
        description: str,
        worker: str,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        with self.lock:
            dependencies = list(
                dict.fromkeys(
                    depends_on or []
                )
            )

            now = self._now()

            status = (
                TaskStatus.PENDING.value
                if (
                    not dependencies
                    or self.dependencies_satisfied_ids(
                        dependencies
                    )
                )
                else TaskStatus.WAITING_DEPENDENCY.value
            )

            task = Task(
                id=(
                    "task_"
                    + uuid.uuid4().hex[:12]
                ),
                title=title,
                description=description,
                worker=worker,
                status=status,
                created_at=now,
                updated_at=now,
                depends_on=dependencies,
                metadata=metadata or {},
            )

            self.tasks[task.id] = task
            self._save()
            return task

    def get(
        self,
        task_id: str,
    ) -> Task | None:
        return self.tasks.get(task_id)

    def list(self) -> list[Task]:
        return sorted(
            self.tasks.values(),
            key=lambda task: task.created_at,
            reverse=True,
        )

    def update(
        self,
        task_id: str,
        **changes,
    ) -> Task:
        with self.lock:
            task = self.tasks[task_id]

            for key, value in changes.items():
                if not hasattr(task, key):
                    raise ValueError(
                        f"Champ inconnu : {key}"
                    )

                setattr(
                    task,
                    key,
                    value,
                )

            task.updated_at = self._now()
            self._save()
            return task

    def dependencies_satisfied_ids(
        self,
        ids: list[str],
    ) -> bool:
        return all(
            self.tasks.get(task_id)
            and (
                self.tasks[task_id].status
                == TaskStatus.COMPLETED.value
            )
            for task_id in ids
        )

    def dependency_failure(
        self,
        task: Task,
    ) -> str | None:
        for task_id in task.depends_on:
            dependency = self.tasks.get(
                task_id
            )

            if dependency is None:
                return (
                    "Dépendance introuvable : "
                    f"{task_id}"
                )

            if (
                dependency.status
                == TaskStatus.FAILED.value
            ):
                return (
                    "Dépendance échouée : "
                    f"{task_id}"
                )

            if (
                dependency.status
                == TaskStatus.CANCELLED.value
            ):
                return (
                    "Dépendance annulée : "
                    f"{task_id}"
                )

        return None

    def dependents_of(
        self,
        task_id: str,
    ) -> list[Task]:
        return [
            task
            for task in self.tasks.values()
            if task_id in task.depends_on
        ]

    def dependency_context(
        self,
        task: Task,
    ) -> list[dict[str, Any]]:
        context = []

        for task_id in task.depends_on:
            dependency = self.tasks.get(
                task_id
            )

            if dependency is None:
                continue

            context.append(
                {
                    "task_id": dependency.id,
                    "title": dependency.title,
                    "worker": dependency.worker,
                    "status": dependency.status,
                    "result": dependency.result,
                    "result_data": dependency.result_data,
                }
            )

        return context

    def set_paused(
        self,
        task_id: str,
    ) -> Task:
        task = self.tasks[task_id]

        if task.status in {
            TaskStatus.PENDING.value,
            TaskStatus.WAITING_DEPENDENCY.value,
        }:
            return self.update(
                task_id,
                status=TaskStatus.PAUSED.value,
            )

        return task

    def reset_for_execution(
        self,
        task_id: str,
    ) -> Task:
        task = self.tasks[task_id]

        status = (
            TaskStatus.PENDING.value
            if (
                not task.depends_on
                or self.dependencies_satisfied_ids(
                    task.depends_on
                )
            )
            else TaskStatus.WAITING_DEPENDENCY.value
        )

        return self.update(
            task_id,
            status=status,
            error=None,
        )

    def recover_interrupted(
        self,
        task_ids: list[str] | None = None,
    ) -> list[str]:
        selected = (
            set(task_ids)
            if task_ids is not None
            else None
        )

        recovered: list[str] = []

        with self.lock:
            changed = False

            for task in self.tasks.values():
                if (
                    selected is not None
                    and task.id not in selected
                ):
                    continue

                if (
                    task.status
                    != TaskStatus.RUNNING.value
                ):
                    continue

                if (
                    task.depends_on
                    and not self.dependencies_satisfied_ids(
                        task.depends_on
                    )
                ):
                    task.status = (
                        TaskStatus
                        .WAITING_DEPENDENCY
                        .value
                    )
                else:
                    task.status = (
                        TaskStatus.PENDING.value
                    )

                task.error = None
                task.updated_at = self._now()

                recovered.append(
                    task.id
                )
                changed = True

            if changed:
                self._save()

        return recovered

    def format(self) -> str:
        if not self.tasks:
            return "Aucune tâche."

        lines = []

        for task in self.list():
            line = (
                f"{task.id} | "
                f"{task.status} | "
                f"{task.worker} | "
                f"{task.title}"
            )

            if task.depends_on:
                line += (
                    " | dépend de "
                    + ",".join(
                        task.depends_on
                    )
                )

            lines.append(line)

        return "\n".join(lines)