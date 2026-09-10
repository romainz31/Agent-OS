from __future__ import annotations

import os
import threading

from agentos.client import (
    AgentOSClient,
    AgentOSClientError,
    AgentOSUnavailable,
)


DEFAULT_API_URL = (
    "http://127.0.0.1:8765"
)


def notification_loop(
    client: AgentOSClient,
    stop_event: threading.Event,
) -> None:
    offline_reported = False

    while not stop_event.wait(0.35):
        try:
            result = client.notifications(
                limit=100
            )

            offline_reported = False

        except AgentOSClientError as exc:
            if not offline_reported:
                print()
                print(
                    "[CLI] Connexion au serveur perdue :"
                )
                print(
                    str(exc),
                    flush=True,
                )
                print()
                offline_reported = True

            continue

        for notification in (
            result.get(
                "items",
                [],
            )
            or []
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


def main() -> None:
    api_url = (
        os.environ.get(
            "AGENTOS_API_URL",
            DEFAULT_API_URL,
        )
        .strip()
        .rstrip("/")
    )

    client = AgentOSClient(
        api_url
    )

    print(
        "=" * 64
    )
    print(
        "AGENT-OS V7 — CLI CLIENT"
    )
    print(
        "=" * 64
    )

    try:
        health = client.health()

    except AgentOSUnavailable as exc:
        print(
            "\nLe serveur Agent-OS n'est pas lancé."
        )
        print(
            f"Détail : {exc}"
        )
        print(
            "\nLance d'abord, dans un autre terminal :"
        )
        print(
            "python -u .\\api_server.py"
        )
        return

    except AgentOSClientError as exc:
        print(
            f"\nImpossible de joindre Agent-OS : {exc}"
        )
        return

    version = health.get(
        "version",
        "?",
    )

    print(
        f"\nConnecté à Agent-OS V{version}"
    )
    print(
        f"Serveur : {api_url}"
    )
    print(
        "\nCette CLI ne crée plus de deuxième runtime."
    )
    print(
        "Le navigateur et cette fenêtre parlent au même Manager."
    )
    print(
        "\nCommandes naturelles, status, missions, "
        "pause M-xxx, reprends M-xxx, etc."
    )
    print(
        "Tape quit pour fermer uniquement cette CLI.\n"
    )

    stop_notifications = threading.Event()

    notification_thread = threading.Thread(
        target=notification_loop,
        args=(
            client,
            stop_notifications,
        ),
        daemon=True,
        name="agentos-cli-notifications",
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

            value = message.strip()

            if value.lower() == "quit":
                break

            if not value:
                continue

            try:
                result = client.chat(
                    value
                )

            except AgentOSClientError as exc:
                print()
                print(
                    "ERREUR >"
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
            "\nFermeture de la CLI demandée."
        )

    finally:
        stop_notifications.set()
        notification_thread.join(
            timeout=1.0
        )

        print(
            "\nCLI fermée."
        )
        print(
            "Le serveur Agent-OS continue de tourner."
        )


if __name__ == "__main__":
    main()
