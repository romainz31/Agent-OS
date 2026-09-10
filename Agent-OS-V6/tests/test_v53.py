from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
checks = 0


def ok(condition: bool, label: str) -> None:
    global checks
    if not condition:
        raise AssertionError(label)
    checks += 1
    print(f"[OK] {label}")


# ============================================================
# STUBS POUR CHARGER specialists.py INDÉPENDAMMENT
# ============================================================
agentos_pkg = types.ModuleType("agentos")
config_mod = types.ModuleType("agentos.config")
storage_mod = types.ModuleType("agentos.storage")
sys.modules["agentos"] = agentos_pkg
sys.modules["agentos.config"] = config_mod
sys.modules["agentos.storage"] = storage_mod


class JsonStore:
    def __init__(self, path, default):
        self.path = Path(path)
        self.default = default

    def load(self):
        if not self.path.exists():
            return json.loads(json.dumps(self.default))
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return json.loads(json.dumps(self.default))

    def save(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


storage_mod.JsonStore = JsonStore


@dataclass
class FakeMission:
    id: str
    human_id: str
    task_ids: list[str] = field(default_factory=list)


@dataclass
class FakeTask:
    id: str
    worker: str
    description: str = "Tâche test"
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeMissions:
    def __init__(self, missions):
        self.items = {m.id: m for m in missions}

    def get(self, mission_id):
        return self.items.get(mission_id)

    def resolve(self, reference):
        wanted = str(reference or "").upper()
        for mission in self.items.values():
            if mission.id == reference or mission.human_id.upper() == wanted:
                return mission
        return None


class FakeTasks:
    def __init__(self, tasks):
        self.items = {t.id: t for t in tasks}

    def get(self, task_id):
        return self.items.get(task_id)


class FakeEngine:
    def __init__(self):
        self.running = {}
        import threading
        self.lock = threading.RLock()


class FakeManager:
    def __init__(self, missions, tasks):
        self.missions = FakeMissions(missions)
        self.tasks = FakeTasks(tasks)
        self.engine = FakeEngine()


class FakeSkills:
    def __init__(self, contexts):
        self.contexts = contexts

    def context_for_task(self, task, *, record_usage=False):
        task_id = task.get("id") if isinstance(task, dict) else task.id
        return json.loads(json.dumps(self.contexts.get(task_id, {
            "required": [],
            "available": [],
            "missing": [],
            "text": "",
        })))


class CaptureLLM:
    def __init__(self):
        self.calls = []

    def chat(self, user: str, system: str = "") -> str:
        self.calls.append({"user": user, "system": system})
        return "OK"


@dataclass
class FakeResult:
    success: bool
    message: str
    data: dict[str, Any]
    error: str | None = None


class FakeDeveloper:
    name = "developer"

    def __init__(self):
        self.llm = CaptureLLM()
        self.received = None

    def execute(self, task):
        self.received = json.loads(json.dumps(task))
        answer = self.llm.chat(
            "PROMPT DEVELOPER",
            system="Tu es le Developer d'Agent-OS.",
        )
        return FakeResult(True, answer, {"worker": self.name})


with tempfile.TemporaryDirectory() as tmp:
    config_mod.DATA_DIR = Path(tmp)

    spec = importlib.util.spec_from_file_location(
        "agentos.specialists",
        ROOT / "agentos" / "specialists.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["agentos.specialists"] = module
    spec.loader.exec_module(module)

    SpecialistManager = module.SpecialistManager
    SpecializedWorkerAdapter = module.SpecializedWorkerAdapter
    SpecialistLLMProxy = module.SpecialistLLMProxy

    mission = FakeMission("mission_1", "M-001", ["task_dev"])
    task = FakeTask(
        "task_dev",
        "developer",
        "Crée workspace/automation.yaml",
        {"mission_id": mission.id, "original_message": "Crée workspace/automation.yaml"},
    )

    yaml_skill = {
        "key": "yaml",
        "name": "YAML",
        "level": "intermediate",
        "confidence": 0.80,
        "effective_confidence": 0.80,
        "freshness": {"status": "fresh", "age_days": 0, "max_days": 90},
        "workers": ["developer"],
        "sources": [{"tier": "A", "url": "https://yaml.org/spec/"}],
        "knowledge": "Indentation avec espaces.",
        "notes": [],
    }
    contexts = {
        "task_dev": {
            "required": ["yaml"],
            "available": [yaml_skill],
            "missing": [],
            "text": (
                "SKILL YAML (yaml)\n"
                "niveau=intermédiaire\n"
                "confiance_effective=0.80\n"
                "SOURCES:\n- [A] YAML specification — https://yaml.org/spec/"
            ),
        }
    }
    skills = FakeSkills(contexts)
    manager = FakeManager([mission], [task])
    specialists = SpecialistManager(skills, manager)

    # --------------------------------------------------------
    # PROFIL DYNAMIQUE
    # --------------------------------------------------------
    profile = specialists.build_profile("developer", task)
    ok(profile["activated"] is True, "Mission avec skill requis active un spécialiste")
    ok(profile["name"] == "YAML Developer", "Nom dynamique YAML Developer")
    ok(profile["worker"] == "developer", "Worker de base conservé")
    ok(profile["required"] == ["yaml"], "Skill requis conservé dans le profil")
    ok(len(profile["skills"]) == 1, "Skill compatible activé")
    ok(profile["missing"] == [], "Aucun faux skill manquant")
    ok(profile["unassigned"] == [], "Skill attribué au Developer reconnu")
    ok("PROFIL SPÉCIALISTE TEMPORAIRE" in profile["system_prompt"], "Prompt spécialiste construit")
    ok("YAML Developer" in profile["system_prompt"], "Rôle dynamique présent dans le prompt")
    ok("yaml.org/spec" in profile["system_prompt"], "Documentation du Skill Registry transmise")
    ok("sources de niveau A puis B" in profile["system_prompt"], "Hiérarchie des sources rappelée")

    # --------------------------------------------------------
    # ADAPTER : ENRICHIT LE SYSTEM PROMPT, PAS LA DEMANDE
    # --------------------------------------------------------
    worker = FakeDeveloper()
    adapter = SpecializedWorkerAdapter(worker, specialists)
    original_payload = {
        "id": task.id,
        "worker": task.worker,
        "description": task.description,
        "metadata": dict(task.metadata),
        "skill_context": contexts["task_dev"],
    }
    frozen_payload = json.loads(json.dumps(original_payload))
    result = adapter.execute(original_payload)

    ok(result.success is True, "Worker spécialisé conserve le résultat du worker de base")
    ok(original_payload == frozen_payload, "Payload original non modifié par la spécialisation")
    ok(worker.received["metadata"]["original_message"] == "Crée workspace/automation.yaml", "Demande originale intacte côté Developer")
    ok(len(worker.llm.calls) == 1, "LLM appelé une seule fois")
    system = worker.llm.calls[0]["system"]
    ok("YAML Developer" in system, "LLM reçoit le profil spécialiste")
    ok("Tu es le Developer d'Agent-OS." in system, "System prompt historique conservé")
    ok("yaml.org/spec" in system, "LLM reçoit les sources techniques")
    ok("specialist_profile" in result.data, "Résultat annoté avec le profil spécialiste")
    ok(result.data["specialist_profile"]["name"] == "YAML Developer", "Profil d'exécution traçable")
    ok(worker.llm.__class__ is CaptureLLM, "LLM original restauré après exécution")

    snap = specialists.snapshot()
    ok(snap["executions"] == 1, "Exécution spécialisée historisée")
    ok(snap["recent"][-1]["success"] is True, "Succès du spécialiste historisé")

    reloaded = SpecialistManager(skills, manager)
    ok(reloaded.snapshot()["executions"] == 1, "Historique spécialistes persistant")

    # --------------------------------------------------------
    # AUCUN SKILL REQUIS => PAS DE FAUX SPÉCIALISTE
    # --------------------------------------------------------
    task_plain = FakeTask("task_plain", "developer", metadata={"mission_id": mission.id})
    manager.tasks.items[task_plain.id] = task_plain
    skills.contexts[task_plain.id] = {
        "required": [], "available": [], "missing": [], "text": ""
    }
    plain = specialists.build_profile("developer", task_plain)
    ok(plain["activated"] is False, "Pas de skill requis => worker généraliste")
    ok(plain["name"] == "Developer", "Nom généraliste conservé sans skill")

    plain_worker = FakeDeveloper()
    plain_adapter = SpecializedWorkerAdapter(plain_worker, specialists)
    plain_adapter.execute({
        "id": task_plain.id,
        "worker": "developer",
        "description": "Analyse",
        "metadata": {"mission_id": mission.id},
        "skill_context": skills.contexts[task_plain.id],
    })
    ok("PROFIL SPÉCIALISTE" not in plain_worker.llm.calls[0]["system"], "Pas d'injection spécialiste inutile")

    # --------------------------------------------------------
    # SKILL CONNU MAIS ATTRIBUÉ À UN AUTRE WORKER
    # --------------------------------------------------------
    task_tester = FakeTask("task_test", "tester", metadata={"mission_id": mission.id})
    manager.tasks.items[task_tester.id] = task_tester
    skills.contexts[task_tester.id] = contexts["task_dev"]
    tester_profile = specialists.build_profile("tester", task_tester)
    ok(tester_profile["activated"] is True, "Tester voit qu'une spécialisation est requise")
    ok(tester_profile["skills"] == [], "Tester ne s'approprie pas le skill Developer")
    ok(tester_profile["unassigned"] == ["yaml"], "Skill non attribué signalé")
    ok("spécialisation à compléter" in tester_profile["name"], "Profil incomplet nommé prudemment")
    ok("NON ATTRIBUÉES" in tester_profile["system_prompt"], "Prompt interdit de prétendre maîtriser le skill")

    # --------------------------------------------------------
    # SKILL MANQUANT / FAIBLE / PÉRIMÉ
    # --------------------------------------------------------
    task_missing = FakeTask("task_missing", "developer", metadata={"mission_id": mission.id})
    manager.tasks.items[task_missing.id] = task_missing
    skills.contexts[task_missing.id] = {
        "required": ["home_assistant"],
        "available": [],
        "missing": ["home_assistant"],
        "text": "",
    }
    missing = specialists.build_profile("developer", task_missing)
    ok(missing["missing"] == ["home_assistant"], "Skill absent conservé comme manquant")
    ok("Ne les invente pas" in missing["system_prompt"], "Skill manquant interdit à l'hallucination")

    weak_skill = dict(yaml_skill)
    weak_skill["effective_confidence"] = 0.35
    weak_skill["freshness"] = {"status": "stale", "age_days": 200, "max_days": 90}
    task_weak = FakeTask("task_weak", "developer", metadata={"mission_id": mission.id})
    manager.tasks.items[task_weak.id] = task_weak
    skills.contexts[task_weak.id] = {
        "required": ["yaml"],
        "available": [weak_skill],
        "missing": [],
        "text": "SKILL YAML périmé",
    }
    weak = specialists.build_profile("developer", task_weak)
    ok(weak["weak"] == ["yaml"], "Skill faible/périmé détecté")
    ok("CONFIANCE FAIBLE OU PÉRIMÉES" in weak["system_prompt"], "Avertissement de fraîcheur injecté")

    # --------------------------------------------------------
    # PLUSIEURS SKILLS => PROFIL COMPOSÉ
    # --------------------------------------------------------
    ha_skill = {
        "key": "home_assistant",
        "name": "Home Assistant",
        "level": "advanced",
        "confidence": 0.85,
        "effective_confidence": 0.85,
        "freshness": {"status": "fresh"},
        "workers": ["developer"],
        "sources": [],
        "knowledge": "Automations modernes.",
        "notes": [],
    }
    task_multi = FakeTask("task_multi", "developer", metadata={"mission_id": mission.id})
    manager.tasks.items[task_multi.id] = task_multi
    skills.contexts[task_multi.id] = {
        "required": ["yaml", "home_assistant"],
        "available": [yaml_skill, ha_skill],
        "missing": [],
        "text": "YAML + Home Assistant",
    }
    multi = specialists.build_profile("developer", task_multi)
    ok(multi["name"] == "YAML / Home Assistant Developer", "Profil composé avec plusieurs domaines")
    ok(len(multi["skills"]) == 2, "Deux skills compatibles activés")

    # --------------------------------------------------------
    # COMMANDES / MISSION SUMMARY
    # --------------------------------------------------------
    mission.task_ids = [task.id, task_tester.id]
    mission_text = specialists.mission_summary("M-001")
    ok("SPÉCIALISTES — M-001" in mission_text, "Résumé mission spécialiste lisible")
    ok("developer → YAML Developer" in mission_text, "Résumé montre le Developer spécialisé")
    ok("non attribués : yaml" in mission_text, "Résumé montre les gaps du Tester")
    ok("SPÉCIALISTES DYNAMIQUES V5.3" in specialists.command_response("specialists"), "Commande specialists")
    ok("SPÉCIALISTES — M-001" in specialists.command_response("specialist M-001"), "Commande specialist M-xxx")
    ok("Usage" in specialists.command_response("specialist "), "Commande spécialiste vide donne une aide")

    # --------------------------------------------------------
    # PROFIL ACTIF DÉRIVÉ DU MOTEUR
    # --------------------------------------------------------
    manager.engine.running[task.id] = object()
    active = specialists.snapshot()["active"]
    ok(any(item["task_id"] == task.id for item in active), "Spécialiste actif visible dans snapshot")

    # --------------------------------------------------------
    # PROXY LLM ISOLÉ
    # --------------------------------------------------------
    direct_llm = CaptureLLM()
    proxy = SpecialistLLMProxy(direct_llm, "SPECIAL")
    proxy.chat("hello", system="BASE")
    ok(direct_llm.calls[-1]["system"].startswith("SPECIAL"), "Proxy place le profil avant le system historique")
    ok("BASE" in direct_llm.calls[-1]["system"], "Proxy conserve le system historique")

print()
print(f"TOUS LES TESTS V5.3 SONT PASSÉS — {checks} contrôles.")
