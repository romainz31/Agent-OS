from __future__ import annotations

from typing import Any

from agentos.tasks import TaskStatus


class RepairLoop:
    MAX_ATTEMPTS = 3

    def __init__(
        self,
        *,
        missions,
        tasks,
        engine,
    ) -> None:
        self.missions = missions
        self.tasks = tasks
        self.engine = engine

    @staticmethod
    def _metadata(task) -> dict[str, Any]:
        return (
            dict(task.metadata)
            if isinstance(
                task.metadata,
                dict,
            )
            else {}
        )

    @staticmethod
    def _result_data(task) -> dict[str, Any]:
        return (
            dict(task.result_data)
            if isinstance(
                task.result_data,
                dict,
            )
            else {}
        )

    @staticmethod
    def _clean_targets(
        raw_targets,
    ) -> list[str]:
        result = []

        for value in (
            raw_targets
            or []
        ):
            path = str(
                value
            ).strip().replace(
                "\\",
                "/",
            )

            if path.startswith(
                "workspace/"
            ):
                path = path[
                    len("workspace/"):
                ]

            if (
                path
                and path not in result
            ):
                result.append(
                    path
                )

        return result

    def _mission_for_task(
        self,
        task,
    ):
        metadata = self._metadata(
            task
        )

        mission_id = metadata.get(
            "mission_id"
        )

        if not mission_id:
            return None

        return self.missions.get(
            mission_id
        )

    def _existing_repair_tasks(
        self,
        tester_task_id: str,
    ) -> list:
        result = []

        for task in self.tasks.list():
            metadata = self._metadata(
                task
            )

            if (
                metadata.get(
                    "repair_origin_tester"
                )
                == tester_task_id
            ):
                result.append(
                    task
                )

        return result

    def _repair_message(
        self,
        *,
        tester_task,
        mission,
        targets: list[str],
        attempt: int,
    ) -> str:
        metadata = self._metadata(
            tester_task
        )

        original_message = str(
            metadata.get(
                "user_original_message",
                metadata.get(
                    "original_message",
                    mission.description,
                ),
            )
        ).strip()

        feedback = str(
            tester_task.result
            or "Le Tester a indiqué que la vérification n'est pas validée."
        ).strip()

        target_text = ", ".join(
            f"workspace/{path}"
            for path in targets
        )

        return (
            f"Corrige {target_text}.\n\n"
            "DEMANDE UTILISATEUR D'ORIGINE :\n"
            f"{original_message}\n\n"
            "RAPPORT DU TESTER :\n"
            f"{feedback}\n\n"
            "OBJECTIF DE CORRECTION :\n"
            "Corrige uniquement les fichiers ciblés afin que la demande "
            "utilisateur soit satisfaite et que la prochaine vérification "
            "réussisse. Conserve le comportement correct déjà présent.\n\n"
            f"Tentative de correction automatique : {attempt}/{self.MAX_ATTEMPTS}."
        )

    def _append_dynamic_plan(
        self,
        *,
        mission,
        tester_task,
        repair_task,
        retest_task,
        attempt: int,
    ) -> None:
        plan = list(
            mission.plan
            if isinstance(
                mission.plan,
                list,
            )
            else []
        )

        task_ids = list(
            mission.task_ids
        )

        try:
            tester_index = task_ids.index(
                tester_task.id
            )
        except ValueError:
            tester_index = max(
                0,
                len(plan) - 1,
            )

        repair_plan_index = len(
            plan
        )

        plan.append(
            {
                "title": (
                    "Correction automatique "
                    f"{attempt}/{self.MAX_ATTEMPTS}"
                ),
                "description": (
                    repair_task.description
                ),
                "worker": "developer",
                "depends_on": [
                    tester_index
                ],
            }
        )

        plan.append(
            {
                "title": (
                    "Retest automatique "
                    f"{attempt}/{self.MAX_ATTEMPTS}"
                ),
                "description": (
                    retest_task.description
                ),
                "worker": "tester",
                "depends_on": [
                    repair_plan_index
                ],
            }
        )

        task_ids.extend(
            [
                repair_task.id,
                retest_task.id,
            ]
        )

        self.missions.attach_plan(
            mission.id,
            plan=plan,
            task_ids=task_ids,
        )

    def _rewire_dependents(
        self,
        *,
        original_dependents: list,
        retest_task_id: str,
    ) -> None:
        for dependent in (
            original_dependents
        ):
            dependencies = list(
                dict.fromkeys(
                    list(
                        dependent.depends_on
                    )
                    + [
                        retest_task_id
                    ]
                )
            )

            self.tasks.update(
                dependent.id,
                depends_on=dependencies,
            )

    def handle_non_validated(
        self,
        tester_task_id: str,
    ) -> dict[str, Any]:
        tester_task = self.tasks.get(
            tester_task_id
        )

        if tester_task is None:
            return {
                "scheduled": False,
                "reason": "Tâche Tester introuvable.",
            }

        metadata = self._metadata(
            tester_task
        )

        if not metadata.get(
            "auto_repair_enabled",
            False,
        ):
            return {
                "scheduled": False,
                "reason": "Correction automatique désactivée pour cette tâche.",
            }

        mission = self._mission_for_task(
            tester_task
        )

        if mission is None:
            return {
                "scheduled": False,
                "reason": "Mission introuvable pour la correction automatique.",
            }

        mission_metadata = (
            mission.metadata
            if isinstance(
                mission.metadata,
                dict,
            )
            else {}
        )

        if (
            mission_metadata.get(
                "control_status"
            )
            == "cancelled"
        ):
            return {
                "scheduled": False,
                "reason": "Mission annulée.",
            }

        existing = self._existing_repair_tasks(
            tester_task_id
        )

        if existing:
            existing_attempt = int(
                metadata.get(
                    "repair_attempt",
                    0,
                )
            ) + 1

            data = self._result_data(
                tester_task
            )
            data[
                "auto_repair_scheduled"
            ] = True

            self.tasks.update(
                tester_task.id,
                result_data=data,
            )

            return {
                "scheduled": True,
                "attempt": existing_attempt,
                "maximum": self.MAX_ATTEMPTS,
                "reused": True,
            }

        current_attempt = int(
            metadata.get(
                "repair_attempt",
                0,
            )
        )

        next_attempt = (
            current_attempt + 1
        )

        if (
            next_attempt
            > self.MAX_ATTEMPTS
        ):
            return {
                "scheduled": False,
                "exhausted": True,
                "reason": (
                    "Échec des vérifications après "
                    f"{self.MAX_ATTEMPTS} correction(s) automatique(s)."
                ),
            }

        data = self._result_data(
            tester_task
        )

        targets = self._clean_targets(
            data.get(
                "targets",
                [],
            )
        )

        if not targets:
            return {
                "scheduled": False,
                "reason": (
                    "Le Tester n'a fourni aucun fichier cible "
                    "à corriger automatiquement."
                ),
            }

        original_message = str(
            metadata.get(
                "user_original_message",
                metadata.get(
                    "original_message",
                    mission.description,
                ),
            )
        ).strip()

        repair_message = (
            self._repair_message(
                tester_task=tester_task,
                mission=mission,
                targets=targets,
                attempt=next_attempt,
            )
        )

        original_dependents = [
            task
            for task
            in self.tasks.dependents_of(
                tester_task.id
            )
        ]

        repair_task = self.tasks.create(
            title=(
                "Correction automatique "
                f"{next_attempt}/{self.MAX_ATTEMPTS}"
            ),
            description=repair_message,
            worker="developer",
            depends_on=[
                tester_task.id
            ],
            metadata={
                "mission_id": mission.id,
                "original_message": repair_message,
                "user_original_message": original_message,
                "router_reason": "auto_repair",
                "repair_attempt": next_attempt,
                "repair_origin_tester": (
                    tester_task.id
                ),
                "repair_targets": targets,
            },
        )

        retest_task = self.tasks.create(
            title=(
                "Retest automatique "
                f"{next_attempt}/{self.MAX_ATTEMPTS}"
            ),
            description=(
                "Vérifie à nouveau les fichiers corrigés après "
                f"la tentative automatique {next_attempt}/{self.MAX_ATTEMPTS}."
            ),
            worker="tester",
            depends_on=[
                repair_task.id
            ],
            metadata={
                "mission_id": mission.id,
                "original_message": original_message,
                "user_original_message": original_message,
                "router_reason": "auto_repair",
                "repair_attempt": next_attempt,
                "repair_origin_tester": (
                    tester_task.id
                ),
                "auto_repair_enabled": True,
            },
        )

        self._rewire_dependents(
            original_dependents=(
                original_dependents
            ),
            retest_task_id=(
                retest_task.id
            ),
        )

        self._append_dynamic_plan(
            mission=mission,
            tester_task=tester_task,
            repair_task=repair_task,
            retest_task=retest_task,
            attempt=next_attempt,
        )

        data = self._result_data(
            tester_task
        )
        data[
            "auto_repair_scheduled"
        ] = True
        data[
            "auto_repair_attempt"
        ] = next_attempt

        self.tasks.update(
            tester_task.id,
            result_data=data,
        )

        paused = (
            mission_metadata.get(
                "control_status"
            )
            == "paused"
        )

        if paused:
            self.tasks.set_paused(
                repair_task.id
            )
            self.tasks.set_paused(
                retest_task.id
            )

            self.missions.refresh(
                mission,
                self.tasks,
            )

            submitted = False

        else:
            submitted = self.engine.submit(
                repair_task.id
            )

            self.missions.refresh(
                mission,
                self.tasks,
            )

        return {
            "scheduled": True,
            "attempt": next_attempt,
            "maximum": self.MAX_ATTEMPTS,
            "repair_task_id": (
                repair_task.id
            ),
            "retest_task_id": (
                retest_task.id
            ),
            "submitted": submitted,
            "paused": paused,
        }

    def recover_pending_repairs(
        self,
    ) -> dict[str, Any]:
        restored = []
        exhausted = []
        failed = []

        candidates = []

        for task in reversed(
            self.tasks.list()
        ):
            if task.worker != "tester":
                continue

            if (
                task.status
                != TaskStatus.COMPLETED.value
            ):
                continue

            metadata = self._metadata(
                task
            )

            if not metadata.get(
                "auto_repair_enabled",
                False,
            ):
                continue

            data = self._result_data(
                task
            )

            if (
                str(
                    data.get(
                        "verdict",
                        "",
                    )
                ).upper()
                != "NON_VALIDÉ"
            ):
                continue

            if data.get(
                "auto_repair_scheduled"
            ):
                continue

            if data.get(
                "auto_repair_exhausted"
            ):
                continue

            candidates.append(
                task
            )

        for task in candidates:
            try:
                outcome = self.handle_non_validated(
                    task.id
                )

            except Exception as exc:
                failed.append(
                    {
                        "task": task.id,
                        "error": str(exc),
                    }
                )
                continue

            if outcome.get(
                "scheduled"
            ):
                mission = self._mission_for_task(
                    task
                )

                restored.append(
                    mission.human_id
                    if mission
                    else task.id
                )

            elif outcome.get(
                "exhausted"
            ):
                exhausted.append(
                    task.id
                )

        return {
            "restored": restored,
            "exhausted": exhausted,
            "failed": failed,
        }