from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agentos.config import BASE_DIR
from agentos.manager import PersonalManager


app = FastAPI(
    title="Agent-OS V8",
    version="8.0.0",
    description="Paul + mémoire/agenda/Mission Control + intégrations Agent Zero/LangGraph/MAF/OpenHands.",
)
manager = PersonalManager()
WEB_DIR = BASE_DIR / "web"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=50000)


class MissionRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=50000)


class ControlRequest(BaseModel):
    action: str


class ParallelRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=50000)


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    status = manager.status(remote_checks=False)
    return {"ok": True, "version": status["version"], "name": status["name"], "ollama": status["ollama"]}


@app.get("/api/status")
def status(remote_checks: bool = Query(False)) -> dict[str, Any]:
    return manager.status(remote_checks=remote_checks)


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict[str, str]:
    return {"response": manager.chat(body.message)}


@app.get("/api/memory")
def memory() -> dict[str, Any]:
    return {"count": manager.memory.count(), "items": manager.memory.list_active(limit=500)}


@app.delete("/api/memory")
def reset_personal_memory() -> dict[str, Any]:
    manager.reset_personal()
    return {"ok": True, "message": "Mémoire personnelle, conversation et agenda vidés."}


@app.get("/api/agenda")
def agenda(date_ref: str) -> dict[str, Any]:
    from agentos.agenda import parse_date_reference

    target = parse_date_reference(date_ref)
    if not target:
        raise HTTPException(status_code=400, detail="Date non reconnue")
    return {"date": target.isoformat(), "items": manager.agenda.list_for(target)}


@app.get("/api/missions")
def missions() -> dict[str, Any]:
    return {"items": manager.missions.list(limit=200)}


@app.post("/api/missions")
def launch_mission(body: MissionRequest) -> dict[str, Any]:
    return manager.runner.launch(body.objective)


@app.post("/api/missions/{reference}/control")
def control_mission(reference: str, body: ControlRequest) -> dict[str, Any]:
    action = body.action.strip().lower()
    if action not in {"pause", "resume", "cancel"}:
        raise HTTPException(status_code=400, detail="action = pause, resume ou cancel")
    mission = manager.missions.control(reference, action)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    return mission


@app.get("/api/integrations")
def integrations(remote_checks: bool = Query(False)) -> dict[str, Any]:
    return manager.integrations.status(remote_checks=remote_checks)


@app.post("/api/integrations/maf/test")
def maf_test(body: ParallelRequest) -> dict[str, Any]:
    try:
        return {"items": manager.integrations.maf.run(body.prompt)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/integrations/agent-zero/test")
def agent_zero_test(body: ParallelRequest) -> dict[str, Any]:
    try:
        return manager.integrations.agent_zero.send(body.prompt)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/reset")
def reset_v8() -> dict[str, Any]:
    manager.reset_all()
    return {"ok": True, "message": "V8 remise à zéro : mémoire, conversation, agenda et missions vidés."}
