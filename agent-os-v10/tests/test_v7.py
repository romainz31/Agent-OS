"""Contrôles ciblés de la fondation modulaire Agent-OS V7."""

from __future__ import annotations

import time
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agentos.decision import ActionDecisionEngine
from agentos.engine import WorkerEngine
from agentos.extensions import ExtensionBus
from agentos.personal_manager import PersonalManager
from agentos.personal_profile import PersonalProfileMemory
from agentos.permissions import PermissionEngine
from agentos.tasks import TaskManager, TaskStatus
from agentos.toolkit import ToolRegistry, ToolSpec
from agentos.understanding import Understanding, UnderstandingEngine


CHECKS = 0


def check(condition, label):
    global CHECKS
    if not condition:
        raise AssertionError(label)
    CHECKS += 1
    print(f"[OK] {label}")


@dataclass
class Result:
    success: bool
    message: str
    data: dict
    error: str | None = None


class DemoWorker:
    name = "developer"

    def execute(self, task):
        return Result(True, task["description"], {"seen": task.get("v7_marker")})


class HostileUnderstandingLLM:
    """Simule précisément le mauvais classement observé avec un petit modèle."""

    def chat(self, _prompt, system=""):
        return json.dumps({
            "primary_intent": "learning",
            "conversation_goal": "none",
            "confidence": 0.99,
            "topic": "API REST Spring Boot",
            "work": {
                "requested": True,
                "explicit": True,
                "objective": "Apprendre les API REST avec Spring Boot",
                "worker": "researcher",
                "confidence": 0.99,
            },
            "learning": {
                "requested": True,
                "subject": "API REST",
                "confidence": 0.99,
            },
            "durable_items": [],
            "memory_items": [],
        })


class ProfileMemoryHarness:
    def __init__(self, root):
        self.profile = PersonalProfileMemory(Path(root) / "profile.db")

    def personal_profile_value(self, *subjects):
        return self.profile.profile_value(*subjects)

    def personal_identity_facts(self, message):
        return self.profile.explicit_identity_facts(message)

    def personal_profile_observe(self, message, understanding, decision_owner=""):
        return self.profile.ingest_understanding(
            message, understanding, decision_owner=decision_owner
        )

    def concise_summary(self):
        return self.profile.summary()

    def personal_people_status(self):
        return ""

    def personal_person_response(self, _message):
        return None

    def personal_profile_status(self):
        return self.profile.status_summary()

    def personal_profile_summary(self, category=None):
        return self.profile.summary(category)

    def personal_profile_context(self, query, limit=14):
        return self.profile.context_for(query, limit)


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def main():
    bus = ExtensionBus()
    calls = []

    bus.register("demo", lambda event: calls.append("late"), priority=200)
    bus.register("demo", lambda event: calls.append("early"), priority=10)
    bus.emit("demo", {"value": 1})
    check(calls == ["early", "late"], "Extensions exécutées par priorité")

    def broken(_event):
        raise RuntimeError("panne volontaire")

    bus.register("demo", broken, name="broken", priority=50)
    bus.emit("demo")
    check(bus.snapshot()["failure_count"] == 1, "Erreur d'extension isolée")
    check(bus.failures()[0]["extension"] == "broken", "Diagnostic d'extension conservé")

    permissions = PermissionEngine()
    registry = ToolRegistry(permissions, bus)
    registry.register(
        ToolSpec(
            name="upper",
            description="Met un texte en majuscules.",
            handler=lambda text: text.upper(),
            permissions=("read_workspace",),
            profiles=frozenset({"developer"}),
            schema={
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
        )
    )
    ok = registry.execute("upper", {"text": "v7"}, profile="developer")
    check(ok.success and ok.message == "V7", "Outil typé exécuté")
    blocked = registry.execute("upper", {"text": "v7"}, profile="researcher")
    check(blocked.error == "profile_blocked", "Outil bloqué hors profil")
    invalid = registry.execute("upper", {}, profile="developer")
    check(not invalid.success and "requis" in invalid.message, "Schéma d'arguments vérifié")
    check(
        permissions.check("create_file", profile="researcher").decision.value == "blocked",
        "Politique Researcher empêche la création de fichiers",
    )

    tasks = TaskManager()
    lifecycle = ExtensionBus()
    observed = []

    def enrich(event):
        event.data["payload"]["v7_marker"] = "extension-active"
        observed.append(event.name)

    lifecycle.register("task.before_execute", enrich)
    lifecycle.register("task.after_execute", lambda event: observed.append(event.name))
    lifecycle.register("task.submitted", lambda event: observed.append(event.name))

    engine = WorkerEngine(tasks, lambda _message: None, lifecycle)
    try:
        engine.register(DemoWorker())
        task = tasks.create(
            title="Test V7",
            description="cycle modulaire",
            worker="developer",
        )
        check(engine.submit(task.id), "Tâche V7 soumise")
        check(
            wait_for(lambda: tasks.get(task.id).status == TaskStatus.COMPLETED.value),
            "Tâche V7 terminée",
        )
        completed = tasks.get(task.id)
        check(completed.result_data["seen"] == "extension-active", "Hook enrichit le payload")
        check(
            observed == ["task.submitted", "task.before_execute", "task.after_execute"],
            "Cycle de tâche V7 complet et ordonné",
        )
    finally:
        engine.shutdown()

    # V7.0.1 — reproduction exacte du défaut de mémoire signalé. Ce test est
    # intégralement local : ni LLM réel, ni navigateur, ni moteur de recherche.
    hostile = HostileUnderstandingLLM()
    understanding_engine = UnderstandingEngine(hostile)
    identity_text = "ok je m'appelle Romain et j'habite a Brens dans le Tarn"
    parsed = understanding_engine.analyze(identity_text)
    check(not parsed.work_requested, "Identité jamais transformée en mission")
    check(not parsed.learning_requested, "Faux apprentissage LLM neutralisé")

    bad_understanding = Understanding(
        primary_intent="learning",
        confidence=0.99,
        work_requested=True,
        work_explicit=True,
        work_objective="API REST Spring Boot",
        worker="researcher",
        work_confidence=0.99,
        learning_requested=True,
        learning_subject="API",
        learning_confidence=0.99,
        source="llm",
    )
    decision = ActionDecisionEngine(hostile).decide(identity_text, bad_understanding)
    check(decision.owner == "personal_memory", "Routeur impose la mémoire personnelle")
    check(not decision.allow_web, "Identité interdite de recherche Web")
    check(
        ActionDecisionEngine(hostile).decide(
            "bonjour, comment je mapelle?", bad_understanding
        ).owner == "personal_memory",
        "Faute 'mapelle' reconnue comme rappel d'identité",
    )
    check(
        ActionDecisionEngine(hostile).decide(
            "dis moi ce que tu possede en memmoire", bad_understanding
        ).owner == "personal_memory",
        "Faute 'memmoire' reconnue comme lecture locale",
    )

    with tempfile.TemporaryDirectory(prefix="agentos-v701-") as directory:
        harness = object.__new__(PersonalManager)
        harness.memory = ProfileMemoryHarness(directory)

        unknown = harness._v65_profile_response("bonjour, comment je mapelle?")
        check("ne connais pas" in unknown.lower(), "Prénom absent annoncé sans invention")

        empty = harness._v65_profile_response("dis moi ce que tu possede en memmoire")
        check("aucune information" in empty.lower(), "Mémoire vide annoncée explicitement")

        harness.memory.personal_profile_observe(
            identity_text, bad_understanding, decision_owner=decision.owner
        )
        acknowledgement = harness._v65_profile_response(identity_text)
        check(
            "Romain" in acknowledgement and "Brens dans le Tarn" in acknowledgement,
            "Prénom et domicile enregistrés depuis le texte brut",
        )
        recalled_name = harness._v65_profile_response("comment je m'appelle ?")
        recalled_home = harness._v65_profile_response("où est-ce que j'habite ?")
        check("Romain" in recalled_name, "Prénom rappelé fidèlement")
        check("Brens dans le Tarn" in recalled_home, "Domicile rappelé fidèlement")

    print(f"\nTOUS LES TESTS V7 SONT PASSÉS — {CHECKS} contrôles.")


if __name__ == "__main__":
    main()
