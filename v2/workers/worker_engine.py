"""
Worker Engine Agent-OS V2.2.

Responsabilités :
- exécuter les workers en parallèle ;
- attendre les dépendances ;
- transmettre les résultats précédents ;
- réveiller automatiquement les tâches dépendantes.
"""

from __future__ import annotations

from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
)

from v2.events.event_bus import (
    EventBus,
)

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

        self.task_manager = (
            task_manager
        )

        self.event_bus = (
            event_bus
        )

        self.executor = (
            ThreadPoolExecutor(
                max_workers=(
                    max_workers
                ),
                thread_name_prefix=(
                    "agent-worker"
                ),
            )
        )

        self.workers: dict[
            str,
            Worker,
        ] = {}

        self.running: dict[
            str,
            Future,
        ] = {}

    # ========================================================
    # WORKERS
    # ========================================================

    def register(
        self,
        worker: Worker,
    ) -> None:

        self.workers[
            worker.name
        ] = worker

    def get_worker(
        self,
        name: str,
    ) -> Worker | None:

        return self.workers.get(
            name
        )

    # ========================================================
    # SUBMIT
    # ========================================================

    def submit(
        self,
        task_id: str,
    ) -> bool:

        task = (
            self.task_manager.get(
                task_id
            )
        )

        if task is None:
            return False

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

            return False

        if not task.assigned_agent:

            self.task_manager.fail(
                task_id,
                (
                    "Aucun worker assigné "
                    "à cette tâche."
                ),
            )

            return False

        worker = self.get_worker(
            task.assigned_agent
        )

        if worker is None:

            self.task_manager.fail(
                task_id,
                (
                    "Worker inconnu : "
                    f"{task.assigned_agent}"
                ),
            )

            return False

        dependency_failure = (
            self.task_manager
            .dependency_failure(
                task_id
            )
        )

        if dependency_failure:

            self.task_manager.fail(
                task_id,
                dependency_failure,
            )

            self.event_bus.publish(
                "task.failed",
                {
                    "task_id": (
                        task_id
                    ),
                    "error": (
                        dependency_failure
                    ),
                },
            )

            return False

        if not (
            self.task_manager
            .dependencies_satisfied(
                task_id
            )
        ):

            self.task_manager.mark_waiting_dependency(
                task_id
            )

            self.event_bus.publish(
                "task.waiting_dependency",
                {
                    "task_id": (
                        task_id
                    ),
                    "depends_on": list(
                        task.depends_on
                    ),
                },
            )

            return True

        if (
            task.status
            == TaskStatus
            .WAITING_DEPENDENCY
            .value
        ):

            self.task_manager.mark_pending(
                task_id
            )

        self.task_manager.start(
            task_id
        )

        self.event_bus.publish(
            "task.started",
            {
                "task_id": (
                    task_id
                ),
                "worker": (
                    worker.name
                ),
            },
        )

        future = (
            self.executor.submit(
                self._execute,
                task_id,
                worker,
            )
        )

        self.running[
            task_id
        ] = future

        future.add_done_callback(
            lambda completed_future:
            self._finished(
                task_id,
                completed_future,
            )
        )

        return True

    # ========================================================
    # EXECUTION
    # ========================================================

    def _execute(
        self,
        task_id: str,
        worker: Worker,
    ) -> WorkerResult:

        task = (
            self.task_manager.get(
                task_id
            )
        )

        if task is None:

            return WorkerResult(
                success=False,
                message=(
                    "Tâche introuvable."
                ),
                error=(
                    "task_not_found"
                ),
            )

        payload = (
            task.to_dict()
        )

        dependency_context = (
            self.task_manager
            .build_dependency_context(
                task_id
            )
        )

        payload[
            "dependency_context"
        ] = dependency_context

        metadata = dict(
            payload.get(
                "metadata",
                {},
            )
            or {}
        )

        metadata[
            "dependency_context"
        ] = dependency_context

        payload[
            "metadata"
        ] = metadata

        try:

            result = worker.execute(
                payload
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
                    error=(
                        "invalid_worker_result"
                    ),
                )

            return result

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Le worker a rencontré "
                    "une erreur."
                ),
                error=str(
                    exc
                ),
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

            result = (
                future.result()
            )

        except Exception as exc:

            self.task_manager.fail(
                task_id,
                str(exc),
            )

            self.event_bus.publish(
                "task.failed",
                {
                    "task_id": (
                        task_id
                    ),
                    "error": str(
                        exc
                    ),
                },
            )

            self._resume_dependents(
                task_id
            )

            return

        if result.success:

            self.task_manager.complete(
                task_id,
                result.message,
                result.data,
            )

            self.event_bus.publish(
                "task.completed",
                {
                    "task_id": (
                        task_id
                    ),
                    "message": (
                        result.message
                    ),
                    "data": (
                        result.data
                        or {}
                    ),
                },
            )

        else:

            error = (
                result.error
                or result.message
            )

            self.task_manager.fail(
                task_id,
                error,
            )

            self.event_bus.publish(
                "task.failed",
                {
                    "task_id": (
                        task_id
                    ),
                    "error": (
                        error
                    ),
                },
            )

        self._resume_dependents(
            task_id
        )

    # ========================================================
    # DEPENDENCIES
    # ========================================================

    def _resume_dependents(
        self,
        completed_task_id: str,
    ) -> None:

        for dependent in (
            self.task_manager
            .dependents_of(
                completed_task_id
            )
        ):

            if (
                dependent.status
                not in {
                    TaskStatus
                    .PENDING
                    .value,
                    TaskStatus
                    .WAITING_DEPENDENCY
                    .value,
                }
            ):

                continue

            failure = (
                self.task_manager
                .dependency_failure(
                    dependent.id
                )
            )

            if failure:

                self.task_manager.fail(
                    dependent.id,
                    failure,
                )

                self.event_bus.publish(
                    "task.failed",
                    {
                        "task_id": (
                            dependent.id
                        ),
                        "error": (
                            failure
                        ),
                    },
                )

                continue

            if (
                self.task_manager
                .dependencies_satisfied(
                    dependent.id
                )
            ):

                self.submit(
                    dependent.id
                )

    # ========================================================
    # CONTROL
    # ========================================================

    def is_running(
        self,
        task_id: str,
    ) -> bool:

        return (
            task_id
            in self.running
        )

    def shutdown(
        self,
        wait: bool = True,
    ) -> None:

        self.executor.shutdown(
            wait=wait,
            cancel_futures=False,
        )