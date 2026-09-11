from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


GATE = Path(__file__).resolve().parents[1] / "overlay" / "usr" / "extensions" / "python" / "_functions" / "agent" / "AgentContext" / "_process_chain" / "start" / "_05_agent_os_personal_intake.py"


class GateContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_gate_short_circuits_process_chain_for_handled_memory_turn(self):
        # Stubs minimaux : on teste le contrat du gate sans avoir besoin du runtime
        # Agent Zero complet dans le Python Windows de l'utilisateur.
        agent_mod = types.ModuleType("agent")
        class LoopData:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        agent_mod.LoopData = LoopData
        sys.modules["agent"] = agent_mod

        helpers = types.ModuleType("helpers")
        helpers.__path__ = []
        sys.modules["helpers"] = helpers

        ext_mod = types.ModuleType("helpers.extension")
        class Extension:
            def __init__(self, agent=None, **kwargs):
                self.agent = agent
        ext_mod.Extension = Extension
        sys.modules["helpers.extension"] = ext_mod

        llm_mod = types.ModuleType("helpers.llm_result")
        class LLMResult:
            @staticmethod
            def non_llm():
                return object()
        llm_mod.LLMResult = LLMResult
        sys.modules["helpers.llm_result"] = llm_mod

        intake_mod = types.ModuleType("usr.plugins.agent_os_memory.helpers.intake")
        async def semantic_intake(**kwargs):
            return SimpleNamespace(status="captured", raw_plan={"mode": "capture"})
        def render_direct_reply(outcome):
            return "D'accord, je retiens que tu habites à Brens."
        intake_mod.semantic_intake = semantic_intake
        intake_mod.render_direct_reply = render_direct_reply
        sys.modules["usr.plugins.agent_os_memory.helpers.intake"] = intake_mod

        runtime_mod = types.ModuleType("usr.plugins.agent_os_memory.helpers.runtime")
        runtime_mod.context_id = lambda agent: "chat-test"
        runtime_mod.get_store = lambda agent: object()
        runtime_mod.plugin_config = lambda agent: {"semantic_intake_enabled": True, "semantic_intake_debug": False}
        temp = tempfile.TemporaryDirectory()
        runtime_mod.data_path = lambda: Path(temp.name) / "assistant.db"
        sys.modules["usr.plugins.agent_os_memory.helpers.runtime"] = runtime_mod

        spec = importlib.util.spec_from_file_location("gate_v116_contract", GATE)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        class FakeHistory:
            def output_text(self, **kwargs):
                return ""

        class FakeLog:
            def __init__(self):
                self.entries = []
            def log(self, **kwargs):
                self.entries.append(kwargs)

        class FakeAgent:
            number = 0
            agent_name = "Paul"
            config = SimpleNamespace(profile="paul")
            history = FakeHistory()
            context = SimpleNamespace(log=FakeLog())
            def hist_add_user_message(self, message):
                return SimpleNamespace(id="u1")
            def hist_add_ai_response(self, reply, llm_result=None):
                return SimpleNamespace(id="a1")
            def get_chat_model(self):
                raise AssertionError("Le LLM conversationnel ne doit pas être appelé dans ce test")

        message = SimpleNamespace(message="j'habite à Brens")
        data = {"args": (SimpleNamespace(), FakeAgent(), message), "kwargs": {}}
        gate = module.AgentOSPersonalIntakeGate(agent=FakeAgent())
        await gate.execute(data=data)

        self.assertEqual(data.get("result"), "D'accord, je retiens que tu habites à Brens.")
        temp.cleanup()


if __name__ == "__main__":
    unittest.main()
