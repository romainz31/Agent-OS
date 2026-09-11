from agent import LoopData
from helpers.extension import Extension
from usr.plugins.agent_os_memory.helpers.runtime import get_store, plugin_config


class RolloverPersonalTasks(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent or self.agent.number != 0:
            return
        config = plugin_config(self.agent)
        if config.get("auto_rollover_tasks", True):
            get_store(self.agent).rollover()
