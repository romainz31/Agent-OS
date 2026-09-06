"""
Task Manager Agent-OS V2.

Gestion centralisée et persistante des tâches.

Une tâche possède notamment :
- un identifiant
- un titre
- une description
- un statut
- une priorité
- une échéance
- un worker assigné
- un résultat
- une erreur éventuelle
- des métadonnées
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
    """
    États possibles d'une tâche.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """
    Représentation d'une tâche Agent-OS.
    """

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
    error: Optional[str] = None

    parent_task_id: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit la tâche en dictionnaire.
        """

        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
    ) -> "Task":
        """
        Reconstruit une tâche depuis un dictionnaire.
        """

        return cls(
            id=str(data["id"]),
            title=str(data.get("title", "")),
            description=str(
                data.get("description", "")
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
            deadline=data.get("deadline"),
            assigned_agent=data.get(
                "assigned_agent"
            ),
            result=data.get("result"),
            error=data.get("error"),
            parent_task_id=data.get(
                "parent_task_id"
            ),
            metadata=dict(
                data.get(
                    "metadata",
                    {},
                )
            ),
        )


class TaskManager:
    """
    Gestionnaire persistant des tâches.

    Les tâches sont stockées dans :

        data/v2/tasks/tasks.json
    """

    PRIORITIES = {
        "low",
        "normal",
        "high",
        "critical",
    }

    def __init__(
        self,
        storage_path: Optional[Path] = None,
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

        self._tasks: Dict[str, Task] = {}

        self._load()

    # ============================================================
    # STORAGE
    # ============================================================

    def _load(self) -> None:
        """
        Charge les tâches depuis le disque.
        """

        if not self.storage_path.exists():
            self._tasks = {}
            return

        try:

            with self.storage_path.open(
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

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

        if not isinstance(data, list):
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

                self._tasks[task.id] = task

            except (
                KeyError,
                TypeError,
                ValueError,
            ):

                continue

    def _save(self) -> None:
        """
        Sauvegarde toutes les tâches.

        Écriture atomique via fichier temporaire.
        """

        data = [
            task.to_dict()
            for task in self._tasks.values()
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

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _now() -> str:
        """
        Retourne l'heure UTC actuelle.
        """

        return datetime.now(
            timezone.utc
        ).isoformat()

    def _touch(
        self,
        task: Task,
    ) -> None:
        """
        Met à jour updated_at.
        """

        task.updated_at = self._now()

    def _get_task_or_raise(
        self,
        task_id: str,
    ) -> Task:

        task = self.get(task_id)

        if task is None:
            raise ValueError(
                f"Tâche introuvable : {task_id}"
            )

        return task

    # ============================================================
    # CREATE
    # ============================================================

    def create(
        self,
        title: str,
        description: str,
        priority: str = "normal",
        deadline: Optional[str] = None,
        assigned_agent: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Task:
        """
        Crée une nouvelle tâche.
        """

        if not title or not title.strip():
            raise ValueError(
                "Le titre de la tâche est obligatoire."
            )

        if priority not in self.PRIORITIES:
            raise ValueError(
                f"Priorité invalide : {priority}"
            )

        now = self._now()

        task = Task(
            id=(
                "task_"
                + uuid.uuid4().hex[:12]
            ),
            title=title.strip(),
            description=(
                description.strip()
                if description
                else ""
            ),
            status=TaskStatus.PENDING.value,
            priority=priority,
            created_at=now,
            updated_at=now,
            deadline=deadline,
            assigned_agent=assigned_agent,
            result=None,
            error=None,
            parent_task_id=parent_task_id,
            metadata=metadata or {},
        )

        self._tasks[task.id] = task

        self._save()

        return task

    # ============================================================
    # READ
    # ============================================================

    def get(
        self,
        task_id: str,
    ) -> Optional[Task]:
        """
        Retourne une tâche.
        """

        return self._tasks.get(task_id)

    def list(
        self,
        status: Optional[str] = None,
    ) -> List[Task]:
        """
        Retourne les tâches.

        Si status est fourni, filtre sur ce statut.
        """

        tasks = list(
            self._tasks.values()
        )

        if status is not None:

            tasks = [
                task
                for task in tasks
                if task.status == status
            ]

        return tasks

    # ============================================================
    # UPDATE
    # ============================================================

    def update(
        self,
        task_id: str,
        **changes: Any,
    ) -> Task:
        """
        Modifie les champs d'une tâche.
        """

        task = self._get_task_or_raise(
            task_id
        )

        allowed_fields = {
            "title",
            "description",
            "status",
            "priority",
            "deadline",
            "assigned_agent",
            "result",
            "error",
            "parent_task_id",
            "metadata",
        }

        for key, value in changes.items():

            if key not in allowed_fields:
                raise ValueError(
                    f"Champ de tâche inconnu : {key}"
                )

            if key == "priority":

                if value not in self.PRIORITIES:
                    raise ValueError(
                        f"Priorité invalide : {value}"
                    )

            setattr(
                task,
                key,
                value,
            )

        self._touch(task)
        self._save()

        return task

    # ============================================================
    # STATUS TRANSITIONS
    # ============================================================

    def start(
        self,
        task_id: str,
    ) -> Task:
        """
        Passe une tâche à running.
        """

        task = self._get_task_or_raise(
            task_id
        )

        if task.status != TaskStatus.PENDING.value:
            raise ValueError(
                "Seules les tâches pending "
                "peuvent démarrer."
            )

        task.status = TaskStatus.RUNNING.value
        task.error = None

        self._touch(task)
        self._save()

        return task

    def wait_for_approval(
        self,
        task_id: str,
        reason: Optional[str] = None,
    ) -> Task:
        """
        Place une tâche en attente d'approbation.
        """

        task = self._get_task_or_raise(
            task_id
        )

        task.status = (
            TaskStatus.WAITING_APPROVAL.value
        )

        if reason:
            task.metadata[
                "approval_reason"
            ] = reason

        self._touch(task)
        self._save()

        return task

    def block(
        self,
        task_id: str,
        reason: Optional[str] = None,
    ) -> Task:
        """
        Bloque une tâche.
        """

        task = self._get_task_or_raise(
            task_id
        )

        task.status = (
            TaskStatus.BLOCKED.value
        )

        if reason:
            task.error = reason

        self._touch(task)
        self._save()

        return task

    def complete(
        self,
        task_id: str,
        result: Optional[str] = None,
        data: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Task:
        """
        Termine une tâche avec succès.

        Le message principal est stocké dans result.
        Les données structurées sont stockées dans metadata.
        """

        task = self._get_task_or_raise(
            task_id
        )

        task.status = (
            TaskStatus.COMPLETED.value
        )

        task.result = result
        task.error = None

        if data is not None:
            task.metadata[
                "result_data"
            ] = data

        self._touch(task)
        self._save()

        return task

    def fail(
        self,
        task_id: str,
        error: Optional[str] = None,
    ) -> Task:
        """
        Marque une tâche comme échouée.
        """

        task = self._get_task_or_raise(
            task_id
        )

        task.status = (
            TaskStatus.FAILED.value
        )

        task.error = error

        self._touch(task)
        self._save()

        return task

    def cancel(
        self,
        task_id: str,
    ) -> Task:
        """
        Annule une tâche.
        """

        task = self._get_task_or_raise(
            task_id
        )

        task.status = (
            TaskStatus.CANCELLED.value
        )

        self._touch(task)
        self._save()

        return task

    # ============================================================
    # RESULT
    # ============================================================

    def set_result(
        self,
        task_id: str,
        result: Optional[str],
        data: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Task:
        """
        Enregistre un résultat sans modifier
        automatiquement le statut.
        """

        task = self._get_task_or_raise(
            task_id
        )

        task.result = result

        if data is not None:
            task.metadata[
                "result_data"
            ] = data

        self._touch(task)
        self._save()

        return task

    # ============================================================
    # DELETE
    # ============================================================

    def delete(
        self,
        task_id: str,
    ) -> bool:
        """
        Supprime une tâche.
        """

        if task_id not in self._tasks:
            return False

        del self._tasks[task_id]

        self._save()

        return True