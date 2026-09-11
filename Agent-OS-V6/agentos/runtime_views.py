from __future__ import annotations

import copy
from typing import Any


class RuntimeViewService:
    """Construit les payloads exposés par l'API/Web/Telegram.

    Le runtime garde ses méthodes publiques historiques, mais délègue ici tout
    ce qui concerne sérialisation, statut et vue des agents.
    """

    def __init__(self, manager) -> None:
        self.manager = manager

    @staticmethod
    def task_payload(
        task,
        *,
        detailed: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "worker": task.worker,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "result": task.result,
            "error": task.error,
            "depends_on": list(task.depends_on),
            "metadata": copy.deepcopy(
                task.metadata
                if isinstance(task.metadata, dict)
                else {}
            ),
        }

        if detailed:
            payload["result_data"] = copy.deepcopy(
                task.result_data
                if isinstance(task.result_data, dict)
                else {}
            )

        return payload

    def mission_payload(
        self,
        mission,
        *,
        detailed: bool = True,
    ) -> dict[str, Any]:
        self.manager.missions.refresh(
            mission,
            self.manager.tasks,
        )

        completed, total = self.manager.missions.progress(
            mission,
            self.manager.tasks,
        )

        tasks = []
        for task_id in mission.task_ids:
            task = self.manager.tasks.get(task_id)
            if task is None:
                continue
            tasks.append(
                self.task_payload(
                    task,
                    detailed=detailed,
                )
            )

        payload = {
            "id": mission.id,
            "human_id": mission.human_id,
            "title": mission.title,
            "description": mission.description,
            "status": mission.status,
            "created_at": mission.created_at,
            "updated_at": mission.updated_at,
            "progress": {
                "completed": completed,
                "total": total,
            },
            "task_ids": list(mission.task_ids),
            "tasks": tasks,
            "metadata": copy.deepcopy(
                mission.metadata
                if isinstance(mission.metadata, dict)
                else {}
            ),
        }

        if detailed:
            payload["plan"] = copy.deepcopy(
                mission.plan
                if isinstance(mission.plan, list)
                else []
            )

        return payload

    def status(
        self,
        *,
        version: str,
        started_at: str,
    ) -> dict[str, Any]:
        active = self.manager.missions.active(
            self.manager.tasks
        )

        with self.manager.engine.lock:
            running_ids = list(
                self.manager.engine.running
            )

        return {
            "version": version,
            "started_at": started_at,
            "workers": list(
                self.manager.engine.workers
            ),
            "running_jobs": len(running_ids),
            "running_task_ids": running_ids,
            "active_missions": len(active),
            "active_mission_ids": [
                mission.human_id
                for mission in active
            ],
            "pending_approvals": len(
                self.manager.approvals.pending()
            ),
            "total_missions": len(
                self.manager.missions.missions
            ),
            "total_tasks": len(
                self.manager.tasks.tasks
            ),
        }

    def agents(self) -> list[dict[str, Any]]:
        running_tasks = [
            task
            for task in self.manager.tasks.list()
            if task.status == "running"
        ]

        result = []

        for worker_name in self.manager.engine.workers:
            worker_tasks = [
                task
                for task in running_tasks
                if task.worker == worker_name
            ]

            missions = []
            for task in worker_tasks:
                metadata = (
                    task.metadata
                    if isinstance(task.metadata, dict)
                    else {}
                )
                mission = self.manager.missions.get(
                    metadata.get("mission_id", "")
                )
                if (
                    mission is not None
                    and mission.human_id not in missions
                ):
                    missions.append(mission.human_id)

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
                        for task in worker_tasks
                    ],
                    "missions": missions,
                }
            )

        return result
