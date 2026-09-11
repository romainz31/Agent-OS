from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "hierarchy_under_test",
    Path(__file__).resolve().parents[1] / "agentos" / "hierarchy.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
MissionHierarchy = MODULE.MissionHierarchy


@dataclass
class FakeTask:
    id: str
    title: str
    description: str
    worker: str
    status: str
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeTasks:
    def __init__(self):
        self.items: dict[str, FakeTask] = {}
        self.counter = 0

    def create(self, *, title, description, worker, depends_on=None, metadata=None):
        self.counter += 1
        dependencies = list(depends_on or [])
        status = "pending"
        if dependencies and not self.dependencies_satisfied_ids(dependencies):
            status = "waiting_dependency"
        task = FakeTask(
            id=f"task_{self.counter:03d}",
            title=title,
            description=description,
            worker=worker,
            status=status,
            depends_on=dependencies,
            metadata=dict(metadata or {}),
        )
        self.items[task.id] = task
        return task

    def get(self, task_id):
        return self.items.get(task_id)

    def update(self, task_id, **changes):
        task = self.items[task_id]
        for key, value in changes.items():
            setattr(task, key, value)
        return task

    def dependencies_satisfied_ids(self, ids):
        return all(
            self.items.get(task_id)
            and self.items[task_id].status == "completed"
            for task_id in ids
        )


@dataclass
class FakeMission:
    id: str
    human_id: str
    title: str
    description: str
    status: str
    created_at: str
    task_ids: list[str] = field(default_factory=list)
    plan: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeMissions:
    def __init__(self, tasks):
        self.tasks = tasks
        self.items: dict[str, FakeMission] = {}
        self.counter = 0

    def create(self, *, title, description, metadata=None):
        self.counter += 1
        mission = FakeMission(
            id=f"mission_{self.counter:03d}",
            human_id=f"M-{self.counter:03d}",
            title=title,
            description=description,
            status="planning",
            created_at=f"2026-09-09T00:00:{self.counter:02d}+00:00",
            metadata=dict(metadata or {}),
        )
        self.items[mission.id] = mission
        return mission

    def get(self, mission_id):
        return self.items.get(mission_id)

    def resolve(self, reference):
        for mission in self.items.values():
            if mission.id == reference or mission.human_id == reference.upper():
                return mission
        return None

    def list(self):
        return sorted(
            self.items.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )

    def attach_plan(self, mission_id, *, plan, task_ids):
        mission = self.items[mission_id]
        mission.plan = list(plan)
        mission.task_ids = list(task_ids)
        mission.status = "running" if task_ids else "failed"
        return mission

    def set_status(self, mission_id, status, *, metadata_patch=None):
        mission = self.items[mission_id]
        mission.status = status
        if metadata_patch:
            mission.metadata.update(dict(metadata_patch))
        return mission

    def refresh(self, mission, tasks):
        linked = [tasks.get(task_id) for task_id in mission.task_ids]
        linked = [task for task in linked if task is not None]
        if not linked:
            return mission
        if any(task.status == "failed" for task in linked):
            mission.status = "failed"
        elif all(task.status == "completed" for task in linked):
            mission.status = "completed"
        elif any(task.status == "waiting_approval" for task in linked):
            mission.status = "waiting_approval"
        elif any(task.status == "running" for task in linked):
            mission.status = "running"
        else:
            mission.status = "queued"
        return mission

    def progress(self, mission, tasks):
        total = len(mission.task_ids)
        completed = sum(
            1
            for task_id in mission.task_ids
            if tasks.get(task_id)
            and tasks.get(task_id).status == "completed"
        )
        return completed, total


@dataclass
class FakeStep:
    title: str
    description: str
    worker: str
    depends_on: list[int] = field(default_factory=list)

    def to_dict(self):
        return {
            "title": self.title,
            "description": self.description,
            "worker": self.worker,
            "depends_on": list(self.depends_on),
        }


class FakePlanner:
    def plan(self, *, message, initial_worker):
        # Developer reçoit aussi un test afin de vérifier le chaînage interne.
        if initial_worker == "developer":
            return [
                FakeStep("Développer", message, "developer", []),
                FakeStep("Tester", message, "tester", [0]),
            ]
        return [
            FakeStep("Étape", message, initial_worker, []),
        ]


@dataclass
class FakeRoute:
    kind: str
    worker: str | None
    reason: str


class FakeRouter:
    def route(self, message):
        value = message.lower()
        if "recherche" in value:
            return FakeRoute("task", "researcher", "recherche")
        if "crée" in value or "cree" in value:
            return FakeRoute("task", "developer", "développement")
        if "teste" in value:
            return FakeRoute("task", "tester", "test")
        return FakeRoute("conversation", None, "conversation")


class FakeEngine:
    def __init__(self):
        self.submitted: list[str] = []
        self.wake_count = 0

    def submit(self, task_id):
        self.submitted.append(task_id)
        return True

    def wake_scheduler(self):
        self.wake_count += 1


class FakeAutonomy:
    PRIORITIES = {
        "low": 10,
        "normal": 20,
        "high": 30,
        "critical": 40,
    }

    def policy_for(self, mission):
        return {
            "priority": mission.metadata.get("priority", "normal"),
            "deadline": mission.metadata.get("deadline"),
            "enabled": mission.metadata.get("autonomy_enabled", True),
        }

    def _priority_from_text(self, text):
        value = text.lower()
        for word, canonical in (
            ("critique", "critical"),
            ("haute", "high"),
            ("basse", "low"),
            ("normale", "normal"),
        ):
            if "priorité " + word in value or "priorite " + word in value:
                return canonical
        return None

    def parse_deadline(self, text):
        value = text.lower()
        if "dans 1h" in value:
            return datetime.now().astimezone() + timedelta(hours=1)
        if "dans 2h" in value:
            return datetime.now().astimezone() + timedelta(hours=2)
        return None

    def apply_creation_policy(self, mission, text):
        priority = self._priority_from_text(text)
        deadline = self.parse_deadline(text)
        if priority is not None:
            mission.metadata["priority"] = priority
        elif "priority" not in mission.metadata:
            mission.metadata["priority"] = "normal"
        if deadline is not None:
            mission.metadata["deadline"] = deadline.isoformat()
        mission.metadata["autonomy_enabled"] = True
        return {
            "priority": priority,
            "deadline": deadline,
        }


class FakeManager:
    def __init__(self):
        self.tasks = FakeTasks()
        self.missions = FakeMissions(self.tasks)
        self.planner = FakePlanner()
        self.router = FakeRouter()
        self.engine = FakeEngine()


checks = 0


def ok(condition, label):
    global checks
    if not condition:
        raise AssertionError(label)
    checks += 1
    print(f"[OK] {label}")


def create_root(manager, *, priority="high", deadline="2026-09-10T18:00:00+02:00"):
    root = manager.missions.create(
        title="Projet racine",
        description="Projet racine",
        metadata={
            "priority": priority,
            "deadline": deadline,
            "autonomy_enabled": True,
        },
    )
    task = manager.tasks.create(
        title="Racine",
        description="Racine",
        worker="ai_worker",
        metadata={"mission_id": root.id},
    )
    manager.missions.attach_plan(
        root.id,
        plan=[{"title": "Racine"}],
        task_ids=[task.id],
    )
    return root, task


def main():
    print("=" * 68)
    print("TEST AGENT-OS V5.1 — ARBRES DE MISSIONS")
    print("=" * 68)

    manager = FakeManager()
    autonomy = FakeAutonomy()
    hierarchy = MissionHierarchy(
        manager,
        autonomy,
    )

    root, root_task = create_root(manager)

    child = hierarchy.create_sub_mission(
        parent_reference=root.human_id,
        description="Recherche la documentation Home Assistant",
    )
    ok(child is not None, "Sous-mission créée")
    ok(child.metadata["parent_mission_id"] == root.id, "Parent interne persisté")
    ok(child.metadata["parent_human_id"] == root.human_id, "Parent humain persisté")
    ok(child.metadata["root_mission_id"] == root.id, "Racine persistée")
    ok(child.metadata["hierarchy_depth"] == 1, "Profondeur 1")
    ok(child.metadata["priority"] == "high", "Priorité héritée à la création")
    ok(child.metadata["deadline"] == root.metadata["deadline"], "Deadline héritée à la création")
    ok(child.metadata["hierarchy_priority_explicit"] is False, "Priorité marquée héritée")
    ok(child.metadata["hierarchy_deadline_explicit"] is False, "Deadline marquée héritée")
    ok(len(child.task_ids) == 1, "Plan Researcher créé")
    ok(manager.tasks.get(child.task_ids[0]).worker == "researcher", "Router => Researcher")
    ok(child.task_ids[0] in manager.engine.submitted, "Tâche enfant envoyée au backlog")

    # Héritage dynamique après changement du parent.
    root.metadata["priority"] = "critical"
    effective = hierarchy.effective_policy(child)
    ok(effective["priority"] == "critical", "Changement parent propagé dynamiquement")

    root.metadata["deadline"] = "2026-09-11T12:00:00+02:00"
    effective = hierarchy.effective_policy(child)
    ok(effective["deadline"] == root.metadata["deadline"], "Nouvelle deadline parent propagée")

    # Override local.
    override = hierarchy.create_sub_mission(
        parent_reference=root.human_id,
        description="Crée workspace/test.yaml en priorité basse dans 1h",
    )
    ok(override.metadata["hierarchy_priority_explicit"] is True, "Override priorité détecté")
    ok(override.metadata["hierarchy_deadline_explicit"] is True, "Override deadline détecté")
    ok(hierarchy.effective_policy(override)["priority"] == "low", "Override priorité conservé")
    root.metadata["priority"] = "high"
    ok(hierarchy.effective_policy(override)["priority"] == "low", "Override isolé des changements parent")
    ok(len(override.task_ids) == 2, "Developer + Tester créés")
    dev_task = manager.tasks.get(override.task_ids[0])
    test_task = manager.tasks.get(override.task_ids[1])
    ok(test_task.depends_on == [dev_task.id], "Dépendance interne Developer -> Tester")

    # Niveau 2.
    grandchild = hierarchy.create_sub_mission(
        parent_reference=child.human_id,
        description="Analyse les différences de syntaxe",
    )
    ok(grandchild.metadata["hierarchy_depth"] == 2, "Sous-mission imbriquée profondeur 2")
    ok(grandchild.metadata["root_mission_id"] == root.id, "Racine conservée au niveau 2")
    ok(hierarchy.root_of(grandchild).id == root.id, "root_of remonte toute la chaîne")
    ok(grandchild in hierarchy.descendants_of(root), "Descendant niveau 2 détecté")

    # Dépendance mission -> mission.
    dependent = hierarchy.create_sub_mission(
        parent_reference=root.human_id,
        description="Crée workspace/final.yaml",
        depends_on_references=[override.human_id],
    )
    terminals = hierarchy._terminal_task_ids(override)
    dependent_root = manager.tasks.get(dependent.task_ids[0])
    ok(dependent.metadata["depends_on_mission_refs"] == [override.human_id], "Dépendance mission persistée")
    ok(all(task_id in dependent_root.depends_on for task_id in terminals), "Barrière de tâches terminales injectée")
    ok(dependent_root.status == "waiting_dependency", "Sous-mission dépendante mise en attente")

    # Commandes.
    response = hierarchy.command_response(
        f"sous-mission {root.human_id} : Teste workspace/final.yaml"
    )
    ok(response is not None and "créée sous" in response, "Commande sous-mission comprise")

    command_child_ref = sorted(
        hierarchy.children_of(root),
        key=lambda item: item.created_at,
    )[-1].human_id
    ok(command_child_ref in response, "Commande retourne la référence enfant")

    response_dep = hierarchy.command_response(
        f"sous-mission {root.human_id} après {child.human_id} : Analyse le résultat"
    )
    ok("Dépend de" in response_dep and child.human_id in response_dep, "Commande dépendance comprise")

    tree = hierarchy.tree_summary(root.human_id)
    ok("ARBRE DE MISSION" in tree, "Résumé arbre disponible")
    ok(root.human_id in tree and child.human_id in tree and grandchild.human_id in tree, "Arbre affiche tous les niveaux")
    ok("après" in tree, "Arbre affiche les dépendances")

    children_text = hierarchy.children_summary(root.human_id)
    ok("SOUS-MISSIONS" in children_text, "Résumé enfants disponible")
    ok(child.human_id in children_text, "Résumé enfants contient le premier enfant")

    roots_text = hierarchy.roots_summary()
    ok(root.human_id in roots_text, "Résumé des arbres contient la racine")

    snapshot = hierarchy.snapshot()
    ok(snapshot["trees"] == 1, "Un arbre détecté")
    ok(snapshot["sub_missions"] >= 6, "Sous-missions comptabilisées")

    payload = hierarchy.tree_payload(grandchild.human_id)
    ok(payload["root"]["human_id"] == root.human_id, "tree_payload revient à la racine")
    ok(payload["mission_count"] == 1 + len(hierarchy.descendants_of(root)), "Nombre de missions agrégé")

    progress = hierarchy.aggregate_progress(root)
    expected_total = sum(
        len(node.task_ids)
        for node in [root, *hierarchy.descendants_of(root)]
    )
    ok(progress["total"] == expected_total, "Progression agrège toutes les tâches")

    # Quelques tâches terminées => compteur agrégé exact.
    manager.tasks.update(root_task.id, status="completed")
    manager.tasks.update(child.task_ids[0], status="completed")
    progress2 = hierarchy.aggregate_progress(root)
    ok(progress2["completed"] >= 2, "Progression agrégée compte les tâches terminées")

    # Une mission échouée fait remonter l'attention globale.
    manager.tasks.update(grandchild.task_ids[0], status="failed")
    ok(hierarchy.aggregate_status(root) == "attention", "Échec enfant remonte en attention globale")

    # Erreurs propres.
    missing = hierarchy.command_response(
        "sous-mission M-999 : Analyse ceci"
    )
    ok("introuvable" in missing.lower(), "Parent introuvable géré")

    missing_dep = hierarchy.command_response(
        f"sous-mission {root.human_id} après M-999 : Analyse ceci"
    )
    ok("introuvable" in missing_dep.lower(), "Dépendance introuvable gérée")

    no_ref = hierarchy.command_response("mission tree")
    ok("ARBRES DE MISSIONS" in no_ref, "mission tree sans ref liste les arbres")

    ok(manager.engine.wake_count >= 1, "Scheduler réveillé après création")

    print()
    print(f"TOUS LES TESTS V5.1 SONT PASSÉS — {checks} contrôles.")


if __name__ == "__main__":
    main()
