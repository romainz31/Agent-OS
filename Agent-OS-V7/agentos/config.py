from __future__ import annotations
import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("AGENTOS_DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
WORKSPACE_DIR = Path(os.getenv("AGENTOS_WORKSPACE_DIR", str(BASE_DIR / "workspace"))).expanduser().resolve()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
MAX_WORKERS = int(os.getenv("AGENT_OS_MAX_WORKERS", "3"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
