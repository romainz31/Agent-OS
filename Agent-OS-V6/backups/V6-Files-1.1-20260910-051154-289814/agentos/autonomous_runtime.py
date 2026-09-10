from __future__ import annotations

import unicodedata
from typing import Any

from agentos import __version__
from agentos.autonomy import AutonomyController
from agentos.hierarchy import MissionHierarchy
from agentos.skills import SkillRegistry
from agentos.specialists import SpecialistManager, SpecializedWorkerAdapter
from agentos.learning import SkillLearningManager, LearningResearcherAdapter
from agentos.collaboration import CollaborationManager, CollaborativeWorkerAdapter
from agentos.runtime import AgentOSRuntime as CoreRuntime


class AutonomousRuntime(CoreRuntime):
    """Runtime Agent-OS V5.5 : autonomie + workload + hiérarchie + skills + apprentissage + collaboration."""

    VERSION = __version__

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

        # V5.3 : les workers existants sont enveloppés à chaud. Aucun agent
        # Python supplémentaire n'est créé ; le profil spécialiste est calculé
        # à partir des skills requis au moment de l'exécution.
        self.specialists = SpecialistManager(
            self.skills,
            self.manager,
        )
        for worker_name, worker in list(
            self.manager.engine.workers.items()
        ):
            if isinstance(worker, SpecializedWorkerAdapter):
                continue
            self.manager.engine.register(
                SpecializedWorkerAdapter(
                    worker,
                    self.specialists,
                )
            )

        # V5.5 : le contrôleur d'apprentissage intervient AVANT le lancement
        # réel d'une tâche. Un skill manquant crée une dépendance Researcher ;
        # le worker métier n'occupe donc aucun slot pendant sa formation.
        self.learning = SkillLearningManager(
            self.manager,
            self.skills,
            self.hierarchy,
        )
        if hasattr(self.manager.engine, "set_preparation_provider"):
            self.manager.engine.set_preparation_provider(
                self.learning.prepare_task
            )

        # Le Researcher spécialisé est ensuite enveloppé pour transformer les
        # recherches marquées skill_learning en connaissances persistantes.
        researcher = self.manager.engine.workers.get("researcher")
        if researcher is not None and not isinstance(
            researcher, LearningResearcherAdapter
        ):
            self.manager.engine.register(
                LearningResearcherAdapter(
                    researcher,
                    self.learning,
                )
            )

        # V5.5 : enveloppe finale de collaboration. Elle se place après la
        # spécialisation et l'adaptateur Learning du Researcher afin de pouvoir
        # suspendre proprement n'importe quel worker, créer un renfort et le
        # reprendre ensuite avec la réponse du collègue.
        self.collaboration = CollaborationManager(
            self.manager,
            max_requests_per_task=2,
        )
        for worker_name, worker in list(
            self.manager.engine.workers.items()
        ):
            if isinstance(worker, CollaborativeWorkerAdapter):
                continue
            self.manager.engine.register(
                CollaborativeWorkerAdapter(
                    worker,
                    self.collaboration,
                )
            )

        if hasattr(self.manager.engine, "set_collaboration_handler"):
            self.manager.engine.set_collaboration_handler(
                self.collaboration.handle_request
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
    # V5.3 DYNAMIC SPECIALISTS
    # =========================================================

    def specialists_status(self) -> dict[str, Any]:
        result = self.specialists.snapshot()
        result["available"] = True
        return result

    def specialist_detail(
        self,
        reference: str,
    ) -> dict[str, Any]:
        profiles = self.specialists.profile_for_mission(
            reference
        )
        return {
            "mission": str(reference).upper(),
            "profiles": profiles,
        }

    # =========================================================
    # V5.5 AUTONOMOUS LEARNING
    # =========================================================

    def learning_status(self) -> dict[str, Any]:
        result = self.learning.snapshot()
        result["available"] = True
        return result

    def learning_history(self) -> list[dict[str, Any]]:
        with self.learning.lock:
            return [
                dict(item)
                for item in self.learning.data.get("history", [])
                if isinstance(item, dict)
            ]

    # =========================================================
    # V5.5 INTER-AGENT COLLABORATION
    # =========================================================

    def collaboration_status(self) -> dict[str, Any]:
        result = self.collaboration.snapshot()
        result["available"] = True
        return result

    def collaboration_history(self) -> list[dict[str, Any]]:
        with self.collaboration.lock:
            return [
                dict(item)
                for item in self.collaboration.data.get("history", [])
                if isinstance(item, dict)
            ]

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

        if hasattr(self, "specialists"):
            result["specialists"] = (
                self.specialists.snapshot()
            )

        if hasattr(self, "learning"):
            result["learning"] = (
                self.learning.snapshot()
            )

        if hasattr(self, "collaboration"):
            result["collaboration"] = (
                self.collaboration.snapshot()
            )

        return result

    def handle_message(
        self,
        message: str,
    ) -> dict[str, Any]:
        # V6-FILES 1.0 — approved document operations
        from agentos.file_assistant import dispatch_file_message
        file_response = dispatch_file_message(self, message)
        if file_response is not None:
            return file_response

        value = str(
            message
        ).strip()

        collaboration_response = (
            self.collaboration.command_response(
                value
            )
        )
        if collaboration_response is not None:
            return {
                "response": collaboration_response,
                "handled_by": "collaboration",
                "status": self.status(),
            }

        learning_response = (
            self.learning.command_response(
                value
            )
        )
        if learning_response is not None:
            return {
                "response": learning_response,
                "handled_by": "learning",
                "status": self.status(),
            }

        specialist_response = (
            self.specialists.command_response(
                value
            )
        )
        if specialist_response is not None:
            return {
                "response": specialist_response,
                "handled_by": "specialists",
                "status": self.status(),
            }

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
        if hasattr(self, "file_assistant"):
            self.file_assistant.close()
        if hasattr(self, "autonomy"):
            self.autonomy.stop()
        super().shutdown()
