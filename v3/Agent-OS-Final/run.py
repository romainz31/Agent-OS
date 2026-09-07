from __future__ import annotations

import threading
import time

from agentos.manager import (
    Manager,
)

from agentos.mission_control import (
    MissionControl,
)


def recover_active_work(
    manager: Manager,
) -> dict:
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

    planning_recovery = (
        manager.orchestrator
        .recover_planning_missions()
    )

    repair_recovery = (
        manager.orchestrator
        .repair_loop
        .recover_pending_repairs()
    )

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
        "repair_recovery": (
            repair_recovery
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

    repair_recovery = (
        recovery.get(
            "repair_recovery",
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

    paused = (
        task_recovery.get(
            "paused",
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

    restored_repairs = (
        repair_recovery.get(
            "restored",
            [],
        )
        or []
    )

    exhausted_repairs = (
        repair_recovery.get(
            "exhausted",
            [],
        )
        or []
    )

    failed_repairs = (
        repair_recovery.get(
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
        or paused
        or resumed_planning
        or duplicates
        or failed_planning
        or restored_repairs
        or exhausted_repairs
        or failed_repairs
    ):
        return

    print(
        "[REPRISE V3.8]"
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

    if paused:
        print(
            (
                "Tâches conservées "
                "en pause : "
            )
            + str(
                len(paused)
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

    if restored_repairs:
        print(
            (
                "Boucles de correction "
                "restaurées : "
            )
            + ", ".join(
                restored_repairs
            )
        )

    if exhausted_repairs:
        print(
            (
                "Corrections automatiques "
                "arrivées à leur limite : "
            )
            + str(
                len(exhausted_repairs)
            )
        )

    for item in duplicates:
        print(
            (
                "Mission interrompue annulée "
                "comme doublon : "
            )
            + item["mission"]
            + " -> "
            + item["duplicate_of"]
        )

    for item in failed_planning:
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

    for item in failed_repairs:
        print(
            (
                "Échec de reprise "
                "d'une correction : "
            )
            + item["task"]
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
            "AGENT-OS V3.8 — "
            "AUTO-REPAIR LOOP"
        )
    )

    print(
        "=" * 64
    )

    print(
        "\nCommandes : "
        "status | missions | tasks | approvals | memory\n"
        "Contrôle : pause M-xxx | reprends M-xxx | "
        "annule M-xxx | retente M-xxx | quit\n"
        "V3.8 : Tester NON VALIDÉ -> Developer corrige -> Tester reteste "
        "(3 corrections max)\n"
    )

    manager = Manager()

    control = MissionControl(
        missions=manager.missions,
        tasks=manager.tasks,
        engine=manager.engine,
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
            target=notification_loop,
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

            control_response = (
                control.handle(
                    message
                )
            )

            if (
                control_response
                is not None
            ):
                print()
                print(
                    "MANAGER >"
                )
                print(
                    control_response
                )
                print()
                continue

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