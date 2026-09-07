from __future__ import annotations

from agentos.tasks import (
    TaskStatus,
)


class ApprovalManager:

    def __init__(
        self,
        tasks,
        files,
        runner,
        resume,
    ) -> None:

        self.tasks = tasks
        self.files = files
        self.runner = runner
        self.resume = resume

    # =========================================================
    # PENDING
    # =========================================================

    def pending(
        self,
    ):

        return [
            task
            for task
            in self.tasks.list()
            if task.status
            == TaskStatus.WAITING_APPROVAL.value
        ]

    def pending_for_mission(
        self,
        mission_id: str,
    ):

        result = []

        for task in (
            self.pending()
        ):

            metadata = (
                task.metadata
                if isinstance(
                    task.metadata,
                    dict,
                )
                else {}
            )

            if (
                metadata.get(
                    "mission_id"
                )
                == mission_id
            ):

                result.append(
                    task
                )

        return result

    # =========================================================
    # FORMAT
    # =========================================================

    def format(
        self,
    ) -> str:

        pending = (
            self.pending()
        )

        if not pending:

            return (
                "Aucune approbation "
                "en attente."
            )

        lines = []

        for task in pending:

            files = (
                task.result_data.get(
                    "approval_required_files",
                    [],
                )
                if isinstance(
                    task.result_data,
                    dict,
                )
                else []
            )

            mission_id = (
                task.metadata.get(
                    "mission_id",
                    "?",
                )
                if isinstance(
                    task.metadata,
                    dict,
                )
                else "?"
            )

            lines.append(
                (
                    f"{task.id} | "
                    f"{mission_id} | "
                    f"{task.title} | "
                    + ", ".join(
                        files
                    )
                )
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # APPLY
    # =========================================================

    def approve_task(
        self,
        task_id: str,
    ) -> str:

        task = self.tasks.get(
            task_id
        )

        if (
            task is None
            or task.status
            != TaskStatus.WAITING_APPROVAL.value
        ):

            return (
                "Cette tâche n'attend "
                "pas d'approbation."
            )

        modified = []

        try:

            result_data = (
                task.result_data
                if isinstance(
                    task.result_data,
                    dict,
                )
                else {}
            )

            for plan in (
                result_data.get(
                    "plans",
                    [],
                )
                or []
            ):

                if not plan.get(
                    "approval_required"
                ):

                    continue

                path = plan[
                    "path"
                ]

                content = plan[
                    "content"
                ]

                if path.lower().endswith(
                    ".py"
                ):

                    ok, error = (
                        self.runner
                        .validate_source(
                            content,
                            path,
                        )
                    )

                    if not ok:

                        raise RuntimeError(
                            (
                                "Proposition Python "
                                "invalide : "
                                + error
                            )
                        )

                self.files.apply_approved_write(
                    relative_path=path,
                    content=content,
                    expected_sha256=(
                        plan.get(
                            "original_sha256"
                        )
                    ),
                )

                modified.append(
                    path
                )

        except Exception as exc:

            self.tasks.update(
                task.id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=str(exc),
            )

            self.resume(
                task.id
            )

            return (
                "Approbation non appliquée : "
                f"{exc}"
            )

        data = dict(
            task.result_data
            or {}
        )

        data[
            "approval_required_files"
        ] = []

        data[
            "modified_files"
        ] = modified

        data[
            "approval_status"
        ] = "approved"

        self.tasks.update(
            task.id,
            status=(
                TaskStatus
                .COMPLETED
                .value
            ),
            result=(
                (
                    task.result
                    or ""
                )
                + "\n\n"
                + (
                    "Modification approuvée "
                    "et appliquée."
                )
            ),
            result_data=data,
            error=None,
        )

        self.resume(
            task.id
        )

        return (
            "Modification autorisée.\n"
            + "\n".join(
                f"- {path}"
                for path
                in modified
            )
        )

    # =========================================================
    # REJECT HELPERS
    # =========================================================

    def _cancel_dependents(
        self,
        task_id: str,
    ) -> list[str]:

        cancelled = []

        for dependent in (
            self.tasks.dependents_of(
                task_id
            )
        ):

            if dependent.status not in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:

                self.tasks.update(
                    dependent.id,
                    status=(
                        TaskStatus
                        .CANCELLED
                        .value
                    ),
                    result=(
                        "Étape annulée : la modification "
                        "précédente a été refusée."
                    ),
                    error=(
                        "approval_rejected_dependency"
                    ),
                )

                cancelled.append(
                    dependent.id
                )

            cancelled.extend(
                self._cancel_dependents(
                    dependent.id
                )
            )

        return list(
            dict.fromkeys(
                cancelled
            )
        )

    # =========================================================
    # REJECT
    # =========================================================

    def reject_task(
        self,
        task_id: str,
    ) -> str:

        task = self.tasks.get(
            task_id
        )

        if (
            task is None
            or task.status
            != TaskStatus.WAITING_APPROVAL.value
        ):

            return (
                "Cette tâche n'attend "
                "pas d'approbation."
            )

        data = dict(
            task.result_data
            or {}
        )

        data[
            "approval_status"
        ] = "rejected"

        data[
            "approval_required_files"
        ] = []

        self.tasks.update(
            task.id,
            status=(
                TaskStatus
                .CANCELLED
                .value
            ),
            result=(
                (
                    task.result
                    or ""
                )
                + "\n\n"
                + "Modification refusée."
            ),
            result_data=data,
            error="approval_rejected",
        )

        self._cancel_dependents(
            task.id
        )

        return (
            "Modification refusée. "
            "Aucun fichier n'a été modifié."
        )
