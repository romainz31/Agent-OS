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

    def __init__(
        self,
    ) -> None:

        # =====================================================
        # CORE
        # =====================================================

        self.llm = LLM()

        self.memory = Memory()

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

        # =====================================================
        # TOOLS
        # =====================================================

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

        # =====================================================
        # NOTIFICATIONS
        # =====================================================

        self._lock = (
            threading.RLock()
        )

        self._notifications: list[
            str
        ] = []

        self._mission_status_cache: dict[
            str,
            str,
        ] = {}

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
        # APPROVALS
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
        # PLANNER / ORCHESTRATOR
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
    # NOTIFICATION STORAGE
    # =========================================================

    def _append_notification(
        self,
        text: str,
    ) -> None:

        with self._lock:

            self._notifications.append(
                text
            )

    # =========================================================
    # TASK FROM EVENT
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

            if files:

                file_text = "\n".join(
                    f"- {path}"
                    for path
                    in files
                )

                return (
                    "La modification est prête.\n\n"
                    "J'ai besoin de ton autorisation "
                    "pour modifier :\n"
                    f"{file_text}\n\n"
                    "Tu valides ?"
                )

            return (
                "Une action nécessite "
                "ton autorisation.\n\n"
                "Tu valides ?"
            )

        # =====================================================
        # FAILURE
        # =====================================================

        if text.startswith(
            "✗"
        ):

            detail = (
                task.error
                or task.result
                or "erreur inconnue"
            )

            return (
                "Une étape de la mission "
                "a rencontré un problème.\n\n"
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
                    "La recherche est terminée. "
                    "Je poursuis la mission."
                )

            if (
                task.worker
                == "developer"
            ):

                return (
                    "Le développement est terminé. "
                    "Je lance les vérifications."
                )

            if (
                task.worker
                == "tester"
            ):

                return (
                    "Les vérifications "
                    "sont terminées."
                )

            if (
                task.worker
                == "ai_worker"
            ):

                return (
                    "L'analyse est terminée."
                )

        return None

    # =========================================================
    # MISSION FOR TASK
    # =========================================================

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
    # MISSION SUMMARY
    # =========================================================

    def _mission_summary(
        self,
        mission,
    ) -> str:

        modified_files = []
        created_files = []
        tested_files = []

        for task_id in (
            mission.task_ids
        ):

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

                if path not in (
                    modified_files
                ):

                    modified_files.append(
                        path
                    )

            for path in (
                data.get(
                    "created_files",
                    [],
                )
                or []
            ):

                if path not in (
                    created_files
                ):

                    created_files.append(
                        path
                    )

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

                    if path not in (
                        tested_files
                    ):

                        tested_files.append(
                            path
                        )

        lines = [
            "Mission terminée.",
            "",
            mission.title,
        ]

        if modified_files:

            lines.extend(
                [
                    "",
                    "Fichier(s) modifié(s) :",
                ]
            )

            lines.extend(
                f"- {path}"
                for path
                in modified_files
            )

        if created_files:

            lines.extend(
                [
                    "",
                    "Fichier(s) créé(s) :",
                ]
            )

            lines.extend(
                f"- {path}"
                for path
                in created_files
            )

        if tested_files:

            lines.extend(
                [
                    "",
                    "Vérification effectuée sur :",
                ]
            )

            lines.extend(
                f"- {path}"
                for path
                in tested_files
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # REFRESH MISSION
    # =========================================================

    def _refresh_mission(
        self,
        mission,
    ) -> None:

        if mission is None:

            return

        previous = (
            self._mission_status_cache.get(
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

        if (
            previous
            == current
        ):

            return

        if current == "completed":

            summary = (
                self._mission_summary(
                    mission
                )
            )

            self._append_notification(
                summary
            )

            # Le Manager garde également
            # une trace conversationnelle
            # du travail terminé.
            self.memory.add_session(
                "system",
                summary,
            )

            return

        if current == "failed":

            self._append_notification(
                (
                    "La mission n'a pas pu "
                    "être terminée correctement.\n\n"
                    f"{mission.title}"
                )
            )

            return

        if current == "cancelled":

            self._append_notification(
                (
                    "La mission a été annulée.\n\n"
                    f"{mission.title}"
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
    # DRAIN
    # =========================================================

    def drain_notifications(
        self,
    ) -> list[str]:

        with self._lock:

            notifications = list(
                self._notifications
            )

            self._notifications.clear()

            return notifications

    # =========================================================
    # ACTIVE MISSIONS CONTEXT
    # =========================================================

    def _active_missions_context(
        self,
    ) -> str:

        lines = []

        for mission in (
            self.missions.list()
        ):

            self.missions.refresh(
                mission,
                self.tasks,
            )

            if mission.status not in {
                "planning",
                "queued",
                "running",
                "waiting_approval",
            }:

                continue

            lines.append(
                (
                    f"- {mission.title}\n"
                    f"  Statut : "
                    f"{mission.status}"
                )
            )

            completed = 0

            total = len(
                mission.task_ids
            )

            for task_id in (
                mission.task_ids
            ):

                task = (
                    self.tasks.get(
                        task_id
                    )
                )

                if (
                    task is not None
                    and task.status
                    == "completed"
                ):

                    completed += 1

            lines.append(
                (
                    f"  Progression : "
                    f"{completed}/{total}"
                )
            )

        if not lines:

            return (
                "Aucune mission active."
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # COMMAND NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_command(
        message: str,
    ) -> str:

        return " ".join(
            message
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
    # NATURAL APPROVAL
    # =========================================================

    @classmethod
    def _looks_like_approval(
        cls,
        message: str,
    ) -> bool:

        value = (
            cls._normalize_command(
                message
            )
        )

        exact = {
            "oui",
            "yes",
            "y",
            "ok",
            "okay",
            "go",
            "vas y",
            "je valide",
            "validé",
            "valide",
            "c'est bon",
            "cest bon",
            "d'accord",
            "daccord",
            "tu peux",
            "autorise",
            "j'autorise",
            "jautorise",
            "approuve",
            "je confirme",
        }

        if value in exact:

            return True

        prefixes = (
            "ok pour ",
            "je valide ",
            "je confirme ",
            "tu peux modifier",
            "tu peux créer",
            "tu peux creer",
            "tu peux faire",
            "vas y ",
            "j'autorise ",
            "jautorise ",
        )

        return value.startswith(
            prefixes
        )

    # =========================================================
    # NATURAL REJECTION
    # =========================================================

    @classmethod
    def _looks_like_rejection(
        cls,
        message: str,
    ) -> bool:

        value = (
            cls._normalize_command(
                message
            )
        )

        exact = {
            "non",
            "no",
            "n",
            "refuse",
            "je refuse",
            "annule",
            "annuler",
            "stop",
            "laisse tomber",
            "ne fais pas",
            "ne modifie pas",
        }

        if value in exact:

            return True

        prefixes = (
            "non ",
            "je refuse ",
            "annule ",
            "ne modifie pas ",
            "ne crée pas ",
            "ne cree pas ",
            "ne fais pas ",
        )

        return value.startswith(
            prefixes
        )

    # =========================================================
    # CONVERSATION
    # =========================================================

    def _conversation(
        self,
        message: str,
    ) -> str:

        memory_context = (
            self.memory.context()
        )

        missions_context = (
            self._active_missions_context()
        )

        system = """
Tu es le Manager personnel d'Agent-OS.

Tu es l'interlocuteur principal de l'utilisateur.

IMPORTANT :

Tu n'es PAS un assistant spécialisé en programmation.

Tu es un interlocuteur généraliste.

Si l'utilisateur parle de tortues,
il parle probablement des animaux sauf indication contraire.

Si l'utilisateur parle de cuisine,
de météo, de voitures, de poissons,
de jardinage ou de sa journée,
réponds naturellement sur ce sujet.

Ne ramène jamais spontanément une discussion
vers Python, Agent-OS ou la programmation.

Tu peux discuter normalement pendant que
les workers travaillent en arrière-plan.

Tu connais uniquement les missions indiquées
dans le contexte système.

Ne prétends jamais qu'une mission a avancé,
échoué ou réussi si le contexte ne l'indique pas.

Ne prétends jamais avoir utilisé un outil
si aucun outil réel n'a été utilisé.

Réponds en français naturel.

Utilise le tutoiement.

Sois direct et conversationnel.
"""

        prompt = f"""
CONTEXTE MÉMOIRE :

{memory_context}

MISSIONS ACTIVES :

{missions_context}

MESSAGE UTILISATEUR :

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

        active = 0

        for mission in (
            self.missions.list()
        ):

            self.missions.refresh(
                mission,
                self.tasks,
            )

            if mission.status in {
                "planning",
                "queued",
                "running",
                "waiting_approval",
            }:

                active += 1

        return (
            "Workers : "
            + ", ".join(
                self.engine.workers
            )
            + "\n"
            + "Travaux en cours : "
            + str(
                len(
                    self.engine.running
                )
            )
            + "\n"
            + "Missions actives : "
            + str(active)
            + "\n"
            + "Approbations : "
            + str(
                len(
                    self.approvals.pending()
                )
            )
        )

    # =========================================================
    # APPROVE
    # =========================================================

    def _approve(
        self,
    ) -> str:

        pending = (
            self.approvals.pending()
        )

        task = (
            pending[0]
            if pending
            else None
        )

        response = (
            self.approvals
            .approve_latest()
        )

        if task is None:

            return response

        mission = (
            self._mission_for_task(
                task
            )
        )

        self._refresh_mission(
            mission
        )

        return (
            "C'est validé.\n\n"
            "La modification a été appliquée. "
            "Je poursuis automatiquement "
            "la mission."
        )

    # =========================================================
    # REJECT
    # =========================================================

    def _reject(
        self,
    ) -> str:

        pending = (
            self.approvals.pending()
        )

        task = (
            pending[0]
            if pending
            else None
        )

        response = (
            self.approvals
            .reject_latest()
        )

        if task is None:

            return response

        mission = (
            self._mission_for_task(
                task
            )
        )

        self._refresh_mission(
            mission
        )

        return (
            "D'accord. "
            "Je n'applique pas "
            "cette modification."
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
        # COMMANDS
        # =====================================================

        if command == "tasks":

            return self.tasks.format()

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

            return self.memory.format()

        if command == "status":

            return self._status()

        # =====================================================
        # APPROVALS
        # =====================================================

        if (
            self.approvals.pending()
        ):

            if self._looks_like_approval(
                value
            ):

                return self._approve()

            if self._looks_like_rejection(
                value
            ):

                return self._reject()

        if command in {
            "oui",
            "yes",
            "y",
            "approve",
            "autorise",
        }:

            return self._approve()

        if command in {
            "non",
            "no",
            "n",
            "reject",
            "refuse",
        }:

            return self._reject()

        # =====================================================
        # MEMORY INPUT
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
        # NORMAL CONVERSATION
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
        # MISSION
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
            self.orchestrator
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