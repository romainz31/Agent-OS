from __future__ import annotations

import unicodedata
from typing import Any

from agentos.autonomy import AutonomyController
from agentos.hierarchy import MissionHierarchy
from agentos.skills import SkillRegistry
from agentos.runtime import AgentOSRuntime as CoreRuntime


class AutonomousRuntime(CoreRuntime):
    """Runtime Agent-OS V5.2 : autonomie + workload + hiérarchie + skills."""

    VERSION = "5.2"

    def _recover_active_work(self) -> dict[str, Any]:
        # CoreRuntime.__init__ appelle cette méthode avant que les contrôleurs
        # V5.x existent. On diffère la reprise jusqu'à ce que la politique de
        # workload et la hiérarchie soient branchées.
        if not hasattr(self, "autonomy"):
            return {
                "deferred_v51": True,
                "task_recovery": {},
                "planning_recovery": {},
                "repair_recovery": {},
                "active_missions": [],
            }

        return super()._recover_active_work()

    def __init__(self) -> None:
        super().__init__()

        self.autonomy = AutonomyController(
            self.manager
        )

        if hasattr(
            self.manager,
            "set_autonomy_controller",
        ):
            self.manager.set_autonomy_controller(
                self.autonomy
            )

        self.hierarchy = MissionHierarchy(
            self.manager,
            self.autonomy,
        )

        self.skills = SkillRegistry(
            self.manager,
            self.hierarchy,
        )

        # Le moteur V5.0 relit cette politique à chaque arbitrage du backlog.
        # V5.1 ajoute l'héritage dynamique parent -> sous-mission.
        if hasattr(
            self.manager.engine,
            "set_schedule_provider",
        ):
            self.manager.engine.set_schedule_provider(
                self._schedule_for_task
            )

        if hasattr(
            self.manager.engine,
            "set_skill_provider",
        ):
            self.manager.engine.set_skill_provider(
                self._skill_context_for_task
            )

        # La récupération historique avait été différée pendant
        # CoreRuntime.__init__. Elle peut maintenant respecter priorités,
        # deadlines et hiérarchie dès le premier arbitrage.
        self.recovery = super()._recover_active_work()

        self.autonomy.check_once()
        self.autonomy.start()

    # =========================================================
    # V5.x WORKLOAD POLICY
    # =========================================================

    def _schedule_for_task(
        self,
        task,
    ) -> dict[str, Any]:
        metadata = (
            task.metadata
            if isinstance(
                task.metadata,
                dict,
            )
            else {}
        )

        mission_id = metadata.get(
            "mission_id"
        )

        if not mission_id:
            return {
                "priority": "normal",
                "deadline": None,
                "mission": None,
            }

        mission = self.manager.missions.get(
            mission_id
        )

        if mission is None:
            return {
                "priority": "normal",
                "deadline": None,
                "mission": None,
            }

        policy = self.hierarchy.effective_policy(
            mission
        )

        return {
            "priority": policy.get(
                "priority",
                "normal",
            ),
            "deadline": policy.get(
                "deadline"
            ),
            "mission": mission.human_id,
        }

    @staticmethod
    def _normalize(
        text: str,
    ) -> str:
        value = unicodedata.normalize(
            "NFKD",
            str(text or ""),
        )
        value = "".join(
            char
            for char in value
            if not unicodedata.combining(char)
        )
        return " ".join(
            value.lower().strip().split()
        )

    def workload_status(self) -> dict[str, Any]:
        if not hasattr(
            self.manager.engine,
            "workload_snapshot",
        ):
            return {
                "available": False,
            }

        result = self.manager.engine.workload_snapshot()
        result["available"] = True
        return result

    # =========================================================
    # V5.2 SKILL REGISTRY
    # =========================================================

    def _skill_context_for_task(
        self,
        task,
    ) -> dict[str, Any]:
        return self.skills.context_for_task(
            task,
            record_usage=True,
        )

    def skills_status(self) -> dict[str, Any]:
        result = self.skills.snapshot()
        result["available"] = True
        return result

    def skill_detail(
        self,
        name: str,
    ) -> dict[str, Any]:
        skill = self.skills.get(name)
        if skill is None:
            raise KeyError(
                f"Compétence {name} introuvable."
            )
        result = dict(skill)
        result["freshness"] = (
            self.skills.freshness(skill)
        )
        result["effective_confidence"] = (
            self.skills.effective_confidence(skill)
        )
        return result

    # =========================================================
    # V5.1 HIERARCHY API
    # =========================================================

    def hierarchy_status(self) -> dict[str, Any]:
        return self.hierarchy.snapshot()

    def hierarchy_tree(
        self,
        reference: str,
    ) -> dict[str, Any]:
        return self.hierarchy.tree_payload(
            reference
        )

    # =========================================================
    # STATUS / CHAT
    # =========================================================

    def status(self) -> dict[str, Any]:
        result = dict(
            super().status()
        )

        if hasattr(self, "autonomy"):
            result["autonomy"] = (
                self.autonomy.snapshot()
            )

        if hasattr(
            self.manager.engine,
            "workload_snapshot",
        ):
            result["workload"] = (
                self.manager.engine.workload_snapshot()
            )

        if hasattr(self, "hierarchy"):
            result["hierarchy"] = (
                self.hierarchy.snapshot()
            )

        if hasattr(self, "skills"):
            result["skills"] = (
                self.skills.snapshot()
            )

        return result

    def handle_message(
        self,
        message: str,
    ) -> dict[str, Any]:
        value = str(
            message
        ).strip()

        skill_response = self.skills.command_response(
            value
        )
        if skill_response is not None:
            return {
                "response": skill_response,
                "handled_by": "skills",
                "status": self.status(),
            }

        hierarchy_response = (
            self.hierarchy.command_response(
                value
            )
        )
        if hierarchy_response is not None:
            return {
                "response": hierarchy_response,
                "handled_by": "hierarchy",
                "status": self.status(),
            }

        normalized = self._normalize(
            value
        )

        workload_commands = {
            "workload status",
            "manager workload",
            "charge manager",
            "charge equipe",
            "charge de l equipe",
            "file de travail",
        }

        backlog_commands = {
            "backlog",
            "backlog status",
            "file d attente",
            "file attente",
            "taches en attente",
            "travail en attente",
        }

        workers_commands = {
            "workers status",
            "worker status",
            "etat workers",
            "etat des workers",
            "agents disponibles",
            "qui travaille",
        }

        if (
            normalized in workload_commands
            and hasattr(
                self.manager.engine,
                "workload_summary",
            )
        ):
            return {
                "response": (
                    self.manager.engine
                    .workload_summary()
                ),
                "handled_by": "workload",
                "status": self.status(),
            }

        if (
            normalized in backlog_commands
            and hasattr(
                self.manager.engine,
                "backlog_summary",
            )
        ):
            return {
                "response": (
                    self.manager.engine
                    .backlog_summary()
                ),
                "handled_by": "workload",
                "status": self.status(),
            }

        if (
            normalized in workers_commands
            and hasattr(
                self.manager.engine,
                "workers_summary",
            )
        ):
            return {
                "response": (
                    self.manager.engine
                    .workers_summary()
                ),
                "handled_by": "workload",
                "status": self.status(),
            }

        return super().handle_message(
            value
        )

    # =========================================================
    # EXISTING V4.9 / V5.0 ENDPOINT HELPERS
    # =========================================================

    def autonomy_status(self) -> dict[str, Any]:
        return self.autonomy.snapshot()

    def autonomy_decisions(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.autonomy.lock:
            return list(
                self.autonomy.decisions[
                    -max(1, int(limit)):
                ]
            )

    def autonomy_check(self) -> dict[str, Any]:
        return self.autonomy.check_once()

    def conversation_status(self) -> dict[str, Any]:
        tracker = getattr(
            self.manager,
            "conversation_tracker",
            None,
        )
        if tracker is None:
            return {
                "available": False,
            }
        result = tracker.snapshot()
        result["available"] = True
        return result

    def conversation_history(self) -> list[dict[str, Any]]:
        tracker = getattr(
            self.manager,
            "conversation_tracker",
            None,
        )
        if tracker is None:
            return []
        with tracker.lock:
            return [
                dict(item)
                for item in tracker.data.get("history", [])
                if isinstance(item, dict)
            ]

    def research_status(self) -> dict[str, Any]:
        gateway = getattr(
            self.manager,
            "research_gateway",
            None,
        )
        if gateway is None:
            return {"available": False}
        result = gateway.snapshot()
        result["available"] = True
        return result

    def research_history(self) -> list[dict[str, Any]]:
        gateway = getattr(
            self.manager,
            "research_gateway",
            None,
        )
        if gateway is None:
            return []
        with gateway.lock:
            return [
                dict(item)
                for item in gateway.data.get("history", [])
                if isinstance(item, dict)
            ]

    def shutdown(self) -> None:
        if hasattr(self, "autonomy"):
            self.autonomy.stop()
        super().shutdown()
