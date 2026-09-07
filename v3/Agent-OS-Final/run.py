from __future__ import annotations

import threading
import time

from agentos.runtime import (
    AgentOSRuntime,
)


def print_recovery_report(
    runtime: AgentOSRuntime,
) -> None:
    lines = (
        runtime
        .recovery_report_lines()
    )

    if not lines:
        return

    for line in lines:
        print(
            line
        )

    print()


def notification_loop(
    runtime: AgentOSRuntime,
    stop_event: threading.Event,
) -> None:
    while not (
        stop_event.is_set()
    ):
        notifications = (
            runtime.notifications()
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
            "AGENT-OS V3.9 — "
            "API-READY RUNTIME"
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
        "API séparée : python -u .\\api_server.py\n"
    )

    runtime = AgentOSRuntime()

    print_recovery_report(
        runtime
    )

    stop_notifications = (
        threading.Event()
    )

    notification_thread = (
        threading.Thread(
            target=notification_loop,
            args=(
                runtime,
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

            try:
                result = (
                    runtime.handle_message(
                        message
                    )
                )

            except ValueError as exc:
                print()
                print(
                    "MANAGER >"
                )
                print(
                    str(exc)
                )
                print()
                continue

            response = str(
                result.get(
                    "response",
                    "",
                )
                or ""
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

        runtime.shutdown()

        for notification in (
            runtime.notifications()
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