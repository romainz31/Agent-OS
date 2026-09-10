from __future__ import annotations

import uvicorn
from fastapi import Query, Request

from agentos.personal_manager import PersonalManager

# ============================================================
# MANAGER + RUNTIME UPGRADE V5.5
# ============================================================
#
# V5.5 conserve l'apprentissage autonome V5.4.1 et ajoute :
# - demandes de renfort structurées entre workers ;
# - tâche d'aide réelle dans le backlog ;
# - reprise automatique du worker avec le contexte du collègue ;
# - garde-fous anti-boucle et historique des collaborations.

import agentos.runtime as runtime_module

runtime_module.Manager = PersonalManager

from agentos.autonomous_runtime import AutonomousRuntime

runtime_module.AgentOSRuntime = AutonomousRuntime

from agentos import api as api_module

api_module.APP_VERSION = "5.5"
api_module.app.version = "5.5"
api_module.app.description = (
    "Backend local d'Agent-OS V5.5 avec Manager relationnel, mémoire "
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
# SPECIALISTS API — V5.3
# ============================================================


@api_module.app.get(
    "/api/specialists",
    tags=["Specialists"],
)
def specialists_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.specialists_status()


@api_module.app.get(
    "/api/specialists/{reference}",
    tags=["Specialists"],
)
def specialist_detail(
    reference: str,
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    try:
        return runtime.specialist_detail(
            reference
        )
    except KeyError as exc:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


# ============================================================
# AUTONOMOUS LEARNING API — V5.4.1
# ============================================================


@api_module.app.get(
    "/api/learning",
    tags=["Learning"],
)
def learning_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.learning_status()


@api_module.app.get(
    "/api/learning/history",
    tags=["Learning"],
)
def learning_history(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return {
        "items": runtime.learning_history()
    }


# ============================================================
# COLLABORATION API — V5.5
# ============================================================


@api_module.app.get(
    "/api/collaboration",
    tags=["Collaboration"],
)
def collaboration_status(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return runtime.collaboration_status()


@api_module.app.get(
    "/api/collaboration/history",
    tags=["Collaboration"],
)
def collaboration_history(
    request: Request,
) -> dict:
    runtime = api_module.runtime_from(
        request
    )
    return {
        "items": runtime.collaboration_history()
    }


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
    print("AGENT-OS V5.5 — INTER-AGENT COLLABORATION")
    print("=" * 64)

    print("\nCe processus est le cerveau unique d'Agent-OS.")
    print("Interface   : http://127.0.0.1:8765")
    print("API         : http://127.0.0.1:8765/api")
    print("Autonomie   : http://127.0.0.1:8765/api/autonomy")
    print("Workload    : http://127.0.0.1:8765/api/workload")
    print("Hiérarchie  : http://127.0.0.1:8765/api/hierarchy")
    print("Skills      : http://127.0.0.1:8765/api/skills")
    print("Spécialistes: http://127.0.0.1:8765/api/specialists")
    print("Learning    : http://127.0.0.1:8765/api/learning")
    print("Collaboration: http://127.0.0.1:8765/api/collaboration")
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
    print(
        "V5.4.1 détecte les besoins techniques : si un skill est absent, faible "
        "ou périmé, Researcher se documente avant la reprise du worker."
    )
    print(
        "V5.5 permet aussi aux workers de demander un renfort ponctuel à un "
        "collègue, puis de reprendre automatiquement avec sa réponse."
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
