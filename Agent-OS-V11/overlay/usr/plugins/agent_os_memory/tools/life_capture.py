import json

from helpers.tool import Response, Tool
from usr.plugins.agent_os_memory.helpers.normalization import normalize
from usr.plugins.agent_os_memory.helpers.runtime import context_id, get_store


GUARD_KEY = "_agent_os_semantic_intake_guard"


class LifeCapture(Tool):
    async def execute(self, **kwargs):
        # The semantic intake runs before the main model. If Paul nevertheless
        # tries to call life_capture for the exact same item in the same turn,
        # do not reinforce it and falsely increment occurrences.
        guard = self.agent.get_data(GUARD_KEY) if self.agent else None
        if isinstance(guard, dict):
            wanted_kind = normalize(kwargs.get("kind", ""))
            wanted_title = normalize(kwargs.get("title", "") or kwargs.get("value", ""))
            for item in guard.get("items", []):
                if (
                    isinstance(item, dict)
                    and wanted_kind == item.get("kind")
                    and wanted_title
                    and wanted_title == item.get("title")
                ):
                    return Response(
                        message=json.dumps(
                            {
                                "operation": "already_captured_by_semantic_intake",
                                "kind": wanted_kind,
                                "title": kwargs.get("title", ""),
                            },
                            ensure_ascii=False,
                        ),
                        break_loop=False,
                    )

        kwargs.setdefault("context_id", context_id(self.agent))
        result = get_store(self.agent).capture(**kwargs)
        return Response(
            message=json.dumps(result, ensure_ascii=False, default=str),
            break_loop=False,
        )
