from pathlib import Path
import unittest


ROOT = (
    Path(__file__).resolve().parents[1]
    / "overlay"
    / "usr"
    / "plugins"
    / "agent_os_memory"
    / "agents"
    / "paul"
)


class PaulProfileTests(unittest.TestCase):
    def test_local_model_contract_and_repeat_guard_are_installed(self):
        prompts = ROOT / "prompts"
        required = {
            "agent.system.main.communication.md",
            "agent.system.main.solving.md",
            "agent.system.tools.md",
            "agent.system.tool.response.md",
            "fw.msg_repeat.md",
        }
        self.assertTrue(required.issubset({path.name for path in prompts.iterdir()}))

        combined = "\n".join(
            (prompts / name).read_text(encoding="utf-8") for name in required
        )
        self.assertIn("tool_name", combined)
        self.assertIn("tool_args", combined)
        self.assertIn("life_*", combined)
        self.assertIn("response", combined)
        self.assertIn("même outil", combined)

    def test_profile_context_does_not_treat_tool_output_as_user_memory(self):
        profile = (ROOT / "agent.yaml").read_text(encoding="utf-8")
        self.assertIn("Un résultat d'outil n'est jamais une nouvelle", profile)
        self.assertIn("réenregistré", profile)


if __name__ == "__main__":
    unittest.main()
