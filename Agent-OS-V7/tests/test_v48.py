from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import agentos.autonomy as autonomy_module
import agentos.conversation as conversation_module
import agentos.missions as missions_module
import agentos.tasks as tasks_module

from agentos.autonomy import AutonomyController
from agentos.conversation import ConversationTracker
from agentos.missions import MissionManager
from agentos.personal_manager import PersonalManager
from agentos.tasks import TaskManager, TaskStatus


class FakeEngine:
    def __init__(self, tasks: TaskManager) -> None:
        self.tasks = tasks
        self.submitted: list[str] = []
        self.running: set[str] = set()

    def submit(self, task_id: str) -> bool:
        if task_id in self.running:
            return False
        self.submitted.append(task_id)
        return True

    def is_running(self, task_id: str) -> bool:
        return task_id in self.running


class FakeManager:
    def __init__(
        self,
        missions: MissionManager,
        tasks: TaskManager,
    ) -> None:
        self.missions = missions
        self.tasks = tasks
        self.engine = FakeEngine(tasks)
        self.notifications: list[str] = []

    def _append_notification(self, text: str) -> None:
        self.notifications.append(str(text))


checks = 0


def ok(condition: bool, label: str) -> None:
    global checks
    if not condition:
        raise AssertionError(label)
    checks += 1
    print(f"[OK] {label}")


def create_mission_with_task(
    manager: FakeManager,
    *,
    title: str = "Mission test",
    worker: str = "developer",
):
    mission = manager.missions.create(
        title=title,
        description=title,
        metadata={
            "autonomy_enabled": True,
            "priority": "normal",
        },
    )
    task = manager.tasks.create(
        title="Étape test",
        description="Étape test",
        worker=worker,
        metadata={
            "mission_id": mission.id,
            "original_message": title,
        },
    )
    manager.missions.attach_plan(
        mission.id,
        plan=[
            {
                "title": task.title,
                "worker": worker,
            }
        ],
        task_ids=[task.id],
    )
    return mission, task


def main() -> None:
    print("=" * 68)
    print("TEST AGENT-OS V4.8 — MANAGER AUTONOME")
    print("=" * 68)

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)

        # Les managers historiques lisent DATA_DIR depuis leurs modules.
        missions_module.DATA_DIR = data_dir
        tasks_module.DATA_DIR = data_dir
        autonomy_module.DATA_DIR = data_dir
        conversation_module.DATA_DIR = data_dir

        missions = MissionManager()
        tasks = TaskManager()
        manager = FakeManager(
            missions,
            tasks,
        )
        controller = AutonomyController(
            manager,
            check_interval=60,
            approval_reminder_seconds=60,
        )

        # -----------------------------------------------------
        # Parsing priorité / deadline
        # -----------------------------------------------------
        ok(
            controller._priority_from_text(
                "Crée ceci en priorité haute"
            ) == "high",
            "Priorité haute détectée",
        )
        ok(
            controller._priority_from_text(
                "C'est urgent"
            ) == "critical",
            "Urgence => priorité critique",
        )

        before = datetime.now().astimezone()
        deadline = controller.parse_deadline(
            "deadline M-001 dans 2h"
        )
        ok(
            deadline is not None
            and 6900
            <= (deadline - before).total_seconds()
            <= 7500,
            "Deadline relative dans 2h",
        )

        tomorrow = controller.parse_deadline(
            "deadline M-001 demain 18h"
        )
        ok(
            tomorrow is not None
            and tomorrow.date()
            == (before + timedelta(days=1)).date()
            and tomorrow.hour == 18,
            "Deadline demain 18h",
        )

        # -----------------------------------------------------
        # Politique mission
        # -----------------------------------------------------
        mission, task = create_mission_with_task(
            manager,
            title="Créer un fichier",
        )
        policy_result = controller.apply_creation_policy(
            mission,
            "Crée un fichier en priorité haute dans 2h",
        )
        policy = controller.policy_for(mission)
        ok(
            policy_result["priority"] == "high"
            and policy["priority"] == "high",
            "Politique de priorité persistée sur la mission",
        )
        ok(
            policy["deadline"] is not None,
            "Échéance persistée sur la mission",
        )

        # -----------------------------------------------------
        # Premier échec : retry discret
        # -----------------------------------------------------
        manager.tasks.update(
            task.id,
            status=TaskStatus.FAILED.value,
            error="erreur test 1",
        )
        handled = controller.handle_failed_task(
            manager.tasks.get(task.id)
        )
        task_after = manager.tasks.get(task.id)
        ok(
            handled is True,
            "Premier échec absorbé par l'autonomie",
        )
        ok(
            int(task_after.metadata.get("autonomy_retry_count", 0)) == 1,
            "Compteur de retry autonome enregistré",
        )
        ok(
            task.id in manager.engine.submitted,
            "Même tâche relancée au premier échec",
        )

        # -----------------------------------------------------
        # Deuxième échec : diagnostic AI Worker
        # -----------------------------------------------------
        manager.tasks.update(
            task.id,
            status=TaskStatus.FAILED.value,
            error="erreur test 2",
        )
        handled = controller.handle_failed_task(
            manager.tasks.get(task.id)
        )
        task_after = manager.tasks.get(task.id)
        diagnostic_id = task_after.metadata.get(
            "autonomy_diagnostic_task"
        )
        diagnostic = manager.tasks.get(
            diagnostic_id
        )
        ok(
            handled is True
            and diagnostic is not None,
            "Deuxième échec => diagnostic créé",
        )
        ok(
            diagnostic.worker == "ai_worker",
            "Diagnostic confié à AI Worker",
        )
        ok(
            diagnostic.id in task_after.depends_on,
            "Nouvelle tentative attend le diagnostic",
        )
        ok(
            task_after.status
            == TaskStatus.WAITING_DEPENDENCY.value,
            "Tâche originale remise en attente du diagnostic",
        )

        # -----------------------------------------------------
        # Troisième échec : escalade
        # -----------------------------------------------------
        manager.tasks.update(
            diagnostic.id,
            status=TaskStatus.COMPLETED.value,
            result="Diagnostic terminé",
        )
        manager.tasks.update(
            task.id,
            status=TaskStatus.FAILED.value,
            error="erreur test 3",
        )
        handled = controller.handle_failed_task(
            manager.tasks.get(task.id)
        )
        ok(
            handled is False,
            "Troisième échec => escalade humaine",
        )
        ok(
            any(
                item.get("action") == "escalation_required"
                for item in controller.decisions
            ),
            "Escalade journalisée",
        )

        # -----------------------------------------------------
        # Tâche orpheline : running sans Future
        # -----------------------------------------------------
        mission2, task2 = create_mission_with_task(
            manager,
            title="Mission orpheline",
        )
        manager.tasks.update(
            task2.id,
            status=TaskStatus.RUNNING.value,
        )
        result = controller.check_once()
        ok(
            result["orphan_recovered"] >= 1,
            "Tâche running sans worker récupérée",
        )
        ok(
            task2.id in manager.engine.submitted,
            "Tâche orpheline resoumise",
        )

        # -----------------------------------------------------
        # Deadline dépassée : notification unique
        # -----------------------------------------------------
        manager.tasks.update(
            task2.id,
            status=TaskStatus.PENDING.value,
        )
        controller.set_deadline(
            mission2,
            datetime.now().astimezone()
            - timedelta(minutes=1),
            record=False,
        )
        before_notifications = len(
            manager.notifications
        )
        result = controller.check_once()
        ok(
            result["deadline_events"] >= 1,
            "Deadline dépassée détectée",
        )
        ok(
            len(manager.notifications)
            == before_notifications + 1,
            "Deadline dépassée notifiée une seule fois",
        )
        controller.check_once()
        ok(
            len(manager.notifications)
            == before_notifications + 1,
            "Pas de spam sur deadline déjà signalée",
        )

        # -----------------------------------------------------
        # Commandes Manager
        # -----------------------------------------------------
        response = controller.command_response(
            f"priorité {mission2.human_id} critique"
        )
        ok(
            response is not None
            and controller.policy_for(mission2)["priority"]
            == "critical",
            "Commande priorité mission",
        )

        response = controller.command_response(
            f"deadline {mission2.human_id} dans 3h"
        )
        ok(
            response is not None
            and controller.policy_for(mission2)["deadline"]
            is not None,
            "Commande deadline mission",
        )

        response = controller.command_response(
            f"autonomie {mission2.human_id} off"
        )
        ok(
            response is not None
            and controller.policy_for(mission2)["enabled"]
            is False,
            "Autonomie désactivable par mission",
        )

        response = controller.command_response(
            f"autonomie {mission2.human_id} on"
        )
        ok(
            response is not None
            and controller.policy_for(mission2)["enabled"]
            is True,
            "Autonomie réactivable par mission",
        )

        ok(
            "MANAGER AUTONOME"
            in controller.status_summary(),
            "Résumé d'état du Manager autonome",
        )
        ok(
            "DÉCISIONS RÉCENTES DU MANAGER"
            in controller.decisions_summary(),
            "Journal des décisions lisible",
        )

        # -----------------------------------------------------
        # Persistance des décisions / état global
        # -----------------------------------------------------
        controller.state["enabled"] = False
        controller._save_state()
        controller.record(
            "test_persistence",
            detail="persisté",
        )

        controller2 = AutonomyController(
            manager,
            check_interval=60,
        )
        ok(
            controller2.state.get("enabled") is False,
            "État global d'autonomie persistant",
        )
        ok(
            any(
                item.get("action") == "test_persistence"
                for item in controller2.decisions
            ),
            "Journal des décisions persistant",
        )

        # -----------------------------------------------------
        # Sécurité : aucune approbation automatique
        # -----------------------------------------------------
        mission3, task3 = create_mission_with_task(
            manager,
            title="Mission approbation",
        )
        old = (
            datetime.now(timezone.utc)
            - timedelta(minutes=2)
        ).isoformat()
        manager.tasks.update(
            task3.id,
            status=TaskStatus.WAITING_APPROVAL.value,
            updated_at=old,
        )
        # update() remplace updated_at par maintenant ; on force pour le test
        task3 = manager.tasks.get(task3.id)
        task3.updated_at = old
        manager.tasks._save()
        controller.state["enabled"] = True
        controller._save_state()
        before_status = task3.status
        controller.check_once()
        after_status = manager.tasks.get(task3.id).status
        ok(
            before_status == after_status
            == TaskStatus.WAITING_APPROVAL.value,
            "Aucune approbation sensible validée automatiquement",
        )

        # -----------------------------------------------------
        # Finition status : état à la demande + mission récente
        # -----------------------------------------------------
        mission4, task4 = create_mission_with_task(
            manager,
            title="Mission statut live",
        )
        live_status = controller.status_summary()
        ok(
            mission4.human_id in live_status
            and "Missions actives supervisées" in live_status,
            "Manager status lit les missions actives à la demande",
        )

        manager.tasks.update(
            task4.id,
            status=TaskStatus.COMPLETED.value,
            result="OK",
        )
        manager.missions.refresh(mission4, manager.tasks)
        completed_status = controller.status_summary()
        ok(
            "Missions actives supervisées" in completed_status
            and "Dernière mission récente" in completed_status
            and mission4.human_id in completed_status,
            "Une mission juste terminée reste visible sans faux compteur actif",
        )

        sample_utc = "2026-09-08T18:20:46+00:00"
        expected_local = datetime.fromisoformat(
            sample_utc
        ).astimezone().strftime("%H:%M:%S")
        ok(
            controller._display_time(sample_utc) == expected_local,
            "Journal Manager affiché dans le fuseau local",
        )

        # -----------------------------------------------------
        # Fil conversationnel persistant
        # -----------------------------------------------------
        tracker = ConversationTracker(
            idle_rotation_hours=999,
        )
        bootstrapped = tracker.bootstrap_from_session([
            {
                "role": "user",
                "content": "On travaille sur Agent-OS et la V4.8.",
                "at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "role": "assistant",
                "content": "D'accord.",
                "at": datetime.now(timezone.utc).isoformat(),
            },
        ])
        ok(
            bootstrapped is True,
            "Migration de l'ancienne session vers le fil persistant",
        )

        tracker.add_exchange(
            "Du coup, on continue avec ça ?",
            "Oui, on continue sur la V4.8.",
        )
        context = tracker.context_for(
            "Et le statut ?"
        )
        ok(
            "On travaille sur Agent-OS" in context
            and "Du coup, on continue" in context,
            "Le fil conserve les échanges nécessaires aux questions de suivi",
        )

        tracker_reloaded = ConversationTracker(
            idle_rotation_hours=999,
        )
        ok(
            tracker_reloaded.snapshot()["messages"] >= 4,
            "Le fil conversationnel survit au redémarrage",
        )

        tracker_reloaded.add_exchange(
            "Ma copine s'appelle Alice.",
            "C'est retenu.",
        )
        tracker_reloaded.add_exchange(
            "Corrige : ma copine s'appelle Coralie.",
            "Mis à jour : Copine : Coralie.",
        )
        removed = tracker_reloaded.forget_values(
            ["Alice", "Coralie"]
        )
        serialized_context = tracker_reloaded.context_for("")
        serialized_history = str(
            tracker_reloaded.data.get("history", [])
        )
        ok(
            removed >= 2
            and "Alice" not in serialized_context
            and "Coralie" not in serialized_context
            and "Alice" not in serialized_history
            and "Coralie" not in serialized_history,
            "Un oubli purge aussi le fil conversationnel",
        )

        # -----------------------------------------------------
        # Contexte temporaire : ne doit pas contaminer le sujet
        # -----------------------------------------------------
        tracker_reloaded.new_thread()
        tracker_reloaded.add_exchange(
            "Je suis crevé, je vais me reposer.",
            "D'accord, repose-toi.",
        )
        tracker_reloaded.add_exchange(
            "On parlait de l'accident de Lady Di.",
            "Oui, on parlait de cet accident.",
        )
        tracker_reloaded.add_exchange(
            "Finalement je suis reposé.",
            "Compris.",
        )

        snapshot = tracker_reloaded.snapshot()
        ok(
            "Lady Di" in str(snapshot.get("topic")),
            "Un état temporaire ne remplace pas le sujet substantiel",
        )

        neutral_context = tracker_reloaded.context_for(
            "On en était où ?"
        )
        ok(
            "crevé" not in neutral_context
            and "repose-toi" not in neutral_context
            and "reposée" not in neutral_context
            and "reposé" not in neutral_context,
            "Repos/fatigue exclus d'un contexte qui porte sur un autre sujet",
        )

        resume = tracker_reloaded.resume_response()
        ok(
            "Lady Di" in resume
            and "repos" not in resume.lower()
            and "fatigu" not in resume.lower(),
            "On en était où reprend le sujet sans recycler l'ancien état",
        )

        state_context = tracker_reloaded.context_for(
            "Est-ce que je t'avais dit que j'étais fatigué ?"
        )
        ok(
            "crevé" in state_context
            or "reposé" in state_context,
            "Le contexte temporaire reste disponible quand la question le concerne",
        )

        summary = str(tracker_reloaded.snapshot().get("summary") or "")
        ok(
            "Lady Di" in summary
            and "crevé" not in summary
            and "reposé" not in summary,
            "Le résumé du fil exclut les états temporaires",
        )

        # -----------------------------------------------------
        # Anti-boucle de soutien / bien-être hors sujet
        # -----------------------------------------------------
        polluted_assistant = (
            "D'accord, on parlait de Lady Di. "
            "Si tu as d'autres questions, n'hésite pas à me le faire savoir. "
            "Ton confort et ton bien-être restent ma priorité."
        )
        cleaned_context = (
            ConversationTracker.sanitize_assistant_context(
                polluted_assistant
            )
        )
        ok(
            "Lady Di" in cleaned_context
            and "bien-être" not in cleaned_context
            and "confort" not in cleaned_context
            and "n'hésite" not in cleaned_context,
            "Le contexte ne réinjecte plus les clôtures de bien-être de Paul",
        )

        bad_output = (
            "D'accord, on parlait de l'accident impliquant Lady Di. "
            "Comme tu as de l'énergie pour le moment, je vais procéder à la recherche. "
            "Voici le point principal. "
            "Si tu as besoin de quoi que ce soit, n'hésite pas à me le faire savoir. "
            "Ton bien-être reste ma priorité."
        )
        cleaned_output = PersonalManager._sanitize_response_for_user(
            "On parlait de l'accident de Lady Di.",
            bad_output,
        )
        ok(
            "Lady Di" in cleaned_output
            and "point principal" in cleaned_output
            and "énergie" not in cleaned_output
            and "bien-être" not in cleaned_output
            and "n'hésite" not in cleaned_output,
            "Une réponse factuelle ne recycle plus l'état émotionnel",
        )

        factual_followup = PersonalManager._sanitize_response_for_user(
            "Où s'est déroulé l'accident ?",
            (
                "L'accident s'est déroulé à Paris. "
                "Ton confort et ton bien-être restent ma priorité."
            ),
        )
        ok(
            factual_followup == "L'accident s'est déroulé à Paris.",
            "Une question factuelle reste factuelle jusqu'à la fin",
        )

        emotional_output = PersonalManager._sanitize_response_for_user(
            "Je suis crevé, je vais me reposer.",
            "Compris. Repose-toi et récupère.",
        )
        ok(
            "Repose-toi" in emotional_output,
            "Le soutien reste autorisé quand le message parle réellement de repos",
        )

        old_id = tracker_reloaded.snapshot()["id"]
        tracker_reloaded.new_thread()
        new_snapshot = tracker_reloaded.snapshot()
        ok(
            new_snapshot["id"] != old_id
            and new_snapshot["messages"] == 0
            and new_snapshot["archived_threads"] >= 1,
            "Nouvelle conversation archive le fil précédent",
        )

        ok(
            "FIL DE CONVERSATION" in tracker_reloaded.status_summary(),
            "Statut du fil conversationnel disponible",
        )

    print()
    print(f"TOUS LES TESTS V4.8 SONT PASSÉS — {checks} contrôles.")
    print("Tu peux ensuite lancer api_server.py et tester Paul/Telegram.")


if __name__ == "__main__":
    main()
