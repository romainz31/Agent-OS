from __future__ import annotations

import re
import threading

from agentos.approvals import (
    ApprovalManager,
)

from agentos.engine import (
    WorkerEngine,
)

from agentos.llm import (
    LLM,
    LLMError,
)

from agentos.memory import (
    Memory,
)

from agentos.missions import (
    MissionManager,
)

from agentos.orchestrator import (
    Orchestrator,
)

from agentos.permissions import (
    PermissionEngine,
)

from agentos.planner import (
    Planner,
)

from agentos.project_files import (
    ProjectFiles,
)

from agentos.python_runner import (
    PythonRunner,
)

from agentos.router import (
    Router,
)

from agentos.tasks import (
    TaskManager,
)

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

    PROGRESS_MARKERS = (
        "ça avance",
        "ca avance",
        "où ça en est",
        "ou ca en est",
        "où en est",
        "ou en est",
        "avancement",
        "progression",
        "quelles missions",
        "mes missions",
    )

    def __init__(
        self,
    ) -> None:

        self.llm = LLM()

        self.memory = (
            Memory()
        )

        self.permissions = (
            PermissionEngine()
        )

        self.tasks = (
            TaskManager()
        )

        self.missions = (
            MissionManager()
        )

        self.router = (
            Router()
        )

        self.files = (
            ProjectFiles(
                self.permissions
            )
        )

        self.runner = (
            PythonRunner(
                self.permissions
            )
        )

        self._lock = (
            threading.RLock()
        )

        self._notifications = []

        self._mission_status_cache = {}

        # =====================================================
        # ENGINE
        # =====================================================

        self.engine = (
            WorkerEngine(
                self.tasks,
                self.notify,
            )
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
        # APPROVAL
        # =====================================================

        self.approvals = (
            ApprovalManager(
                self.tasks,
                self.files,
                self.runner,
                self.engine.resume_dependents,
            )
        )

        # =====================================================
        # PLANNER
        # =====================================================

        self.planner = (
            Planner(
                self.llm
            )
        )

        self.orchestrator = (
            Orchestrator(
                planner=self.planner,
                missions=self.missions,
                tasks=self.tasks,
                engine=self.engine,
            )
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

        match = (
            self.TASK_ID_RE.search(
                text
            )
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

        mission_id = (
            metadata.get(
                "mission_id"
            )
        )

        if not mission_id:

            return None

        return self.missions.get(
            mission_id
        )

    # =========================================================
    # HUMAN EVENT
    # =========================================================

    def _humanize_task_event(
        self,
        text: str,
    ) -> str | None:

        task = (
            self._task_from_event(
                text
            )
        )

        if task is None:

            return text

        mission = (
            self._mission_for_task(
                task
            )
        )

        mission_ref = (
            mission.human_id
            if mission
            else "Mission"
        )

        # =====================================================
        # APPROVAL
        # =====================================================

        if (
            "attend ton approbation"
            in text
        ):

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
                for path
                in files
            )

            return (
                f"{mission_ref} — "
                "la modification est prête.\n\n"
                "J'ai besoin de ton autorisation "
                "pour modifier :\n"
                f"{file_text}\n\n"
                "Tu valides ?"
            )

        # =====================================================
        # FAILURE
        # =====================================================

        if text.startswith(
            "✗"
        ):

            if (
                task.error
                and task.error.startswith(
                    "Dépendance échouée"
                )
            ):

                return None

            detail = (
                task.error
                or task.result
                or "erreur inconnue"
            )

            return (
                f"{mission_ref} — "
                "une étape a rencontré "
                "un problème.\n\n"
                f"Étape : {task.title}\n"
                f"Détail : {detail}"
            )

        # =====================================================
        # SUCCESS
        # =====================================================

        if text.startswith(
            "✓"
        ):

            if (
                task.worker
                == "researcher"
            ):

                return (
                    f"{mission_ref} — "
                    "la recherche est terminée. "
                    "Je poursuis."
                )

            if (
                task.worker
                == "developer"
            ):

                return (
                    f"{mission_ref} — "
                    "le développement est terminé. "
                    "Je lance les vérifications."
                )

            if (
                task.worker
                == "tester"
            ):

                return (
                    f"{mission_ref} — "
                    "les vérifications sont terminées."
                )

            if (
                task.worker
                == "ai_worker"
            ):

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

        modified = []
        created = []
        tested = []
        intellectual_results = []
        sources = []

        for task_id in (
            mission.task_ids
        ):

            task = (
                self.tasks.get(
                    task_id
                )
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

            # -------------------------------------------------
            # FILES
            # -------------------------------------------------

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

            # -------------------------------------------------
            # TESTS
            # -------------------------------------------------

            if (
                task.worker
                == "tester"
            ):

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

            # -------------------------------------------------
            # AI RESULT
            # -------------------------------------------------

            if (
                task.worker
                == "ai_worker"
                and task.status
                == "completed"
            ):

                result = str(
                    task.result
                    or ""
                ).strip()

                if (
                    result
                    and result not in intellectual_results
                ):

                    intellectual_results.append(
                        result
                    )

            # -------------------------------------------------
            # RESEARCH SOURCES
            # -------------------------------------------------

            if (
                task.worker
                == "researcher"
            ):

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

                    already_exists = any(
                        existing.get(
                            "url"
                        )
                        == url
                        for existing
                        in sources
                    )

                    if already_exists:

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

    # =========================================================
    # MISSION SUMMARY
    # =========================================================

    def _mission_summary(
        self,
        mission,
    ) -> str:

        results = (
            self._mission_results(
                mission
            )
        )

        modified = (
            results[
                "modified"
            ]
        )

        created = (
            results[
                "created"
            ]
        )

        tested = (
            results[
                "tested"
            ]
        )

        intellectual_results = (
            results[
                "intellectual_results"
            ]
        )

        sources = (
            results[
                "sources"
            ]
        )

        lines = [
            (
                f"{mission.human_id} — "
                "mission terminée."
            ),
            "",
            mission.title,
        ]

        # =====================================================
        # INTELLECTUAL RESULT
        # =====================================================

        if intellectual_results:

            lines.extend(
                [
                    "",
                    "Résultat :",
                    "",
                ]
            )

            # Dans la majorité des cas,
            # le dernier AIWorker représente
            # la synthèse finale.
            lines.append(
                intellectual_results[-1]
            )

        # =====================================================
        # SOURCES
        # =====================================================

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
                    source.get(
                        "title"
                    )
                    or "Source"
                )

                url = source.get(
                    "url",
                    "",
                )

                lines.append(
                    (
                        f"{index}. "
                        f"{title}\n"
                        f"   {url}"
                    )
                )

        # =====================================================
        # MODIFIED FILES
        # =====================================================

        if modified:

            lines.extend(
                [
                    "",
                    "Fichier(s) modifié(s) :",
                ]
            )

            lines.extend(
                f"- {path}"
                for path
                in modified
            )

        # =====================================================
        # CREATED FILES
        # =====================================================

        if created:

            lines.extend(
                [
                    "",
                    "Fichier(s) créé(s) :",
                ]
            )

            lines.extend(
                f"- {path}"
                for path
                in created
            )

        # =====================================================
        # TESTED FILES
        # =====================================================

        if tested:

            lines.extend(
                [
                    "",
                    "Vérification :",
                ]
            )

            lines.extend(
                f"- {path}"
                for path
                in tested
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # REFRESH
    # =========================================================

    def _refresh_mission(
        self,
        mission,
    ) -> None:

        if mission is None:

            return

        previous = (
            self._mission_status_cache
            .get(
                mission.id
            )
        )

        self.missions.refresh(
            mission,
            self.tasks,
        )

        current = (
            mission.status
        )

        self._mission_status_cache[
            mission.id
        ] = current

        if previous == current:

            return

        # =====================================================
        # COMPLETED
        # =====================================================

        if current == "completed":

            summary = (
                self._mission_summary(
                    mission
                )
            )

            self._append_notification(
                summary
            )

            self.memory.add_session(
                "system",
                summary,
            )

        # =====================================================
        # FAILED
        # =====================================================

        elif current == "failed":

            self._append_notification(
                (
                    f"{mission.human_id} — "
                    "la mission s'est arrêtée "
                    "à cause d'une erreur."
                )
            )

        # =====================================================
        # CANCELLED
        # =====================================================

        elif current == "cancelled":

            self._append_notification(
                (
                    f"{mission.human_id} — "
                    "mission annulée."
                )
            )

    # =========================================================
    # ENGINE NOTIFY
    # =========================================================

    def notify(
        self,
        text: str,
    ) -> None:

        task = (
            self._task_from_event(
                text
            )
        )

        human = (
            self._humanize_task_event(
                text
            )
        )

        if human:

            self._append_notification(
                human
            )

        mission = (
            self._mission_for_task(
                task
            )
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
            .replace(
                "!",
                "",
            )
            .replace(
                "?",
                "",
            )
            .replace(
                ".",
                "",
            )
            .replace(
                ",",
                "",
            )
            .split()
        )

    # =========================================================
    # MISSION REFERENCE
    # =========================================================

    def _extract_mission_reference(
        self,
        message: str,
    ) -> str | None:

        match = (
            self.MISSION_REF_RE.search(
                message
            )
        )

        if not match:

            return None

        raw = (
            match.group(0)
            .upper()
        )

        number = int(
            raw.split(
                "-"
            )[1]
        )

        return (
            f"M-{number:03d}"
        )

    # =========================================================
    # APPROVAL DETECTION
    # =========================================================

    @classmethod
    def _looks_like_approval(
        cls,
        message: str,
    ) -> bool:

        value = (
            cls._normalize(
                message
            )
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
            for marker
            in starters
        )

    @classmethod
    def _looks_like_rejection(
        cls,
        message: str,
    ) -> bool:

        value = (
            cls._normalize(
                message
            )
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
            for marker
            in starters
        )

    # =========================================================
    # PENDING APPROVAL SUMMARY
    # =========================================================

    def _pending_approval_summary(
        self,
    ) -> str:

        pending = (
            self.approvals.pending()
        )

        if not pending:

            return (
                "Aucune autorisation "
                "en attente."
            )

        lines = [
            (
                "Plusieurs missions attendent "
                "une autorisation."
                if len(pending) > 1
                else
                "Une mission attend "
                "une autorisation."
            )
        ]

        for task in pending:

            mission = (
                self._mission_for_task(
                    task
                )
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
                    (
                        "Réponds par exemple : "
                        "\"oui M-002\"."
                    ),
                ]
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # APPROVE
    # =========================================================

    def _approve(
        self,
        message: str,
    ) -> str:

        pending = (
            self.approvals.pending()
        )

        if not pending:

            return (
                "Aucune autorisation "
                "en attente."
            )

        reference = (
            self._extract_mission_reference(
                message
            )
        )

        if reference:

            mission = (
                self.missions.resolve(
                    reference
                )
            )

            if mission is None:

                return (
                    f"Je ne trouve pas "
                    f"la mission {reference}."
                )

            candidates = (
                self.approvals
                .pending_for_mission(
                    mission.id
                )
            )

            if not candidates:

                return (
                    f"{mission.human_id} "
                    "n'attend aucune "
                    "autorisation."
                )

            task = candidates[0]

        elif len(pending) == 1:

            task = pending[0]

            mission = (
                self._mission_for_task(
                    task
                )
            )

        else:

            return (
                self._pending_approval_summary()
            )

        result = (
            self.approvals
            .approve_task(
                task.id
            )
        )

        mission = (
            self._mission_for_task(
                task
            )
        )

        self._refresh_mission(
            mission
        )

        if (
            result.startswith(
                "Approbation non"
            )
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
            "Je poursuis automatiquement "
            "la mission."
        )

    # =========================================================
    # REJECT
    # =========================================================

    def _reject(
        self,
        message: str,
    ) -> str:

        pending = (
            self.approvals.pending()
        )

        if not pending:

            return (
                "Aucune autorisation "
                "en attente."
            )

        reference = (
            self._extract_mission_reference(
                message
            )
        )

        if reference:

            mission = (
                self.missions.resolve(
                    reference
                )
            )

            if mission is None:

                return (
                    f"Mission {reference} "
                    "introuvable."
                )

            candidates = (
                self.approvals
                .pending_for_mission(
                    mission.id
                )
            )

            if not candidates:

                return (
                    f"{reference} "
                    "n'attend aucune "
                    "autorisation."
                )

            task = candidates[0]

        elif len(pending) == 1:

            task = pending[0]

        else:

            return (
                self._pending_approval_summary()
            )

        result = (
            self.approvals
            .reject_task(
                task.id
            )
        )

        mission = (
            self._mission_for_task(
                task
            )
        )

        self._refresh_mission(
            mission
        )

        return result

    # =========================================================
    # PROGRESS
    # =========================================================

    @classmethod
    def _looks_like_progress_question(
        cls,
        message: str,
    ) -> bool:

        value = (
            message.lower()
        )

        return any(
            marker in value
            for marker
            in cls.PROGRESS_MARKERS
        )

    def _progress_summary(
        self,
        message: str = "",
    ) -> str:

        reference = (
            self._extract_mission_reference(
                message
            )
        )

        if reference:

            mission = (
                self.missions.resolve(
                    reference
                )
            )

            if mission is None:

                return (
                    f"Mission {reference} "
                    "introuvable."
                )

            missions = [
                mission
            ]

        else:

            missions = (
                self.missions.active(
                    self.tasks
                )
            )

        if not missions:

            return (
                "Aucune mission active "
                "pour le moment."
            )

        lines = []

        for mission in missions:

            self.missions.refresh(
                mission,
                self.tasks,
            )

            completed, total = (
                self.missions.progress(
                    mission,
                    self.tasks,
                )
            )

            status_labels = {
                "planning": (
                    "préparation"
                ),
                "queued": (
                    "en attente"
                ),
                "running": (
                    "en cours"
                ),
                "waiting_approval": (
                    "attend ton autorisation"
                ),
                "completed": (
                    "terminée"
                ),
                "failed": (
                    "échouée"
                ),
                "cancelled": (
                    "annulée"
                ),
            }

            label = (
                status_labels.get(
                    mission.status,
                    mission.status,
                )
            )

            lines.append(
                (
                    f"{mission.human_id} — "
                    f"{mission.title}\n"
                    f"Statut : {label}\n"
                    f"Progression : "
                    f"{completed}/{total}"
                )
            )

        return "\n\n".join(
            lines
        )

    # =========================================================
    # CONVERSATION CONTEXT
    # =========================================================

    def _active_missions_context(
        self,
    ) -> str:

        return (
            self._progress_summary()
        )

    def _conversation(
        self,
        message: str,
    ) -> str:

        system = """
Tu es le Manager personnel d'Agent-OS.

Tu es un interlocuteur généraliste,
pas un assistant spécialisé en programmation.

Tu peux parler normalement de n'importe quel sujet.

Ne ramène jamais spontanément une discussion
à Python ou Agent-OS.

Tu peux discuter pendant que des missions
travaillent en arrière-plan.

Les informations de missions fournies
dans le contexte sont factuelles.

N'invente jamais l'avancement d'une mission.

Réponds naturellement en français.
Utilise le tutoiement.
"""

        prompt = f"""
MÉMOIRE :

{self.memory.context()}

MISSIONS :

{self._active_missions_context()}

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

        active = (
            self.missions.active(
                self.tasks
            )
        )

        return (
            "Workers : "
            + ", ".join(
                self.engine.workers
            )
            + "\n"
            + "Travaux exécutés : "
            + str(
                len(
                    self.engine.running
                )
            )
            + "\n"
            + "Missions actives : "
            + str(
                len(active)
            )
            + "\n"
            + "Approbations : "
            + str(
                len(
                    self.approvals.pending()
                )
            )
        )

    # =========================================================
    # HANDLE
    # =========================================================

    def handle(
        self,
        message: str,
    ) -> str:

        value = (
            message.strip()
        )

        command = (
            value.lower()
        )

        if not value:

            return ""

        # =====================================================
        # DEBUG COMMANDS
        # =====================================================

        if command == "tasks":

            return (
                self.tasks.format()
            )

        if command == "missions":

            return (
                self.missions.format(
                    self.tasks
                )
            )

        if command == "approvals":

            return (
                self.approvals.format()
            )

        if command == "memory":

            return (
                self.memory.format()
            )

        if command == "status":

            return (
                self._status()
            )

        # =====================================================
        # PROGRESS
        # =====================================================

        if (
            self._looks_like_progress_question(
                value
            )
        ):

            return (
                self._progress_summary(
                    value
                )
            )

        # =====================================================
        # APPROVAL
        # =====================================================

        if (
            self._looks_like_approval(
                value
            )
        ):

            return (
                self._approve(
                    value
                )
            )

        if (
            self._looks_like_rejection(
                value
            )
        ):

            return (
                self._reject(
                    value
                )
            )

        # =====================================================
        # MEMORY
        # =====================================================

        self.memory.add_session(
            "user",
            value,
        )

        self.memory.maybe_remember(
            value
        )

        # =====================================================
        # ROUTER
        # =====================================================

        route = (
            self.router.route(
                value
            )
        )

        # =====================================================
        # CONVERSATION
        # =====================================================

        if (
            route.kind
            == "conversation"
        ):

            answer = (
                self._conversation(
                    value
                )
            )

            self.memory.add_session(
                "assistant",
                answer,
            )

            return answer

        # =====================================================
        # NEW MISSION
        # =====================================================

        mission = (
            self.orchestrator
            .create_mission(
                message=value,
                initial_worker=(
                    route.worker
                    or "ai_worker"
                ),
                router_reason=(
                    route.reason
                ),
            )
        )

        if mission is None:

            return (
                "Je n'ai pas pu "
                "créer la mission."
            )

        self._mission_status_cache[
            mission.id
        ] = mission.status

        response = (
            f"Mission {mission.human_id}\n\n"
            + self.orchestrator
            .format_created(
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