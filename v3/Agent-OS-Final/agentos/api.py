from __future__ import annotations

import re
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
)

from fastapi.middleware.cors import (
    CORSMiddleware,
)

from fastapi.responses import (
    FileResponse,
)

from fastapi.staticfiles import (
    StaticFiles,
)

from pydantic import (
    BaseModel,
    Field,
)

from agentos.events import (
    NotificationHub,
)
from agentos.runtime import (
    AgentOSRuntime,
)


APP_VERSION = "4.6"
SERVER_INSTANCE_ID = uuid.uuid4().hex

PROJECT_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

WEB_DIR = (
    PROJECT_DIR
    / "web"
)

CLIENT_ID_RE = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=20000,
    )


def notification_collector(
    runtime: AgentOSRuntime,
    hub: NotificationHub,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(0.2):
        try:
            hub.ingest(
                runtime.notifications()
            )
        except Exception:
            # Une erreur de collecte ne doit jamais arrêter le runtime.
            continue

    try:
        hub.ingest(
            runtime.notifications()
        )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    runtime = AgentOSRuntime()
    notification_hub = NotificationHub(
        max_events=1000,
        max_clients=200,
    )
    stop_notifications = threading.Event()

    collector = threading.Thread(
        target=notification_collector,
        args=(
            runtime,
            notification_hub,
            stop_notifications,
        ),
        daemon=True,
        name="agentos-notification-hub",
    )

    app.state.runtime = runtime
    app.state.notification_hub = (
        notification_hub
    )
    app.state.server_instance_id = (
        SERVER_INSTANCE_ID
    )

    collector.start()

    yield

    # Laisse les workers terminer proprement pendant que le collecteur
    # continue d'enregistrer leurs dernières notifications.
    runtime.shutdown()

    stop_notifications.set()
    collector.join(
        timeout=2.0
    )


app = FastAPI(
    title="Agent-OS API",
    description=(
        "Backend local d'Agent-OS V4.6. "
        "Le serveur API possède l'unique runtime et expose le Manager, "
        "les missions, les agents, les approbations, la mémoire et "
        "les notifications multi-clients au Web, à la CLI et aux "
        "futurs adaptateurs Telegram/Discord."
    ),
    version=APP_VERSION,
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
        "http://localhost:8765",
        "http://127.0.0.1:8765",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/static",
    StaticFiles(
        directory=WEB_DIR,
        check_dir=True,
    ),
    name="static",
)


# ============================================================
# HELPERS
# ============================================================


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


def notification_hub_from(
    request: Request,
) -> NotificationHub:
    hub = getattr(
        request.app.state,
        "notification_hub",
        None,
    )

    if hub is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Le bus de notifications n'est pas encore prêt."
            ),
        )

    return hub


def client_id_from(
    request: Request,
    response: Response,
) -> str:
    header_value = str(
        request.headers.get(
            "X-AgentOS-Client",
            "",
        )
        or ""
    ).strip()

    cookie_value = str(
        request.cookies.get(
            "agentos_client",
            "",
        )
        or ""
    ).strip()

    candidate = (
        header_value
        or cookie_value
    )

    if not CLIENT_ID_RE.fullmatch(
        candidate
    ):
        candidate = (
            "web-"
            + uuid.uuid4().hex
        )

    if not header_value:
        response.set_cookie(
            key="agentos_client",
            value=candidate,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )

    return candidate


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


def public_status(
    runtime: AgentOSRuntime,
) -> dict:
    status = dict(
        runtime.status()
    )

    core_version = status.get(
        "version",
        "3.9",
    )

    status[
        "core_version"
    ] = core_version

    status[
        "version"
    ] = APP_VERSION

    status[
        "server_instance_id"
    ] = SERVER_INSTANCE_ID

    status[
        "runtime_owner"
    ] = "api_server"

    return status


# ============================================================
# ROOT / STATUS
# ============================================================


@app.get("/")
def control_center() -> FileResponse:
    return FileResponse(
        WEB_DIR
        / "index.html"
    )


@app.get("/api")
def api_root() -> dict:
    return {
        "name": "Agent-OS",
        "version": APP_VERSION,
        "interface": "/",
        "api": "/api",
        "docs": "/docs",
        "binding": "localhost",
        "runtime_owner": "api_server",
        "multi_client": True,
        "server_instance_id": (
            SERVER_INSTANCE_ID
        ),
    }


@app.get("/api/health")
def health(
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    status = public_status(
        runtime
    )

    return {
        "ok": True,
        "version": status[
            "version"
        ],
        "core_version": status[
            "core_version"
        ],
        "started_at": status[
            "started_at"
        ],
        "server_instance_id": (
            SERVER_INSTANCE_ID
        ),
        "runtime_owner": "api_server",
    }


@app.get("/api/status")
def status(
    request: Request,
) -> dict:
    return public_status(
        runtime_from(
            request
        )
    )


@app.get("/api/dashboard")
def dashboard(
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    return {
        "status": public_status(
            runtime
        ),
        "agents": runtime.agents(),
        "missions": runtime.missions(),
        "approvals": runtime.approvals(),
    }


@app.get("/api/agents")
def agents(
    request: Request,
) -> dict:
    return {
        "items": runtime_from(
            request
        ).agents()
    }


# ============================================================
# CHAT
# ============================================================


@app.post("/api/chat")
def chat(
    body: ChatRequest,
    request: Request,
) -> dict:
    runtime = runtime_from(
        request
    )

    try:
        result = runtime.handle_message(
            body.message
        )

        result = dict(
            result
        )

        result[
            "status"
        ] = public_status(
            runtime
        )

        return result

    except Exception as exc:
        raise_http_error(
            exc
        )

    raise RuntimeError(
        "Erreur API inattendue."
    )


# ============================================================
# MISSIONS
# ============================================================


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


# ============================================================
# TASKS
# ============================================================


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


# ============================================================
# APPROVALS
# ============================================================


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


# ============================================================
# MEMORY
# ============================================================


@app.get("/api/memory")
def memory(
    request: Request,
) -> dict:
    return runtime_from(
        request
    ).memory()


# ============================================================
# MULTI-CLIENT NOTIFICATIONS — V4.3
# ============================================================


@app.get("/api/notifications")
def notifications(
    request: Request,
    response: Response,
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
) -> dict:
    client_id = client_id_from(
        request,
        response,
    )

    result = notification_hub_from(
        request
    ).read_for_client(
        client_id,
        limit=limit,
    )

    result[
        "server_instance_id"
    ] = SERVER_INSTANCE_ID

    return result


@app.get("/api/notifications/status")
def notifications_status(
    request: Request,
) -> dict:
    return {
        "server_instance_id": (
            SERVER_INSTANCE_ID
        ),
        **notification_hub_from(
            request
        ).status(),
    }


# ============================================================
# RECOVERY
# ============================================================


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
