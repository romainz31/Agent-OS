from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "overlay" / "usr" / "plugins" / "agent_os_memory"


class AgentZeroContractTests(unittest.TestCase):
    def test_personal_memory_plugin_is_always_enabled(self):
        manifest = (PLUGIN / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("version: 11.1.0", manifest)
        self.assertIn("always_enabled: true", manifest)

    def test_paul_profile_requires_capture_before_personal_reply(self):
        prompt = (
            PLUGIN / "agents" / "paul" / "prompts" /
            "agent.system.main.specifics.md"
        ).read_text(encoding="utf-8")
        self.assertIn("utilise `life_capture`", prompt)
        self.assertIn("Ne réponds jamais", prompt)
        self.assertIn("task_bucket=backlog", prompt)

    def test_capture_prompt_preserves_source_and_occurrences(self):
        prompt = (
            PLUGIN / "prompts" / "agent.system.tool.life_capture.md"
        ).read_text(encoding="utf-8")
        self.assertIn("source_text", prompt)
        self.assertIn("metadata", prompt)
        self.assertIn("occurrence", prompt)

    def test_global_memory_contract_is_injected_by_an_extension(self):
        prompt = (PLUGIN / "prompts" / "agent.system.personal_memory.md").read_text(
            encoding="utf-8"
        )
        extension = (
            PLUGIN / "extensions" / "python" / "system_prompt" /
            "_05_personal_memory_contract.py"
        ).read_text(encoding="utf-8")
        self.assertIn("life_capture", prompt)
        self.assertIn("life_query", prompt)
        self.assertIn("read_prompt(\"agent.system.personal_memory.md\")", extension)


if __name__ == "__main__":
    unittest.main()
