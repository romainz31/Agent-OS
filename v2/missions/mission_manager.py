"""
Mission Manager Agent-OS V2.

Une mission représente un objectif global du Manager.

Une mission peut contenir plusieurs tâches exécutées
successivement par différents workers.

Architecture :

Manager
    ↓
MissionManager
    ↓
TaskManager
    ↓
WorkerEngine
    ↓
Worker
    ↓
résultat
    ↓
Manager
    ↓
prochaine tâche
"""

from __future__ import annotations

import json
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from v2.config import DATA_DIR


class MissionStatus:
    """
    États possibles d'une mission.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Mission:
    """
    Représente une mission globale.
    """

    id: str

    title: str

    objective: str

    status: str = MissionStatus.PENDING

    priority: str = "normal"

    created_at: str = ""

    updated_at: str = ""

    deadline: Optional[str] = None

    task_ids: List[str] = field(
        default_factory=list
    )

    current_task_id: Optional[str] = None

    result: Optional[str] = None

    error: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
    ) -> "Mission":

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
            objective=str(
                data.get(
                    "objective",
                    "",
                )
            ),
            status=str(
                data.get(
                    "status",
                    MissionStatus.PENDING,
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
            task_ids=list(
                data.get(
                    "task_ids",
                    [],
                )
            ),
            current_task_id=data.get(
                "current_task_id"
            ),
            result=data.get(
                "result"
            ),
            error=data.get(
                "error"
            ),
            metadata=dict(
                data.get(
                    "metadata",
                    {},
                )
            ),
        )


class MissionManager:
    """
    Gestionnaire persistant des missions.
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
                / "missions"
                / "missions.json"
            )

        self.storage_path = Path(
            storage_path
        )

        self.storage_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._missions: Dict[
            str,
            Mission,
        ] = {}

        self._load()

    # ============================================================
    # STORAGE
    # ============================================================

    def _load(
        self,
    ) -> None:

        if not self.storage_path.exists():

            self._missions = {}

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
                "[MISSION MANAGER] "
                "Impossible de charger missions.json."
            )

            self._missions = {}

            return

        if not isinstance(
            data,
            list,
        ):

            self._missions = {}

            return

        self._missions = {}

        for item in data:

            if not isinstance(
                item,
                dict,
            ):
                continue

            try:

                mission = (
                    Mission.from_dict(
                        item
                    )
                )

                self._missions[
                    mission.id
                ] = mission

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
            mission.to_dict()
            for mission
            in self._missions.values()
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

        return datetime.now(
            timezone.utc
        ).isoformat()

    def _touch(
        self,
        mission: Mission,
    ) -> None:

        mission.updated_at = (
            self._now()
        )

    def _get_or_raise(
        self,
        mission_id: str,
    ) -> Mission:

        mission = self.get(
            mission_id
        )

        if mission is None:

            raise ValueError(
                f"Mission introuvable : "
                f"{mission_id}"
            )

        return mission

    # ============================================================
    # CREATE
    # ============================================================

    def create(
        self,
        title: str,
        objective: str,
        priority: str = "normal",
        deadline: Optional[str] = None,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Mission:

        if not title.strip():

            raise ValueError(
                "Le titre de la mission est obligatoire."
            )

        if not objective.strip():

            raise ValueError(
                "L'objectif de la mission est obligatoire."
            )

        if priority not in self.PRIORITIES:

            raise ValueError(
                f"Priorité invalide : {priority}"
            )

        now = self._now()

        mission = Mission(
            id=(
                "mission_"
                + uuid.uuid4().hex[:12]
            ),
            title=title.strip(),
            objective=objective.strip(),
            status=MissionStatus.PENDING,
            priority=priority,
            created_at=now,
            updated_at=now,
            deadline=deadline,
            task_ids=[],
            current_task_id=None,
            result=None,
            error=None,
            metadata=metadata or {},
        )

        self._missions[
            mission.id
        ] = mission

        self._save()

        return mission

    # ============================================================
    # READ
    # ============================================================

    def get(
        self,
        mission_id: str,
    ) -> Optional[Mission]:

        return self._missions.get(
            mission_id
        )

    def list(
        self,
        status: Optional[str] = None,
    ) -> List[Mission]:

        missions = list(
            self._missions.values()
        )

        if status is not None:

            missions = [
                mission
                for mission in missions
                if mission.status == status
            ]

        return missions

    # ============================================================
    # TASK LINKING
    # ============================================================

    def add_task(
        self,
        mission_id: str,
        task_id: str,
    ) -> Mission:

        mission = self._get_or_raise(
            mission_id
        )

        if task_id not in mission.task_ids:

            mission.task_ids.append(
                task_id
            )

        mission.current_task_id = (
            task_id
        )

        if mission.status == (
            MissionStatus.PENDING
        ):

            mission.status = (
                MissionStatus.RUNNING
            )

        self._touch(
            mission
        )

        self._save()

        return mission

    # ============================================================
    # STATUS
    # ============================================================

    def start(
        self,
        mission_id: str,
    ) -> Mission:

        mission = self._get_or_raise(
            mission_id
        )

        mission.status = (
            MissionStatus.RUNNING
        )

        self._touch(
            mission
        )

        self._save()

        return mission

    def wait_for_approval(
        self,
        mission_id: str,
        reason: Optional[str] = None,
    ) -> Mission:

        mission = self._get_or_raise(
            mission_id
        )

        mission.status = (
            MissionStatus.WAITING_APPROVAL
        )

        if reason:

            mission.metadata[
                "approval_reason"
            ] = reason

        self._touch(
            mission
        )

        self._save()

        return mission

    def block(
        self,
        mission_id: str,
        reason: Optional[str] = None,
    ) -> Mission:

        mission = self._get_or_raise(
            mission_id
        )

        mission.status = (
            MissionStatus.BLOCKED
        )

        if reason:

            mission.error = reason

        self._touch(
            mission
        )

        self._save()

        return mission

    def complete(
        self,
        mission_id: str,
        result: Optional[str] = None,
    ) -> Mission:

        mission = self._get_or_raise(
            mission_id
        )

        mission.status = (
            MissionStatus.COMPLETED
        )

        mission.result = result

        mission.error = None

        mission.current_task_id = None

        self._touch(
            mission
        )

        self._save()

        return mission

    def fail(
        self,
        mission_id: str,
        error: Optional[str] = None,
    ) -> Mission:

        mission = self._get_or_raise(
            mission_id
        )

        mission.status = (
            MissionStatus.FAILED
        )

        mission.error = error

        self._touch(
            mission
        )

        self._save()

        return mission

    def cancel(
        self,
        mission_id: str,
    ) -> Mission:

        mission = self._get_or_raise(
            mission_id
        )

        mission.status = (
            MissionStatus.CANCELLED
        )

        self._touch(
            mission
        )

        self._save()

        return mission

    # ============================================================
    # RESULT
    # ============================================================

    def set_result(
        self,
        mission_id: str,
        result: Optional[str],
    ) -> Mission:

        mission = self._get_or_raise(
            mission_id
        )

        mission.result = result

        self._touch(
            mission
        )

        self._save()

        return mission

    # ============================================================
    # DELETE
    # ============================================================

    def delete(
        self,
        mission_id: str,
    ) -> bool:

        if mission_id not in self._missions:

            return False

        del self._missions[
            mission_id
        ]

        self._save()

        return True