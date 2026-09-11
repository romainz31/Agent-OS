import json

from helpers.tool import Response, Tool
from usr.plugins.agent_os_memory.helpers.runtime import context_id, get_store


class LifeCapture(Tool):
    async def execute(self, **kwargs):
        kwargs.setdefault("context_id", context_id(self.agent))
        result = get_store(self.agent).capture(**kwargs)
        return Response(
            message=json.dumps(result, ensure_ascii=False, default=str),
            break_loop=False,
        )
