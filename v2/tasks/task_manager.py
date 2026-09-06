"""
Task Manager Agent-OS V2.2.

Ajoute :
- dépendances entre tâches ;
- attente automatique des dépendances ;
- résultats structurés ;
- contexte provenant des tâches précédentes.
"""

from __future__ import annotations

import json
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from v2.config import DATA_DIR


class TaskStatus(str, Enum):
    PENDING = "pending"
    WAITING_DEPENDENCY = "waiting_dependency"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str
    title: str
    description: str

    status: str = TaskStatus.PENDING.value
    priority: str = "normal"

    created_at: str = ""
    updated_at: str = ""

    deadline: Optional[str] = None
    assigned_agent: Optional[str] = None

    result: Optional[str] = None
    result_data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    parent_task_id: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
    ) -> "Task":

        legacy_metadata = dict(
            data.get("metadata", {}) or {}
        )

        legacy_result_data = (
            legacy_metadata.get(
                "result_data",
                {},
            )
        )

        result_data = data.get(
            "result_data",
            legacy_result_data,
        )

        if not isinstance(
            result_data,
            dict,
        ):
            result_data = {}

        depends_on = data.get(
            "depends_on",
            [],
        )

        if not isinstance(
            depends_on,
            list,
        ):
            depends_on = []

        return cls(
            id=str(
                data["id"]
            ),
            title=str(
                data.get(
                    "title",
                    "",
                )
            ),
            description=str(
                data.get(
                    "description",
                    "",
                )
            ),
            status=str(
                data.get(
                    "status",
                    TaskStatus.PENDING.value,
                )
            ),
            priority=str(
                data.get(
                    "priority",
                    "normal",
                )
            ),
            created_at=str(
                data.get(
                    "created_at",
                    "",
                )
            ),
            updated_at=str(
                data.get(
                    "updated_at",
                    "",
                )
            ),
            deadline=data.get(
                "deadline"
            ),
            assigned_agent=data.get(
                "assigned_agent"
            ),
            result=data.get(
                "result"
            ),
            result_data=result_data,
            error=data.get(
                "error"
            ),
            parent_task_id=data.get(
                "parent_task_id"
            ),
            depends_on=[
                str(item)
                for item
                in depends_on
                if item
            ],
            metadata=legacy_metadata,
        )


class TaskManager:
    PRIORITIES = {
        "low",
        "normal",
        "high",
        "critical",
    }

    TERMINAL_STATUSES = {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }

    def __init__(
        self,
        storage_path: Optional[
            Path
        ] = None,
    ) -> None:

        if storage_path is None:

            storage_path = (
                DATA_DIR
                / "tasks"
                / "tasks.json"
            )

        self.storage_path = Path(
            storage_path
        )

        self.storage_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._tasks: Dict[
            str,
            Task,
        ] = {}

        self._load()

    # ========================================================
    # STORAGE
    # ========================================================

    def _load(
        self,
    ) -> None:

        if not self.storage_path.exists():

            self._tasks = {}
            return

        try:

            with self.storage_path.open(
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(
                    file
                )

        except (
            OSError,
            json.JSONDecodeError,
        ):

            print(
                "[TASK MANAGER] "
                "Impossible de charger tasks.json."
            )

            self._tasks = {}
            return

        if not isinstance(
            data,
            list,
        ):

            self._tasks = {}
            return

        self._tasks = {}

        for item in data:

            if not isinstance(
                item,
                dict,
            ):
                continue

            try:

                task = Task.from_dict(
                    item
                )

                self._tasks[
                    task.id
                ] = task

            except (
                KeyError,
                TypeError,
                ValueError,
            ):

                continue

    def _save(
        self,
    ) -> None:

        data = [
            task.to_dict()
            for task
            in self._tasks.values()
        ]

        temporary_path = (
            self.storage_path.with_suffix(
                ".tmp"
            )
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )

        temporary_path.replace(
            self.storage_path
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _now(
    ) -> str:

        return datetime.now(
            timezone.utc
        ).isoformat()

    def _touch(
        self,
        task: Task,
    ) -> None:

        task.updated_at = (
            self._now()
        )

    def _get_task_or_raise(
        self,
        task_id: str,
    ) -> Task:

        task = self.get(
            task_id
        )

        if task is None:

            raise ValueError(
                "Tâche introuvable : "
                f"{task_id}"
            )

        return task

    # ========================================================
    # CREATE
    # ========================================================

    def create(
        self,
        title: str,
        description: str,
        priority: str = "normal",
        deadline: Optional[
            str
        ] = None,
        assigned_agent: Optional[
            str
        ] = None,
        parent_task_id: Optional[
            str
        ] = None,
        depends_on: Optional[
            List[str]
        ] = None,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Task:

        if (
            not title
            or not title.strip()
        ):

            raise ValueError(
                "Le titre de la tâche "
                "est obligatoire."
            )

        if (
            priority
            not in self.PRIORITIES
        ):

            raise ValueError(
                "Priorité invalide : "
                f"{priority}"
            )

        dependency_ids = []

        for dependency_id in (
            depends_on
            or []
        ):

            dependency_id = str(
                dependency_id
            ).strip()

            if (
                dependency_id
                and dependency_id
                not in dependency_ids
            ):

                dependency_ids.append(
                    dependency_id
                )

        for dependency_id in (
            dependency_ids
        ):

            if (
                dependency_id
                not in self._tasks
            ):

                raise ValueError(
                    "Dépendance introuvable : "
                    f"{dependency_id}"
                )

        now = self._now()

        status = (
            TaskStatus.PENDING.value
        )

        if (
            dependency_ids
            and not self.dependencies_satisfied_ids(
                dependency_ids
            )
        ):

            status = (
                TaskStatus
                .WAITING_DEPENDENCY
                .value
            )

        task = Task(
            id=(
                "task_"
                + uuid.uuid4().hex[
                    :12
                ]
            ),
            title=title.strip(),
            description=(
                description.strip()
                if description
                else ""
            ),
            status=status,
            priority=priority,
            created_at=now,
            updated_at=now,
            deadline=deadline,
            assigned_agent=(
                assigned_agent
            ),
            result=None,
            result_data={},
            error=None,
            parent_task_id=(
                parent_task_id
            ),
            depends_on=(
                dependency_ids
            ),
            metadata=(
                metadata
                or {}
            ),
        )

        self._tasks[
            task.id
        ] = task

        self._save()

        return task

    # ========================================================
    # READ
    # ========================================================

    def get(
        self,
        task_id: str,
    ) -> Optional[Task]:

        return self._tasks.get(
            task_id
        )

    def list(
        self,
        status: Optional[
            str
        ] = None,
    ) -> List[Task]:

        tasks = list(
            self._tasks.values()
        )

        if status is not None:

            tasks = [
                task
                for task
                in tasks
                if (
                    task.status
                    == status
                )
            ]

        return sorted(
            tasks,
            key=lambda task:
            task.created_at,
        )

    def latest(
        self,
    ) -> Optional[Task]:

        tasks = self.list()

        return (
            tasks[-1]
            if tasks
            else None
        )

    def dependents_of(
        self,
        task_id: str,
    ) -> List[Task]:

        return [
            task
            for task
            in self._tasks.values()
            if (
                task_id
                in task.depends_on
            )
        ]

    # ========================================================
    # DEPENDENCIES
    # ========================================================

    def dependencies_satisfied_ids(
        self,
        dependency_ids: List[
            str
        ],
    ) -> bool:

        for dependency_id in (
            dependency_ids
        ):

            dependency = self.get(
                dependency_id
            )

            if dependency is None:
                return False

            if (
                dependency.status
                != TaskStatus
                .COMPLETED
                .value
            ):

                return False

        return True

    def dependencies_satisfied(
        self,
        task_id: str,
    ) -> bool:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        return (
            self
            .dependencies_satisfied_ids(
                task.depends_on
            )
        )

    def dependency_failure(
        self,
        task_id: str,
    ) -> Optional[str]:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        for dependency_id in (
            task.depends_on
        ):

            dependency = self.get(
                dependency_id
            )

            if dependency is None:

                return (
                    "Dépendance introuvable : "
                    f"{dependency_id}"
                )

            if (
                dependency.status
                == TaskStatus
                .FAILED
                .value
            ):

                return (
                    f"La dépendance "
                    f"{dependency.id} "
                    f"a échoué : "
                    f"{dependency.error or 'erreur inconnue'}"
                )

            if (
                dependency.status
                == TaskStatus
                .CANCELLED
                .value
            ):

                return (
                    f"La dépendance "
                    f"{dependency.id} "
                    "a été annulée."
                )

        return None

    def build_dependency_context(
        self,
        task_id: str,
    ) -> List[
        Dict[str, Any]
    ]:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        context: List[
            Dict[str, Any]
        ] = []

        for dependency_id in (
            task.depends_on
        ):

            dependency = self.get(
                dependency_id
            )

            if dependency is None:
                continue

            context.append(
                {
                    "task_id": (
                        dependency.id
                    ),
                    "title": (
                        dependency.title
                    ),
                    "worker": (
                        dependency
                        .assigned_agent
                    ),
                    "status": (
                        dependency.status
                    ),
                    "result": (
                        dependency.result
                    ),
                    "result_data": (
                        dependency
                        .result_data
                    ),
                }
            )

        return context

    def mark_waiting_dependency(
        self,
        task_id: str,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        task.status = (
            TaskStatus
            .WAITING_DEPENDENCY
            .value
        )

        self._touch(
            task
        )

        self._save()

        return task

    def mark_pending(
        self,
        task_id: str,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        task.status = (
            TaskStatus.PENDING.value
        )

        self._touch(
            task
        )

        self._save()

        return task

    # ========================================================
    # UPDATE
    # ========================================================

    def update(
        self,
        task_id: str,
        **changes: Any,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        allowed_fields = {
            "title",
            "description",
            "status",
            "priority",
            "deadline",
            "assigned_agent",
            "result",
            "result_data",
            "error",
            "parent_task_id",
            "depends_on",
            "metadata",
        }

        for (
            key,
            value,
        ) in changes.items():

            if (
                key
                not in allowed_fields
            ):

                raise ValueError(
                    "Champ de tâche "
                    f"inconnu : {key}"
                )

            if (
                key == "priority"
                and value
                not in self.PRIORITIES
            ):

                raise ValueError(
                    "Priorité invalide : "
                    f"{value}"
                )

            setattr(
                task,
                key,
                value,
            )

        self._touch(
            task
        )

        self._save()

        return task

    # ========================================================
    # STATUS
    # ========================================================

    def start(
        self,
        task_id: str,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        if (
            task.status
            not in {
                TaskStatus
                .PENDING
                .value,
                TaskStatus
                .WAITING_DEPENDENCY
                .value,
            }
        ):

            raise ValueError(
                "Seules les tâches pending "
                "ou waiting_dependency "
                "peuvent démarrer."
            )

        failure = (
            self.dependency_failure(
                task_id
            )
        )

        if failure:

            raise ValueError(
                failure
            )

        if not (
            self.dependencies_satisfied(
                task_id
            )
        ):

            raise ValueError(
                "Les dépendances ne sont "
                "pas encore terminées."
            )

        task.status = (
            TaskStatus.RUNNING.value
        )

        task.error = None

        self._touch(
            task
        )

        self._save()

        return task

    def wait_for_approval(
        self,
        task_id: str,
        reason: Optional[
            str
        ] = None,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        task.status = (
            TaskStatus
            .WAITING_APPROVAL
            .value
        )

        if reason:

            task.metadata[
                "approval_reason"
            ] = reason

        self._touch(
            task
        )

        self._save()

        return task

    def block(
        self,
        task_id: str,
        reason: Optional[
            str
        ] = None,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        task.status = (
            TaskStatus.BLOCKED.value
        )

        if reason:
            task.error = reason

        self._touch(
            task
        )

        self._save()

        return task

    def complete(
        self,
        task_id: str,
        result: Optional[
            str
        ] = None,
        data: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        task.status = (
            TaskStatus
            .COMPLETED
            .value
        )

        task.result = result

        task.result_data = (
            data
            or {}
        )

        task.error = None

        self._touch(
            task
        )

        self._save()

        return task

    def fail(
        self,
        task_id: str,
        error: Optional[
            str
        ] = None,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        task.status = (
            TaskStatus.FAILED.value
        )

        task.error = error

        self._touch(
            task
        )

        self._save()

        return task

    def cancel(
        self,
        task_id: str,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        task.status = (
            TaskStatus
            .CANCELLED
            .value
        )

        self._touch(
            task
        )

        self._save()

        return task

    def set_result(
        self,
        task_id: str,
        result: Optional[
            str
        ],
        data: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Task:

        task = (
            self._get_task_or_raise(
                task_id
            )
        )

        task.result = result

        if data is not None:

            task.result_data = (
                data
            )

        self._touch(
            task
        )

        self._save()

        return task

    def delete(
        self,
        task_id: str,
    ) -> bool:

        if (
            task_id
            not in self._tasks
        ):

            return False

        del self._tasks[
            task_id
        ]

        self._save()

        return True