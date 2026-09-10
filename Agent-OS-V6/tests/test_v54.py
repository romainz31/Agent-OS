from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import types
from dataclasses import dataclass, field, asdict
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
# STUBS AGENTOS
# ============================================================
agentos_pkg = types.ModuleType("agentos")
config_mod = types.ModuleType("agentos.config")
storage_mod = types.ModuleType("agentos.storage")
tasks_mod = types.ModuleType("agentos.tasks")
sys.modules["agentos"] = agentos_pkg
sys.modules["agentos.config"] = config_mod
sys.modules["agentos.storage"] = storage_mod
sys.modules["agentos.tasks"] = tasks_mod


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
config_mod.MAX_WORKERS = 3


class TaskStatus(str, Enum):
    PENDING = "pending"
    WAITING_DEPENDENCY = "waiting_dependency"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


tasks_mod.TaskStatus = TaskStatus


@dataclass
class FakeTask:
    id: str
    title: str
    description: str
    worker: str
    status: str = TaskStatus.PENDING.value
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: str | None = None
    result_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class FakeMission:
    id: str
    human_id: str
    title: str = "Mission"
    description: str = "Mission"
    status: str = "running"
    task_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FakeTasks:
    def __init__(self):
        self.items: dict[str, FakeTask] = {}
        self.counter = 0

    def add(self, task: FakeTask):
        self.items[task.id] = task
        return task

    def create(self, *, title, description, worker, depends_on=None, metadata=None):
        self.counter += 1
        task = FakeTask(
            id=f"task_auto_{self.counter}",
            title=title,
            description=description,
            worker=worker,
            depends_on=list(depends_on or []),
            metadata=dict(metadata or {}),
        )
        if task.depends_on and not self.dependencies_satisfied_ids(task.depends_on):
            task.status = TaskStatus.WAITING_DEPENDENCY.value
        self.items[task.id] = task
        return task

    def get(self, task_id):
        return self.items.get(task_id)

    def list(self):
        return list(self.items.values())

    def update(self, task_id, **changes):
        task = self.items[task_id]
        for key, value in changes.items():
            setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc).isoformat()
        return task

    def dependencies_satisfied_ids(self, ids):
        return all(
            self.items.get(task_id)
            and self.items[task_id].status == TaskStatus.COMPLETED.value
            for task_id in ids
        )

    def dependency_failure(self, task):
        for task_id in task.depends_on:
            dep = self.items.get(task_id)
            if dep is None:
                return f"Dépendance introuvable : {task_id}"
            if dep.status == TaskStatus.FAILED.value:
                return f"Dépendance échouée : {task_id}"
            if dep.status == TaskStatus.CANCELLED.value:
                return f"Dépendance annulée : {task_id}"
        return None

    def dependency_context(self, task):
        return [
            {
                "task_id": dep.id,
                "title": dep.title,
                "worker": dep.worker,
                "status": dep.status,
                "result": dep.result,
                "result_data": dep.result_data,
            }
            for task_id in task.depends_on
            for dep in [self.items.get(task_id)]
            if dep is not None
        ]

    def dependents_of(self, task_id):
        return [task for task in self.items.values() if task_id in task.depends_on]

    def recover_interrupted(self, selected):
        return []


class FakeMissions:
    def __init__(self):
        import threading
        self.lock = threading.RLock()
        self.items: dict[str, FakeMission] = {}

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _save(self):
        return None

    def add(self, mission):
        self.items[mission.id] = mission
        return mission

    def get(self, mission_id):
        return self.items.get(mission_id)

    def resolve(self, reference):
        wanted = str(reference or "").upper()
        for mission in self.items.values():
            if mission.id == reference or mission.human_id.upper() == wanted:
                return mission
        return None

    def set_status(self, mission_id, status, *, metadata_patch=None):
        mission = self.items[mission_id]
        mission.status = status
        if metadata_patch:
            mission.metadata.update(dict(metadata_patch))
        mission.updated_at = self._now()
        return mission


class FakeEngine:
    def __init__(self):
        self.submitted = []

    def submit(self, task_id):
        if task_id not in self.submitted:
            self.submitted.append(task_id)
        return True


class FakeManager:
    def __init__(self):
        self.missions = FakeMissions()
        self.tasks = FakeTasks()
        self.engine = FakeEngine()


class FakeHierarchy:
    def parent_of(self, mission):
        return None


@dataclass
class FakeResult:
    success: bool
    message: str
    data: dict[str, Any]
    error: str | None = None


class FakeResearchWorker:
    name = "researcher"

    def __init__(self):
        self.calls = []
        self.searcher = types.SimpleNamespace(
            BACKENDS=("wikipedia", "brave", "bing")
        )

    def execute(self, task):
        description = (
            task.get("description", "")
            if isinstance(task, dict)
            else task.description
        )
        self.calls.append({
            "description": str(description),
            "backends": tuple(self.searcher.BACKENDS),
        })
        metadata = task.get("metadata", {}) if isinstance(task, dict) else task.metadata
        skill = metadata.get("learning_skill")
        if skill == "yaml":
            sources = [
                {"title": "YAML Specification", "url": "https://yaml.org/spec/", "body": "spec"},
            ]
        elif skill == "home_assistant":
            sources = [
                {"title": "Home Assistant Developer Docs", "url": "https://developers.home-assistant.io/", "body": "docs"},
            ]
        elif skill == "risky":
            sources = [
                {"title": "Random Reddit thread", "url": "https://www.reddit.com/r/example/1", "body": "opinion"},
            ]
        else:
            sources = [
                {"title": "Documentation", "url": "https://docs.example.org/guide", "body": "docs"},
            ]
        return FakeResult(
            True,
            f"Synthèse technique vérifiée pour {skill} [S1].",
            {"worker": "researcher", "sources": sources},
        )


with tempfile.TemporaryDirectory() as tmp:
    config_mod.DATA_DIR = Path(tmp)

    # Modules réels V5.4
    skill_spec = importlib.util.spec_from_file_location(
        "agentos.skills", ROOT / "agentos" / "skills.py"
    )
    skill_module = importlib.util.module_from_spec(skill_spec)
    assert skill_spec.loader is not None
    sys.modules["agentos.skills"] = skill_module
    skill_spec.loader.exec_module(skill_module)
    SkillRegistry = skill_module.SkillRegistry

    learning_spec = importlib.util.spec_from_file_location(
        "agentos.learning", ROOT / "agentos" / "learning.py"
    )
    learning_module = importlib.util.module_from_spec(learning_spec)
    assert learning_spec.loader is not None
    sys.modules["agentos.learning"] = learning_module
    learning_spec.loader.exec_module(learning_module)
    SkillLearningManager = learning_module.SkillLearningManager
    LearningResearcherAdapter = learning_module.LearningResearcherAdapter

    manager = FakeManager()
    hierarchy = FakeHierarchy()
    registry = SkillRegistry(manager, hierarchy)
    learning = SkillLearningManager(manager, registry, hierarchy)

    mission = FakeMission(
        id="mission_1",
        human_id="M-001",
        description="Créer une automation Home Assistant",
    )
    manager.missions.add(mission)
    original = FakeTask(
        id="task_dev",
        title="Créer configuration",
        description="Crée workspace/configuration.yaml pour Home Assistant",
        worker="developer",
        metadata={
            "mission_id": mission.id,
            "original_message": "Crée workspace/configuration.yaml pour Home Assistant",
            "user_original_message": "Crée workspace/configuration.yaml pour Home Assistant",
        },
    )
    manager.tasks.add(original)
    mission.task_ids.append(original.id)

    # --------------------------------------------------------
    # INFÉRENCE AUTOMATIQUE
    # --------------------------------------------------------
    inferred = learning.infer_requirements(original)
    ok("yaml" in inferred, ".yaml => skill yaml détecté automatiquement")
    ok("home_assistant" in inferred, "Home Assistant détecté automatiquement")

    frigate_task = FakeTask(
        id="task_frigate",
        title="Frigate",
        description="Configurer Frigate avec MQTT",
        worker="developer",
        metadata={"mission_id": mission.id},
    )
    inferred_frigate = learning.infer_requirements(frigate_task)
    ok("frigate" in inferred_frigate, "Frigate détecté automatiquement")
    ok("mqtt" in inferred_frigate, "MQTT détecté automatiquement")

    # --------------------------------------------------------
    # QUALITÉ DES SOURCES
    # --------------------------------------------------------
    ok(
        learning.source_tier({"url": "https://yaml.org/spec/", "title": "YAML"}) == "A",
        "yaml.org classé source A",
    )
    ok(
        learning.source_tier({"url": "https://docs.vendor.example/guide", "title": "Docs"}) == "B",
        "Sous-domaine docs classé source B",
    )
    ok(
        learning.source_tier({"url": "https://www.reddit.com/r/test", "title": "Thread"}) == "C",
        "Reddit classé source C",
    )
    ok(
        learning._quality_ok([{"tier": "A", "url": "https://yaml.org/spec/"}]),
        "Une source A suffit à valider la base documentaire",
    )
    ok(
        not learning._quality_ok([{"tier": "C", "url": "https://blog.example/a"}]),
        "Une seule source C est insuffisante",
    )
    ok(
        learning._quality_ok([
            {"tier": "C", "url": "https://one.example/a"},
            {"tier": "C", "url": "https://two.example/b"},
        ]),
        "Deux sources C indépendantes sont acceptables",
    )

    bad_frigate_sources = [
        {
            "tier": "C",
            "url": "https://heritage.example/patrimoine.pdf",
            "title": "Un patrimoine pour l'avenir",
            "body": "Patrimoine culturel et musées",
        },
        {
            "tier": "C",
            "url": "https://nightlife.example/soiree",
            "title": "Les plus grandes soirées",
            "body": "Discothèque et concerts",
        },
    ]
    ok(
        not any(
            learning._source_relevant(source, "frigate")
            for source in bad_frigate_sources
        ),
        "Sources hors sujet rejetées même si plusieurs domaines sont présents",
    )
    ok(
        learning._source_relevant(
            {
                "tier": "A",
                "url": "https://docs.frigate.video/configuration/",
                "title": "Frigate configuration",
                "body": "NVR camera configuration with MQTT",
            },
            "frigate",
        ),
        "Documentation Frigate technique reconnue pertinente",
    )
    ok(
        not learning._source_relevant(
            {
                "tier": "C",
                "url": "https://history.example/frigate",
                "title": "Frigate",
                "body": "A naval warship and military vessel",
            },
            "frigate",
        ),
        "Le mot Frigate seul dans un contexte naval ne suffit pas",
    )
    ok(
        learning._knowledge_reject_reason(
            "Aucune des sources fournies ne contient d'informations pertinentes sur Frigate."
        ) is not None,
        "Synthèse explicitement non concluante détectée",
    )

    # --------------------------------------------------------
    # PRÉPARATION : LE WORKER ATTEND LE RESEARCHER
    # --------------------------------------------------------
    prepared = learning.prepare_task(original)
    ok(prepared["ready"] is False, "Skill manquant diffère le Developer")
    ok(set(prepared["skills"]) >= {"yaml", "home_assistant"}, "Deux skills manquants identifiés")
    ok(original.status == TaskStatus.WAITING_DEPENDENCY.value, "Tâche métier mise en attente de dépendance")
    ok(len(original.depends_on) == 2, "Deux tâches d'apprentissage deviennent dépendances réelles")
    learning_tasks = [manager.tasks.get(task_id) for task_id in original.depends_on]
    ok(all(task is not None for task in learning_tasks), "Tâches d'apprentissage créées")
    ok(all(task.worker == "researcher" for task in learning_tasks), "Apprentissage confié au Researcher")
    ok(all(task.metadata.get("skill_learning") for task in learning_tasks), "Tâches marquées skill_learning")
    ok(set(manager.engine.submitted) == set(original.depends_on), "Tâches Researcher envoyées au backlog")
    ok(all(task.id in mission.task_ids for task in learning_tasks), "Apprentissages rattachés à la mission pour récupération")
    ok(set(registry.effective_requirements(mission)) >= {"yaml", "home_assistant"}, "Skills inférés persistés sur la mission")

    count_before = len(manager.tasks.items)
    prepared_again = learning.prepare_task(original)
    ok(prepared_again["ready"] is False, "Deuxième préparation reste en attente")
    ok(len(manager.tasks.items) == count_before, "Aucun doublon de tâche d'apprentissage")

    concurrent = FakeTask(
        id="task_dev_2",
        title="Deuxième YAML",
        description="Crée workspace/second.yaml pour Home Assistant",
        worker="developer",
        metadata={
            "mission_id": mission.id,
            "original_message": "Crée workspace/second.yaml pour Home Assistant",
        },
    )
    manager.tasks.add(concurrent)
    mission.task_ids.append(concurrent.id)
    before_shared = len(manager.tasks.items)
    concurrent_prepare = learning.prepare_task(concurrent)
    ok(concurrent_prepare["ready"] is False, "Deuxième tâche métier attend le même apprentissage")
    ok(len(manager.tasks.items) == before_shared, "Recherche identique mutualisée dans une même mission")
    ok(set(concurrent.depends_on) == set(original.depends_on), "Deux tâches métier partagent les dépendances learning")

    # --------------------------------------------------------
    # RESEARCHER -> SKILL REGISTRY
    # --------------------------------------------------------
    fake_research_worker = FakeResearchWorker()
    researcher = LearningResearcherAdapter(fake_research_worker, learning)
    for learn_task in learning_tasks:
        result = researcher.execute(learn_task.to_dict())
        ok(result.success is True, f"Apprentissage {learn_task.metadata['learning_skill']} validé")
        manager.tasks.update(
            learn_task.id,
            status=TaskStatus.COMPLETED.value,
            result=result.message,
            result_data=result.data,
        )

    ok(
        all(
            "Apprends la compétence technique" not in call["description"]
            for call in fake_research_worker.calls
        ),
        "Le moteur Web reçoit une requête learning concise, pas la grosse consigne métier",
    )
    ok(
        all(
            call["backends"] and call["backends"][0] == "brave"
            for call in fake_research_worker.calls
        ),
        "Learning privilégie les moteurs Web avant Wikipedia",
    )
    ok(
        fake_research_worker.searcher.BACKENDS
        == ("wikipedia", "brave", "bing"),
        "Ordre normal des backends restauré après apprentissage",
    )

    yaml = registry.get("yaml")
    home_assistant = registry.get("home_assistant")
    ok(yaml is not None, "YAML créé automatiquement dans le Skill Registry")
    ok(home_assistant is not None, "Home Assistant créé automatiquement dans le Skill Registry")
    ok("developer" in yaml["workers"], "YAML appris pour Developer")
    ok("developer" in home_assistant["workers"], "Home Assistant appris pour Developer")
    ok(yaml["sources"][0]["tier"] == "A", "Source YAML conserve le tier A")
    ok(home_assistant["sources"][0]["tier"] == "A", "Source Home Assistant conserve le tier A")
    ok("Synthèse technique" in yaml["knowledge"], "Synthèse Researcher devient connaissance persistante")
    ok(float(yaml["confidence"]) >= 0.60, "Confiance autonome reste prudente mais exploitable")
    ok(yaml["level"] in {"basic", "intermediate"}, "Researcher ne s'auto-proclame pas expert")

    ready_after = learning.prepare_task(original)
    ok(ready_after["ready"] is True, "Developer peut reprendre après apprentissage")
    ok(original.metadata.get("skill_learning_pending") is False, "État d'attente learning nettoyé")

    # --------------------------------------------------------
    # TRANSFERT INTER-WORKERS SANS NOUVELLE RECHERCHE
    # --------------------------------------------------------
    tester = FakeTask(
        id="task_test",
        title="Tester YAML",
        description="Vérifie workspace/configuration.yaml pour Home Assistant",
        worker="tester",
        metadata={"mission_id": mission.id, "original_message": "Vérifie workspace/configuration.yaml"},
    )
    manager.tasks.add(tester)
    mission.task_ids.append(tester.id)
    before_transfer_count = len(manager.tasks.items)
    tester_ready = learning.prepare_task(tester)
    ok(tester_ready["ready"] is True, "Tester réutilise les skills fiables existants")
    ok("tester" in registry.get("yaml")["workers"], "YAML transféré automatiquement au Tester")
    ok("tester" in registry.get("home_assistant")["workers"], "Home Assistant transféré automatiquement au Tester")
    ok(len(manager.tasks.items) == before_transfer_count, "Transfert fiable sans nouvelle recherche Web")

    # --------------------------------------------------------
    # RAFRAÎCHISSEMENT D'UN SKILL PÉRIMÉ
    # --------------------------------------------------------
    raw_yaml = registry.data["skills"]["yaml"]
    raw_yaml["last_verified_at"] = (
        datetime.now(timezone.utc) - timedelta(days=200)
    ).isoformat()
    raw_yaml["freshness_days"] = 30
    registry._save()
    refresh_task = FakeTask(
        id="task_refresh",
        title="Modifier YAML",
        description="Modifie workspace/refresh.yaml",
        worker="developer",
        metadata={"mission_id": mission.id, "original_message": "Modifie workspace/refresh.yaml"},
    )
    manager.tasks.add(refresh_task)
    mission.task_ids.append(refresh_task.id)
    refresh = learning.prepare_task(refresh_task)
    ok(refresh["ready"] is False, "Skill périmé déclenche un rafraîchissement Researcher")
    ok("yaml" in refresh["skills"], "YAML périmé identifié comme besoin de refresh")

    # --------------------------------------------------------
    # SÉCURITÉ : UNE SOURCE C ISOLÉE NE DEVIENT PAS UN SKILL
    # --------------------------------------------------------
    risky = FakeTask(
        id="task_risky_learning",
        title="Apprentissage risky",
        description="Recherche risky",
        worker="researcher",
        metadata={
            "mission_id": mission.id,
            "skill_learning": True,
            "learning_skill": "risky",
            "learning_for_worker": "developer",
        },
    )
    manager.tasks.add(risky)
    risky_result = researcher.execute(risky.to_dict())
    ok(risky_result.success is False, "Source C isolée refuse l'apprentissage")
    ok(registry.get("risky") is None, "Skill douteux non ajouté au registre")
    ok(
        "aucune source pertinente" in str(risky_result.error)
        or "qualité des sources" in str(risky_result.error),
        "Erreur de qualité/pertinence explicite",
    )

    # --------------------------------------------------------
    # CORRECTIF V5.4.1 : SOURCES HORS SUJET / SKILL EMPOISONNÉ
    # --------------------------------------------------------
    poisoned_task = FakeTask(
        id="task_poisoned_learning",
        title="Apprentissage Frigate raté",
        description="Recherche Frigate",
        worker="researcher",
        metadata={
            "mission_id": mission.id,
            "skill_learning": True,
            "learning_skill": "frigate_bad",
            "learning_for_worker": "developer",
        },
    )
    manager.tasks.add(poisoned_task)
    poisoned_result = FakeResult(
        True,
        (
            "Je suis désolé, mais aucune des sources fournies ne contient "
            "d'informations pertinentes sur frigate_bad."
        ),
        {
            "sources": [
                {
                    "title": "Frigate bad random page",
                    "url": "https://one.example/frigate_bad",
                    "body": "configuration technique random",
                },
                {
                    "title": "Frigate bad random guide",
                    "url": "https://two.example/frigate_bad",
                    "body": "configuration technique random",
                },
            ]
        },
    )
    try:
        learning.commit_learning(poisoned_task, poisoned_result)
        poisoned_rejected = False
    except RuntimeError as exc:
        poisoned_rejected = "synthèse Researcher" in str(exc)
    ok(poisoned_rejected, "Synthèse Researcher négative interdit toute promotion du skill")
    ok(registry.get("frigate_bad") is None, "Skill non conclu probant absent du registre")

    legacy = registry.register(
        "Frigate Legacy",
        level="intermediate",
        confidence=0.82,
        workers=["developer"],
        knowledge=(
            "Aucune des sources fournies ne contient d'informations pertinentes "
            "sur Frigate Legacy."
        ),
    )
    registry.data["skills"][legacy["key"]]["tags"] = ["autonomous_learning"]
    registry.data["skills"][legacy["key"]]["sources"] = [
        {
            "url": "https://heritage.example/patrimoine",
            "title": "Patrimoine",
            "tier": "C",
        }
    ]
    registry._save()
    quarantined_count = learning._quarantine_invalid_existing_skills()
    legacy_after = registry.get(legacy["key"])
    ok(quarantined_count >= 1, "Migration détecte un ancien apprentissage empoisonné")
    ok(float(legacy_after["confidence"]) <= 0.20, "Ancien skill empoisonné perd sa confiance")
    ok(legacy_after["level"] == "novice", "Ancien skill empoisonné est rétrogradé")
    ok("quarantined_learning" in legacy_after["tags"], "Ancien skill empoisonné marqué en quarantaine")

    # --------------------------------------------------------
    # APPRENTISSAGE NE DÉGRADE PAS UN SKILL MANUEL MEILLEUR
    # --------------------------------------------------------
    manual = registry.register(
        "Manual Expert",
        level="advanced",
        confidence=0.90,
        workers=["developer"],
        knowledge="Connaissance manuelle fiable",
    )
    updated = registry.apply_learning(
        "manual_expert",
        knowledge="Nouvelle vérification automatique",
        sources=[{"url": "https://docs.example.org/", "title": "Docs", "tier": "B"}],
        worker="developer",
        confidence=0.65,
        level="basic",
        mission="M-001",
    )
    ok(updated["level"] == "advanced", "Apprentissage autonome ne baisse pas un niveau supérieur")
    ok(abs(float(updated["confidence"]) - 0.90) < 0.001, "Apprentissage autonome ne baisse pas une confiance supérieure")

    # --------------------------------------------------------
    # RESEARCHER / OFF / STATUS
    # --------------------------------------------------------
    research_normal = FakeTask(
        id="task_research_normal",
        title="Recherche Frigate",
        description="Recherche Frigate",
        worker="researcher",
        metadata={"mission_id": mission.id},
    )
    manager.tasks.add(research_normal)
    ok(learning.prepare_task(research_normal)["ready"] is True, "Researcher normal n'est pas précédé d'une recherche sur sa recherche")

    ok("APPRENTISSAGE AUTONOME V5.4" in learning.summary(), "Résumé learning disponible")
    ok("HISTORIQUE APPRENTISSAGE V5.4" in learning.history_summary(), "Historique learning disponible")
    ok(learning.command_response("learning off") is not None, "Commande learning off")
    disabled_task = FakeTask(
        id="task_disabled",
        title="Docker",
        description="Crée Dockerfile",
        worker="developer",
        metadata={"mission_id": mission.id},
    )
    manager.tasks.add(disabled_task)
    count_disabled = len(manager.tasks.items)
    ok(learning.prepare_task(disabled_task)["ready"] is True, "Learning désactivé ne bloque pas les workers")
    ok(len(manager.tasks.items) == count_disabled, "Learning off ne crée aucune recherche")
    ok(learning.command_response("learning on") is not None, "Commande learning on")
    ok(learning.snapshot()["learned"] >= 2, "Snapshot compte les skills appris")
    ok(learning.snapshot()["failed"] >= 1, "Snapshot compte les apprentissages refusés")

    # --------------------------------------------------------
    # HOOK MOTEUR : PREPARATION AVANT RUNNING
    # --------------------------------------------------------
    engine_spec = importlib.util.spec_from_file_location(
        "agentos.engine", ROOT / "agentos" / "engine.py"
    )
    engine_module = importlib.util.module_from_spec(engine_spec)
    assert engine_spec.loader is not None
    sys.modules["agentos.engine"] = engine_module
    engine_spec.loader.exec_module(engine_module)
    WorkerEngine = engine_module.WorkerEngine

    class EngineWorker:
        name = "developer"
        def __init__(self):
            self.calls = 0
        def execute(self, payload):
            self.calls += 1
            return FakeResult(True, "OK", {"worker": self.name})

    engine_tasks = FakeTasks()
    engine_task = FakeTask(
        id="task_engine",
        title="Engine",
        description="Engine",
        worker="developer",
    )
    engine_tasks.add(engine_task)
    notifications = []
    engine = WorkerEngine(engine_tasks, notifications.append)
    engine_worker = EngineWorker()
    engine.register(engine_worker)

    def defer_provider(task):
        engine_tasks.update(
            task.id,
            status=TaskStatus.WAITING_DEPENDENCY.value,
        )
        return {"ready": False, "reason": "learning"}

    engine.set_preparation_provider(defer_provider)
    ok(engine.submit(engine_task.id) is True, "Moteur accepte la tâche avant préparation")
    time.sleep(0.3)
    ok(engine_worker.calls == 0, "Provider V5.4 diffère le worker avant RUNNING")
    ok(engine_task.status == TaskStatus.WAITING_DEPENDENCY.value, "Statut différé conservé")

    engine_tasks.update(engine_task.id, status=TaskStatus.PENDING.value)
    engine.set_preparation_provider(lambda task: {"ready": True})
    ok(engine.submit(engine_task.id) is True, "Tâche resoumise après préparation")
    deadline = time.time() + 3
    while engine_worker.calls < 1 and time.time() < deadline:
        time.sleep(0.05)
    ok(engine_worker.calls == 1, "Worker démarre une fois la préparation validée")
    deadline = time.time() + 3
    while engine_task.status != TaskStatus.COMPLETED.value and time.time() < deadline:
        time.sleep(0.05)
    ok(engine_task.status == TaskStatus.COMPLETED.value, "Tâche termine normalement après learning")
    engine.shutdown()

print("\n" + "=" * 68)
print(f"TOUS LES TESTS V5.4.1 SONT PASSÉS — {checks} contrôles.")
print("=" * 68)
