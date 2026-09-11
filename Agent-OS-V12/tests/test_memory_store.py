from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "overlay" / "usr" / "plugins"))

from agent_os_memory.helpers.store import PersonalMemoryStore  # noqa: E402


class PersonalMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.current = datetime(2026, 9, 10, 9, 0, tzinfo=ZoneInfo("Europe/Paris"))
        self.store = PersonalMemoryStore(
            Path(self.temp.name) / "assistant.db",
            clock=lambda: self.current,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_repeated_action_is_reinforced_not_duplicated(self):
        first = self.store.capture(
            kind="action", title="nettoyé le filtre", source_text="J'ai nettoyé le filtre"
        )
        second = self.store.capture(
            kind="action", title="nettoyé le filtre", source_text="J'ai nettoyé le filtre"
        )
        result = self.store.query(kinds=["action"], start="2026-09-10", end="2026-09-10")
        self.assertEqual(first["operation"], "created")
        self.assertEqual(second["operation"], "reinforced")
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["occurrences"], 2)

    def test_completed_task_is_the_only_completed_record(self):
        task = self.store.capture(
            kind="task", title="nettoyer le filtre", due_at="2026-09-10",
            date_precision="day", source_text="Aujourd'hui je dois nettoyer le filtre",
        )
        done = self.store.capture(
            kind="action", title="nettoyé le filtre", source_text="J'ai nettoyé le filtre"
        )
        result = self.store.query(start="2026-09-10", end="2026-09-10")
        self.assertEqual(done["operation"], "completed_existing_task")
        self.assertEqual(done["record"]["id"], task["record"]["id"])
        self.assertEqual(done["record"]["status"], "done")
        self.assertEqual(len(result["records"]), 1)

    def test_current_fact_replaces_old_value_and_preserves_history(self):
        old = self.store.capture(
            kind="preference", title="style détaillé", subject="user",
            predicate="style de réponse", value="détaillé", source_text="Je préfère les réponses détaillées",
        )
        new = self.store.capture(
            kind="preference", title="style direct", subject="user",
            predicate="style de réponse", value="direct", source_text="Je préfère maintenant les réponses directes",
        )
        current = self.store.query(
            kinds=["preference"], subject="user", predicate="style de réponse"
        )
        all_versions = self.store.query(
            kinds=["preference"], subject="user", predicate="style de réponse",
            current_facts_only=False,
        )
        self.assertEqual([item["value"] for item in current["facts"]], ["direct"])
        self.assertEqual(len(all_versions["facts"]), 2)
        self.assertEqual(new["fact"]["supersedes_fact_id"], old["fact"]["id"])

    def test_follow_up_changes_date_but_keeps_previous_intent(self):
        self.store.capture(
            kind="appointment", title="dentiste", start_at="2026-10-10T15:00:00",
            date_precision="exact", source_text="Dentiste le 10 octobre à 15h",
        )
        self.store.capture(
            kind="appointment", title="contrôle médical", start_at="2026-10-12T11:00:00",
            date_precision="exact", source_text="Contrôle médical le 12 octobre à 11h",
        )
        first = self.store.query(
            kinds=["appointment"], start="2026-10-10", end="2026-10-10",
            context_id="chat-a",
        )
        follow = self.store.query(
            start="2026-10-12", end="2026-10-12", follow_up=True,
            context_id="chat-a",
        )
        self.assertEqual([item["title"] for item in first["records"]], ["dentiste"])
        self.assertEqual([item["title"] for item in follow["records"]], ["contrôle médical"])
        self.assertEqual(follow["query"]["kinds"], ["appointment"])

    def test_follow_up_state_is_isolated_per_chat(self):
        self.store.capture(
            kind="task", title="arroser les plantes", due_at="2026-09-12",
            date_precision="day", source_text="Arroser les plantes samedi",
        )
        self.store.query(kinds=["task"], context_id="chat-a")
        other = self.store.query(follow_up=True, context_id="chat-b")
        self.assertEqual(other["query"]["kinds"], [])

    def test_query_can_filter_people_and_places(self):
        self.store.capture(
            kind="event", title="chercher Coralie à l'aéroport",
            start_at="2026-09-12T18:00:00", date_precision="exact",
            source_text="Samedi je vais chercher Coralie à l'aéroport",
            entities=[
                {"type": "person", "name": "Coralie", "role": "with"},
                {"type": "place", "name": "aéroport", "role": "location"},
            ],
        )
        with_coralie = self.store.query(entity="Coralie", entity_type="person")
        at_airport = self.store.query(entity="aéroport", entity_type="place")
        self.assertEqual(with_coralie["records"][0]["title"], "chercher Coralie à l'aéroport")
        self.assertEqual(at_airport["records"][0]["entities"][0]["entity_type"], "person")

    def test_rollover_moves_only_explicit_overdue_tasks(self):
        dated = self.store.capture(
            kind="task", title="barbe", due_at="2026-09-09",
            date_precision="day", source_text="Mercredi faire la barbe",
        )
        self.store.capture(
            kind="task", title="changer une ampoule", due_at="2026-09-09",
            date_precision="unknown", source_text="À faire : changer une ampoule",
        )
        self.store.capture(
            kind="appointment", title="dentiste", start_at="2026-09-09T15:00:00",
            date_precision="exact", source_text="Dentiste mercredi à 15h",
        )
        result = self.store.rollover(target_date="2026-09-10")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["moved"][0]["id"], dated["record"]["id"])
        self.assertTrue(result["moved"][0]["due_at"].startswith("2026-09-10"))

    def test_ambiguous_update_requires_user_choice(self):
        self.store.capture(kind="task", title="nettoyer filtre aquarium", source_text="À faire")
        self.store.capture(kind="task", title="nettoyer filtre clim", source_text="À faire")
        result = self.store.update(query="nettoyer filtre", action="complete")
        self.assertEqual(result["operation"], "ambiguous")
        self.assertTrue(result["requires_user_choice"])
        self.assertEqual(len(result["candidates"]), 2)

    def test_assistant_output_cannot_be_stored_as_user_memory(self):
        with self.assertRaises(ValueError):
            self.store.capture(
                kind="fact", title="Romain aime tout", subject="user",
                predicate="goûts", value="tout", source_role="assistant",
                source_text="Réponse de Paul",
            )

    def test_forget_is_soft_and_audited(self):
        created = self.store.capture(kind="note", title="souvenir test", source_text="Souviens-toi")
        record_id = created["record"]["id"]
        forgotten = self.store.forget(record_ids=[record_id])
        self.assertEqual(forgotten["count"], 1)
        self.assertEqual(self.store.query(text="souvenir test")["found"], 0)
        self.assertEqual(self.store.history(record_id)[-1]["action"], "forget")


if __name__ == "__main__":
    unittest.main()
