from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from .store import PersonalMemoryStore


_stores: dict[str, PersonalMemoryStore] = {}
_lock = Lock()


def data_path() -> Path:
    try:
        from helpers import files

        return Path(files.get_abs_path("usr/agent_os_memory/assistant.db"))
    except ImportError:
        return Path.cwd() / "usr" / "agent_os_memory" / "assistant.db"


def get_store(agent: Any = None) -> PersonalMemoryStore:
    path = str(data_path().resolve())
    with _lock:
        if path not in _stores:
            _stores[path] = PersonalMemoryStore(path)
        return _stores[path]


def context_id(agent: Any) -> str:
    try:
        return str(agent.context.id)
    except (AttributeError, TypeError):
        return ""


def plugin_config(agent: Any) -> dict[str, Any]:
    try:
        from helpers.plugins import get_plugin_config

        return dict(get_plugin_config("agent_os_memory", agent=agent) or {})
    except ImportError:
        return {}
