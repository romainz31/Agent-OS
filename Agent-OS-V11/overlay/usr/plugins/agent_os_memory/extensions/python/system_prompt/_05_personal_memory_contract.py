from agent import LoopData
from helpers.extension import Extension


class PersonalMemoryContract(Extension):
    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs,
    ):
        if not self.agent:
            return
        system_prompt.insert(
            0,
            self.agent.read_prompt("agent.system.personal_memory.md"),
        )
