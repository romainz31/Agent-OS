from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENGINE_FILE = ROOT / "agentos" / "engine.py"


# ============================================================
# STUBS MINIMAUX POUR TESTER ENGINE.PY EN ISOLEMENT
# ============================================================


class TaskStatus(str, Enum):
    PENDING = "pending"
    WAITING_DEPENDENCY = "waiting_dependency"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str
    title: str
    description: str
    worker: str
    status: str = TaskStatus.PENDING.value
    created_at: str = "2026-09-08T20:00:00+00:00"
    updated_at: str = "2026-09-08T20:00:00+00:00"
    result: str | None = None
    result_data: dict = field(default_factory=dict)
    error: str | None = None
    depends_on: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

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


class FakeTasks:
    def __init__(self):
        self.items: dict[str, Task] = {}

    def add(self, task: Task):
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
        return []

    def dependents_of(self, task_id):
        return [
            task
            for task in self.items.values()
            if task_id in task.depends_on
        ]

    def reset_for_execution(self, task_id):
        task = self.items[task_id]
        task.status = (
            TaskStatus.PENDING.value
            if self.dependencies_satisfied_ids(task.depends_on)
            else TaskStatus.WAITING_DEPENDENCY.value
        )
        task.error = None
        return task

    def recover_interrupted(self, selected):
        recovered = []
        selected = set(selected or [])
        for task in self.items.values():
            if task.id not in selected:
                continue
            if task.status == TaskStatus.RUNNING.value:
                task.status = TaskStatus.PENDING.value
                recovered.append(task.id)
        return recovered


@dataclass
class WorkerResult:
    success: bool = True
    message: str = "ok"
    data: dict = field(default_factory=dict)
    error: str | None = None


class ControlledWorker:
    def __init__(self, name, starts, gates):
        self.name = name
        self.starts = starts
        self.gates = gates
        self.lock = threading.Lock()

    def execute(self, payload):
        task_id = payload["id"]
        with self.lock:
            self.starts.append((self.name, task_id, time.monotonic()))
        gate = self.gates.get(task_id)
        if gate is not None:
            gate.wait(timeout=5.0)
        return WorkerResult(
            True,
            "ok",
            {"worker": self.name},
        )


agentos_pkg = types.ModuleType("agentos")
agentos_pkg.__path__ = []
sys.modules["agentos"] = agentos_pkg

config_mod = types.ModuleType("agentos.config")
config_mod.MAX_WORKERS = 3
sys.modules["agentos.config"] = config_mod

tasks_mod = types.ModuleType("agentos.tasks")
tasks_mod.TaskStatus = TaskStatus
sys.modules["agentos.tasks"] = tasks_mod

spec = importlib.util.spec_from_file_location(
    "agentos.engine",
    ENGINE_FILE,
)
engine_mod = importlib.util.module_from_spec(spec)
sys.modules["agentos.engine"] = engine_mod
assert spec.loader is not None
spec.loader.exec_module(engine_mod)
WorkerEngine = engine_mod.WorkerEngine


# ============================================================
# HELPERS
# ============================================================


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


checks = []


def ok(label, condition):
    if not condition:
        raise AssertionError(label)
    checks.append(label)
    print(f"[OK] {label}")


notifications = []
tasks = FakeTasks()
starts = []
gates = {}
engine = WorkerEngine(tasks, notifications.append)

for name in ("developer", "researcher", "tester", "ai_worker"):
    engine.register(
        ControlledWorker(
            name,
            starts,
            gates,
        )
    )


# ============================================================
# 1. TROIS TYPES DE WORKERS PEUVENT TOURNER EN PARALLÈLE
# ============================================================

parallel_ids = ["dev_parallel", "research_parallel", "test_parallel"]
parallel_workers = ["developer", "researcher", "tester"]
parallel_gates = []

for task_id, worker in zip(parallel_ids, parallel_workers):
    gate = threading.Event()
    gates[task_id] = gate
    parallel_gates.append(gate)
    tasks.add(Task(task_id, task_id, task_id, worker))
    ok(f"Soumission {worker}", engine.submit(task_id))

ok(
    "Trois workers différents peuvent travailler en parallèle",
    wait_until(lambda: len(engine.running) == 3),
)

snap = engine.workload_snapshot()
ok("Capacité globale V5.0 = 3", snap["capacity"] == 3)
ok("Trois slots utilisés", snap["running"] == 3)

for gate in parallel_gates:
    gate.set()

ok(
    "Les trois tâches parallèles se terminent",
    wait_until(
        lambda: all(
            tasks.get(task_id).status == TaskStatus.COMPLETED.value
            for task_id in parallel_ids
        )
    ),
)


# ============================================================
# 2. UN SEUL DEVELOPER ACTIF + PRIORITÉ DU BACKLOG
# ============================================================

blocker_gate = threading.Event()
gates["dev_blocker"] = blocker_gate

tasks.add(Task(
    "dev_blocker",
    "Blocage Developer",
    "blocage",
    "developer",
    metadata={"schedule_priority": "normal"},
))

tasks.add(Task(
    "dev_low",
    "Basse priorité",
    "low",
    "developer",
    created_at="2026-09-08T20:01:00+00:00",
    metadata={"schedule_priority": "low"},
))

tasks.add(Task(
    "dev_critical",
    "Critique",
    "critical",
    "developer",
    created_at="2026-09-08T20:02:00+00:00",
    metadata={"schedule_priority": "critical"},
))

ok("Developer blocker soumis", engine.submit("dev_blocker"))
ok(
    "Developer blocker réellement lancé",
    wait_until(lambda: engine.is_running("dev_blocker")),
)

ok("Developer basse priorité en backlog", engine.submit("dev_low"))
ok("Developer critique en backlog", engine.submit("dev_critical"))

time.sleep(0.15)

snap = engine.workload_snapshot()
ok(
    "Un seul Developer actif malgré plusieurs missions",
    sum(
        1
        for row in snap["running_tasks"]
        if row["worker"] == "developer"
    ) == 1,
)
ok("Deux tâches Developer attendent", snap["backlog"] >= 2)

backlog_ids = [row["task_id"] for row in snap["backlog_tasks"]]
ok(
    "La tâche critique passe devant la tâche basse",
    backlog_ids.index("dev_critical") < backlog_ids.index("dev_low"),
)

blocker_gate.set()

ok(
    "La tâche critique démarre avant la tâche basse",
    wait_until(
        lambda: any(
            task_id == "dev_critical"
            for _, task_id, _ in starts
        )
    ),
)

critical_start = next(
    at for _, task_id, at in starts
    if task_id == "dev_critical"
)

ok(
    "La tâche basse finit aussi par démarrer",
    wait_until(
        lambda: any(
            task_id == "dev_low"
            for _, task_id, _ in starts
        )
    ),
)

low_start = next(
    at for _, task_id, at in starts
    if task_id == "dev_low"
)

ok(
    "Ordre réel critique puis basse",
    critical_start <= low_start,
)


# ============================================================
# 3. DEADLINE PROCHE REMONTE À PRIORITÉ ÉGALE
# ============================================================

blocker2_gate = threading.Event()
gates["dev_blocker2"] = blocker2_gate

tasks.add(Task(
    "dev_blocker2",
    "Blocage 2",
    "blocage2",
    "developer",
))

now_plus_30m = datetime_now = None
from datetime import datetime, timedelta, timezone
now_plus_30m = (
    datetime.now(timezone.utc)
    + timedelta(minutes=30)
).isoformat()

tasks.add(Task(
    "dev_no_deadline",
    "Sans échéance",
    "none",
    "developer",
    created_at="2026-09-08T20:03:00+00:00",
    metadata={"schedule_priority": "normal"},
))

tasks.add(Task(
    "dev_due_soon",
    "Échéance proche",
    "soon",
    "developer",
    created_at="2026-09-08T20:04:00+00:00",
    metadata={
        "schedule_priority": "normal",
        "schedule_deadline": now_plus_30m,
    },
))

engine.submit("dev_blocker2")
ok(
    "Deuxième blocker Developer lancé",
    wait_until(lambda: engine.is_running("dev_blocker2")),
)
engine.submit("dev_no_deadline")
engine.submit("dev_due_soon")
time.sleep(0.1)

snap = engine.workload_snapshot()
ids = [row["task_id"] for row in snap["backlog_tasks"]]
ok(
    "Une deadline proche remonte devant une tâche normale sans deadline",
    ids.index("dev_due_soon") < ids.index("dev_no_deadline"),
)

blocker2_gate.set()
ok(
    "La tâche à deadline proche est exécutée",
    wait_until(
        lambda: tasks.get("dev_due_soon").status
        == TaskStatus.COMPLETED.value
    ),
)


# ============================================================
# 4. PRIORITÉ MODIFIÉE PENDANT L'ATTENTE
# ============================================================

blocker3_gate = threading.Event()
gates["dev_blocker3"] = blocker3_gate
policy = {
    "dynamic_a": "normal",
    "dynamic_b": "low",
}


def provider(task):
    if task.id in policy:
        return {
            "priority": policy[task.id],
            "mission": "M-DYN",
        }
    return {}

engine.set_schedule_provider(provider)

tasks.add(Task("dev_blocker3", "Blocage 3", "b3", "developer"))
tasks.add(Task("dynamic_a", "A", "A", "developer"))
tasks.add(Task("dynamic_b", "B", "B", "developer"))

engine.submit("dev_blocker3")
ok(
    "Troisième blocker Developer lancé",
    wait_until(lambda: engine.is_running("dev_blocker3")),
)
engine.submit("dynamic_a")
engine.submit("dynamic_b")
time.sleep(0.1)

before = [
    row["task_id"]
    for row in engine.workload_snapshot()["backlog_tasks"]
]
ok(
    "Avant changement A passe devant B",
    before.index("dynamic_a") < before.index("dynamic_b"),
)

policy["dynamic_b"] = "critical"
engine.wake_scheduler()
time.sleep(0.1)

after = [
    row["task_id"]
    for row in engine.workload_snapshot()["backlog_tasks"]
]
ok(
    "Changer la priorité réordonne le backlog sans recréer la tâche",
    after.index("dynamic_b") < after.index("dynamic_a"),
)

blocker3_gate.set()
ok(
    "La tâche devenue critique démarre",
    wait_until(
        lambda: tasks.get("dynamic_b").status
        == TaskStatus.COMPLETED.value
    ),
)


# ============================================================
# 5. ANNULATION D'UNE TÂCHE EN BACKLOG
# ============================================================

blocker4_gate = threading.Event()
gates["dev_blocker4"] = blocker4_gate

tasks.add(Task("dev_blocker4", "Blocage 4", "b4", "developer"))
tasks.add(Task("dev_cancel_me", "À annuler", "cancel", "developer"))

engine.submit("dev_blocker4")
ok(
    "Quatrième blocker Developer lancé",
    wait_until(lambda: engine.is_running("dev_blocker4")),
)
engine.submit("dev_cancel_me")
ok("Tâche présente dans le backlog", engine.is_queued("dev_cancel_me"))
ok("Annulation retire une tâche du backlog", engine.cancel("dev_cancel_me"))
tasks.update("dev_cancel_me", status=TaskStatus.CANCELLED.value)
ok("Tâche retirée du backlog", not engine.is_queued("dev_cancel_me"))
blocker4_gate.set()
time.sleep(0.15)
ok(
    "Une tâche annulée ne démarre pas ensuite",
    not any(task_id == "dev_cancel_me" for _, task_id, _ in starts),
)


# ============================================================
# 6. DÉPENDANCES CONSERVÉES
# ============================================================

engine.set_schedule_provider(None)

tasks.add(Task("dep_root", "Root", "root", "researcher"))
tasks.add(Task(
    "dep_child",
    "Child",
    "child",
    "tester",
    status=TaskStatus.WAITING_DEPENDENCY.value,
    depends_on=["dep_root"],
))

ok("Dépendance racine soumise", engine.submit("dep_root"))
ok(
    "Tâche dépendante refusée tant que la racine n'est pas finie",
    not engine.submit("dep_child"),
)
ok(
    "Racine terminée",
    wait_until(
        lambda: tasks.get("dep_root").status
        == TaskStatus.COMPLETED.value
    ),
)
ok(
    "Le dépendant est ensuite repris automatiquement",
    wait_until(
        lambda: tasks.get("dep_child").status
        == TaskStatus.COMPLETED.value
    ),
)


# ============================================================
# 7. VISIBILITÉ WORKLOAD
# ============================================================

summary = engine.workload_summary()
workers_summary = engine.workers_summary()
backlog_summary = engine.backlog_summary()

ok("Résumé workload disponible", "WORKLOAD V5.0" in summary)
ok("Résumé workers disponible", "WORKERS V5.0" in workers_summary)
ok("Résumé backlog disponible", "BACKLOG V5.0" in backlog_summary)
ok("Snapshot expose les workers", len(engine.workload_snapshot()["workers"]) == 4)

engine.shutdown()

print("\n" + "=" * 68)
print(f"TOUS LES TESTS V5.0 SONT PASSÉS — {len(checks)} contrôles.")
print("=" * 68)
