from __future__ import annotations

import uvicorn
from fastapi import Query, Request

from agentos.personal_manager import PersonalManager

# ============================================================
# MANAGER + RUNTIME UPGRADE V5.2
# ============================================================
#
# V5.2 conserve toutes les briques V4.9/V5.0/V5.1 et ajoute :
# - Skill Registry persistant ;
# - niveau, confiance, fraîcheur et sources ;
# - compétences requises par mission ;
# - héritage des skills parent -> enfant ;
# - injection du contexte technique dans le pipeline worker.

import agentos.runtime as runtime_module

runtime_module.Manager = PersonalManager

from agentos.autonomous_runtime import AutonomousRuntime

runtime_module.AgentOSRuntime = AutonomousRuntime

from agentos import api as api_module

api_module.APP_VERSION = "5.2"
api_module.app.version = "5.2"
api_module.app.description = (
    "Backend local d'Agent-OS V5.2 avec Manager relationnel, mémoire "
    "personnelle, conversation persistante, recherche factuelle, autonomie, "
    "workload multi-missions, arbres de sous-missions et Skill Registry persistant."
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
# WORKLOAD API — V5.0
# ============================================================


@api_module.app.get(
    "/api/workload",
    tags=["Workload"],
)
def workload_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.workload_status()


# ============================================================
# HIERARCHY API — V5.1
# ============================================================


@api_module.app.get(
    "/api/hierarchy",
    tags=["Hierarchy"],
)
def hierarchy_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.hierarchy_status()


@api_module.app.get(
    "/api/hierarchy/{reference}",
    tags=["Hierarchy"],
)
def hierarchy_tree(
    reference: str,
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.hierarchy_tree(
        reference
    )


# ============================================================
# SKILLS API — V5.2
# ============================================================


@api_module.app.get(
    "/api/skills",
    tags=["Skills"],
)
def skills_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.skills_status()


@api_module.app.get(
    "/api/skills/{name}",
    tags=["Skills"],
)
def skill_detail(
    name: str,
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    try:
        return runtime.skill_detail(
            name
        )
    except KeyError as exc:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


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
    print("AGENT-OS V5.2 — SKILL REGISTRY")
    print("=" * 64)

    print("\nCe processus est le cerveau unique d'Agent-OS.")
    print("Interface   : http://127.0.0.1:8765")
    print("API         : http://127.0.0.1:8765/api")
    print("Autonomie   : http://127.0.0.1:8765/api/autonomy")
    print("Workload    : http://127.0.0.1:8765/api/workload")
    print("Hiérarchie  : http://127.0.0.1:8765/api/hierarchy")
    print("Skills      : http://127.0.0.1:8765/api/skills")
    print("Conversation: http://127.0.0.1:8765/api/conversation")
    print("Recherche   : http://127.0.0.1:8765/api/research")
    print("Docs        : http://127.0.0.1:8765/docs")
    print("CLI         : python -u .\\run.py")

    print(
        "\nAgent-OS dispose maintenant d'un Skill Registry séparé de la mémoire "
        "personnelle : compétences, niveaux, confiance, fraîcheur et sources."
    )
    print(
        "Les missions peuvent déclarer les skills requis ; les sous-missions "
        "les héritent et le moteur injecte leur contexte technique au worker."
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
