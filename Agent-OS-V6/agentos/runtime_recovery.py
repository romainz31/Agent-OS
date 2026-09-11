from __future__ import annotations

from typing import Any


class RuntimeRecoveryService:
    """Centralise la reprise des missions/tâches interrompues.

    Cette classe ne possède aucun état métier propre : elle orchestre les
    managers déjà persistants d'Agent-OS. L'objectif est de sortir la logique
    de récupération de runtime.py sans changer le comportement existant.
    """

    def __init__(self, manager) -> None:
        self.manager = manager

    def recover(self) -> dict[str, Any]:
        active_before = self.manager.missions.active(
            self.manager.tasks
        )

        existing_task_ids: list[str] = []
        for mission in active_before:
            if mission.task_ids:
                existing_task_ids.extend(mission.task_ids)

        task_recovery = self.manager.engine.recover(
            existing_task_ids
        )

        planning_recovery = (
            self.manager.orchestrator
            .recover_planning_missions()
        )

        repair_recovery = (
            self.manager.orchestrator
            .repair_loop
            .recover_pending_repairs()
        )

        active_after = self.manager.missions.active(
            self.manager.tasks
        )

        return {
            "task_recovery": task_recovery,
            "planning_recovery": planning_recovery,
            "repair_recovery": repair_recovery,
            "active_missions": [
                mission.human_id
                for mission in active_after
            ],
        }

    @staticmethod
    def report_lines(
        recovery: dict[str, Any] | None,
    ) -> list[str]:
        recovery = recovery if isinstance(recovery, dict) else {}

        task_recovery = recovery.get("task_recovery", {}) or {}
        planning_recovery = recovery.get("planning_recovery", {}) or {}
        repair_recovery = recovery.get("repair_recovery", {}) or {}

        interrupted = task_recovery.get("interrupted", []) or []
        submitted = task_recovery.get("submitted", []) or []
        waiting_approval = task_recovery.get("waiting_approval", []) or []
        paused = task_recovery.get("paused", []) or []

        resumed_planning = planning_recovery.get("resumed", []) or []
        duplicates = planning_recovery.get("cancelled_duplicates", []) or []
        failed_planning = planning_recovery.get("failed", []) or []

        restored_repairs = repair_recovery.get("restored", []) or []
        exhausted_repairs = repair_recovery.get("exhausted", []) or []
        failed_repairs = repair_recovery.get("failed", []) or []

        active_missions = recovery.get("active_missions", []) or []

        if not (
            interrupted
            or submitted
            or waiting_approval
            or paused
            or resumed_planning
            or duplicates
            or failed_planning
            or restored_repairs
            or exhausted_repairs
            or failed_repairs
        ):
            return []

        lines = ["[REPRISE AGENT-OS]"]

        if active_missions:
            lines.append(
                "Missions actives après reprise : "
                + ", ".join(active_missions)
            )

        if interrupted:
            lines.append(
                "Tâches interrompues restaurées : "
                + str(len(interrupted))
            )

        if submitted:
            lines.append(
                "Tâches relancées automatiquement : "
                + str(len(submitted))
            )

        if waiting_approval:
            lines.append(
                "Tâches toujours en attente d'autorisation : "
                + str(len(waiting_approval))
            )

        if paused:
            lines.append(
                "Tâches conservées en pause : "
                + str(len(paused))
            )

        if resumed_planning:
            lines.append(
                "Missions reprises depuis la planification : "
                + ", ".join(resumed_planning)
            )

        if restored_repairs:
            lines.append(
                "Boucles de correction restaurées : "
                + ", ".join(restored_repairs)
            )

        if exhausted_repairs:
            lines.append(
                "Corrections automatiques arrivées à leur limite : "
                + str(len(exhausted_repairs))
            )

        for item in duplicates:
            lines.append(
                "Mission interrompue annulée comme doublon : "
                + item["mission"]
                + " -> "
                + item["duplicate_of"]
            )

        for item in failed_planning:
            lines.append(
                "Échec de reprise de planification : "
                + item["mission"]
                + " ("
                + item["error"]
                + ")"
            )

        for item in failed_repairs:
            lines.append(
                "Échec de reprise d'une correction : "
                + item["task"]
                + " ("
                + item["error"]
                + ")"
            )

        return lines
