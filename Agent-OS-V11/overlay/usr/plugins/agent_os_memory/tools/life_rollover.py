import json

from helpers.tool import Response, Tool
from usr.plugins.agent_os_memory.helpers.runtime import get_store


class LifeRollover(Tool):
    async def execute(self, target_date="", **kwargs):
        result = get_store(self.agent).rollover(target_date=target_date or None)
        return Response(
            message=json.dumps(result, ensure_ascii=False, default=str),
            break_loop=False,
        )
