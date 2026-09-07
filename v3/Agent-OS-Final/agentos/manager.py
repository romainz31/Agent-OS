from __future__ import annotations

import re
import threading

from agentos.approvals import ApprovalManager
from agentos.engine import WorkerEngine
from agentos.llm import LLM, LLMError
from agentos.memory import Memory
from agentos.missions import MissionManager
from agentos.orchestrator import Orchestrator
from agentos.permissions import PermissionEngine
from agentos.planner import Planner
from agentos.project_files import ProjectFiles
from agentos.python_runner import PythonRunner
from agentos.router import Router
from agentos.tasks import TaskManager
from agentos.workers import (
    AIWorker,
    DeveloperWorker,
    ResearcherWorker,
    TesterWorker,
)


class Manager:
    TASK_ID_RE = re.compile(
        r"(task_[A-Za-z0-9]+)"
    )

    MISSION_REF_RE = re.compile(
        r"\bM-\d{1,6}\b",
        flags=re.IGNORECASE,
    )

    ACTIVE_STATUSES = {
        "planning",
        "queued",
        "running",
        "waiting_approval",
        "paused",
    }

    STATUS_LABELS = {
        "planning": "préparation",
        "queued": "en attente",
        "running": "en cours",
        "waiting_approval": "attend ton autorisation",
        "paused": "en pause",
        "completed": "terminée",
        "failed": "échouée",
        "rejected": "refusée",
        "cancelled": "annulée",
    }

    PROGRESS_MARKERS = (
        "ça avance",
        "ca avance",
        "où ça en est",
        "ou ca avance",
        "ou ca en est",
        "où en est",
        "ou en est",
        "avancement",
        "progression",
        "quelles missions",
        "mes missions",
        "mission en cours",
        "missions en cours",
    )

    OPERATIONAL_MARKERS = (
        "combien de missions",
        "nombre de missions",
        "missions totales",
        "mission totale",
        "missions terminées",
        "missions terminees",
        "missions échouées",
        "missions echouees",
        "missions refusées",
        "missions refusees",
        "missions annulées",
        "missions annulees",
        "état des missions",
        "etat des missions",
        "état de l'équipe",
        "etat de l'equipe",
        "etat de l'équipe",
        "état de lequipe",
        "bilan des missions",
        "bilan de nos missions",
        "qui travaille",
        "qui bosse",
        "qui est occupé",
        "qui est occupe",
        "worker occup",
        "workers occup",
        "developer occup",
        "researcher occup",
        "tester occup",
        "ai worker occup",
        "developer disponible",
        "researcher disponible",
        "tester disponible",
        "ai worker disponible",
        "qu'est-ce qui tourne",
        "qu est ce qui tourne",
        "qu'est ce qui tourne",
        "tu fais quoi en ce moment",
        "on fait quoi en ce moment",
        "on a beaucoup de boulot",
        "quelle mission j'ai refus",
        "quelles missions j'ai refus",
        "quelle mission a échoué",
        "quelles missions ont échoué",
        "dernière mission",
        "derniere mission",
        "missions récentes",
        "missions recentes",
    )

    RECENT_MISSION_LIMIT = 8
    SPECIAL_HISTORY_LIMIT = 5

    def __init__(self) -> None:
        self.llm = LLM()
        self.memory = Memory()
        self.permissions = PermissionEngine()
        self.tasks = TaskManager()
        self.missions = MissionManager()
        self.router = Router()

        self.files = ProjectFiles(
            self.permissions
        )

        self.runner = PythonRunner(
            self.permissions
        )

        self._lock = threading.RLock()
        self._notifications: list[str] = []
        self._mission_status_cache: dict[str, str] = {}

        # =====================================================
        # ENGINE
        # =====================================================

        self.engine = WorkerEngine(
            self.tasks,
            self.notify,
        )

        self.engine.register(
            AIWorker(
                self.llm
            )
        )

        self.engine.register(
            ResearcherWorker(
                self.llm,
                self.permissions,
            )
        )

        self.engine.register(
            DeveloperWorker(
                self.llm,
                self.files,
                self.runner,
            )
        )

        self.engine.register(
            TesterWorker(
                self.llm,
                self.files,
                self.runner,
            )
        )

        # =====================================================
        # APPROVALS
        # =====================================================

        self.approvals = ApprovalManager(
            self.tasks,
            self.files,
            self.runner,
            self.engine.resume_dependents,
        )

        # =====================================================
        # ORCHESTRATION
        # =====================================================

        self.planner = Planner(
            self.llm
        )

        self.orchestrator = Orchestrator(
            planner=self.planner,
            missions=self.missions,
            tasks=self.tasks,
            engine=self.engine,
        )

    # =========================================================
    # NOTIFICATIONS
    # =========================================================

    def _append_notification(
        self,
        text: str,
    ) -> None:
        with self._lock:
            self._notifications.append(
                text
            )

    def drain_notifications(
        self,
    ) -> list[str]:
        with self._lock:
            values = list(
                self._notifications
            )
            self._notifications.clear()
            return values

    # =========================================================
    # EVENT HELPERS
    # =========================================================

    def _task_from_event(
        self,
        text: str,
    ):
        match = self.TASK_ID_RE.search(
            text
        )

        if match is None:
            return None

        return self.tasks.get(
            match.group(1)
        )

    def _mission_for_task(
        self,
        task,
    ):
        if task is None:
            return None

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
            return None

        return self.missions.get(
            mission_id
        )

    def _status_label(
        self,
        status: str,
    ) -> str:
        return self.STATUS_LABELS.get(
            status,
            status,
        )

    # =========================================================
    # HUMANIZED WORKER EVENTS
    # =========================================================

    def _humanize_task_event(
        self,
        text: str,
    ) -> str | None:
        task = self._task_from_event(
            text
        )

        if task is None:
            return text

        mission = self._mission_for_task(
            task
        )

        mission_ref = (
            mission.human_id
            if mission
            else "Mission"
        )

        if "attend ton approbation" in text:
            data = (
                task.result_data
                if isinstance(
                    task.result_data,
                    dict,
                )
                else {}
            )

            files = (
                data.get(
                    "approval_required_files",
                    [],
                )
                or []
            )

            file_text = "\n".join(
                f"- {path}"
                for path in files
            )

            return (
                f"{mission_ref} — "
                "la modification est prête.\n\n"
                "J'ai besoin de ton autorisation "
                "pour modifier :\n"
                f"{file_text}\n\n"
                "Tu valides ?"
            )

        if text.startswith("✗"):
            error = str(
                task.error
                or ""
            )

            if (
                error.startswith(
                    "Dépendance échouée"
                )
                or error in {
                    "approval_rejected",
                    "approval_rejected_dependency",
                }
            ):
                return None

            detail = (
                task.error
                or task.result
                or "erreur inconnue"
            )

            return (
                f"{mission_ref} — "
                "une étape a rencontré un problème.\n\n"
                f"Étape : {task.title}\n"
                f"Détail : {detail}"
            )

        if text.startswith("✓"):
            if task.worker == "researcher":
                return (
                    f"{mission_ref} — "
                    "la recherche est terminée. "
                    "Je poursuis."
                )

            if task.worker == "developer":
                return (
                    f"{mission_ref} — "
                    "le développement est terminé. "
                    "Je lance les vérifications."
                )

            if task.worker == "tester":
                return (
                    f"{mission_ref} — "
                    "les vérifications sont terminées."
                )

            if task.worker == "ai_worker":
                return (
                    f"{mission_ref} — "
                    "l'analyse est terminée."
                )

        return None

    # =========================================================
    # MISSION RESULT EXTRACTION
    # =========================================================

    def _mission_results(
        self,
        mission,
    ) -> dict:
        modified: list[str] = []
        created: list[str] = []
        tested: list[str] = []
        intellectual_results: list[str] = []
        sources: list[dict] = []

        for task_id in mission.task_ids:
            task = self.tasks.get(
                task_id
            )

            if task is None:
                continue

            data = (
                task.result_data
                if isinstance(
                    task.result_data,
                    dict,
                )
                else {}
            )

            for path in (
                data.get(
                    "modified_files",
                    [],
                )
                or []
            ):
                if path not in modified:
                    modified.append(
                        path
                    )

            for path in (
                data.get(
                    "created_files",
                    [],
                )
                or []
            ):
                if path not in created:
                    created.append(
                        path
                    )

            if task.worker == "tester":
                for path in (
                    data.get(
                        "targets",
                        [],
                    )
                    or []
                ):
                    if path not in tested:
                        tested.append(
                            path
                        )

            if (
                task.worker == "ai_worker"
                and task.status == "completed"
            ):
                result = str(
                    task.result
                    or ""
                ).strip()

                if (
                    result
                    and result
                    not in intellectual_results
                ):
                    intellectual_results.append(
                        result
                    )

            if task.worker == "researcher":
                raw_sources = (
                    data.get(
                        "sources",
                        [],
                    )
                    or []
                )

                for source in raw_sources:
                    if not isinstance(
                        source,
                        dict,
                    ):
                        continue

                    url = str(
                        source.get(
                            "url",
                            "",
                        )
                    ).strip()

                    title = str(
                        source.get(
                            "title",
                            "",
                        )
                    ).strip()

                    if not url:
                        continue

                    if any(
                        existing.get("url")
                        == url
                        for existing in sources
                    ):
                        continue

                    sources.append(
                        {
                            "title": title,
                            "url": url,
                        }
                    )

        return {
            "modified": modified,
            "created": created,
            "tested": tested,
            "intellectual_results": (
                intellectual_results
            ),
            "sources": sources,
        }

    def _mission_summary(
        self,
        mission,
    ) -> str:
        results = self._mission_results(
            mission
        )

        lines = [
            f"{mission.human_id} — mission terminée.",
            "",
            mission.title,
        ]

        intellectual_results = results[
            "intellectual_results"
        ]

        if intellectual_results:
            lines.extend(
                [
                    "",
                    "Résultat :",
                    "",
                    intellectual_results[-1],
                ]
            )

        sources = results[
            "sources"
        ]

        if sources:
            lines.extend(
                [
                    "",
                    "Sources utilisées :",
                ]
            )

            for index, source in enumerate(
                sources,
                1,
            ):
                title = (
                    source.get("title")
                    or "Source"
                )
                url = source.get(
                    "url",
                    "",
                )

                lines.append(
                    f"{index}. {title}\n   {url}"
                )

        modified = results[
            "modified"
        ]

        if modified:
            lines.extend(
                [
                    "",
                    "Fichier(s) modifié(s) :",
                    *(
                        f"- {path}"
                        for path in modified
                    ),
                ]
            )

        created = results[
            "created"
        ]

        if created:
            lines.extend(
                [
                    "",
                    "Fichier(s) créé(s) :",
                    *(
                        f"- {path}"
                        for path in created
                    ),
                ]
            )

        tested = results[
            "tested"
        ]

        if tested:
            lines.extend(
                [
                    "",
                    "Vérification :",
                    *(
                        f"- {path}"
                        for path in tested
                    ),
                ]
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # MISSION REFRESH / NOTIFICATIONS
    # =========================================================

    def _refresh_mission(
        self,
        mission,
    ) -> None:
        if mission is None:
            return

        previous = self._mission_status_cache.get(
            mission.id
        )

        self.missions.refresh(
            mission,
            self.tasks,
        )

        current = mission.status

        self._mission_status_cache[
            mission.id
        ] = current

        if previous == current:
            return

        if current == "completed":
            summary = self._mission_summary(
                mission
            )

            self._append_notification(
                summary
            )

            self.memory.add_session(
                "system",
                summary,
            )

        elif current == "failed":
            self._append_notification(
                f"{mission.human_id} — "
                "la mission s'est arrêtée "
                "à cause d'une erreur."
            )

        elif current == "cancelled":
            self._append_notification(
                f"{mission.human_id} — mission annulée."
            )

        elif current == "rejected":
            self._append_notification(
                f"{mission.human_id} — mission refusée. "
                "La modification n'a pas été appliquée."
            )

    def notify(
        self,
        text: str,
    ) -> None:
        task = self._task_from_event(
            text
        )

        human = self._humanize_task_event(
            text
        )

        if human:
            self._append_notification(
                human
            )

        mission = self._mission_for_task(
            task
        )

        self._refresh_mission(
            mission
        )

    # =========================================================
    # COMMAND NORMALIZATION
    # =========================================================

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

    def _extract_mission_reference(
        self,
        message: str,
    ) -> str | None:
        match = self.MISSION_REF_RE.search(
            message
        )

        if not match:
            return None

        raw = match.group(0).upper()
        number = int(
            raw.split("-")[1]
        )

        return f"M-{number:03d}"

    # =========================================================
    # APPROVAL / REJECTION
    # =========================================================

    @classmethod
    def _looks_like_approval(
        cls,
        message: str,
    ) -> bool:
        value = cls._normalize(
            message
        )

        starters = (
            "oui",
            "yes",
            "ok",
            "okay",
            "go",
            "vas y",
            "je valide",
            "valide",
            "autorise",
            "j'autorise",
            "jautorise",
            "je confirme",
        )

        return any(
            value == marker
            or value.startswith(
                marker + " "
            )
            for marker in starters
        )

    @classmethod
    def _looks_like_rejection(
        cls,
        message: str,
    ) -> bool:
        value = cls._normalize(
            message
        )

        starters = (
            "non",
            "no",
            "refuse",
            "je refuse",
            "annule",
            "stop",
            "ne fais pas",
            "ne modifie pas",
        )

        return any(
            value == marker
            or value.startswith(
                marker + " "
            )
            for marker in starters
        )

    def _pending_approval_summary(
        self,
    ) -> str:
        pending = self.approvals.pending()

        if not pending:
            return (
                "Aucune autorisation en attente."
            )

        lines = [
            (
                "Plusieurs missions attendent "
                "une autorisation."
                if len(pending) > 1
                else
                "Une mission attend une autorisation."
            )
        ]

        for task in pending:
            mission = self._mission_for_task(
                task
            )

            ref = (
                mission.human_id
                if mission
                else "?"
            )

            title = (
                mission.title
                if mission
                else task.title
            )

            lines.append(
                f"- {ref} : {title}"
            )

        if len(pending) > 1:
            lines.extend(
                [
                    "",
                    'Réponds par exemple : "oui M-002".',
                ]
            )

        return "\n".join(
            lines
        )

    def _approve(
        self,
        message: str,
    ) -> str:
        pending = self.approvals.pending()

        if not pending:
            return (
                "Aucune autorisation en attente."
            )

        reference = self._extract_mission_reference(
            message
        )

        if reference:
            mission = self.missions.resolve(
                reference
            )

            if mission is None:
                return (
                    f"Je ne trouve pas la mission {reference}."
                )

            candidates = self.approvals.pending_for_mission(
                mission.id
            )

            if not candidates:
                return (
                    f"{mission.human_id} "
                    "n'attend aucune autorisation."
                )

            task = candidates[0]

        elif len(pending) == 1:
            task = pending[0]
            mission = self._mission_for_task(
                task
            )

        else:
            return self._pending_approval_summary()

        result = self.approvals.approve_task(
            task.id
        )

        mission = self._mission_for_task(
            task
        )
        self._refresh_mission(
            mission
        )

        if result.startswith(
            "Approbation non"
        ):
            return result

        ref = (
            mission.human_id
            if mission
            else "Mission"
        )

        return (
            f"{ref} validée.\n\n"
            "La modification a été appliquée. "
            "Je poursuis automatiquement la mission."
        )

    def _reject(
        self,
        message: str,
    ) -> str:
        pending = self.approvals.pending()

        if not pending:
            return (
                "Aucune autorisation en attente."
            )

        reference = self._extract_mission_reference(
            message
        )

        if reference:
            mission = self.missions.resolve(
                reference
            )

            if mission is None:
                return (
                    f"Mission {reference} introuvable."
                )

            candidates = self.approvals.pending_for_mission(
                mission.id
            )

            if not candidates:
                return (
                    f"{reference} "
                    "n'attend aucune autorisation."
                )

            task = candidates[0]

        elif len(pending) == 1:
            task = pending[0]

        else:
            return self._pending_approval_summary()

        result = self.approvals.reject_task(
            task.id
        )

        mission = self._mission_for_task(
            task
        )
        self._refresh_mission(
            mission
        )

        return result

    # =========================================================
    # OPERATIONAL AWARENESS — V4.1
    # =========================================================

    def _all_missions_refreshed(
        self,
    ) -> list:
        missions = self.missions.list()

        for mission in missions:
            self.missions.refresh(
                mission,
                self.tasks,
            )

        return missions

    def _mission_counts(
        self,
        missions: list,
    ) -> dict[str, int]:
        counts = {
            "planning": 0,
            "queued": 0,
            "running": 0,
            "waiting_approval": 0,
            "paused": 0,
            "completed": 0,
            "failed": 0,
            "rejected": 0,
            "cancelled": 0,
        }

        for mission in missions:
            counts.setdefault(
                mission.status,
                0,
            )
            counts[mission.status] += 1

        counts["total"] = len(
            missions
        )

        counts["active"] = sum(
            counts.get(
                status,
                0,
            )
            for status in self.ACTIVE_STATUSES
        )

        return counts

    def _worker_snapshot(
        self,
    ) -> list[dict]:
        running_tasks = [
            task
            for task in self.tasks.list()
            if task.status == "running"
        ]

        workers = []

        for worker_name in self.engine.workers:
            worker_tasks = [
                task
                for task in running_tasks
                if task.worker == worker_name
            ]

            mission_refs: list[str] = []
            task_titles: list[str] = []

            for task in worker_tasks:
                task_titles.append(
                    task.title
                )

                mission = self._mission_for_task(
                    task
                )

                if (
                    mission is not None
                    and mission.human_id
                    not in mission_refs
                ):
                    mission_refs.append(
                        mission.human_id
                    )

            workers.append(
                {
                    "name": worker_name,
                    "status": (
                        "busy"
                        if worker_tasks
                        else "available"
                    ),
                    "missions": mission_refs,
                    "task_titles": task_titles,
                }
            )

        return workers

    def _mission_context_line(
        self,
        mission,
    ) -> str:
        completed, total = self.missions.progress(
            mission,
            self.tasks,
        )

        return (
            f"{mission.human_id} | "
            f"{self._status_label(mission.status)} | "
            f"{completed}/{total} | "
            f"{mission.title}"
        )

    def _operational_snapshot(
        self,
    ) -> dict:
        missions = self._all_missions_refreshed()
        counts = self._mission_counts(
            missions
        )

        active = [
            mission
            for mission in missions
            if mission.status in self.ACTIVE_STATUSES
        ]

        recent = missions[
            : self.RECENT_MISSION_LIMIT
        ]

        rejected = [
            mission
            for mission in missions
            if mission.status == "rejected"
        ][
            : self.SPECIAL_HISTORY_LIMIT
        ]

        failed = [
            mission
            for mission in missions
            if mission.status == "failed"
        ][
            : self.SPECIAL_HISTORY_LIMIT
        ]

        pending_approvals = self.approvals.pending()

        with self.engine.lock:
            running_jobs = len(
                self.engine.running
            )

        return {
            "counts": counts,
            "workers": self._worker_snapshot(),
            "active": active,
            "recent": recent,
            "rejected": rejected,
            "failed": failed,
            "pending_approvals": (
                pending_approvals
            ),
            "running_jobs": running_jobs,
            "total_tasks": len(
                self.tasks.tasks
            ),
        }

    def _operational_context(
        self,
    ) -> str:
        snapshot = self._operational_snapshot()
        counts = snapshot[
            "counts"
        ]

        lines = [
            "RÉSUMÉ GLOBAL",
            (
                "Missions : "
                f"{counts['total']} totales | "
                f"{counts['active']} actives | "
                f"{counts['completed']} terminées | "
                f"{counts['failed']} échouées | "
                f"{counts['rejected']} refusées | "
                f"{counts['cancelled']} annulées"
            ),
            (
                "Détail actif : "
                f"{counts['planning']} préparation | "
                f"{counts['queued']} attente | "
                f"{counts['running']} en cours | "
                f"{counts['waiting_approval']} approbation | "
                f"{counts['paused']} pause"
            ),
            (
                "Tâches : "
                f"{snapshot['total_tasks']} totales | "
                f"{snapshot['running_jobs']} worker(s) "
                "en exécution"
            ),
            (
                "Approbations en attente : "
                f"{len(snapshot['pending_approvals'])}"
            ),
            "",
            "ÉQUIPE",
        ]

        for worker in snapshot[
            "workers"
        ]:
            if worker[
                "status"
            ] == "busy":
                missions = (
                    ", ".join(
                        worker[
                            "missions"
                        ]
                    )
                    or "mission inconnue"
                )

                task_text = (
                    " / ".join(
                        worker[
                            "task_titles"
                        ][:2]
                    )
                )

                lines.append(
                    f"- {worker['name']} : OCCUPÉ | "
                    f"{missions} | {task_text}"
                )
            else:
                lines.append(
                    f"- {worker['name']} : DISPONIBLE"
                )

        lines.extend(
            [
                "",
                "MISSIONS ACTIVES",
            ]
        )

        active = snapshot[
            "active"
        ]

        if active:
            lines.extend(
                self._mission_context_line(
                    mission
                )
                for mission in active
            )
        else:
            lines.append(
                "Aucune mission active."
            )

        lines.extend(
            [
                "",
                "MISSIONS RÉCENTES",
            ]
        )

        recent = snapshot[
            "recent"
        ]

        if recent:
            lines.extend(
                self._mission_context_line(
                    mission
                )
                for mission in recent
            )
        else:
            lines.append(
                "Aucune mission enregistrée."
            )

        rejected = snapshot[
            "rejected"
        ]

        if rejected:
            lines.extend(
                [
                    "",
                    "DERNIÈRES MISSIONS REFUSÉES",
                    *(
                        self._mission_context_line(
                            mission
                        )
                        for mission in rejected
                    ),
                ]
            )

        failed = snapshot[
            "failed"
        ]

        if failed:
            lines.extend(
                [
                    "",
                    "DERNIÈRES MISSIONS ÉCHOUÉES",
                    *(
                        self._mission_context_line(
                            mission
                        )
                        for mission in failed
                    ),
                ]
            )

        return "\n".join(
            lines
        )

    @classmethod
    def _looks_like_operational_question(
        cls,
        message: str,
    ) -> bool:
        value = cls._normalize(
            message
        )

        return any(
            marker in value
            for marker in cls.OPERATIONAL_MARKERS
        )

    @staticmethod
    def _contains_any(
        value: str,
        markers: tuple[str, ...],
    ) -> bool:
        return any(
            marker in value
            for marker in markers
        )

    def _direct_operational_response(
        self,
        message: str,
    ) -> str | None:
        """Répond aux faits Agent-OS qui ne doivent jamais être devinés."""
        value = self._normalize(
            message
        )

        snapshot = self._operational_snapshot()
        counts = snapshot["counts"]

        # -----------------------------------------------------
        # DERNIÈRE MISSION REFUSÉE
        # -----------------------------------------------------
        asks_rejected = (
            "refus" in value
            and self._contains_any(
                value,
                (
                    "dernière mission",
                    "derniere mission",
                    "quelle mission",
                    "la dernière",
                    "la derniere",
                ),
            )
        )

        if asks_rejected:
            rejected = snapshot["rejected"]

            if not rejected:
                return (
                    "Tu n'as aucune mission refusée "
                    "dans l'historique."
                )

            mission = rejected[0]
            completed, total = self.missions.progress(
                mission,
                self.tasks,
            )

            return (
                "La dernière mission refusée est "
                f"{mission.human_id} — {mission.title}\n"
                f"Statut : refusée | Progression : "
                f"{completed}/{total}."
            )

        # -----------------------------------------------------
        # DERNIÈRE MISSION ÉCHOUÉE
        # -----------------------------------------------------
        asks_failed = (
            self._contains_any(
                value,
                (
                    "échou",
                    "echou",
                    "échec",
                    "echec",
                ),
            )
            and self._contains_any(
                value,
                (
                    "dernière mission",
                    "derniere mission",
                    "quelle mission",
                    "la dernière",
                    "la derniere",
                ),
            )
        )

        if asks_failed:
            failed = snapshot["failed"]

            if not failed:
                return (
                    "Aucune mission échouée "
                    "dans l'historique."
                )

            mission = failed[0]
            completed, total = self.missions.progress(
                mission,
                self.tasks,
            )

            return (
                "La dernière mission échouée est "
                f"{mission.human_id} — {mission.title}\n"
                f"Progression : {completed}/{total}."
            )

        # -----------------------------------------------------
        # QUI TRAVAILLE / SUR QUOI
        # -----------------------------------------------------
        if self._contains_any(
            value,
            (
                "qui travaille",
                "qui bosse",
                "qui est occup",
                "workers occup",
                "worker occup",
                "équipe travaille",
                "equipe travaille",
            ),
        ):
            busy = [
                worker
                for worker in snapshot["workers"]
                if worker["status"] == "busy"
            ]

            if not busy:
                return (
                    "Personne ne travaille actuellement : "
                    "AI Worker, Researcher, Developer et Tester "
                    "sont tous disponibles."
                )

            lines = [
                "En ce moment :"
            ]

            for worker in busy:
                missions = (
                    ", ".join(worker["missions"])
                    or "mission inconnue"
                )
                tasks = (
                    " / ".join(worker["task_titles"][:2])
                    or "tâche en cours"
                )
                lines.append(
                    f"- {worker['name']} : {missions} — {tasks}"
                )

            available = [
                worker["name"]
                for worker in snapshot["workers"]
                if worker["status"] == "available"
            ]

            if available:
                lines.append(
                    "Disponibles : "
                    + ", ".join(available)
                    + "."
                )

            return "\n".join(lines)

        # -----------------------------------------------------
        # NOMBRE DE MISSIONS
        # -----------------------------------------------------
        if self._contains_any(
            value,
            (
                "combien de missions",
                "nombre de missions",
                "missions totales",
                "mission totale",
            ),
        ):
            return (
                f"Nous avons {counts['total']} missions enregistrées "
                f"au total, dont {counts['active']} active(s).\n"
                f"Terminées : {counts['completed']} | "
                f"Échouées : {counts['failed']} | "
                f"Refusées : {counts['rejected']} | "
                f"Annulées : {counts['cancelled']}."
            )

        # -----------------------------------------------------
        # CHARGE DE TRAVAIL
        # -----------------------------------------------------
        if self._contains_any(
            value,
            (
                "beaucoup de boulot",
                "beaucoup de travail",
                "charge de travail",
                "on est chargé",
                "on est charge",
                "équipe chargée",
                "equipe chargee",
            ),
        ):
            busy_count = sum(
                1
                for worker in snapshot["workers"]
                if worker["status"] == "busy"
            )

            if (
                counts["active"] == 0
                and busy_count == 0
            ):
                return (
                    "Non. Il n'y a actuellement aucune mission active "
                    "et les 4 workers sont disponibles."
                )

            return (
                f"Nous avons {counts['active']} mission(s) active(s) "
                f"et {busy_count} worker(s) occupé(s) sur 4. "
                f"Approbations en attente : "
                f"{len(snapshot['pending_approvals'])}."
            )

        # -----------------------------------------------------
        # BILAN / MISSIONS RÉCENTES
        # -----------------------------------------------------
        if self._contains_any(
            value,
            (
                "bilan des missions",
                "bilan de nos missions",
                "bilan rapide",
                "missions récentes",
                "missions recentes",
            ),
        ):
            recent = snapshot["recent"][:5]

            lines = [
                (
                    f"Bilan : {counts['total']} missions au total, "
                    f"{counts['active']} active(s), "
                    f"{counts['completed']} terminée(s), "
                    f"{counts['failed']} échouée(s), "
                    f"{counts['rejected']} refusée(s), "
                    f"{counts['cancelled']} annulée(s)."
                )
            ]

            if recent:
                lines.append("Dernières missions :")
                lines.extend(
                    "- " + self._mission_context_line(mission)
                    for mission in recent
                )

            return "\n".join(lines)

        # -----------------------------------------------------
        # DERNIÈRE MISSION, TOUS STATUTS
        # -----------------------------------------------------
        if self._contains_any(
            value,
            (
                "dernière mission",
                "derniere mission",
            ),
        ):
            recent = snapshot["recent"]

            if not recent:
                return "Aucune mission enregistrée."

            mission = recent[0]
            return (
                "La dernière mission enregistrée est :\n"
                + self._mission_context_line(mission)
            )

        return None

    # =========================================================
    # PROGRESS
    # =========================================================

    @classmethod
    def _looks_like_progress_question(
        cls,
        message: str,
    ) -> bool:
        value = message.lower()

        return any(
            marker in value
            for marker in cls.PROGRESS_MARKERS
        )

    def _progress_summary(
        self,
        message: str = "",
    ) -> str:
        reference = self._extract_mission_reference(
            message
        )

        if reference:
            mission = self.missions.resolve(
                reference
            )

            if mission is None:
                return (
                    f"Mission {reference} introuvable."
                )

            missions = [
                mission
            ]

        else:
            missions = self.missions.active(
                self.tasks
            )

        if not missions:
            total = len(
                self.missions.missions
            )

            return (
                "Aucune mission active pour le moment.\n"
                f"Missions enregistrées au total : {total}."
            )

        lines: list[str] = []

        for mission in missions:
            self.missions.refresh(
                mission,
                self.tasks,
            )

            completed, total = self.missions.progress(
                mission,
                self.tasks,
            )

            lines.append(
                f"{mission.human_id} — {mission.title}\n"
                f"Statut : {self._status_label(mission.status)}\n"
                f"Progression : {completed}/{total}"
            )

        return "\n\n".join(
            lines
        )

    # =========================================================
    # CONVERSATION
    # =========================================================

    def _conversation(
        self,
        message: str,
    ) -> str:
        system = """
Tu es le Manager personnel d'Agent-OS.

Tu es l'interlocuteur principal de l'utilisateur et le chef
d'équipe des workers Agent-OS.

Tu peux parler normalement de n'importe quel sujet. Ne ramène
jamais spontanément une discussion à Agent-OS si ce n'est pas
pertinent.

Le bloc ÉTAT AGENT-OS fourni dans le contexte est une photographie
factuelle et actuelle du moteur. Utilise exclusivement ces données
pour parler des missions, workers, approbations et progressions.

Fais toujours la différence entre :
- le nombre total de missions enregistrées ;
- les missions actuellement actives ;
- les missions terminées, échouées, refusées ou annulées.

Si l'utilisateur demande ce que fait l'équipe, qui est disponible,
ce qui tourne, une mission récente ou un bilan, réponds à partir de
cet état réel. N'invente jamais une mission, un statut, une
progression ou une occupation de worker.

Tu peux discuter pendant que des missions travaillent en arrière-plan.
Réponds naturellement en français et utilise toujours le tutoiement.
Pour une question simple, réponds de façon courte et directe.
N'ajoute pas de formule du type « n'hésite pas » ou de proposition générique
à la fin si l'utilisateur ne l'a pas demandée.
"""

        prompt = f"""
MÉMOIRE :

{self.memory.context()}

ÉTAT AGENT-OS :

{self._operational_context()}

MESSAGE :

{message}
"""

        try:
            return self.llm.chat(
                prompt,
                system=system,
            )

        except LLMError as exc:
            return (
                "Ollama inaccessible : "
                f"{exc}"
            )

    # =========================================================
    # STATUS
    # =========================================================

    def _status(
        self,
    ) -> str:
        return self._operational_context()

    # =========================================================
    # HANDLE
    # =========================================================

    def handle(
        self,
        message: str,
    ) -> str:
        value = message.strip()
        command = value.lower()

        if not value:
            return ""

        # Debug / direct commands
        if command == "tasks":
            return self.tasks.format()

        if command == "missions":
            return self.missions.format(
                self.tasks
            )

        if command == "approvals":
            return self.approvals.format()

        if command == "memory":
            return self.memory.format()

        if command == "status":
            return self._status()

        # Exact progress / mission reference queries
        if self._looks_like_progress_question(
            value
        ):
            return self._progress_summary(
                value
            )

        # Approvals
        if self._looks_like_approval(
            value
        ):
            return self._approve(
                value
            )

        if self._looks_like_rejection(
            value
        ):
            return self._reject(
                value
            )

        # Memory
        self.memory.add_session(
            "user",
            value,
        )
        self.memory.maybe_remember(
            value
        )

        # Operational facts: use deterministic code first.
        # This prevents the LLM from altering a mission id,
        # a status, a count or a worker occupation.
        direct_operational = (
            self._direct_operational_response(
                value
            )
        )

        if direct_operational is not None:
            self.memory.add_session(
                "assistant",
                direct_operational,
            )
            return direct_operational

        # Other operational questions remain conversational,
        # but the LLM still receives the factual snapshot.
        if self._looks_like_operational_question(
            value
        ):
            answer = self._conversation(
                value
            )

            self.memory.add_session(
                "assistant",
                answer,
            )

            return answer

        # Router
        route = self.router.route(
            value
        )

        if route.kind == "conversation":
            answer = self._conversation(
                value
            )

            self.memory.add_session(
                "assistant",
                answer,
            )

            return answer

        # New mission
        mission = self.orchestrator.create_mission(
            message=value,
            initial_worker=(
                route.worker
                or "ai_worker"
            ),
            router_reason=route.reason,
        )

        if mission is None:
            return (
                "Je n'ai pas pu créer la mission."
            )

        self._mission_status_cache[
            mission.id
        ] = mission.status

        response = (
            f"Mission {mission.human_id}\n\n"
            + self.orchestrator.format_created(
                mission
            )
        )

        self.memory.add_session(
            "assistant",
            response,
        )

        return response

    # =========================================================
    # SHUTDOWN
    # =========================================================

    def shutdown(
        self,
    ) -> None:
        self.engine.shutdown()
