from __future__ import annotations

import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
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


from agentos import __version__

APP_VERSION = __version__
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
    next_life_check = 0.0
    while not stop_event.wait(0.2):
        try:
            journal = getattr(runtime.manager, 'life_journal', None)
            if journal and time.monotonic() >= next_life_check:
                next_life_check = time.monotonic() + 20
                for note in journal.notifications():
                    runtime.manager._append_notification(note)
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
        # If this client just sent an image/document without instructions,
        # this message is the natural answer to Paul's question.
        from agentos.file_missions import install_file_missions
        with runtime.lock:
            install_file_missions(runtime)
            file_service = runtime.file_assistant

        client_key = attachment_client_key(request)
        pending = file_service.pending_attachment(client_key)

        if pending is not None:
            normalized = body.message.strip().lower()
            if normalized in {
                "annule", "annuler", "laisse tomber", "rien",
                "oublie", "oublie-la", "oublie le fichier",
            }:
                file_service.clear_pending_attachment(client_key)
                return {
                    "response": "D'accord, je laisse cette image de côté.",
                    "handled_by": "documents",
                    "status": public_status(runtime),
                }

            if "excel" in normalized:
                answer = file_service.request_analysis_excel(
                    pending["path"],
                    body.message,
                )
            else:
                answer = file_service.request_analysis(
                    pending["path"],
                    body.message,
                )

            file_service.clear_pending_attachment(client_key)
            return {
                "response": answer,
                "handled_by": "documents",
                "status": public_status(runtime),
            }

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


@app.get('/api/life')
def life(request: Request, start: str = '1970-01-01', end: str = '9999-12-31', q: str = ''):
    from datetime import date
    try:
        date.fromisoformat(start); date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, 'Dates ISO requises')
    manager = runtime_from(request).manager
    journal = manager.life_journal
    journal.rollover()
    return {'events': journal.rows(start,end,q), 'todos': manager.agenda.backlog_todos(),
            'today': manager.agenda.program_for_date(manager.agenda._now().date())}


def attachment_client_key(request: Request) -> str:
    candidate = str(
        request.headers.get("X-AgentOS-Client", "")
        or request.cookies.get("agentos_client", "")
        or "web-ui"
    ).strip()
    return candidate if CLIENT_ID_RE.fullmatch(candidate) else "web-ui"


@app.post('/api/documents/upload')
def upload_document(request: Request, file: UploadFile = File(...), objective: str = Form('')):
    from agentos.config import WORKSPACE_DIR
    from agentos.file_assistant import TEXT, IMAGES, MAX_BYTES
    from agentos.file_missions import install_file_missions
    name = Path((file.filename or 'document').replace('\\','/')).name
    ext = Path(name).suffix.lower()
    if ext not in TEXT | IMAGES | {'.pdf','.docx','.xlsx'}:
        raise HTTPException(400,'Format non pris en charge : PDF, images, DOCX, XLSX ou texte requis.')
    raw = file.file.read(MAX_BYTES+1)
    if not raw or len(raw)>MAX_BYTES:
        raise HTTPException(413,'Fichier vide ou supérieur à 10 Mio.')
    from agentos.file_assistant import no_links
    target_dir = WORKSPACE_DIR / 'inbox' / uuid.uuid4().hex
    no_links(WORKSPACE_DIR / 'inbox')
    target_dir.mkdir(parents=True)
    target = target_dir / ('document'+ext)
    with target.open('xb') as out:
        out.write(raw)
    runtime=runtime_from(request)
    with runtime.lock:
        install_file_missions(runtime)
        service=runtime.file_assistant
        objective = objective.strip()
        if not objective:
            media_kind = 'image' if ext in IMAGES else 'document'
            service.hold_attachment(
                attachment_client_key(request),
                str(target),
                name,
                media_kind,
            )
            noun = "l'image" if media_kind == 'image' else "le document"
            return {
                'filename': name,
                'awaiting_instruction': True,
                'response': (
                    f"J'ai bien reçu {noun} « {name} ». "
                    "Qu'est-ce que tu veux que j'en fasse ? "
                    "Je peux par exemple le décrire, lire le texte, chercher une information précise "
                    "ou en tirer un récapitulatif."
                ),
            }
        if 'excel' in objective.lower():
            response=service.request_analysis_excel(str(target),objective)
        else:
            response=service.request_analysis(str(target),objective)
    return {'filename':name,'response':response}


@app.get('/api/documents/exports')
def document_exports():
    from agentos.config import WORKSPACE_DIR
    folder=WORKSPACE_DIR/'documents_exports'
    return {'files':[{'name':p.name,'url':'/api/documents/exports/'+p.name} for p in folder.glob('*') if p.is_file() and not p.is_symlink()]}


@app.get('/api/documents/exports/{name}')
def download_document_export(name: str):
    from agentos.config import WORKSPACE_DIR
    from agentos.file_assistant import no_links
    folder=(WORKSPACE_DIR/'documents_exports').resolve()
    target=folder/name
    if Path(name).name!=name or not target.is_file():
        raise HTTPException(404,'Export introuvable')
    no_links(target)
    if target.resolve().parent!=folder: raise HTTPException(403,'Chemin refusé')
    return FileResponse(target,filename=name)
