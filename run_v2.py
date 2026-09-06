"""
Point d'entrée Agent-OS V2.

Permet de tester le Manager et ses workers.
"""

import time

from v2.manager.manager import Manager
from v2.workers.llm_worker import LLMWorker
from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class DemoWorker(Worker):
    """
    Worker de test.

    Simule un travail de 5 secondes.
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
    """
    Lance Agent-OS V2.
    """

    print("=" * 60)
    print("AGENT-OS V2 — MANAGER")
    print("=" * 60)
    print()

    manager = Manager()

    # ------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------

    manager.register_worker(
        DemoWorker()
    )

    manager.register_worker(
        LLMWorker()
    )

    # ------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------

    print("Manager prêt.")
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

            if message.strip().lower() == "quit":
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