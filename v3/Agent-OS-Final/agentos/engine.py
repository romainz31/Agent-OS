from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from agentos.config import MAX_WORKERS
from agentos.tasks import TaskStatus


class WorkerEngine:
    TERMINAL_STATUSES = {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.WAITING_APPROVAL.value,
        TaskStatus.PAUSED.value,
    }

    def __init__(
        self,
        tasks,
        notifier,
    ) -> None:
        self.tasks = tasks
        self.notifier = notifier

        self.pool = ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        )

        self.workers = {}
        self.running: dict[
            str,
            Future,
        ] = {}

        self.lock = threading.RLock()

        self.repair_handler: (
            Callable[[str], dict[str, Any]]
            | None
        ) = None

    def register(
        self,
        worker,
    ) -> None:
        self.workers[
            worker.name
        ] = worker

    def set_repair_handler(
        self,
        handler: Callable[
            [str],
            dict[str, Any],
        ]
        | None,
    ) -> None:
        self.repair_handler = handler

    def is_running(
        self,
        task_id: str,
    ) -> bool:
        with self.lock:
            return (
                task_id
                in self.running
            )

    @staticmethod
    def _is_non_validated_test(
        task,
        result,
    ) -> bool:
        if task.worker != "tester":
            return False

        metadata = (
            task.metadata
            if isinstance(
                task.metadata,
                dict,
            )
            else {}
        )

        if not metadata.get(
            "auto_repair_enabled",
            False,
        ):
            return False

        data = (
            result.data
            if isinstance(
                result.data,
                dict,
            )
            else {}
        )

        return (
            str(
                data.get(
                    "verdict",
                    "",
                )
            ).upper()
            == "NON_VALIDÉ"
        )

    def submit(
        self,
        task_id: str,
    ) -> bool:
        task = self.tasks.get(
            task_id
        )

        if task is None:
            return False

        with self.lock:
            if task_id in self.running:
                return False

        if (
            task.status
            in self.TERMINAL_STATUSES
        ):
            return False

        failure = (
            self.tasks
            .dependency_failure(
                task
            )
        )

        if failure:
            self.tasks.update(
                task.id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=failure,
            )

            self.notifier(
                f"✗ {task.id} : "
                f"{failure}"
            )

            self.resume_dependents(
                task.id
            )

            return False

        if (
            task.depends_on
            and not (
                self.tasks
                .dependencies_satisfied_ids(
                    task.depends_on
                )
            )
        ):
            if (
                task.status
                != TaskStatus
                .WAITING_DEPENDENCY
                .value
            ):
                self.tasks.update(
                    task.id,
                    status=(
                        TaskStatus
                        .WAITING_DEPENDENCY
                        .value
                    ),
                )

            return False

        worker = self.workers.get(
            task.worker
        )

        if worker is None:
            error = (
                "Worker inconnu : "
                f"{task.worker}"
            )

            self.tasks.update(
                task.id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=error,
            )

            self.notifier(
                f"✗ {task.id} : "
                f"{error}"
            )

            self.resume_dependents(
                task.id
            )

            return False

        self.tasks.update(
            task.id,
            status=(
                TaskStatus
                .RUNNING
                .value
            ),
            error=None,
        )

        payload = task.to_dict()

        payload[
            "dependency_context"
        ] = (
            self.tasks
            .dependency_context(
                task
            )
        )

        try:
            future = self.pool.submit(
                worker.execute,
                payload,
            )

        except Exception as exc:
            error = str(exc)

            self.tasks.update(
                task.id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=error,
            )

            self.notifier(
                f"✗ {task.id} : "
                f"{error}"
            )

            self.resume_dependents(
                task.id
            )

            return False

        with self.lock:
            self.running[
                task.id
            ] = future

        future.add_done_callback(
            lambda finished_future: (
                self._finished(
                    task.id,
                    finished_future,
                )
            )
        )

        return True

    def _handle_non_validated_test(
        self,
        task_id: str,
        result,
    ) -> None:
        data = dict(
            result.data
            if isinstance(
                result.data,
                dict,
            )
            else {}
        )

        self.tasks.update(
            task_id,
            status=(
                TaskStatus
                .COMPLETED
                .value
            ),
            result=result.message,
            result_data=data,
            error=None,
        )

        if self.repair_handler is None:
            self.tasks.update(
                task_id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=(
                    "Test non validé et aucun "
                    "gestionnaire de correction "
                    "n'est disponible."
                ),
            )

            self.notifier(
                f"✗ {task_id} : "
                "test non validé"
            )

            self.resume_dependents(
                task_id
            )
            return

        try:
            outcome = (
                self.repair_handler(
                    task_id
                )
                or {}
            )

        except Exception as exc:
            outcome = {
                "scheduled": False,
                "reason": str(exc),
            }

        if outcome.get(
            "scheduled"
        ):
            attempt = outcome.get(
                "attempt",
                "?",
            )

            maximum = outcome.get(
                "maximum",
                "?",
            )

            current = self.tasks.get(
                task_id
            )

            current_data = dict(
                current.result_data
                if (
                    current is not None
                    and isinstance(
                        current.result_data,
                        dict,
                    )
                )
                else data
            )

            current_data[
                "auto_repair_scheduled"
            ] = True

            current_data[
                "auto_repair_attempt"
            ] = attempt

            current_data[
                "auto_repair_maximum"
            ] = maximum

            self.tasks.update(
                task_id,
                result=(
                    str(
                        result.message
                        or ""
                    ).rstrip()
                    + "\n\n"
                    + (
                        "Correction automatique "
                        f"{attempt}/{maximum} lancée."
                    )
                ).strip(),
                result_data=current_data,
                error=None,
            )

            self.notifier(
                f"✗ {task_id} : "
                "vérification non validée, "
                "correction automatique lancée"
            )

            return

        reason = str(
            outcome.get(
                "reason",
                "Test non validé.",
            )
        )

        current = self.tasks.get(
            task_id
        )

        current_data = dict(
            current.result_data
            if (
                current is not None
                and isinstance(
                    current.result_data,
                    dict,
                )
            )
            else data
        )

        if outcome.get(
            "exhausted"
        ):
            current_data[
                "auto_repair_exhausted"
            ] = True

        self.tasks.update(
            task_id,
            status=(
                TaskStatus
                .FAILED
                .value
            ),
            result=result.message,
            result_data=current_data,
            error=reason,
        )

        self.notifier(
            f"✗ {task_id} : "
            f"{reason}"
        )

        self.resume_dependents(
            task_id
        )

    def _finished(
        self,
        task_id: str,
        future: Future,
    ) -> None:
        with self.lock:
            self.running.pop(
                task_id,
                None,
            )

        current = self.tasks.get(
            task_id
        )

        if current is None:
            return

        if (
            current.status
            == TaskStatus.CANCELLED.value
        ):
            return

        try:
            result = future.result()

        except Exception as exc:
            current = self.tasks.get(
                task_id
            )

            if (
                current is not None
                and current.status
                == TaskStatus.CANCELLED.value
            ):
                return

            error = str(exc)

            self.tasks.update(
                task_id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=error,
            )

            self.notifier(
                f"✗ {task_id} : "
                f"{error}"
            )

            self.resume_dependents(
                task_id
            )

            return

        current = self.tasks.get(
            task_id
        )

        if (
            current is None
            or current.status
            == TaskStatus.CANCELLED.value
        ):
            return

        if not result.success:
            error = (
                result.error
                or result.message
            )

            self.tasks.update(
                task_id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                result=result.message,
                result_data=result.data,
                error=error,
            )

            self.notifier(
                f"✗ {task_id} : "
                f"{error}"
            )

            self.resume_dependents(
                task_id
            )

            return

        if self._is_non_validated_test(
            current,
            result,
        ):
            self._handle_non_validated_test(
                task_id,
                result,
            )
            return

        approval = (
            result.data.get(
                "approval_required_files",
                [],
            )
            or []
        )

        if approval:
            self.tasks.update(
                task_id,
                status=(
                    TaskStatus
                    .WAITING_APPROVAL
                    .value
                ),
                result=result.message,
                result_data=result.data,
                error=None,
            )

            self.notifier(
                f"⚠ {task_id} "
                "attend ton approbation : "
                + ", ".join(
                    approval
                )
            )

            return

        self.tasks.update(
            task_id,
            status=(
                TaskStatus
                .COMPLETED
                .value
            ),
            result=result.message,
            result_data=result.data,
            error=None,
        )

        completed_task = (
            self.tasks.get(
                task_id
            )
        )

        worker_name = (
            completed_task.worker
            if completed_task
            else "worker"
        )

        self.notifier(
            f"✓ {task_id} "
            "terminée par "
            f"{worker_name}"
        )

        self.resume_dependents(
            task_id
        )

    def resume_dependents(
        self,
        task_id: str,
    ) -> None:
        for task in (
            self.tasks
            .dependents_of(
                task_id
            )
        ):
            if (
                task.status
                in {
                    TaskStatus.PENDING.value,
                    TaskStatus
                    .WAITING_DEPENDENCY
                    .value,
                }
            ):
                self.submit(
                    task.id
                )

    def cancel(
        self,
        task_id: str,
    ) -> bool:
        with self.lock:
            future = self.running.get(
                task_id
            )

        if future is None:
            return False

        future.cancel()

        return True

    def recover(
        self,
        task_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if task_ids is None:
            selected = [
                task.id
                for task
                in self.tasks.list()
                if (
                    isinstance(
                        task.metadata,
                        dict,
                    )
                    and task.metadata.get(
                        "mission_id"
                    )
                )
            ]

        else:
            selected = list(
                dict.fromkeys(
                    task_ids
                )
            )

        interrupted = (
            self.tasks
            .recover_interrupted(
                selected
            )
        )

        selected_set = set(
            selected
        )

        candidates = [
            task
            for task
            in reversed(
                self.tasks.list()
            )
            if (
                task.id in selected_set
                and task.status
                in {
                    TaskStatus.PENDING.value,
                    TaskStatus
                    .WAITING_DEPENDENCY
                    .value,
                }
            )
        ]

        submitted = []

        for task in candidates:
            if self.submit(
                task.id
            ):
                submitted.append(
                    task.id
                )

        waiting_approval = [
            task.id
            for task
            in self.tasks.list()
            if (
                task.id in selected_set
                and task.status
                == TaskStatus
                .WAITING_APPROVAL
                .value
            )
        ]

        paused = [
            task.id
            for task
            in self.tasks.list()
            if (
                task.id in selected_set
                and task.status
                == TaskStatus.PAUSED.value
            )
        ]

        return {
            "interrupted": interrupted,
            "submitted": submitted,
            "waiting_approval": (
                waiting_approval
            ),
            "paused": paused,
        }

    def shutdown(self) -> None:
        self.pool.shutdown(
            wait=True,
            cancel_futures=False,
        )