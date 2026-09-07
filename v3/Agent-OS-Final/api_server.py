from __future__ import annotations

import uvicorn


def main() -> None:
    print(
        "=" * 64
    )

    print(
        "AGENT-OS V4.0 — CONTROL CENTER"
    )

    print(
        "=" * 64
    )

    print(
        "\nInterface : http://127.0.0.1:8765"
    )

    print(
        "API       : http://127.0.0.1:8765/api"
    )

    print(
        "Docs      : http://127.0.0.1:8765/docs"
    )

    print(
        "\nUn seul processus Agent-OS doit utiliser "
        "les fichiers de données à la fois."
    )

    print(
        "Ne lance pas run.py en parallèle.\n"
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
