from __future__ import annotations

from agentos.config import (
    AGENT_ZERO_API_KEY,
    AGENT_ZERO_URL,
    LANGGRAPH_DB_PATH,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OPENHANDS_API_KEY,
    OPENHANDS_URL,
    USE_LANGGRAPH,
    USE_MAF,
)
from agentos.integrations.agent_zero import AgentZeroBridge
from agentos.integrations.langgraph_engine import LangGraphEngine
from agentos.integrations.maf_parallel import MAFParallel
from agentos.integrations.openhands import OpenHandsBridge


class IntegrationRegistry:
    def __init__(self) -> None:
        self.agent_zero = AgentZeroBridge(AGENT_ZERO_URL, AGENT_ZERO_API_KEY)
        self.langgraph = LangGraphEngine(LANGGRAPH_DB_PATH, enabled=USE_LANGGRAPH)
        self.maf = MAFParallel(enabled=USE_MAF, ollama_host=OLLAMA_HOST, ollama_model=OLLAMA_MODEL)
        self.openhands = OpenHandsBridge(OPENHANDS_URL, OPENHANDS_API_KEY)

    def status(self, remote_checks: bool = False) -> dict:
        result = {
            "langgraph": self.langgraph.status(),
            "maf": self.maf.status(),
            "agent_zero": {"configured": self.agent_zero.configured, "mode": "external-api"},
            "openhands": {"configured": self.openhands.configured, "mode": "agent-server", "auto_delegate": False},
        }
        if remote_checks:
            result["agent_zero"] = self.agent_zero.status()
            result["openhands"] = self.openhands.status()
        return result
