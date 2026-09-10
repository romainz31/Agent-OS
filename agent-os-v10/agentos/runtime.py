from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any

from agentos.manager import Manager
from agentos.mission_control import MissionControl


class AgentOSRuntime:
    VERSION = "3.9"

    def __init__(self) -> None:
        self.started_at = datetime.now(
            timezone.utc
        ).isoformat()

        self.lock = threading.RLock()

        self.manager = Manager()

        self.control = MissionControl(
            missions=self.manager.missions,
            tasks=self.manager.tasks,
            engine=self.manager.engine,
        )

        self.recovery = self._recover_active_work()

    # =========================================================
    # RECOVERY
    # =========================================================

    def _recover_active_work(
        self,
    ) -> dict[str, Any]:
        active_before = (
            self.manager.missions.active(
                self.manager.tasks
            )
        )

        existing_task_ids = []

        for mission in active_before:
            if mission.task_ids:
                existing_task_ids.extend(
                    mission.task_ids
                )

        task_recovery = (
            self.manager.engine.recover(
                existing_task_ids
            )
        )

        planning_recovery = (
            self.manager.orchestrator
            .recover_planning_missions()
        )

        repair_recovery = (
            self.manager.orchestrator
            .repair_loop
            .recover_pending_repairs()
        )

        active_after = (
            self.manager.missions.active(
                self.manager.tasks
            )
        )

        return {
            "task_recovery": task_recovery,
            "planning_recovery": (
                planning_recovery
            ),
            "repair_recovery": (
                repair_recovery
            ),
            "active_missions": [
                mission.human_id
                for mission
                in active_after
            ],
        }

    def recovery_report_lines(
        self,
    ) -> list[str]:
        recovery = (
            self.recovery
            if isinstance(
                self.recovery,
                dict,
            )
            else {}
        )

        task_recovery = (
            recovery.get(
                "task_recovery",
                {},
            )
            or {}
        )

        planning_recovery = (
            recovery.get(
                "planning_recovery",
                {},
            )
            or {}
        )

        repair_recovery = (
            recovery.get(
                "repair_recovery",
                {},
            )
            or {}
        )

        interrupted = (
            task_recovery.get(
                "interrupted",
                [],
            )
            or []
        )

        submitted = (
            task_recovery.get(
                "submitted",
                [],
            )
            or []
        )

        waiting_approval = (
            task_recovery.get(
                "waiting_approval",
                [],
            )
            or []
        )

        paused = (
            task_recovery.get(
                "paused",
                [],
            )
            or []
        )

        resumed_planning = (
            planning_recovery.get(
                "resumed",
                [],
            )
            or []
        )

        duplicates = (
            planning_recovery.get(
                "cancelled_duplicates",
                [],
            )
            or []
        )

        failed_planning = (
            planning_recovery.get(
                "failed",
                [],
            )
            or []
        )

        restored_repairs = (
            repair_recovery.get(
                "restored",
                [],
            )
            or []
        )

        exhausted_repairs = (
            repair_recovery.get(
                "exhausted",
                [],
            )
            or []
        )

        failed_repairs = (
            repair_recovery.get(
                "failed",
                [],
            )
            or []
        )

        active_missions = (
            recovery.get(
                "active_missions",
                [],
            )
            or []
        )

        if not (
            interrupted
            or submitted
            or waiting_approval
            or paused
            or resumed_planning
            or duplicates
            or failed_planning
            or restored_repairs
            or exhausted_repairs
            or failed_repairs
        ):
            return []

        lines = [
            "[REPRISE V3.9]"
        ]

        if active_missions:
            lines.append(
                "Missions actives après reprise : "
                + ", ".join(
                    active_missions
                )
            )

        if interrupted:
            lines.append(
                "Tâches interrompues restaurées : "
                + str(
                    len(interrupted)
                )
            )

        if submitted:
            lines.append(
                "Tâches relancées automatiquement : "
                + str(
                    len(submitted)
                )
            )

        if waiting_approval:
            lines.append(
                "Tâches toujours en attente "
                "d'autorisation : "
                + str(
                    len(
                        waiting_approval
                    )
                )
            )

        if paused:
            lines.append(
                "Tâches conservées en pause : "
                + str(
                    len(paused)
                )
            )

        if resumed_planning:
            lines.append(
                "Missions reprises depuis "
                "la planification : "
                + ", ".join(
                    resumed_planning
                )
            )

        if restored_repairs:
            lines.append(
                "Boucles de correction restaurées : "
                + ", ".join(
                    restored_repairs
                )
            )

        if exhausted_repairs:
            lines.append(
                "Corrections automatiques arrivées "
                "à leur limite : "
                + str(
                    len(
                        exhausted_repairs
                    )
                )
            )

        for item in duplicates:
            lines.append(
                "Mission interrompue annulée "
                "comme doublon : "
                + item["mission"]
                + " -> "
                + item["duplicate_of"]
            )

        for item in failed_planning:
            lines.append(
                "Échec de reprise de planification : "
                + item["mission"]
                + " ("
                + item["error"]
                + ")"
            )

        for item in failed_repairs:
            lines.append(
                "Échec de reprise d'une correction : "
                + item["task"]
                + " ("
                + item["error"]
                + ")"
            )

        return lines

    # =========================================================
    # SERIALIZATION
    # =========================================================

    @staticmethod
    def _task_payload(
        task,
        *,
        detailed: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "id": task.id,
            "title": task.title,
            "description": (
                task.description
            ),
            "worker": task.worker,
            "status": task.status,
            "created_at": (
                task.created_at
            ),
            "updated_at": (
                task.updated_at
            ),
            "result": task.result,
            "error": task.error,
            "depends_on": list(
                task.depends_on
            ),
            "metadata": copy.deepcopy(
                task.metadata
                if isinstance(
                    task.metadata,
                    dict,
                )
                else {}
            ),
        }

        if detailed:
            payload["result_data"] = (
                copy.deepcopy(
                    task.result_data
                    if isinstance(
                        task.result_data,
                        dict,
                    )
                    else {}
                )
            )

        return payload

    def _mission_payload(
        self,
        mission,
        *,
        detailed: bool = True,
    ) -> dict[str, Any]:
        self.manager.missions.refresh(
            mission,
            self.manager.tasks,
        )

        completed, total = (
            self.manager.missions.progress(
                mission,
                self.manager.tasks,
            )
        )

        tasks = []

        for task_id in (
            mission.task_ids
        ):
            task = self.manager.tasks.get(
                task_id
            )

            if task is None:
                continue

            tasks.append(
                self._task_payload(
                    task,
                    detailed=detailed,
                )
            )

        payload = {
            "id": mission.id,
            "human_id": mission.human_id,
            "title": mission.title,
            "description": (
                mission.description
            ),
            "status": mission.status,
            "created_at": (
                mission.created_at
            ),
            "updated_at": (
                mission.updated_at
            ),
            "progress": {
                "completed": completed,
                "total": total,
            },
            "task_ids": list(
                mission.task_ids
            ),
            "tasks": tasks,
            "metadata": copy.deepcopy(
                mission.metadata
                if isinstance(
                    mission.metadata,
                    dict,
                )
                else {}
            ),
        }

        if detailed:
            payload["plan"] = (
                copy.deepcopy(
                    mission.plan
                    if isinstance(
                        mission.plan,
                        list,
                    )
                    else []
                )
            )

        return payload

    # =========================================================
    # STATUS / AGENTS
    # =========================================================

    def status(
        self,
    ) -> dict[str, Any]:
        with self.lock:
            active = (
                self.manager.missions.active(
                    self.manager.tasks
                )
            )

            with self.manager.engine.lock:
                running_ids = list(
                    self.manager.engine.running
                )

            return {
                "version": self.VERSION,
                "started_at": (
                    self.started_at
                ),
                "workers": list(
                    self.manager.engine.workers
                ),
                "running_jobs": len(
                    running_ids
                ),
                "running_task_ids": (
                    running_ids
                ),
                "active_missions": len(
                    active
                ),
                "active_mission_ids": [
                    mission.human_id
                    for mission
                    in active
                ],
                "pending_approvals": len(
                    self.manager.approvals
                    .pending()
                ),
                "total_missions": len(
                    self.manager.missions
                    .missions
                ),
                "total_tasks": len(
                    self.manager.tasks.tasks
                ),
            }

    def agents(
        self,
    ) -> list[dict[str, Any]]:
        with self.lock:
            running_tasks = [
                task
                for task
                in self.manager.tasks.list()
                if task.status == "running"
            ]

            result = []

            for worker_name in (
                self.manager.engine.workers
            ):
                worker_tasks = [
                    task
                    for task
                    in running_tasks
                    if (
                        task.worker
                        == worker_name
                    )
                ]

                result.append(
                    {
                        "name": worker_name,
                        "status": (
                            "busy"
                            if worker_tasks
                            else "available"
                        ),
                        "running_tasks": [
                            task.id
                            for task
                            in worker_tasks
                        ],
                        "missions": list(
                            dict.fromkeys(
                                mission.human_id
                                for task
                                in worker_tasks
                                for mission
                                in [
                                    self.manager.missions.get(
                                        task.metadata.get(
                                            "mission_id",
                                            "",
                                        )
                                    )
                                    if isinstance(
                                        task.metadata,
                                        dict,
                                    )
                                    else None
                                ]
                                if mission is not None
                            )
                        ),
                    }
                )

            return result

    # =========================================================
    # CHAT
    # =========================================================

    def handle_message(
        self,
        message: str,
    ) -> dict[str, Any]:
        value = str(
            message
        ).strip()

        if not value:
            raise ValueError(
                "Le message est vide."
            )

        with self.lock:
            control_response = (
                self.control.handle(
                    value
                )
            )

            if (
                control_response
                is not None
            ):
                response = (
                    control_response
                )

                handled_by = (
                    "mission_control"
                )

            else:
                response = (
                    self.manager.handle(
                        value
                    )
                )

                handled_by = "manager"

            return {
                "response": response,
                "handled_by": handled_by,
                "status": self.status(),
            }

    # =========================================================
    # MISSIONS
    # =========================================================

    def missions(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.lock:
            result = []

            wanted = (
                status.strip().lower()
                if status
                else None
            )

            for mission in (
                self.manager.missions.list()
            ):
                self.manager.missions.refresh(
                    mission,
                    self.manager.tasks,
                )

                if (
                    wanted
                    and mission.status
                    != wanted
                ):
                    continue

                result.append(
                    self._mission_payload(
                        mission,
                        detailed=False,
                    )
                )

            return result

    def mission(
        self,
        reference: str,
    ) -> dict[str, Any]:
        with self.lock:
            mission = (
                self.manager.missions.resolve(
                    reference
                )
            )

            if mission is None:
                raise KeyError(
                    f"Mission {reference} introuvable."
                )

            return self._mission_payload(
                mission,
                detailed=True,
            )

    def control_mission(
        self,
        reference: str,
        action: str,
    ) -> dict[str, Any]:
        with self.lock:
            mission = (
                self.manager.missions.resolve(
                    reference
                )
            )

            if mission is None:
                raise KeyError(
                    f"Mission {reference} introuvable."
                )

            actions = {
                "pause": self.control.pause,
                "resume": self.control.resume,
                "cancel": self.control.cancel,
                "retry": self.control.retry,
            }

            handler = actions.get(
                action
            )

            if handler is None:
                raise ValueError(
                    "Action de mission inconnue."
                )

            message = handler(
                mission
            )

            return {
                "message": message,
                "mission": (
                    self._mission_payload(
                        mission,
                        detailed=True,
                    )
                ),
            }

    # =========================================================
    # TASKS
    # =========================================================

    def tasks(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.lock:
            wanted = (
                status.strip().lower()
                if status
                else None
            )

            result = []

            for task in (
                self.manager.tasks.list()
            ):
                if (
                    wanted
                    and task.status
                    != wanted
                ):
                    continue

                result.append(
                    self._task_payload(
                        task,
                        detailed=True,
                    )
                )

            return result

    # =========================================================
    # APPROVALS
    # =========================================================

    def approvals(
        self,
    ) -> list[dict[str, Any]]:
        with self.lock:
            result = []

            for task in (
                self.manager.approvals.pending()
            ):
                metadata = (
                    task.metadata
                    if isinstance(
                        task.metadata,
                        dict,
                    )
                    else {}
                )

                mission = (
                    self.manager.missions.get(
                        metadata.get(
                            "mission_id",
                            "",
                        )
                    )
                )

                data = (
                    task.result_data
                    if isinstance(
                        task.result_data,
                        dict,
                    )
                    else {}
                )

                result.append(
                    {
                        "task_id": task.id,
                        "mission_id": (
                            mission.human_id
                            if mission
                            else None
                        ),
                        "title": task.title,
                        "files": list(
                            data.get(
                                "approval_required_files",
                                [],
                            )
                            or []
                        ),
                        "created_at": (
                            task.created_at
                        ),
                        "updated_at": (
                            task.updated_at
                        ),
                    }
                )

            return result

    def approve_mission(
        self,
        reference: str,
    ) -> dict[str, Any]:
        return self._approval_action(
            reference=reference,
            approve=True,
        )

    def reject_mission(
        self,
        reference: str,
    ) -> dict[str, Any]:
        return self._approval_action(
            reference=reference,
            approve=False,
        )

    def _approval_action(
        self,
        *,
        reference: str,
        approve: bool,
    ) -> dict[str, Any]:
        with self.lock:
            mission = (
                self.manager.missions.resolve(
                    reference
                )
            )

            if mission is None:
                raise KeyError(
                    f"Mission {reference} introuvable."
                )

            pending = (
                self.manager.approvals
                .pending_for_mission(
                    mission.id
                )
            )

            if not pending:
                raise ValueError(
                    f"{mission.human_id} "
                    "n'attend aucune autorisation."
                )

            task = pending[0]

            if approve:
                message = (
                    self.manager.approvals
                    .approve_task(
                        task.id
                    )
                )
            else:
                message = (
                    self.manager.approvals
                    .reject_task(
                        task.id
                    )
                )

            self.manager._refresh_mission(
                mission
            )

            return {
                "message": message,
                "mission": (
                    self._mission_payload(
                        mission,
                        detailed=True,
                    )
                ),
            }

    # =========================================================
    # MEMORY / NOTIFICATIONS
    # =========================================================

    def memory(
        self,
    ) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(
                self.manager.memory.data
            )

    def notifications(
        self,
    ) -> list[str]:
        return (
            self.manager
            .drain_notifications()
        )

    # =========================================================
    # SHUTDOWN
    # =========================================================

    def shutdown(
        self,
    ) -> None:
        self.manager.shutdown()