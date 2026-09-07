"""
Point d'entrée Agent-OS V2.3.6.

Commandes :
- status
- tasks
- missions
- approvals
- oui
- non
- quit
"""

from v2.manager.manager import (
    Manager,
)

from v2.approvals.approval_manager import (
    ApprovalManager,
)

from v2.tools.project_files import (
    ProjectFilesTool,
)

from v2.tools.python_runner import (
    PythonRunner,
)

from v2.workers.llm_worker import (
    LLMWorker,
)

from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class DemoWorker(
    Worker
):

    name = "demo"

    description = (
        "Worker de démonstration "
        "utilisé pour tester "
        "le système."
    )

    def execute(
        self,
        task: dict,
    ) -> WorkerResult:

        import time

        title = task.get(
            "title",
            "Tâche inconnue",
        )

        print(
            "\n[DEMO WORKER] "
            f"Travail commencé : {title}"
        )

        time.sleep(
            2
        )

        print(
            "[DEMO WORKER] "
            f"Travail terminé : {title}"
        )

        return WorkerResult(
            success=True,
            message=(
                "Le worker a terminé : "
                f"{title}"
            ),
            data={
                "worker": self.name,
                "type": "demo",
            },
        )


# ============================================================
# NOTIFICATIONS
# ============================================================


def show_notifications(
    manager: Manager,
) -> None:

    for notification in (
        manager.drain_notifications()
    ):

        print(
            "\n[MANAGER] "
            f"{notification}"
        )


# ============================================================
# APPROVAL REQUEST
# ============================================================


def show_pending_approval(
    approvals: ApprovalManager,
) -> None:

    request = (
        approvals
        .format_latest_request()
    )

    if request:

        print()

        print(
            "[MANAGER] "
            + request
        )

        print()


# ============================================================
# MAIN
# ============================================================


def main() -> None:

    print(
        "=" * 60
    )

    print(
        "AGENT-OS V2.3.6 — MANAGER"
    )

    print(
        "=" * 60
    )

    print()

    manager = (
        Manager()
    )

    # ========================================================
    # SHARED TOOLS
    # ========================================================

    project_tool = (
        ProjectFilesTool(
            permissions=(
                manager.permissions
            )
        )
    )

    python_runner = (
        PythonRunner(
            permissions=(
                manager.permissions
            )
        )
    )

    # ========================================================
    # WORKERS
    # ========================================================

    manager.register_worker(
        DemoWorker()
    )

    manager.register_worker(
        LLMWorker()
    )

    from v2.workers.researcher import (
        ResearcherWorker,
    )

    from v2.workers.developer import (
        DeveloperWorker,
    )

    from v2.workers.tester import (
        TesterWorker,
    )

    manager.register_worker(
        ResearcherWorker(
            permissions=(
                manager.permissions
            )
        )
    )

    manager.register_worker(
        DeveloperWorker(
            permissions=(
                manager.permissions
            ),
            project_tool=(
                project_tool
            ),
        )
    )

    manager.register_worker(
        TesterWorker(
            permissions=(
                manager.permissions
            ),
            project_tool=(
                project_tool
            ),
            python_runner=(
                python_runner
            ),
        )
    )

    # ========================================================
    # APPROVAL MANAGER
    # ========================================================

    approvals = (
        ApprovalManager(
            task_manager=(
                manager.tasks
            ),
            event_bus=(
                manager.event_bus
            ),
            worker_engine=(
                manager.worker_engine
            ),
            project_tool=(
                project_tool
            ),
        )
    )

    # ========================================================
    # START
    # ========================================================

    print(
        "Manager prêt."
    )

    print(
        "Workers disponibles : "
        f"{', '.join(manager.get_worker_names())}"
    )

    print(
        "Commandes : "
        "status | tasks | missions | "
        "approvals | oui | non | quit"
    )

    print()

    last_shown_approval_id = (
        None
    )

    try:

        while True:

            show_notifications(
                manager
            )

            pending_task = (
                approvals.latest_pending()
            )

            if (
                pending_task
                is not None
                and pending_task.id
                != last_shown_approval_id
            ):

                show_pending_approval(
                    approvals
                )

                last_shown_approval_id = (
                    pending_task.id
                )

            try:

                message = input(
                    "TOI > "
                )

            except EOFError:

                break

            command = (
                message
                .strip()
                .lower()
            )

            # =================================================
            # QUIT
            # =================================================

            if (
                command
                == "quit"
            ):

                break

            if not command:

                continue

            # =================================================
            # APPROVE
            # =================================================

            if command in {
                "oui",
                "yes",
                "y",
                "approve",
                "autorise",
                "autoriser",
            }:

                response = (
                    approvals
                    .approve_latest()
                )

                print()

                print(
                    "MANAGER >"
                )

                print(
                    response
                )

                print()

                last_shown_approval_id = (
                    None
                )

                show_notifications(
                    manager
                )

                continue

            # =================================================
            # REJECT
            # =================================================

            if command in {
                "non",
                "no",
                "n",
                "reject",
                "refuse",
                "refuser",
            }:

                response = (
                    approvals
                    .reject_latest()
                )

                print()

                print(
                    "MANAGER >"
                )

                print(
                    response
                )

                print()

                last_shown_approval_id = (
                    None
                )

                show_notifications(
                    manager
                )

                continue

            # =================================================
            # STATUS
            # =================================================

            if (
                command
                == "status"
            ):

                print()

                print(
                    manager.status()
                )

                print()

                continue

            # =================================================
            # TASKS
            # =================================================

            if (
                command
                == "tasks"
            ):

                print()

                print(
                    manager.format_tasks()
                )

                print()

                continue

            # =================================================
            # MISSIONS
            # =================================================

            if (
                command
                == "missions"
            ):

                print()

                print(
                    manager.format_missions()
                )

                print()

                continue

            # =================================================
            # APPROVALS
            # =================================================

            if (
                command
                == "approvals"
            ):

                print()

                print(
                    approvals
                    .format_pending()
                )

                print()

                continue

            # =================================================
            # NORMAL CHAT
            # =================================================

            response = (
                manager.chat(
                    message
                )
            )

            print()

            print(
                "MANAGER >"
            )

            print(
                response
            )

            print()

            show_notifications(
                manager
            )

    except KeyboardInterrupt:

        print(
            "\nArrêt demandé."
        )

    finally:

        print(
            "\nArrêt du Manager..."
        )

        manager.shutdown()

        show_notifications(
            manager
        )

        print(
            "\nSTATUS FINAL :"
        )

        print(
            manager.status()
        )


if __name__ == "__main__":

    main()