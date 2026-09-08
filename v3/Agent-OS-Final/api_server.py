from __future__ import annotations

import uvicorn
from fastapi import Query, Request

from agentos.personal_manager import PersonalManager

# ============================================================
# MANAGER + RUNTIME UPGRADE V4.9
# ============================================================
#
# Le moteur historique reste intact. On remplace :
# - le Manager par la surcouche relationnelle validée en V4.7 ;
# - le Runtime par une surcouche qui ajoute le superviseur autonome.
#
# L'injection a lieu AVANT le chargement de agentos.api.

import agentos.runtime as runtime_module

runtime_module.Manager = PersonalManager

from agentos.autonomous_runtime import AutonomousRuntime

runtime_module.AgentOSRuntime = AutonomousRuntime

from agentos import api as api_module

api_module.APP_VERSION = "4.9"
api_module.app.version = "4.9"
api_module.app.description = (
    "Backend local d'Agent-OS V4.9 avec Manager relationnel, mémoire "
    "personnelle structurée, fil conversationnel persistant, supervision "
    "autonome des missions, priorités, échéances, récupération contrôlée, "
    "journal des décisions et recherche factuelle sourcée."
)


# ============================================================
# AUTONOMY API
# ============================================================


@api_module.app.get(
    "/api/autonomy",
    tags=["Autonomy"],
)
def autonomy_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.autonomy_status()


@api_module.app.get(
    "/api/autonomy/decisions",
    tags=["Autonomy"],
)
def autonomy_decisions(
    request: Request,
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return {
        "items": runtime.autonomy_decisions(
            limit=limit
        )
    }


@api_module.app.post(
    "/api/autonomy/check",
    tags=["Autonomy"],
)
def autonomy_check(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.autonomy_check()


# ============================================================
# CONVERSATION API
# ============================================================


@api_module.app.get(
    "/api/conversation",
    tags=["Conversation"],
)
def conversation_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(request)
    return runtime.conversation_status()


@api_module.app.get(
    "/api/conversation/history",
    tags=["Conversation"],
)
def conversation_history(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(request)
    return {
        "items": runtime.conversation_history()
    }


# ============================================================
# RESEARCH API
# ============================================================


@api_module.app.get(
    "/api/research",
    tags=["Research"],
)
def research_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(request)
    return runtime.research_status()


@api_module.app.get(
    "/api/research/history",
    tags=["Research"],
)
def research_history(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(request)
    return {
        "items": runtime.research_history()
    }


# ============================================================
# SERVER
# ============================================================


def main() -> None:
    print("=" * 64)
    print("AGENT-OS V4.9 — AUTONOMOUS MANAGER")
    print("=" * 64)

    print("\nCe processus est le cerveau unique d'Agent-OS.")
    print("Interface : http://127.0.0.1:8765")
    print("API       : http://127.0.0.1:8765/api")
    print("Autonomie : http://127.0.0.1:8765/api/autonomy")
    print("Conversation: http://127.0.0.1:8765/api/conversation")
    print("Recherche   : http://127.0.0.1:8765/api/research")
    print("Docs      : http://127.0.0.1:8765/docs")
    print("CLI       : python -u .\\run.py")

    print(
        "\nLe navigateur, la CLI et Telegram se connectent tous "
        "au même runtime."
    )
    print(
        "Paul supervise les missions en arrière-plan, conserve le fil de "
        "conversation, vérifie les questions factuelles et n'auto-valide "
        "jamais les autorisations sensibles."
    )
    print("Ne lance qu'un seul api_server.py.\n")

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
