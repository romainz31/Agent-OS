"""
Point d'entrée Agent-OS V2.3.

Commandes :
- status
- tasks
- missions
- quit
"""

from v2.manager.manager import (
    Manager,
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

    name = (
        "demo"
    )

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

        title = (
            task.get(
                "title",
                "Tâche inconnue",
            )
        )

        print(
            "\n[DEMO WORKER] "
            f"Travail commencé : "
            f"{title}"
        )

        time.sleep(
            2
        )

        print(
            "[DEMO WORKER] "
            f"Travail terminé : "
            f"{title}"
        )

        return WorkerResult(
            success=True,
            message=(
                "Le worker a terminé : "
                f"{title}"
            ),
            data={
                "worker": (
                    self.name
                ),
                "type": (
                    "demo"
                ),
            },
        )


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


def main(
) -> None:

    print(
        "=" * 60
    )

    print(
        "AGENT-OS V2.3 — MANAGER"
    )

    print(
        "=" * 60
    )

    print()

    manager = (
        Manager()
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
        DeveloperWorker()
    )

    manager.register_worker(
        TesterWorker()
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
        "status | tasks | missions | quit"
    )

    print()

    try:

        while True:

            show_notifications(
                manager
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

            if (
                command
                == "quit"
            ):

                break

            if not command:

                continue

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


if __name__ == (
    "__main__"
):

    main()