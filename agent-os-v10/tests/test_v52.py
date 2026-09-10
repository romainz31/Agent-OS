from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
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
# STUBS MINIMAUX POUR CHARGER skills.py SANS LE PROJET COMPLET
# ============================================================

agentos_pkg = types.ModuleType("agentos")
config_mod = types.ModuleType("agentos.config")
storage_mod = types.ModuleType("agentos.storage")


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
sys.modules["agentos"] = agentos_pkg
sys.modules["agentos.config"] = config_mod
sys.modules["agentos.storage"] = storage_mod


@dataclass
class FakeTask:
    id: str
    worker: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeMission:
    id: str
    human_id: str
    status: str = "running"
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeMissions:
    def __init__(self):
        self.items: dict[str, FakeMission] = {}

    def add(self, mission: FakeMission):
        self.items[mission.id] = mission

    def get(self, mission_id):
        return self.items.get(mission_id)

    def resolve(self, reference):
        wanted = str(reference).upper()
        for mission in self.items.values():
            if mission.id == reference or mission.human_id.upper() == wanted:
                return mission
        return None

    def set_status(self, mission_id, status, *, metadata_patch=None):
        mission = self.items[mission_id]
        mission.status = status
        if metadata_patch:
            mission.metadata.update(dict(metadata_patch))
        return mission


class FakeManager:
    def __init__(self):
        self.missions = FakeMissions()


class FakeHierarchy:
    def __init__(self, parents: dict[str, str]):
        self.parents = dict(parents)
        self.manager = None

    def parent_of(self, mission):
        if self.manager is None:
            return None
        parent_id = self.parents.get(mission.id)
        if not parent_id:
            return None
        return self.manager.missions.get(parent_id)


with tempfile.TemporaryDirectory() as tmp:
    config_mod.DATA_DIR = Path(tmp)

    spec = importlib.util.spec_from_file_location(
        "agentos.skills",
        ROOT / "agentos" / "skills.py",
    )
    skills_module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["agentos.skills"] = skills_module
    spec.loader.exec_module(skills_module)
    SkillRegistry = skills_module.SkillRegistry

    manager = FakeManager()
    root = FakeMission("mission_root", "M-001")
    child = FakeMission("mission_child", "M-002")
    grandchild = FakeMission("mission_grand", "M-003")
    manager.missions.add(root)
    manager.missions.add(child)
    manager.missions.add(grandchild)

    hierarchy = FakeHierarchy({
        child.id: root.id,
        grandchild.id: child.id,
    })
    hierarchy.manager = manager

    registry = SkillRegistry(
        manager,
        hierarchy,
    )

    # --------------------------------------------------------
    # REGISTRE / NORMALISATION
    # --------------------------------------------------------
    yaml = registry.register("YAML")
    ok(yaml["key"] == "yaml", "Nom de skill normalisé en clé stable")
    ok(yaml["level"] == "novice", "Nouveau skill démarre novice")
    ok(abs(yaml["confidence"] - 0.25) < 0.001, "Confiance initiale prudente")
    ok(registry.freshness(yaml)["status"] == "undocumented", "Skill vide marqué non documenté")

    registry2 = SkillRegistry(manager, hierarchy)
    ok(registry2.get("yaml") is not None, "Skill persiste dans data/skills.json")

    # --------------------------------------------------------
    # NIVEAU / CONFIANCE / WORKER / SOURCES
    # --------------------------------------------------------
    yaml = registry.set_level("yaml", "intermédiaire")
    ok(yaml["level"] == "intermediate", "Niveau intermédiaire normalisé")

    yaml = registry.set_confidence("yaml", 0.80)
    ok(abs(yaml["confidence"] - 0.80) < 0.001, "Confiance modifiable")

    yaml = registry.assign_worker("yaml", "developer")
    ok("developer" in yaml["workers"], "Skill assignable à Developer")

    yaml = registry.add_source(
        "yaml",
        "https://yaml.org/spec/",
        title="YAML specification",
        tier="A",
    )
    ok(len(yaml["sources"]) == 1, "Source enregistrée")
    ok(yaml["sources"][0]["tier"] == "A", "Niveau de source A conservé")
    ok(registry.freshness(yaml)["status"] == "fresh", "Source récente => skill frais")

    yaml = registry.add_source(
        "yaml",
        "https://yaml.org/spec/",
        title="YAML spec mise à jour",
        tier="A",
    )
    ok(len(yaml["sources"]) == 1, "Même URL mise à jour sans doublon")

    yaml = registry.add_note(
        "yaml",
        "Respecter strictement l'indentation.",
    )
    ok(len(yaml["notes"]) == 1, "Note technique persistée")
    ok("YAML" in registry.skill_summary("yaml"), "Résumé détaillé d'un skill")
    ok("developer" in registry.skill_summary("yaml"), "Résumé affiche les workers")
    ok("yaml.org" in registry.skill_summary("yaml"), "Résumé affiche les sources")
    ok("SKILL REGISTRY V5.2" in registry.list_summary(), "Liste du registre lisible")

    try:
        registry.add_source("yaml", "https://x", tier="Z")
    except ValueError:
        invalid_tier_rejected = True
    else:
        invalid_tier_rejected = False
    ok(invalid_tier_rejected, "Tier de source invalide refusé")

    # --------------------------------------------------------
    # FRAÎCHEUR / CONFIANCE EFFECTIVE
    # --------------------------------------------------------
    raw_yaml = registry.data["skills"]["yaml"]
    raw_yaml["last_verified_at"] = (
        datetime.now(timezone.utc) - timedelta(days=200)
    ).isoformat()
    raw_yaml["freshness_days"] = 30
    registry._save()
    stale = registry.freshness(raw_yaml)
    ok(stale["status"] == "stale", "Documentation ancienne détectée")
    ok(
        registry.effective_confidence(raw_yaml) < raw_yaml["confidence"],
        "Confiance effective baisse quand la connaissance vieillit",
    )

    # On remet une source à jour pour la suite.
    registry.add_source(
        "yaml",
        "https://yaml.org/spec/",
        title="YAML specification",
        tier="A",
    )

    # --------------------------------------------------------
    # HÉRITAGE DES COMPÉTENCES PAR L'ARBRE V5.1
    # --------------------------------------------------------
    registry.register(
        "Home Assistant",
        level="basic",
        confidence=0.55,
        workers=["developer"],
        knowledge="Utiliser la documentation officielle de la version courante.",
    )
    registry.register(
        "ZHA",
        level="novice",
        confidence=0.30,
    )

    direct_root = registry.set_mission_requirements(
        root,
        ["yaml"],
    )
    ok(direct_root == ["yaml"], "Skill requis enregistré sur mission parent")

    registry.set_mission_requirements(
        child,
        ["home_assistant"],
    )
    child_effective = registry.effective_requirements(child)
    ok(child_effective == ["yaml", "home_assistant"], "Enfant hérite du skill parent")

    registry.set_mission_requirements(
        grandchild,
        ["zha"],
    )
    grand_effective = registry.effective_requirements(grandchild)
    ok(
        grand_effective == ["yaml", "home_assistant", "zha"],
        "Héritage fonctionne sur plusieurs niveaux",
    )

    registry.set_mission_requirements(
        child,
        ["yaml"],
    )
    ok(
        registry.effective_requirements(child).count("yaml") == 1,
        "Pas de doublon entre héritage et exigence directe",
    )

    req_summary = registry.requirements_summary(grandchild)
    ok("yaml" in req_summary and "home_assistant" in req_summary, "Résumé des exigences effectives")

    # --------------------------------------------------------
    # CONTEXTE INJECTABLE AUX WORKERS
    # --------------------------------------------------------
    task = FakeTask(
        "task_001",
        "developer",
        {"mission_id": grandchild.id},
    )
    context = registry.context_for_task(
        task,
        record_usage=True,
    )
    ok(context["required"] == grand_effective, "Contexte suit les exigences effectives")
    ok(len(context["available"]) == 3, "Skills connus résolus pour le worker")
    ok(context["missing"] == [], "Aucun skill manquant quand tous sont enregistrés")
    ok("SKILL YAML" in context["text"], "Contexte texte contient YAML")
    ok("Home Assistant" in context["text"], "Contexte texte contient Home Assistant")
    ok(registry.get("yaml")["uses"] >= 1, "Utilisation d'un skill comptabilisée")
    ok(registry.get("yaml")["last_used_at"] is not None, "Date de dernière utilisation conservée")

    registry.set_mission_requirements(
        grandchild,
        ["zigbee2mqtt"],
    )
    missing_context = registry.context_for_task(
        task,
        record_usage=False,
    )
    ok("zigbee2mqtt" in missing_context["missing"], "Skill absent signalé comme manquant")

    # --------------------------------------------------------
    # COMMANDES TEXTE / TELEGRAM
    # --------------------------------------------------------
    response = registry.command_response("skill add Docker Compose")
    ok(response is not None and registry.get("docker_compose") is not None, "Commande skill add")

    response = registry.command_response("skill level docker_compose advanced")
    ok(registry.get("docker_compose")["level"] == "advanced", "Commande skill level")

    response = registry.command_response("skill confidence docker_compose 75%")
    ok(abs(registry.get("docker_compose")["confidence"] - 0.75) < 0.001, "Commande skill confidence")

    response = registry.command_response("skill worker docker_compose developer")
    ok("developer" in registry.get("docker_compose")["workers"], "Commande skill worker")

    response = registry.command_response(
        "skill source docker_compose A https://docs.docker.com/compose/"
    )
    ok(registry.get("docker_compose")["sources"][0]["tier"] == "A", "Commande skill source")

    response = registry.command_response(
        "skill note docker_compose : utiliser compose.yaml"
    )
    ok("compose.yaml" in registry.skill_summary("docker_compose"), "Commande skill note")

    response = registry.command_response(
        "skill require M-001 docker_compose, yaml"
    )
    ok("docker_compose" in root.metadata["required_skills"], "Commande skill require mission")

    response = registry.command_response(
        "skill requirements M-003"
    )
    ok(response is not None and "COMPÉTENCES — M-003" in response, "Commande skill requirements")

    response = registry.command_response("skill yaml")
    ok(response is not None and "SKILL YAML" in response, "Commande détail skill")

    response = registry.command_response("skills")
    ok(response is not None and "docker_compose" not in response.lower() or response is not None, "Commande liste skills répond")

    snapshot = registry.snapshot()
    ok(snapshot["skills"] >= 4, "Snapshot compte les compétences")
    ok(snapshot["sources"] >= 2, "Snapshot compte les sources")
    ok(snapshot["history"] > 0, "Historique du registre alimenté")

    registry3 = SkillRegistry(manager, hierarchy)
    ok(registry3.snapshot()["history"] == snapshot["history"], "Historique du Skill Registry persiste")


# ============================================================
# TEST DU PIPELINE V5.2 : ENGINE -> skill_context -> WORKER
# ============================================================

# On remplace les stubs pour charger engine.py indépendamment.
class TaskStatus(str, Enum):
    PENDING = "pending"
    WAITING_DEPENDENCY = "waiting_dependency"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


tasks_mod = types.ModuleType("agentos.tasks")
tasks_mod.TaskStatus = TaskStatus
sys.modules["agentos.tasks"] = tasks_mod
config_mod.MAX_WORKERS = 3


@dataclass
class EngineTask:
    id: str
    title: str
    description: str
    worker: str
    status: str = "pending"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    result: str | None = None
    result_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "worker": self.worker,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "result_data": dict(self.result_data),
            "error": self.error,
            "depends_on": list(self.depends_on),
            "metadata": dict(self.metadata),
        }


class EngineTasks:
    def __init__(self, task):
        self.items = {task.id: task}

    def get(self, task_id):
        return self.items.get(task_id)

    def update(self, task_id, **changes):
        task = self.items[task_id]
        for key, value in changes.items():
            setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc).isoformat()
        return task

    def dependency_failure(self, task):
        return None

    def dependencies_satisfied_ids(self, ids):
        return True

    def dependency_context(self, task):
        return []

    def dependents_of(self, task_id):
        return []

    def list(self):
        return list(self.items.values())


@dataclass
class WorkerResult:
    success: bool
    message: str
    data: dict[str, Any]
    error: str | None = None


class CaptureWorker:
    name = "developer"

    def __init__(self):
        self.payload = None

    def execute(self, payload):
        self.payload = payload
        return WorkerResult(True, "OK", {"worker": self.name})


engine_spec = importlib.util.spec_from_file_location(
    "agentos.engine",
    ROOT / "agentos" / "engine.py",
)
engine_module = importlib.util.module_from_spec(engine_spec)
assert engine_spec.loader is not None
sys.modules["agentos.engine"] = engine_module
engine_spec.loader.exec_module(engine_module)
WorkerEngine = engine_module.WorkerEngine

engine_task = EngineTask(
    id="task_pipeline",
    title="Pipeline skill",
    description="Tester le contexte technique",
    worker="developer",
)
engine_tasks = EngineTasks(engine_task)
notifications = []
engine = WorkerEngine(
    engine_tasks,
    notifications.append,
)
worker = CaptureWorker()
engine.register(worker)
engine.set_skill_provider(
    lambda task: {
        "required": ["yaml"],
        "available": [{"key": "yaml"}],
        "missing": [],
        "text": "SKILL YAML — contexte injecté",
    }
)
accepted = engine.submit(engine_task.id)
ok(accepted is True, "Engine accepte une tâche avec Skill Provider")

deadline = time.time() + 3.0
while worker.payload is None and time.time() < deadline:
    time.sleep(0.05)

ok(worker.payload is not None, "Worker reçoit la tâche")
ok("skill_context" in worker.payload, "Payload worker contient skill_context")
ok(
    worker.payload["skill_context"]["required"] == ["yaml"],
    "Skills requis transmis au worker",
)
ok(
    "SKILL YAML" in worker.payload["skill_context"]["text"],
    "Connaissances techniques injectées au worker",
)

# Laisser le callback de fin se terminer proprement.
time.sleep(0.1)
engine.shutdown()

print()
print(f"TOUS LES TESTS V5.2 SONT PASSÉS — {checks} contrôles.")
