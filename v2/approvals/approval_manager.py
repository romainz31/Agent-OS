"""
Approval Manager Agent-OS V2.3.5.

Responsabilité :
- trouver les tâches en attente d'approbation ;
- présenter les actions proposées ;
- accepter ou refuser une action ;
- exécuter une modification uniquement
  après validation explicite de l'utilisateur.

IMPORTANT :
Le LLM ne peut jamais approuver sa propre action.
"""

from __future__ import annotations

from typing import Any

from v2.events.event_bus import (
    EventBus,
)

from v2.tasks.task_manager import (
    Task,
    TaskManager,
    TaskStatus,
)

from v2.tools.project_files import (
    ProjectFilesTool,
)

from v2.workers.worker_engine import (
    WorkerEngine,
)


class ApprovalManager:

    def __init__(
        self,
        *,
        task_manager: TaskManager,
        event_bus: EventBus,
        worker_engine: WorkerEngine,
        project_tool: ProjectFilesTool,
    ) -> None:

        self.tasks = (
            task_manager
        )

        self.event_bus = (
            event_bus
        )

        self.worker_engine = (
            worker_engine
        )

        self.project_tool = (
            project_tool
        )

    # ========================================================
    # PENDING
    # ========================================================

    def pending(
        self,
    ) -> list[Task]:

        return [
            task
            for task
            in self.tasks.list()
            if (
                task.status
                == TaskStatus
                .WAITING_APPROVAL
                .value
            )
        ]

    def latest_pending(
        self,
    ) -> Task | None:

        tasks = (
            self.pending()
        )

        if not tasks:

            return None

        return tasks[-1]

    def has_pending(
        self,
    ) -> bool:

        return bool(
            self.pending()
        )

    # ========================================================
    # DISPLAY
    # ========================================================

    def format_pending(
        self,
    ) -> str:

        tasks = (
            self.pending()
        )

        if not tasks:

            return (
                "Aucune approbation en attente."
            )

        sections = []

        for task in tasks:

            data = (
                task.result_data
                if isinstance(
                    task.result_data,
                    dict,
                )
                else {}
            )

            files = data.get(
                "approval_required_files",
                [],
            )

            if not isinstance(
                files,
                list,
            ):

                files = []

            lines = [
                (
                    f"{task.id} | "
                    f"{task.assigned_agent or '-'} | "
                    f"{task.title}"
                )
            ]

            if files:

                lines.append(
                    "Fichier(s) :"
                )

                for path in files:

                    lines.append(
                        f"- {path}"
                    )

            sections.append(
                "\n".join(
                    lines
                )
            )

        return "\n\n".join(
            sections
        )

    def format_latest_request(
        self,
    ) -> str | None:

        task = (
            self.latest_pending()
        )

        if task is None:

            return None

        data = (
            task.result_data
            if isinstance(
                task.result_data,
                dict,
            )
            else {}
        )

        files = data.get(
            "approval_required_files",
            [],
        )

        if not isinstance(
            files,
            list,
        ):

            files = []

        if files:

            file_text = (
                "\n".join(
                    f"- {path}"
                    for path
                    in files
                )
            )

        else:

            file_text = (
                "(action non précisée)"
            )

        return (
            "Autorisation requise pour "
            f"{task.id}.\n"
            f"Worker : {task.assigned_agent}\n"
            f"Action : {task.title}\n"
            "Fichier(s) :\n"
            f"{file_text}\n\n"
            "Réponds 'oui' pour autoriser "
            "ou 'non' pour refuser."
        )

    # ========================================================
    # PROPOSED WRITES
    # ========================================================

    @staticmethod
    def _get_proposed_writes(
        task: Task,
    ) -> list[dict[str, str]]:

        data = (
            task.result_data
            if isinstance(
                task.result_data,
                dict,
            )
            else {}
        )

        proposed = data.get(
            "proposed_writes",
            [],
        )

        if not isinstance(
            proposed,
            list,
        ):

            return []

        results = []

        for item in proposed:

            if not isinstance(
                item,
                dict,
            ):

                continue

            path = str(
                item.get(
                    "path",
                    "",
                )
            ).strip()

            content = item.get(
                "content"
            )

            if (
                not path
                or not isinstance(
                    content,
                    str,
                )
            ):

                continue

            results.append(
                {
                    "path": path,
                    "content": content,
                }
            )

        return results

    # ========================================================
    # APPROVE
    # ========================================================

    def approve_latest(
        self,
    ) -> str:

        task = (
            self.latest_pending()
        )

        if task is None:

            return (
                "Il n'y a aucune approbation "
                "en attente."
            )

        return (
            self.approve(
                task.id
            )
        )

    def approve(
        self,
        task_id: str,
    ) -> str:

        task = (
            self.tasks.get(
                task_id
            )
        )

        if task is None:

            return (
                f"Tâche introuvable : "
                f"{task_id}"
            )

        if (
            task.status
            != TaskStatus
            .WAITING_APPROVAL
            .value
        ):

            return (
                f"La tâche {task_id} "
                "n'attend pas d'approbation."
            )

        proposed_writes = (
            self._get_proposed_writes(
                task
            )
        )

        if not proposed_writes:

            self.tasks.fail(
                task.id,
                (
                    "Aucune modification "
                    "préparée à approuver."
                ),
            )

            return (
                "Impossible d'approuver : "
                "aucune modification préparée."
            )

        modified_files = []

        errors = []

        # ====================================================
        # TRUSTED EXECUTION
        # ====================================================

        for write in proposed_writes:

            path = (
                write["path"]
            )

            content = (
                write["content"]
            )

            try:

                result = (
                    self.project_tool
                    .apply_approved_write(
                        relative_path=path,
                        content=content,
                    )
                )

                if result.modified:

                    modified_files.append(
                        result.path
                    )

            except Exception as exc:

                errors.append(
                    {
                        "path": path,
                        "error": str(
                            exc
                        ),
                    }
                )

        # ====================================================
        # FAILURE
        # ====================================================

        if errors:

            error_message = (
                "Erreur pendant l'exécution "
                "de l'approbation :\n"
                + "\n".join(
                    (
                        f"- {item['path']} : "
                        f"{item['error']}"
                    )
                    for item
                    in errors
                )
            )

            self.tasks.fail(
                task.id,
                error_message,
            )

            self.event_bus.publish(
                "task.failed",
                {
                    "task_id": (
                        task.id
                    ),
                    "error": (
                        error_message
                    ),
                },
            )

            self.worker_engine.resume_dependents(
                task.id
            )

            return error_message

        # ====================================================
        # COMPLETE TASK
        # ====================================================

        data = dict(
            task.result_data
            or {}
        )

        data[
            "approval_status"
        ] = "approved"

        data[
            "approval_required_files"
        ] = []

        data[
            "modified_files"
        ] = modified_files

        result_text = (
            task.result
            or ""
        ).strip()

        if result_text:

            result_text += (
                "\n\n"
            )

        result_text += (
            "Approbation utilisateur accordée.\n"
            "Modification exécutée."
        )

        self.tasks.update(
            task.id,
            status=(
                TaskStatus
                .COMPLETED
                .value
            ),
            result=result_text,
            result_data=data,
            error=None,
        )

        self.event_bus.publish(
            "task.completed",
            {
                "task_id": (
                    task.id
                ),
                "message": (
                    result_text
                ),
                "data": data,
            },
        )

        self.worker_engine.resume_dependents(
            task.id
        )

        if modified_files:

            files_text = (
                "\n".join(
                    (
                        f"- {path}"
                    )
                    for path
                    in modified_files
                )
            )

            return (
                "Modification autorisée.\n"
                f"Fichier(s) modifié(s) :\n"
                f"{files_text}\n"
                f"Tâche {task.id} terminée."
            )

        return (
            "Approbation accordée.\n"
            f"Tâche {task.id} terminée."
        )

    # ========================================================
    # REJECT
    # ========================================================

    def reject_latest(
        self,
    ) -> str:

        task = (
            self.latest_pending()
        )

        if task is None:

            return (
                "Il n'y a aucune approbation "
                "en attente."
            )

        return (
            self.reject(
                task.id
            )
        )

    def reject(
        self,
        task_id: str,
    ) -> str:

        task = (
            self.tasks.get(
                task_id
            )
        )

        if task is None:

            return (
                f"Tâche introuvable : "
                f"{task_id}"
            )

        if (
            task.status
            != TaskStatus
            .WAITING_APPROVAL
            .value
        ):

            return (
                f"La tâche {task_id} "
                "n'attend pas d'approbation."
            )

        data = dict(
            task.result_data
            or {}
        )

        data[
            "approval_status"
        ] = "rejected"

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
                + (
                    "\n\nModification refusée "
                    "par l'utilisateur."
                )
            ),
            result_data=data,
            error=(
                "approval_rejected"
            ),
        )

        self.event_bus.publish(
            "task.failed",
            {
                "task_id": (
                    task.id
                ),
                "error": (
                    "Modification refusée "
                    "par l'utilisateur."
                ),
            },
        )

        self.worker_engine.resume_dependents(
            task.id
        )

        return (
            "Modification refusée.\n"
            "Aucun fichier n'a été modifié.\n"
            f"Tâche {task.id} annulée."
        )