from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any

from agentos.manager import Manager
from agentos.mission_control import MissionControl
from agentos.runtime_recovery import RuntimeRecoveryService
from agentos.runtime_views import RuntimeViewService


class AgentOSRuntime:
    """Façade runtime d'Agent-OS.

    V6.4 consolide le runtime sans casser son API :
    - récupération -> RuntimeRecoveryService ;
    - sérialisation/statut -> RuntimeViewService ;
    - commandes publiques et contrôle -> cette façade.
    """

    VERSION = "6.4"

    def __init__(self) -> None:
        self.started_at = datetime.now(
            timezone.utc
        ).isoformat()

        self.lock = threading.RLock()

        self.manager = Manager()

        self.control = MissionControl(
            missions=self.manager.missions,
            tasks=self.manager.tasks,
            engine=self.manager.engine,
        )

        self.recovery_service = RuntimeRecoveryService(
            self.manager
        )
        self.views = RuntimeViewService(
            self.manager
        )

        self.recovery = self._recover_active_work()

    # =========================================================
    # RECOVERY
    # =========================================================

    def _recover_active_work(
        self,
    ) -> dict[str, Any]:
        return self.recovery_service.recover()

    def recovery_report_lines(
        self,
    ) -> list[str]:
        return self.recovery_service.report_lines(
            self.recovery
        )

    # =========================================================
    # SERIALIZATION — compatibility façade
    # =========================================================

    @staticmethod
    def _task_payload(
        task,
        *,
        detailed: bool = True,
    ) -> dict[str, Any]:
        return RuntimeViewService.task_payload(
            task,
            detailed=detailed,
        )

    def _mission_payload(
        self,
        mission,
        *,
        detailed: bool = True,
    ) -> dict[str, Any]:
        return self.views.mission_payload(
            mission,
            detailed=detailed,
        )

    # =========================================================
    # STATUS / AGENTS
    # =========================================================

    def status(
        self,
    ) -> dict[str, Any]:
        with self.lock:
            return self.views.status(
                version=self.VERSION,
                started_at=self.started_at,
            )

    def agents(
        self,
    ) -> list[dict[str, Any]]:
        with self.lock:
            return self.views.agents()

    # =========================================================
    # CHAT
    # =========================================================

    def handle_message(
        self,
        message: str,
    ) -> dict[str, Any]:
        value = str(message).strip()

        if not value:
            raise ValueError(
                "Le message est vide."
            )

        with self.lock:
            control_response = (
                self.control.handle(value)
            )

            if control_response is not None:
                response = control_response
                handled_by = "mission_control"
            else:
                response = self.manager.handle(value)
                handled_by = "manager"

            return {
                "response": response,
                "handled_by": handled_by,
                "status": self.status(),
            }

    # =========================================================
    # MISSIONS
    # =========================================================

    def missions(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.lock:
            result = []

            wanted = (
                status.strip().lower()
                if status
                else None
            )

            for mission in self.manager.missions.list():
                self.manager.missions.refresh(
                    mission,
                    self.manager.tasks,
                )

                if wanted and mission.status != wanted:
                    continue

                result.append(
                    self._mission_payload(
                        mission,
                        detailed=False,
                    )
                )

            return result

    def mission(
        self,
        reference: str,
    ) -> dict[str, Any]:
        with self.lock:
            mission = self.manager.missions.resolve(
                reference
            )

            if mission is None:
                raise KeyError(
                    f"Mission {reference} introuvable."
                )

            return self._mission_payload(
                mission,
                detailed=True,
            )

    def control_mission(
        self,
        reference: str,
        action: str,
    ) -> dict[str, Any]:
        with self.lock:
            mission = self.manager.missions.resolve(
                reference
            )

            if mission is None:
                raise KeyError(
                    f"Mission {reference} introuvable."
                )

            actions = {
                "pause": self.control.pause,
                "resume": self.control.resume,
                "cancel": self.control.cancel,
                "retry": self.control.retry,
            }

            handler = actions.get(action)

            if handler is None:
                raise ValueError(
                    "Action de mission inconnue."
                )

            message = handler(mission)

            return {
                "message": message,
                "mission": self._mission_payload(
                    mission,
                    detailed=True,
                ),
            }

    # =========================================================
    # TASKS
    # =========================================================

    def tasks(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.lock:
            wanted = (
                status.strip().lower()
                if status
                else None
            )

            result = []

            for task in self.manager.tasks.list():
                if wanted and task.status != wanted:
                    continue

                result.append(
                    self._task_payload(
                        task,
                        detailed=True,
                    )
                )

            return result

    # =========================================================
    # APPROVALS
    # =========================================================

    def approvals(
        self,
    ) -> list[dict[str, Any]]:
        with self.lock:
            result = []

            for task in self.manager.approvals.pending():
                metadata = (
                    task.metadata
                    if isinstance(task.metadata, dict)
                    else {}
                )

                mission = self.manager.missions.get(
                    metadata.get(
                        "mission_id",
                        "",
                    )
                )

                data = (
                    task.result_data
                    if isinstance(task.result_data, dict)
                    else {}
                )

                result.append(
                    {
                        "task_id": task.id,
                        "mission_id": (
                            mission.human_id
                            if mission
                            else None
                        ),
                        "title": task.title,
                        "files": list(
                            data.get(
                                "approval_required_files",
                                [],
                            )
                            or []
                        ),
                        "created_at": task.created_at,
                        "updated_at": task.updated_at,
                    }
                )

            return result

    def approve_mission(
        self,
        reference: str,
    ) -> dict[str, Any]:
        return self._approval_action(
            reference=reference,
            approve=True,
        )

    def reject_mission(
        self,
        reference: str,
    ) -> dict[str, Any]:
        return self._approval_action(
            reference=reference,
            approve=False,
        )

    def _approval_action(
        self,
        *,
        reference: str,
        approve: bool,
    ) -> dict[str, Any]:
        with self.lock:
            mission = self.manager.missions.resolve(
                reference
            )

            if mission is None:
                raise KeyError(
                    f"Mission {reference} introuvable."
                )

            pending = (
                self.manager.approvals
                .pending_for_mission(
                    mission.id
                )
            )

            if not pending:
                raise ValueError(
                    f"{mission.human_id} "
                    "n'attend aucune autorisation."
                )

            task = pending[0]

            if approve:
                message = (
                    self.manager.approvals
                    .approve_task(
                        task.id
                    )
                )
            else:
                message = (
                    self.manager.approvals
                    .reject_task(
                        task.id
                    )
                )

            self.manager._refresh_mission(
                mission
            )

            return {
                "message": message,
                "mission": self._mission_payload(
                    mission,
                    detailed=True,
                ),
            }

    # =========================================================
    # MEMORY / NOTIFICATIONS
    # =========================================================

    def memory(
        self,
    ) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(
                self.manager.memory.data
            )

    def notifications(
        self,
    ) -> list[str]:
        return self.manager.drain_notifications()

    # =========================================================
    # SHUTDOWN
    # =========================================================

    def shutdown(
        self,
    ) -> None:
        self.manager.shutdown()
