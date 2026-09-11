from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATE = (
    ROOT
    / "overlay"
    / "usr"
    / "plugins"
    / "agent_os_memory"
    / "extensions"
    / "python"
    / "_functions"
    / "agent"
    / "AgentContext"
    / "_process_chain"
    / "start"
    / "_10_personal_memory_intake.py"
)


class PersonalMemoryGateTests(unittest.TestCase):
    def test_gate_reads_implicit_process_chain_args_and_short_circuits(self):
        source = GATE.read_text(encoding="utf-8")
        self.assertIn('args = data.get("args")', source)
        self.assertIn('text = _message_text(args[2])', source)
        self.assertIn('data["result"] = result["reply"]', source)
        self.assertIn("if user is False", source)


if __name__ == "__main__":
    unittest.main()
