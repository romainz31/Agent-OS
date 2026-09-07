from __future__ import annotations

import re
import threading
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

from typing import Any

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
    description: str
    status: str
    created_at: str
    updated_at: str

    human_id: str = ""

    task_ids: list[str] = field(
        default_factory=list
    )

    plan: list[
        dict[str, Any]
    ] = field(
        default_factory=list
    )

    metadata: dict[
        str,
        Any,
    ] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return asdict(
            self
        )


class MissionManager:
    HUMAN_ID_RE = re.compile(
        r"^M-(\d+)$",
        flags=re.IGNORECASE,
    )

    def __init__(
        self,
    ) -> None:
        self.store = JsonStore(
            DATA_DIR / "missions.json",
            [],
        )

        self.lock = (
            threading.RLock()
        )

        self.missions: dict[
            str,
            Mission,
        ] = {}

        self._load()

        self._repair_human_ids()

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _load(
        self,
    ) -> None:
        loaded = (
            self.store.load()
        )

        if not isinstance(
            loaded,
            list,
        ):
            loaded = []

        for item in loaded:
            if not isinstance(
                item,
                dict,
            ):
                continue

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

    # =========================================================
    # HUMAN IDs
    # =========================================================

    def _used_human_numbers(
        self,
    ) -> set[int]:
        numbers = set()

        for mission in (
            self.missions.values()
        ):
            match = (
                self.HUMAN_ID_RE.match(
                    mission.human_id
                    or ""
                )
            )

            if match:
                numbers.add(
                    int(
                        match.group(1)
                    )
                )

        return numbers

    def _next_human_id(
        self,
    ) -> str:
        used = (
            self._used_human_numbers()
        )

        number = 1

        while number in used:
            number += 1

        return (
            f"M-{number:03d}"
        )

    def _repair_human_ids(
        self,
    ) -> None:
        changed = False
        used = set()

        missions = sorted(
            self.missions.values(),
            key=lambda mission: (
                mission.created_at
            ),
        )

        for mission in missions:
            current = (
                mission.human_id
                or ""
            )

            match = (
                self.HUMAN_ID_RE.match(
                    current
                )
            )

            if match:
                number = int(
                    match.group(1)
                )

                if number not in used:
                    used.add(
                        number
                    )

                    continue

            number = 1

            while number in used:
                number += 1

            mission.human_id = (
                f"M-{number:03d}"
            )

            used.add(
                number
            )

            changed = True

        if changed:
            self._save()

    # =========================================================
    # CREATE
    # =========================================================

    def create(
        self,
        *,
        title: str,
        description: str,
        metadata: dict[
            str,
            Any,
        ]
        | None = None,
    ) -> Mission:
        with self.lock:
            now = self._now()

            mission = Mission(
                id=(
                    "mission_"
                    + uuid.uuid4()
                    .hex[:10]
                ),
                human_id=(
                    self._next_human_id()
                ),
                title=title,
                description=description,
                status="planning",
                created_at=now,
                updated_at=now,
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

    def get_by_human_id(
        self,
        human_id: str,
    ) -> Mission | None:
        wanted = (
            human_id
            .strip()
            .upper()
        )

        for mission in (
            self.missions.values()
        ):
            if (
                mission.human_id
                .upper()
                == wanted
            ):
                return mission

        return None

    def resolve(
        self,
        reference: str,
    ) -> Mission | None:
        reference = (
            reference.strip()
        )

        if not reference:
            return None

        direct = (
            self.get(
                reference
            )
        )

        if direct is not None:
            return direct

        return (
            self.get_by_human_id(
                reference
            )
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
        plan: list[
            dict[str, Any]
        ],
        task_ids: list[str],
    ) -> Mission:
        with self.lock:
            mission = (
                self.missions[
                    mission_id
                ]
            )

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
    # MANUAL STATUS
    # =========================================================

    def set_status(
        self,
        mission_id: str,
        status: str,
        *,
        metadata_patch: dict[
            str,
            Any,
        ]
        | None = None,
    ) -> Mission:
        with self.lock:
            mission = (
                self.missions[
                    mission_id
                ]
            )

            mission.status = (
                status
            )

            if metadata_patch:
                metadata = dict(
                    mission.metadata
                    if isinstance(
                        mission.metadata,
                        dict,
                    )
                    else {}
                )

                metadata.update(
                    metadata_patch
                )

                mission.metadata = (
                    metadata
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
        # Une mission planning sans tâche
        # est volontairement laissée planning.
        # La récupération V3.6 est responsable
        # de décider s'il faut la reprendre
        # ou l'annuler comme doublon.
        if not mission.task_ids:
            return mission

        linked = [
            tasks.get(
                task_id
            )
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

        if (
            mission.status
            != status
        ):
            with self.lock:
                mission.status = (
                    status
                )

                mission.updated_at = (
                    self._now()
                )

                self._save()

        return mission

    # =========================================================
    # PROGRESS
    # =========================================================

    def progress(
        self,
        mission: Mission,
        tasks: TaskManager,
    ) -> tuple[
        int,
        int,
    ]:
        completed = 0

        total = len(
            mission.task_ids
        )

        for task_id in (
            mission.task_ids
        ):
            task = tasks.get(
                task_id
            )

            if (
                task is not None
                and task.status
                == TaskStatus.COMPLETED.value
            ):
                completed += 1

        return (
            completed,
            total,
        )

    # =========================================================
    # ACTIVE
    # =========================================================

    def active(
        self,
        tasks: TaskManager,
    ) -> list[Mission]:
        result = []

        for mission in (
            self.list()
        ):
            self.refresh(
                mission,
                tasks,
            )

            if mission.status in {
                "planning",
                "queued",
                "running",
                "waiting_approval",
            }:
                result.append(
                    mission
                )

        return result

    # =========================================================
    # DISPLAY
    # =========================================================

    def format(
        self,
        tasks: TaskManager,
    ) -> str:
        if not self.missions:
            return (
                "Aucune mission."
            )

        sections = []

        for mission in (
            self.list()
        ):
            self.refresh(
                mission,
                tasks,
            )

            completed, total = (
                self.progress(
                    mission,
                    tasks,
                )
            )

            lines = [
                (
                    f"{mission.human_id} | "
                    f"{mission.status} | "
                    f"{completed}/{total} | "
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
                "\n".join(
                    lines
                )
            )

        return "\n\n".join(
            sections
        )