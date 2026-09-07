from __future__ import annotations

import threading
import time

from agentos.manager import (
    Manager,
)


def notification_loop(
    manager: Manager,
    stop_event: threading.Event,
) -> None:

    while not stop_event.is_set():

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
        "AGENT-OS V3.4 — MANAGER"
    )

    print(
        "=" * 64
    )

    print(
        "\nCommandes : "
        "status | missions | tasks | "
        "approvals | memory | "
        "oui | non | quit\n"
    )

    manager = Manager()

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

            command = (
                message
                .strip()
                .lower()
            )

            if command == "quit":

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

        remaining = (
            manager
            .drain_notifications()
        )

        for notification in remaining:

            print()

            print(
                "[MANAGER]"
            )

            print(
                notification
            )


if __name__ == "__main__":

    main()