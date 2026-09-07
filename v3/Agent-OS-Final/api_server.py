from __future__ import annotations

import uvicorn


def main() -> None:
    print(
        "=" * 64
    )

    print(
        "AGENT-OS V3.9 — LOCAL API"
    )

    print(
        "=" * 64
    )

    print(
        "\nAPI : http://127.0.0.1:8765"
    )

    print(
        "Docs : http://127.0.0.1:8765/docs"
    )

    print(
        "\nNe lance pas run.py en parallèle "
        "pendant ce test : les deux processus "
        "utiliseraient les mêmes missions.\n"
    )

    uvicorn.run(
        "agentos.api:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()