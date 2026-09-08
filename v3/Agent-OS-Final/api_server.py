from __future__ import annotations

import uvicorn


def main() -> None:
    print(
        "=" * 64
    )

    print(
        "AGENT-OS V4.6 — EMOTIONAL MEMORY"
    )

    print(
        "=" * 64
    )

    print(
        "\nCe processus est le cerveau unique d'Agent-OS."
    )

    print(
        "Interface : http://127.0.0.1:8765"
    )

    print(
        "API       : http://127.0.0.1:8765/api"
    )

    print(
        "Docs      : http://127.0.0.1:8765/docs"
    )

    print(
        "CLI       : python -u .\\run.py"
    )

    print(
        "\nLe navigateur, la CLI et les futurs clients "
        "Telegram/Discord se connectent tous à ce même runtime."
    )

    print(
        "Ne lance qu'un seul api_server.py.\n"
    )

    uvicorn.run(
        "agentos.api:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
