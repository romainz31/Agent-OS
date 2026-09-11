from __future__ import annotations

import re

from agentos.tasks import (
    TaskStatus,
)


class MissionControl:
    MISSION_REF_RE = re.compile(
        r"\bM-\d{1,6}\b",
        flags=re.IGNORECASE,
    )

    PAUSE_MARKERS = (
        "pause",
        "mets en pause",
        "met en pause",
        "suspends",
        "suspend",
    )

    RESUME_MARKERS = (
        "reprends",
        "reprend",
        "resume",
        "relance",
        "continue",
    )

    CANCEL_MARKERS = (
        "annule",
        "annuler",
        "stop",
        "arrête",
        "arrete",
        "abandonne",
    )

    RETRY_MARKERS = (
        "retry",
        "retente",
        "réessaie",
        "reessaie",
        "réessaye",
        "reessaye",
    )

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
    def _normalize(
        text: str,
    ) -> str:
        return " ".join(
            text
            .lower()
            .strip()
            .replace("!", "")
            .replace("?", "")
            .replace(".", "")
            .replace(",", "")
            .split()
        )

    def _reference(
        self,
        message: str,
    ) -> str | None:
        match = (
            self.MISSION_REF_RE.search(
                message
            )
        )

        if match is None:
            return None

        raw = match.group(0).upper()

        number = int(
            raw.split("-")[1]
        )

        return f"M-{number:03d}"

    @staticmethod
    def _contains_marker(
        value: str,
        markers: tuple[str, ...],
    ) -> bool:
        return any(
            marker in value
            for marker
            in markers
        )

    def detect_action(
        self,
        message: str,
    ) -> str | None:
        value = self._normalize(
            message
        )

        if self._contains_marker(
            value,
            self.PAUSE_MARKERS,
        ):
            return "pause"

        if self._contains_marker(
            value,
            self.CANCEL_MARKERS,
        ):
            return "cancel"

        if self._contains_marker(
            value,
            self.RETRY_MARKERS,
        ):
            return "retry"

        if self._contains_marker(
            value,
            self.RESUME_MARKERS,
        ):
            return "resume"

        return None

    def _candidates(
        self,
        action: str,
    ):
        missions = self.missions.list()

        if action == "pause":
            valid = {
                "planning",
                "queued",
                "running",
                "waiting_approval",
            }

        elif action == "resume":
            valid = {
                "paused",
            }

        elif action == "retry":
            valid = {
                "failed",
                "cancelled",
            }

        elif action == "cancel":
            valid = {
                "planning",
                "queued",
                "running",
                "waiting_approval",
                "paused",
            }

        else:
            valid = set()

        result = []

        for mission in missions:
            self.missions.refresh(
                mission,
                self.tasks,
            )

            if mission.status in valid:
                result.append(
                    mission
                )

        return result

    def _resolve(
        self,
        message: str,
        action: str,
    ):
        reference = self._reference(
            message
        )

        if reference:
            return (
                self.missions.resolve(
                    reference
                ),
                None,
            )

        candidates = self._candidates(
            action
        )

        if len(candidates) == 1:
            return (
                candidates[0],
                None,
            )

        if not candidates:
            return (
                None,
                "Aucune mission correspondante.",
            )

        refs = ", ".join(
            mission.human_id
            for mission
            in candidates[:8]
        )

        return (
            None,
            (
                "Plusieurs missions correspondent. "
                "Précise laquelle : "
                f"{refs}"
            ),
        )

    def _tasks_for(
        self,
        mission,
    ):
        result = []

        for task_id in (
            mission.task_ids
        ):
            task = self.tasks.get(
                task_id
            )

            if task is not None:
                result.append(
                    task
                )

        return result

    def pause(
        self,
        mission,
    ) -> str:
        self.missions.refresh(
            mission,
            self.tasks,
        )

        if mission.status in {
            "completed",
            "failed",
            "cancelled",
        }:
            return (
                f"{mission.human_id} ne peut "
                "pas être mise en pause "
                f"(statut : {mission.status})."
            )

        if mission.status == "paused":
            return (
                f"{mission.human_id} est "
                "déjà en pause."
            )

        paused_tasks = 0
        running_tasks = 0

        self.missions.set_control_status(
            mission.id,
            "paused",
        )

        for task in self._tasks_for(
            mission
        ):
            if (
                task.status
                == TaskStatus.RUNNING.value
            ):
                running_tasks += 1
                continue

            if task.status in {
                TaskStatus.PENDING.value,
                TaskStatus.WAITING_DEPENDENCY.value,
            }:
                self.tasks.set_paused(
                    task.id
                )
                paused_tasks += 1

        self.missions.refresh(
            mission,
            self.tasks,
        )

        if running_tasks:
            return (
                f"{mission.human_id} mise en pause.\n\n"
                f"{running_tasks} étape(s) déjà en cours "
                "peuvent finir, mais aucune nouvelle "
                "étape ne démarrera avant reprise."
            )

        return (
            f"{mission.human_id} mise en pause.\n"
            f"{paused_tasks} étape(s) suspendue(s)."
        )

    def resume(
        self,
        mission,
    ) -> str:
        self.missions.refresh(
            mission,
            self.tasks,
        )

        if mission.status != "paused":
            return (
                f"{mission.human_id} n'est "
                "pas en pause."
            )

        self.missions.set_control_status(
            mission.id,
            None,
        )

        reset = []

        for task in self._tasks_for(
            mission
        ):
            if (
                task.status
                == TaskStatus.PAUSED.value
            ):
                self.tasks.reset_for_execution(
                    task.id
                )
                reset.append(
                    task.id
                )

        queued = 0

        for task_id in reset:
            if self.engine.submit(
                task_id
            ):
                queued += 1

        self.missions.refresh(
            mission,
            self.tasks,
        )

        return (
            f"{mission.human_id} reprise.\n"
            f"{len(reset)} étape(s) remise(s) en état.\n"
            f"{queued} étape(s) replacée(s) dans la file de travail."
        )

    def cancel(
        self,
        mission,
    ) -> str:
        self.missions.refresh(
            mission,
            self.tasks,
        )

        if mission.status == "completed":
            return (
                f"{mission.human_id} est déjà terminée."
            )

        if mission.status == "cancelled":
            return (
                f"{mission.human_id} est déjà annulée."
            )

        self.missions.set_control_status(
            mission.id,
            "cancelled",
        )

        cancelled = 0
        running = 0

        for task in self._tasks_for(
            mission
        ):
            if task.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                continue

            # V5.0 : cancel() sait aussi retirer une tâche encore dans le
            # backlog, pas uniquement un Future déjà actif.
            was_running = (
                task.status
                == TaskStatus.RUNNING.value
            )

            self.engine.cancel(
                task.id
            )

            if was_running:
                running += 1

            self.tasks.update(
                task.id,
                status=(
                    TaskStatus
                    .CANCELLED
                    .value
                ),
                error=(
                    "Mission annulée par l'utilisateur."
                ),
            )

            cancelled += 1

        self.missions.refresh(
            mission,
            self.tasks,
        )

        if running:
            return (
                f"{mission.human_id} annulée.\n"
                f"{cancelled} étape(s) annulée(s).\n"
                f"{running} worker(s) déjà en calcul peuvent "
                "encore se terminer en arrière-plan, "
                "mais leur résultat sera ignoré."
            )

        return (
            f"{mission.human_id} annulée.\n"
            f"{cancelled} étape(s) annulée(s)."
        )

    def retry(
        self,
        mission,
    ) -> str:
        self.missions.refresh(
            mission,
            self.tasks,
        )

        if mission.status not in {
            "failed",
            "cancelled",
        }:
            return (
                f"{mission.human_id} n'est "
                "ni échouée ni annulée."
            )

        self.missions.set_control_status(
            mission.id,
            None,
        )

        reset = []

        for task in self._tasks_for(
            mission
        ):
            if task.status in {
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
                TaskStatus.PAUSED.value,
            }:
                self.tasks.reset_for_execution(
                    task.id
                )
                reset.append(
                    task.id
                )

        if not reset:
            self.missions.refresh(
                mission,
                self.tasks,
            )

            return (
                f"{mission.human_id} n'a "
                "aucune étape à retenter."
            )

        queued = 0

        for task_id in reset:
            if self.engine.submit(
                task_id
            ):
                queued += 1

        self.missions.refresh(
            mission,
            self.tasks,
        )

        return (
            f"{mission.human_id} relancée.\n"
            f"{len(reset)} étape(s) remise(s) en état.\n"
            f"{queued} étape(s) replacée(s) dans la file de travail."
        )

    def handle(
        self,
        message: str,
    ) -> str | None:
        action = self.detect_action(
            message
        )

        if action is None:
            return None

        mission, error = self._resolve(
            message,
            action,
        )

        if error:
            return error

        if mission is None:
            reference = (
                self._reference(
                    message
                )
                or "demandée"
            )

            return (
                f"Mission {reference} introuvable."
            )

        if action == "pause":
            return self.pause(
                mission
            )

        if action == "resume":
            return self.resume(
                mission
            )

        if action == "cancel":
            return self.cancel(
                mission
            )

        if action == "retry":
            return self.retry(
                mission
            )

        return None
