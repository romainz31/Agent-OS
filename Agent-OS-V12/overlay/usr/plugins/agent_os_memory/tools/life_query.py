import json

from helpers.tool import Response, Tool
from usr.plugins.agent_os_memory.helpers.runtime import context_id, get_store, plugin_config


class LifeQuery(Tool):
    async def execute(self, **kwargs):
        kwargs.setdefault("context_id", context_id(self.agent))
        kwargs.setdefault(
            "limit", int(plugin_config(self.agent).get("default_query_limit", 20))
        )
        result = get_store(self.agent).query(**kwargs)
        return Response(
            message=json.dumps(result, ensure_ascii=False, default=str),
            break_loop=False,
        )
