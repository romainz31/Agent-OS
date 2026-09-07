from __future__ import annotations

import threading
import time

from agentos.manager import (
    Manager,
)


def recover_active_work(
    manager: Manager,
) -> dict:
    # =========================================================
    # 1. EXISTING TASK RECOVERY
    # =========================================================
    #
    # On reprend d'abord les tâches qui existaient
    # AVANT ce processus.
    #
    # Important : cette étape doit arriver avant
    # recover_planning_missions(), car celle-ci
    # peut créer de nouvelles tâches RUNNING.

    active_before = (
        manager.missions.active(
            manager.tasks
        )
    )

    existing_task_ids = []

    for mission in (
        active_before
    ):
        if mission.task_ids:
            existing_task_ids.extend(
                mission.task_ids
            )

    task_recovery = (
        manager.engine.recover(
            existing_task_ids
        )
    )

    # =========================================================
    # 2. INTERRUPTED PLANNING RECOVERY
    # =========================================================

    planning_recovery = (
        manager.orchestrator
        .recover_planning_missions()
    )

    # =========================================================
    # 3. FINAL STATE
    # =========================================================

    active_after = (
        manager.missions.active(
            manager.tasks
        )
    )

    return {
        "task_recovery": (
            task_recovery
        ),
        "planning_recovery": (
            planning_recovery
        ),
        "active_missions": [
            mission.human_id
            for mission
            in active_after
        ],
    }


def print_recovery_report(
    recovery: dict,
) -> None:
    task_recovery = (
        recovery.get(
            "task_recovery",
            {},
        )
        or {}
    )

    planning_recovery = (
        recovery.get(
            "planning_recovery",
            {},
        )
        or {}
    )

    interrupted = (
        task_recovery.get(
            "interrupted",
            [],
        )
        or []
    )

    submitted = (
        task_recovery.get(
            "submitted",
            [],
        )
        or []
    )

    waiting_approval = (
        task_recovery.get(
            "waiting_approval",
            [],
        )
        or []
    )

    resumed_planning = (
        planning_recovery.get(
            "resumed",
            [],
        )
        or []
    )

    duplicates = (
        planning_recovery.get(
            "cancelled_duplicates",
            [],
        )
        or []
    )

    failed_planning = (
        planning_recovery.get(
            "failed",
            [],
        )
        or []
    )

    active_missions = (
        recovery.get(
            "active_missions",
            [],
        )
        or []
    )

    if not (
        interrupted
        or submitted
        or waiting_approval
        or resumed_planning
        or duplicates
        or failed_planning
    ):
        return

    print(
        "[REPRISE V3.6]"
    )

    if active_missions:
        print(
            (
                "Missions actives "
                "après reprise : "
            )
            + ", ".join(
                active_missions
            )
        )

    if interrupted:
        print(
            (
                "Tâches interrompues "
                "restaurées : "
            )
            + str(
                len(interrupted)
            )
        )

    if submitted:
        print(
            (
                "Tâches relancées "
                "automatiquement : "
            )
            + str(
                len(submitted)
            )
        )

    if waiting_approval:
        print(
            (
                "Tâches toujours en attente "
                "d'autorisation : "
            )
            + str(
                len(
                    waiting_approval
                )
            )
        )

    if resumed_planning:
        print(
            (
                "Missions reprises depuis "
                "la planification : "
            )
            + ", ".join(
                resumed_planning
            )
        )

    for item in (
        duplicates
    ):
        print(
            (
                "Mission interrompue annulée "
                "comme doublon : "
            )
            + item["mission"]
            + " -> "
            + item["duplicate_of"]
        )

    for item in (
        failed_planning
    ):
        print(
            (
                "Échec de reprise "
                "de planification : "
            )
            + item["mission"]
            + " ("
            + item["error"]
            + ")"
        )

    print()


def notification_loop(
    manager: Manager,
    stop_event: threading.Event,
) -> None:
    while not (
        stop_event.is_set()
    ):
        notifications = (
            manager.drain_notifications()
        )

        for notification in (
            notifications
        ):
            print()

            print(
                "[MANAGER]"
            )

            print(
                notification,
                flush=True,
            )

            print()

        time.sleep(
            0.2
        )


def main() -> None:
    print(
        "=" * 64
    )

    print(
        (
            "AGENT-OS V3.6 — "
            "RESILIENT MISSIONS"
        )
    )

    print(
        "=" * 64
    )

    print(
        "\nCommandes : "
        "status | missions | tasks | "
        "approvals | memory | quit\n"
    )

    manager = (
        Manager()
    )

    recovery = (
        recover_active_work(
            manager
        )
    )

    print_recovery_report(
        recovery
    )

    stop_notifications = (
        threading.Event()
    )

    notification_thread = (
        threading.Thread(
            target=(
                notification_loop
            ),
            args=(
                manager,
                stop_notifications,
            ),
            daemon=True,
            name=(
                "agentos-notifications"
            ),
        )
    )

    notification_thread.start()

    try:
        while True:
            try:
                message = input(
                    "TOI > "
                )

            except EOFError:
                break

            if (
                message
                .strip()
                .lower()
                == "quit"
            ):
                break

            response = (
                manager.handle(
                    message
                )
            )

            if response:
                print()

                print(
                    "MANAGER >"
                )

                print(
                    response
                )

                print()

    except KeyboardInterrupt:
        print(
            "\nArrêt demandé."
        )

    finally:
        stop_notifications.set()

        notification_thread.join(
            timeout=1
        )

        print(
            "\nArrêt du Manager..."
        )

        manager.shutdown()

        for notification in (
            manager
            .drain_notifications()
        ):
            print()

            print(
                "[MANAGER]"
            )

            print(
                notification
            )


if __name__ == "__main__":
    main()