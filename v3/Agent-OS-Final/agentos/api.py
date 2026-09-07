from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
)

from fastapi.middleware.cors import (
    CORSMiddleware,
)

from pydantic import (
    BaseModel,
    Field,
)

from agentos.runtime import (
    AgentOSRuntime,
)


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=20000,
    )


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    runtime = AgentOSRuntime()

    app.state.runtime = runtime

    yield

    runtime.shutdown()


app = FastAPI(
    title="Agent-OS API",
    description=(
        "API locale d'Agent-OS. "
        "Elle expose le Manager, les missions, "
        "les agents, les approbations, la mémoire "
        "et le Mission Control."
    ),
    version="3.9",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def runtime_from(
    request: Request,
) -> AgentOSRuntime:
    runtime = getattr(
        request.app.state,
        "runtime",
        None,
    )

    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Agent-OS n'est pas encore prêt."
            ),
        )

    return runtime


def raise_http_error(
    exc: Exception,
) -> None:
    if isinstance(
        exc,
        KeyError,
    ):
        detail = (
            exc.args[0]
            if exc.args
            else str(exc)
        )

        raise HTTPException(
            status_code=404,
            detail=detail,
        ) from exc

    if isinstance(
        exc,
        ValueError,
    ):
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    raise exc


@app.get("/")
def root() -> dict:
    return {
        "name": "Agent-OS",
        "version": "3.9",
        "api": "/api",
        "docs": "/docs",
        "binding": "localhost",
    }


@app.get("/api/health")
def health(
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    status = runtime.status()

    return {
        "ok": True,
        "version": (
            status["version"]
        ),
        "started_at": (
            status["started_at"]
        ),
    }


@app.get("/api/status")
def status(
    request: Request,
) -> dict:
    return runtime_from(
        request
    ).status()


@app.get("/api/agents")
def agents(
    request: Request,
) -> dict:
    return {
        "items": runtime_from(
            request
        ).agents()
    }


@app.post("/api/chat")
def chat(
    body: ChatRequest,
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    try:
        return runtime.handle_message(
            body.message
        )

    except Exception as exc:
        raise_http_error(
            exc
        )

    raise RuntimeError(
        "Erreur API inattendue."
    )


@app.get("/api/missions")
def missions(
    request: Request,
    status: str | None = Query(
        default=None,
    ),
) -> dict:
    return {
        "items": runtime_from(
            request
        ).missions(
            status=status
        )
    }


@app.get(
    "/api/missions/{reference}"
)
def mission(
    reference: str,
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    try:
        return runtime.mission(
            reference
        )

    except Exception as exc:
        raise_http_error(
            exc
        )

    raise RuntimeError(
        "Erreur API inattendue."
    )


def mission_action(
    *,
    reference: str,
    action: str,
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    try:
        return runtime.control_mission(
            reference,
            action,
        )

    except Exception as exc:
        raise_http_error(
            exc
        )

    raise RuntimeError(
        "Erreur API inattendue."
    )


@app.post(
    "/api/missions/{reference}/pause"
)
def pause_mission(
    reference: str,
    request: Request,
) -> dict:
    return mission_action(
        reference=reference,
        action="pause",
        request=request,
    )


@app.post(
    "/api/missions/{reference}/resume"
)
def resume_mission(
    reference: str,
    request: Request,
) -> dict:
    return mission_action(
        reference=reference,
        action="resume",
        request=request,
    )


@app.post(
    "/api/missions/{reference}/cancel"
)
def cancel_mission(
    reference: str,
    request: Request,
) -> dict:
    return mission_action(
        reference=reference,
        action="cancel",
        request=request,
    )


@app.post(
    "/api/missions/{reference}/retry"
)
def retry_mission(
    reference: str,
    request: Request,
) -> dict:
    return mission_action(
        reference=reference,
        action="retry",
        request=request,
    )


@app.get("/api/tasks")
def tasks(
    request: Request,
    status: str | None = Query(
        default=None,
    ),
) -> dict:
    return {
        "items": runtime_from(
            request
        ).tasks(
            status=status
        )
    }


@app.get("/api/approvals")
def approvals(
    request: Request,
) -> dict:
    return {
        "items": runtime_from(
            request
        ).approvals()
    }


@app.post(
    "/api/approvals/{reference}/approve"
)
def approve(
    reference: str,
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    try:
        return runtime.approve_mission(
            reference
        )

    except Exception as exc:
        raise_http_error(
            exc
        )

    raise RuntimeError(
        "Erreur API inattendue."
    )


@app.post(
    "/api/approvals/{reference}/reject"
)
def reject(
    reference: str,
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    try:
        return runtime.reject_mission(
            reference
        )

    except Exception as exc:
        raise_http_error(
            exc
        )

    raise RuntimeError(
        "Erreur API inattendue."
    )


@app.get("/api/memory")
def memory(
    request: Request,
) -> dict:
    return runtime_from(
        request
    ).memory()


@app.get("/api/notifications")
def notifications(
    request: Request,
) -> dict:
    return {
        "items": runtime_from(
            request
        ).notifications()
    }


@app.get("/api/recovery")
def recovery(
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    return {
        "details": runtime.recovery,
        "report": (
            runtime.recovery_report_lines()
        ),
    }