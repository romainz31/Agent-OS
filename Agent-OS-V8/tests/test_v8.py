from __future__ import annotations

import tempfile
import time
from datetime import date
from pathlib import Path

from agentos.agenda import AgendaStore, parse_date_reference
from agentos.db import Database
from agentos.manager import PersonalManager
from agentos.memory import MemoryStore
from agentos.missions import MissionStore


class FakeLLM:
    model = "fake"

    def health(self):
        return {"ok": True, "model": "fake"}

    def ask(self, user: str, system: str = "") -> str:
        return "Réponse fake"


class FakeLangGraph:
    def status(self):
        return {"ok": False, "enabled": False, "installed": False}

    def run(self, mission_id, objective, planner, executor, synthesizer, plan_executor=None):
        plan = planner(objective)
        results = plan_executor(plan) if plan_executor else [executor(step) for step in plan]
        return {"mission_id": mission_id, "objective": objective, "plan": plan, "results": results, "final": synthesizer(objective, results)}


class FakeMAF:
    def status(self):
        return {"ok": False, "enabled": False, "installed": False}

    def available(self):
        return False


class FakeExternal:
    configured = False

    def status(self):
        return {"configured": False, "ok": False}


class FakeIntegrations:
    def __init__(self):
        self.langgraph = FakeLangGraph()
        self.maf = FakeMAF()
        self.agent_zero = FakeExternal()
        self.openhands = FakeExternal()

    def status(self, remote_checks=False):
        return {
            "langgraph": self.langgraph.status(),
            "maf": self.maf.status(),
            "agent_zero": {"configured": False, "ok": False},
            "openhands": {"configured": False, "ok": False},
        }


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[OK] {label}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")

        memory = MemoryStore(db)
        check(memory.count() == 0, "mémoire neuve vide")
        check(memory.remember("identity.first_name", "Romain"), "écriture mémoire")
        check(memory.get("identity.first_name") == "Romain", "lecture mémoire")
        memory.remember("identity.first_name", "Paul")
        check(memory.get("identity.first_name") == "Paul", "contradiction remplace l'ancien souvenir actif")
        memory.reset()
        check(memory.count() == 0, "reset mémoire")

        today = date(2026, 9, 10)
        check(parse_date_reference("samedi", today) == date(2026, 9, 12), "résolution samedi")
        check(parse_date_reference("le 12/10/2026", today) == date(2026, 10, 12), "date explicite")
        agenda = AgendaStore(db)
        check(agenda.add(date(2026, 9, 12), "acheter du terreau"), "ajout agenda")
        check("acheter du terreau" in agenda.format_for(date(2026, 9, 12)), "lecture agenda")

        missions = MissionStore(db)
        m1 = missions.create("Tester le moteur")
        check(m1["human_id"] == "M-001", "première mission M-001")
        m2 = missions.create("Deuxième test")
        check(m2["human_id"] == "M-002", "incrément M-002")
        missions.reset()
        check(missions.count() == 0, "reset missions")

        manager = PersonalManager(db=db, llm=FakeLLM(), integrations=FakeIntegrations())
        check("ne connais pas encore" in manager.chat("comment je m'appelle ?").lower(), "Paul n'invente pas le prénom")
        check("Romain" in manager.chat("je m'appelle Romain"), "Paul apprend le prénom")
        check("Romain" in manager.chat("comment je m'appelle ?"), "Paul restitue le prénom")
        manager.chat("samedi je dois nettoyer le filtre")
        check("nettoyer le filtre" in manager.chat("qu'ai-je prévu samedi ?"), "agenda naturel")
        manager.agenda.add(date(2026, 10, 12), "changer l'eau de l'aquarium")
        check("changer l'eau" in manager.chat("et le 12/10/2026 ?"), "suivi contextuel de date")

        launched = manager.runner.launch("faire un test simple")
        check(launched["human_id"] == "M-001", "numérotation repart après reset")
        deadline = time.time() + 3
        while time.time() < deadline:
            current = manager.missions.get("M-001") or {}
            if current.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        check((manager.missions.get("M-001") or {}).get("status") == "completed", "mission fallback exécutable")

        class WorkingMAF(FakeMAF):
            def available(self):
                return True

            def status(self):
                return {"ok": True, "enabled": True, "installed": True}

            def run(self, prompt, roles=None):
                return [
                    {"agent": name, "text": f"résultat {name}"}
                    for name, _ in (roles or [])
                ]

        manager.integrations.maf = WorkingMAF()
        m_parallel = manager.missions.create("test parallèle")
        manager.missions.replace_steps(m_parallel["human_id"], [
            {"title": "A", "prompt": "A", "worker": "research"},
            {"title": "B", "prompt": "B", "worker": "review"},
        ])
        plan = [
            {"title": "A", "prompt": "A", "worker": "research", "step_index": 1},
            {"title": "B", "prompt": "B", "worker": "review", "step_index": 2},
        ]
        parallel_results = manager.runner._execute_plan(m_parallel["human_id"], "test parallèle", plan)
        check(len(parallel_results) == 2, "MAF fan-out/fan-in branché")
        check((manager.missions.get(m_parallel["human_id"]) or {}).get("backend") == "maf", "mission marque le backend MAF")

        manager.reset_all()
        check(manager.memory.count() == 0, "V8 reset: mémoire vide")
        check(manager.missions.count() == 0, "V8 reset: missions vides")
        check(manager.agenda.list_for(date(2026, 9, 12)) == [], "V8 reset: agenda vide")
        check(manager.conversation.recent() == [], "V8 reset: conversation vide")

    print("\nAgent-OS V8 : tous les tests locaux sont passés.")


if __name__ == "__main__":
    main()
