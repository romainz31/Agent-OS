"""
Worker Engine Agent-OS V2.

Exécute les tâches en arrière-plan.

Architecture :

Manager
    ↓
TaskManager
    ↓
WorkerEngine
    ↓
Worker
    ↓
EventBus
    ↓
Manager / notifications / logs
"""

from __future__ import annotations

from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
)
from typing import Any

from v2.events.event_bus import EventBus
from v2.tasks.task_manager import (
    TaskManager,
    TaskStatus,
)
from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class WorkerEngine:

    def __init__(
        self,
        task_manager: TaskManager,
        event_bus: EventBus,
        max_workers: int = 3,
    ):
        self.task_manager = task_manager
        self.event_bus = event_bus

        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="agent-worker",
        )

        self.workers: dict[
            str,
            Worker
        ] = {}

        self.running: dict[
            str,
            Future
        ] = {}

    # ========================================================
    # WORKERS
    # ========================================================

    def register(
        self,
        worker: Worker,
    ) -> None:
        """
        Enregistre un worker.
        """

        self.workers[worker.name] = worker

    def get_worker(
        self,
        name: str,
    ) -> Worker | None:

        return self.workers.get(name)

    # ========================================================
    # EXÉCUTION
    # ========================================================

    def submit(
        self,
        task_id: str,
    ) -> bool:
        """
        Envoie une tâche dans le pool d'exécution.
        """

        task = self.task_manager.get(
            task_id
        )

        if task is None:
            return False

        if task.status not in {
            TaskStatus.PENDING,
        }:
            return False

        if not task.assigned_agent:
            self.task_manager.fail(
                task_id,
                "Aucun worker assigné à cette tâche.",
            )

            return False

        worker = self.get_worker(
            task.assigned_agent
        )

        if worker is None:
            self.task_manager.fail(
                task_id,
                (
                    f"Worker inconnu : "
                    f"{task.assigned_agent}"
                ),
            )

            return False

        self.task_manager.start(
            task_id
        )

        self.event_bus.publish(
            "task.started",
            {
                "task_id": task_id,
                "worker": worker.name,
            },
        )

        future = self.executor.submit(
            self._execute,
            task_id,
            worker,
        )

        self.running[task_id] = future

        future.add_done_callback(
            lambda completed_future:
            self._finished(
                task_id,
                completed_future,
            )
        )

        return True

    def _execute(
        self,
        task_id: str,
        worker: Worker,
    ) -> WorkerResult:

        task = self.task_manager.get(
            task_id
        )

        if task is None:
            return WorkerResult(
                success=False,
                message="Tâche introuvable.",
                error="task_not_found",
            )

        try:

            result = worker.execute(
                task.to_dict()
            )

            if not isinstance(
                result,
                WorkerResult,
            ):
                return WorkerResult(
                    success=False,
                    message=(
                        "Le worker a retourné "
                        "un résultat invalide."
                    ),
                    error="invalid_worker_result",
                )

            return result

        except Exception as exc:

            return WorkerResult(
                success=False,
                message="Le worker a rencontré une erreur.",
                error=str(exc),
            )

    def _finished(
        self,
        task_id: str,
        future: Future,
    ) -> None:

        self.running.pop(
            task_id,
            None,
        )

        try:

            result = future.result()

        except Exception as exc:

            self.task_manager.fail(
                task_id,
                str(exc),
            )

            self.event_bus.publish(
                "task.failed",
                {
                    "task_id": task_id,
                    "error": str(exc),
                },
            )

            return

        if result.success:

            self.task_manager.complete(
                task_id,
                result.message,
            )

            self.event_bus.publish(
                "task.completed",
                {
                    "task_id": task_id,
                    "message": result.message,
                    "data": result.data,
                },
            )

        else:

            self.task_manager.fail(
                task_id,
                result.error
                or result.message,
            )

            self.event_bus.publish(
                "task.failed",
                {
                    "task_id": task_id,
                    "error": (
                        result.error
                        or result.message
                    ),
                },
            )

    # ========================================================
    # CONTRÔLE
    # ========================================================

    def is_running(
        self,
        task_id: str,
    ) -> bool:

        return task_id in self.running

    def shutdown(
        self,
        wait: bool = True,
    ) -> None:

        self.executor.shutdown(
            wait=wait,
            cancel_futures=False,
        )