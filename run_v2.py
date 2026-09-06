"""
Point d'entrée Agent-OS V2.

Permet de tester le Manager,
les missions et les workers spécialisés.
"""

from v2.manager.manager import Manager

from v2.workers.llm_worker import (
    LLMWorker,
)

from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class DemoWorker(Worker):
    """
    Worker de test.
    """

    name = "demo"

    description = (
        "Worker de démonstration utilisé "
        "pour tester le système."
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
            f"\n[DEMO WORKER] "
            f"Travail commencé : {title}"
        )

        time.sleep(5)

        print(
            f"[DEMO WORKER] "
            f"Travail terminé : {title}"
        )

        return WorkerResult(
            success=True,
            message=(
                f"Le worker a terminé : {title}"
            ),
            data={
                "worker": self.name,
                "type": "demo",
            },
        )


def main() -> None:

    print("=" * 60)

    print(
        "AGENT-OS V2 — MANAGER"
    )

    print("=" * 60)

    print()

    manager = Manager()

    # ============================================================
    # WORKERS
    # ============================================================

    manager.register_worker(
        DemoWorker()
    )

    manager.register_worker(
        LLMWorker()
    )

    # IMPORTANT :
    # Les trois workers spécialisés utilisent
    # actuellement le LLM local.

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
        ResearcherWorker()
    )

    manager.register_worker(
        DeveloperWorker()
    )

    manager.register_worker(
        TesterWorker()
    )

    # ============================================================
    # INTERFACE
    # ============================================================

    print(
        "Manager prêt."
    )

    print(
        "Workers disponibles : "
        f"{', '.join(manager.get_worker_names())}"
    )

    print(
        "Tape 'quit' pour quitter."
    )

    print()

    try:

        while True:

            try:

                message = input(
                    "TOI > "
                )

            except EOFError:

                break

            if (
                message.strip().lower()
                == "quit"
            ):

                break

            if not message.strip():

                continue

            response = manager.chat(
                message
            )

            print()

            print(
                f"MANAGER > {response}"
            )

            print()

    except KeyboardInterrupt:

        print()

        print(
            "Arrêt demandé."
        )

    finally:

        print()

        print(
            "Arrêt du Manager..."
        )

        manager.shutdown()

        print()

        print(
            "STATUS FINAL :"
        )

        print(
            manager.status()
        )


if __name__ == "__main__":

    main()