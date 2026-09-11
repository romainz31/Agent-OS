from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "overlay" / "usr" / "plugins"))

from agent_os_memory.helpers.semantic import SemanticMemoryPipeline  # noqa: E402
from agent_os_memory.helpers.store import PersonalMemoryStore  # noqa: E402


class FakeQwen:
    def __init__(self):
        self.prompts: list[str] = []

    async def generate_json(self, prompt: str):
        self.prompts.append(prompt)
        if "Question:" in prompt or "Combien" in prompt:
            return {
                "route": "query",
                "text": "courses",
                "kinds": ["action"],
                "states": ["completed"],
                "aggregate": "count",
                "start": "2026-09-01",
                "end": "2026-09-30",
            }
        return {
            "route": "capture",
            "type": "action",
            "title": "faire des courses",
            "semantic_state": "completed",
            "location_text": "magasin",
            "date_expression": "aujourd'hui",
            "entities": [{"type": "place", "name": "magasin", "role": "location"}],
            "entity_attributes": [],
            "occurrences": 1,
        }

    async def generate_text(self, prompt: str):
        return "Tu as fait des courses une fois aujourd'hui."


class SemanticPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = datetime(2026, 9, 11, 9, 0, tzinfo=ZoneInfo("Europe/Paris"))
        self.store = PersonalMemoryStore(
            Path(self.temp.name) / "assistant.db", clock=lambda: self.now
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_async(self, value):
        return asyncio.run(value)

    def test_qwen_capture_keeps_source_state_location_and_entities(self):
        ai = FakeQwen()
        pipeline = SemanticMemoryPipeline(self.store, ai=ai)
        result = self.run_async(
            pipeline.handle("Je vais au magasin faire des courses.", context_id="chat")
        )
        self.assertTrue(result["handled"])
        record = result["operation"]["record"]
        self.assertEqual(record["source_text"], "Je vais au magasin faire des courses.")
        self.assertEqual(record["semantic_state"], "completed")
        self.assertEqual(record["location_text"], "magasin")
        stored = self.store.query(kinds=["action"])["records"][0]
        self.assertEqual(stored["entities"][0]["canonical_name"], "magasin")
        self.assertEqual(ai.prompts[0].count("Je vais au magasin"), 1)

    def test_qwen_query_uses_local_evidence_then_synthesizes(self):
        self.store.capture(
            kind="action", title="faire des courses", completed_at="2026-09-11",
            source_text="Je suis allé au magasin faire des courses.",
        )
        ai = FakeQwen()
        pipeline = SemanticMemoryPipeline(self.store, ai=ai)
        result = self.run_async(
            pipeline.handle("Combien de fois suis-je allé faire des courses ce mois-ci ?",
                            context_id="chat")
        )
        self.assertEqual(result["reply"], "Tu as fait des courses une fois aujourd'hui.")
        self.assertEqual(len(ai.prompts), 1)

    def test_count_uses_occurrences_not_rows(self):
        pipeline = SemanticMemoryPipeline(
            self.store, config={"semantic_ai_enabled": False}
        )
        self.run_async(pipeline.handle("J'ai nettoyé la cuisine.", context_id="chat"))
        self.run_async(pipeline.handle("J'ai nettoyé la cuisine.", context_id="chat"))
        result = self.run_async(
            pipeline.handle("Combien de fois ai-je nettoyé la cuisine ce mois-ci ?",
                            context_id="chat")
        )
        self.assertIn("2 fois", result["reply"])

    def test_explicit_quantity_is_counted(self):
        pipeline = SemanticMemoryPipeline(
            self.store, config={"semantic_ai_enabled": False}
        )
        self.run_async(
            pipeline.handle("J'ai nettoyé la cuisine trois fois.", context_id="chat")
        )
        result = self.store.query(
            kinds=["action"], semantic_state="completed", aggregate="count"
        )
        self.assertEqual(result["count"], 3)

    def test_missing_event_date_is_pending_then_clarification_completes_it(self):
        pipeline = SemanticMemoryPipeline(
            self.store, config={"semantic_ai_enabled": False}
        )
        first = self.run_async(
            pipeline.handle("Je vais aller à la mer.", context_id="chat")
        )
        self.assertTrue(first["pending"])
        second = self.run_async(
            pipeline.handle("Le 12/12/26.", context_id="chat")
        )
        self.assertTrue(second["handled"])
        events = self.store.query(kinds=["event"])["records"]
        self.assertEqual(events[0]["start_at"][:10], "2026-12-12")

    def test_offline_identity_and_relation_are_retrievable(self):
        pipeline = SemanticMemoryPipeline(
            self.store, config={"semantic_ai_enabled": False}
        )
        self.run_async(
            pipeline.handle("Je m'appelle Romain et j'habite à Brens.", context_id="chat")
        )
        self.run_async(
            pipeline.handle("Coralie est ma copine.", context_id="chat")
        )
        identity = self.run_async(
            pipeline.handle("Comment je m'appelle et où est-ce que j'habite ?",
                            context_id="chat")
        )
        relation = self.run_async(
            pipeline.handle("Quelle est ma relation avec Coralie ?", context_id="chat")
        )
        self.assertIn("Romain", identity["reply"])
        self.assertIn("Brens", identity["reply"])
        self.assertIn("Coralie", relation["reply"])
        self.assertIn("copine", relation["reply"])

    def test_offline_occupation_is_personal_memory_not_a_work_command(self):
        pipeline = SemanticMemoryPipeline(
            self.store, config={"semantic_ai_enabled": False}
        )
        result = self.run_async(
            pipeline.handle(
                "Je travaille dans la maintenance d'un magasin Leclerc.",
                context_id="chat",
            )
        )
        self.assertTrue(result["handled"])
        self.assertIn("emploi", result["reply"])
        facts = self.store.query(kinds=["fact"], predicate="emploi")["facts"]
        self.assertEqual(len(facts), 1)

    def test_task_is_completed_by_a_later_action(self):
        pipeline = SemanticMemoryPipeline(
            self.store, config={"semantic_ai_enabled": False}
        )
        self.run_async(
            pipeline.handle("Demain il faut que je range la chambre.", context_id="chat")
        )
        self.run_async(
            pipeline.handle("J'ai rangé la chambre.", context_id="chat")
        )
        tasks = self.store.query(kinds=["task"])["records"]
        self.assertEqual(tasks[0]["semantic_state"], "completed")
        self.assertEqual(tasks[0]["status"], "done")

    def test_entity_attribute_is_versioned(self):
        self.store.capture(
            kind="note", title="Coralie aime le bleu",
            source_text="Coralie aime le bleu.",
            entities=[{"type": "person", "name": "Coralie", "role": "subject"}],
            entity_attributes=[{
                "entity": "Coralie", "type": "person",
                "attribute": "couleur préférée", "value": "bleu",
            }],
        )
        attrs = self.store.entity_attributes(entity="Coralie")
        self.assertEqual(attrs[0]["value"], "bleu")


if __name__ == "__main__":
    unittest.main()
