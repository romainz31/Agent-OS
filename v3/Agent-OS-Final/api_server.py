from __future__ import annotations

import uvicorn

from agentos.personal_manager import (
    PersonalManager,
)

# ============================================================
# MANAGER UPGRADE
# ============================================================
#
# On garde le moteur historique de missions intact et on remplace uniquement
# la classe Manager utilisée par le runtime par la surcouche relationnelle.
# Cette injection a lieu AVANT le chargement de agentos.api.

import agentos.runtime as runtime_module

runtime_module.Manager = PersonalManager
runtime_module.AgentOSRuntime.VERSION = "4.7.3"

from agentos import api as api_module

# L'API existante reste inchangée, mais son statut public reflète la mise à
# jour réellement chargée par ce serveur.
api_module.APP_VERSION = "4.7.3"
api_module.app.version = "4.7.3"
api_module.app.description = (
    "Backend local d'Agent-OS avec Manager relationnel, mémoire personnelle "
    "structurée, mémoire émotionnelle et orchestration multi-agents."
)


def main() -> None:
    print(
        "=" * 64
    )

    print(
        "AGENT-OS V4.7.3 — RELATIONAL MANAGER"
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
        "\nLe navigateur, la CLI et Telegram se connectent tous "
        "au même runtime."
    )

    print(
        "Ne lance qu'un seul api_server.py.\n"
    )

    uvicorn.run(
        api_module.app,
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
