from __future__ import annotations

from typing import Any

from helpers.extension import Extension
from usr.plugins.agent_os_memory.helpers.runtime import (
    context_id,
    get_store,
    plugin_config,
)
from usr.plugins.agent_os_memory.helpers.semantic import SemanticMemoryPipeline


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    value = getattr(message, "message", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


class PersonalMemoryIntake(Extension):
    """Give Paul's personal memory first chance at ordinary user messages."""

    async def execute(self, data: dict[str, Any] | None = None, **kwargs: Any):
        if not self.agent or getattr(self.agent, "number", 0) != 0:
            return
        if not isinstance(data, dict):
            return

        # AgentContext._process_chain is an implicit extension hook. Its
        # mutable payload contains args=(context, agent, message, user).
        args = data.get("args")
        if not isinstance(args, tuple) or len(args) < 3:
            return
        user = args[3] if len(args) > 3 else True
        if user is False:
            # A subordinate response is not a new user memory.
            return
        text = _message_text(args[2])
        if not text:
            return
        pipeline = SemanticMemoryPipeline(
            get_store(self.agent), config=plugin_config(self.agent)
        )
        result = await pipeline.handle(text, context_id=context_id(self.agent))
        if not result.get("handled"):
            return
        data["result"] = result["reply"]
        # Do not let Agent Zero's main LLM see a personal-memory turn after
        # the transactional pipeline has handled it.
        data["memory_result"] = result
        data["memory_handled"] = True
        return result
