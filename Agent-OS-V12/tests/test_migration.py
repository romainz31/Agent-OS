from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "overlay" / "usr" / "plugins"))
from agent_os_memory.helpers.store import PersonalMemoryStore  # noqa: E402


class MigrationTests(unittest.TestCase):
    def test_agenda_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            agenda = temp / "agenda.db"
            target = temp / "assistant.db"
            with sqlite3.connect(agenda) as db:
                db.execute(
                    """CREATE TABLE agenda_items(
                        id INTEGER PRIMARY KEY, kind TEXT, title TEXT,
                        due_date TEXT, start_time TEXT, status TEXT,
                        source_text TEXT, metadata_json TEXT, completed_at TEXT
                    )"""
                )
                db.execute(
                    "INSERT INTO agenda_items VALUES(1,'todo','nettoyer filtre','2026-09-12',NULL,'open','samedi nettoyer filtre','{}',NULL)"
                )
            command = [
                sys.executable, str(ROOT / "migration" / "migrate_v10.py"),
                "--agenda", str(agenda), "--target", str(target),
            ]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            second = subprocess.run(command, check=True, capture_output=True, text=True)
            store = PersonalMemoryStore(target)
            self.assertIn("1 éléments", first.stdout)
            self.assertIn("déjà appliquée", second.stdout)
            self.assertEqual(store.query(kinds=["task"])["found"], 1)


if __name__ == "__main__":
    unittest.main()
