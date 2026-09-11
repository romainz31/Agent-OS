from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

DATA_DIR = Path(os.getenv("AGENTOS_DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
WORKSPACE_DIR = Path(os.getenv("AGENTOS_WORKSPACE_DIR", str(BASE_DIR / "workspace"))).expanduser().resolve()
DB_PATH = Path(os.getenv("AGENTOS_DB_PATH", str(DATA_DIR / "agentos_v8.db"))).expanduser().resolve()
LANGGRAPH_DB_PATH = Path(os.getenv("LANGGRAPH_DB_PATH", str(DATA_DIR / "langgraph_checkpoints.sqlite"))).expanduser().resolve()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
AGENTOS_HOST = os.getenv("AGENTOS_HOST", "127.0.0.1")
AGENTOS_PORT = int(os.getenv("AGENTOS_PORT", "8765"))
MAX_WORKERS = max(1, int(os.getenv("AGENTOS_MAX_WORKERS", "3")))

AGENT_ZERO_URL = os.getenv("AGENT_ZERO_URL", "").strip().rstrip("/")
AGENT_ZERO_API_KEY = os.getenv("AGENT_ZERO_API_KEY", "").strip()
OPENHANDS_URL = os.getenv("OPENHANDS_URL", "").strip().rstrip("/")
OPENHANDS_API_KEY = os.getenv("OPENHANDS_API_KEY", "").strip()

USE_LANGGRAPH = os.getenv("AGENTOS_USE_LANGGRAPH", "1").strip().lower() not in {"0", "false", "no"}
USE_MAF = os.getenv("AGENTOS_USE_MAF", "1").strip().lower() not in {"0", "false", "no"}

# Safer serializer mode recommended by the current LangGraph SQLite checkpoint package.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

DATA_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
