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

    # =========================================================
    # TEAM LEAD POLICY — V4.2
    # =========================================================

    DEFAULT_REPORTING_MODE = "important"

    REPORTING_MODES = {
        "quiet",
        "important",
        "verbose",
    }

    REPORTING_MODE_LABELS = {
        "quiet": "silencieux",
        "important": "normal",
        "verbose": "détaillé",
    }

    ATTENTION_MARKERS = (
        "besoin de moi",
        "demande mon attention",
        "demande mon intervention",
        "qu'est-ce qui bloque",
        "qu est ce qui bloque",
        "qu'est ce qui bloque",
        "qu'est-ce qui attend",
        "qu est ce qui attend",
        "qu'est ce qui attend",
        "où dois-je intervenir",
        "ou dois je intervenir",
        "priorité du moment",
        "priorite du moment",
        "priorités du moment",
        "priorites du moment",
    )

    BRIEFING_MARKERS = (
        "briefing",
        "fais le point",
        "fais-moi le point",
        "fais moi le point",
        "point équipe",
        "point equipe",
        "rapport équipe",
        "rapport equipe",
        "compte rendu équipe",
        "compte rendu equipe",
    )

    RESULT_MARKERS = (
        "résultat de",
        "resultat de",
        "résume-moi le résultat",
        "resume-moi le resultat",
        "résume moi le résultat",
        "resume moi le resultat",
        "quel est le résultat",
        "quel est le resultat",
        "qu'a donné",
        "qu a donné",
        "qu'a donne",
        "qu a donne",
    )

    MEMORY_SUMMARY_MARKERS = (
        "que sais-tu sur moi",
        "que sais tu sur moi",
        "qu'est-ce que tu sais sur moi",
        "qu est ce que tu sais sur moi",
        "qu'est ce que tu sais sur moi",
        "tu te souviens de quoi sur moi",
        "tu te rappelles quoi sur moi",
        "rappelle-moi ce que tu sais sur moi",
        "rappelle moi ce que tu sais sur moi",
        "montre-moi ta mémoire sur moi",
        "montre moi ta memoire sur moi",
    )

    MEMORY_TOPIC_MARKERS = (
        "que sais-tu sur mes",
        "que sais tu sur mes",
        "qu'est-ce que tu sais sur mes",
        "qu est ce que tu sais sur mes",
        "qu'est ce que tu sais sur mes",
        "que sais-tu de mes",
        "que sais tu de mes",
        "tu sais quoi sur mes",
        "tu te souviens de mes",
        "tu te rappelles de mes",
    )

    EMOTIONAL_MEMORY_MARKERS = (
        "mon humeur",
        "mon état émotionnel",
        "mon etat emotionnel",
        "mon état du moment",
        "mon etat du moment",
        "ma motivation",
        "mon énergie",
        "mon energie",
        "mon stress",
        "ma frustration",
        "comment je vais",
        "comment j'étais",
        "comment j etais",
        "comment je me sentais",
        "comment je me sens",
    )

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
    # REPORTING POLICY — V4.2
    # =========================================================

    def _mission_reporting_mode(
        self,
        mission,
    ) -> str:
        if mission is None:
            return self.DEFAULT_REPORTING_MODE

        metadata = (
            mission.metadata
            if isinstance(
                mission.metadata,
                dict,
            )
            else {}
        )

        mode = str(
            metadata.get(
                "reporting_mode",
                self.DEFAULT_REPORTING_MODE,
            )
        ).strip().lower()

        if mode not in self.REPORTING_MODES:
            return self.DEFAULT_REPORTING_MODE

        return mode

    def _set_mission_reporting_mode(
        self,
        mission,
        mode: str,
    ) -> None:
        if mission is None:
            return

        wanted = str(
            mode
        ).strip().lower()

        if wanted not in self.REPORTING_MODES:
            wanted = self.DEFAULT_REPORTING_MODE

        self.missions.set_status(
            mission.id,
            mission.status,
            metadata_patch={
                "reporting_mode": wanted,
            },
        )

    @classmethod
    def _reporting_mode_from_text(
        cls,
        message: str,
    ) -> str | None:
        value = cls._normalize(
            message
        )

        quiet_markers = (
            "seulement à la fin",
            "seulement a la fin",
            "uniquement à la fin",
            "uniquement a la fin",
            "préviens moi à la fin",
            "previens moi a la fin",
            "préviens-moi à la fin",
            "previens-moi a la fin",
            "ne me dérange pas",
            "ne me derange pas",
            "pas de notification intermédiaire",
            "pas de notification intermediaire",
            "mode silencieux",
        )

        verbose_markers = (
            "tiens moi au courant",
            "tiens-moi au courant",
            "préviens moi de chaque étape",
            "previens moi de chaque etape",
            "préviens-moi de chaque étape",
            "previens-moi de chaque etape",
            "à chaque étape",
            "a chaque etape",
            "mode détaillé",
            "mode detaille",
            "notifications détaillées",
            "notifications detaillees",
        )

        normal_markers = (
            "mode normal",
            "notifications normales",
            "notification normale",
            "suivi normal",
        )

        if any(
            marker in value
            for marker in quiet_markers
        ):
            return "quiet"

        if any(
            marker in value
            for marker in verbose_markers
        ):
            return "verbose"

        if any(
            marker in value
            for marker in normal_markers
        ):
            return "important"

        return None

    def _reporting_command_response(
        self,
        message: str,
    ) -> str | None:
        mode = self._reporting_mode_from_text(
            message
        )

        if mode is None:
            return None

        reference = self._extract_mission_reference(
            message
        )

        # Si le message contient une vraie demande de travail,
        # l'instruction de reporting appartient à la NOUVELLE mission.
        # On la laissera donc passer jusqu'au routeur puis on appliquera
        # le mode juste après la création de la mission.
        if (
            reference is None
            and self.router.route(
                message
            ).kind != "conversation"
        ):
            return None

        mission = None

        if reference:
            mission = self.missions.resolve(
                reference
            )

            if mission is None:
                return (
                    f"Mission {reference} introuvable."
                )

        else:
            active = self.missions.active(
                self.tasks
            )

            if len(active) == 1:
                mission = active[0]

            elif not active:
                return (
                    "Aucune mission active. "
                    "Précise une mission, par exemple M-024."
                )

            else:
                refs = ", ".join(
                    item.human_id
                    for item in active[:6]
                )

                return (
                    "Plusieurs missions sont actives : "
                    f"{refs}. Précise laquelle."
                )

        self._set_mission_reporting_mode(
            mission,
            mode,
        )

        if mode == "quiet":
            detail = (
                "Je te préviendrai seulement si ton intervention "
                "est indispensable, en cas d'échec final, "
                "ou lorsque la mission sera terminée."
            )

        elif mode == "verbose":
            detail = (
                "Je te signalerai aussi les étapes importantes "
                "entre les workers."
            )

        else:
            detail = (
                "Je te signalerai les éléments importants "
                "sans te notifier à chaque étape."
            )

        return (
            f"{mission.human_id} — suivi "
            f"{self.REPORTING_MODE_LABELS[mode]}.\n"
            f"{detail}"
        )

    def _should_notify_task_event(
        self,
        text: str,
        task,
        mission,
    ) -> bool:
        if task is None:
            return False

        mode = self._mission_reporting_mode(
            mission
        )

        if "attend ton approbation" in text:
            return True

        if "correction automatique lancée" in text:
            return mode in {
                "important",
                "verbose",
            }

        if text.startswith("✓"):
            return mode == "verbose"

        # Les échecs terminaux sont annoncés au niveau mission
        # par _refresh_mission, avec le détail de la tâche.
        if text.startswith("✗"):
            return False

        return mode == "verbose"

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

        if (
            text.startswith("✗")
            and "correction automatique lancée" in text
        ):
            data = (
                task.result_data
                if isinstance(
                    task.result_data,
                    dict,
                )
                else {}
            )

            attempt = data.get(
                "auto_repair_attempt"
            )
            maximum = data.get(
                "auto_repair_maximum"
            )

            suffix = ""

            if attempt and maximum:
                suffix = (
                    f" ({attempt}/{maximum})"
                )

            return (
                f"{mission_ref} — une vérification n'a pas été "
                "validée. J'ai lancé automatiquement une "
                f"correction{suffix}."
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
        *,
        trigger_task=None,
        emit_notification: bool = True,
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

            if emit_notification:
                self._append_notification(
                    summary
                )

            self.memory.add_session(
                "system",
                summary,
            )
            self.memory.forget_working(
                f"mission:{mission.id}"
            )
            self.memory.remember_operational(
                (
                    f"{mission.human_id} terminée : "
                    f"{mission.title}"
                ),
                kind="mission_completed",
                source="agentos",
                confidence=1.0,
            )

        elif current == "failed":
            lines = [
                f"{mission.human_id} — mission échouée."
            ]

            if trigger_task is not None:
                detail = (
                    trigger_task.error
                    or trigger_task.result
                )

                if detail:
                    lines.extend(
                        [
                            "",
                            f"Étape : {trigger_task.title}",
                            f"Détail : {detail}",
                        ]
                    )

            message = "\n".join(
                lines
            )

            if emit_notification:
                self._append_notification(
                    message
                )

            self.memory.add_session(
                "system",
                message,
            )
            self.memory.forget_working(
                f"mission:{mission.id}"
            )
            self.memory.remember_operational(
                (
                    f"{mission.human_id} a échoué : "
                    f"{mission.title}"
                ),
                kind="mission_failed",
                source="agentos",
                confidence=1.0,
            )

        elif current == "cancelled":
            message = (
                f"{mission.human_id} — mission annulée."
            )

            if emit_notification:
                self._append_notification(
                    message
                )

            self.memory.forget_working(
                f"mission:{mission.id}"
            )
            self.memory.remember_operational(
                (
                    f"{mission.human_id} annulée : "
                    f"{mission.title}"
                ),
                kind="mission_cancelled",
                source="agentos",
                confidence=1.0,
            )

        elif current == "rejected":
            message = (
                f"{mission.human_id} — mission refusée. "
                "La modification n'a pas été appliquée."
            )

            if emit_notification:
                self._append_notification(
                    message
                )

            self.memory.forget_working(
                f"mission:{mission.id}"
            )
            self.memory.remember_operational(
                (
                    f"{mission.human_id} refusée : "
                    f"{mission.title}"
                ),
                kind="mission_rejected",
                source="agentos",
                confidence=1.0,
            )

    def notify(
        self,
        text: str,
    ) -> None:
        task = self._task_from_event(
            text
        )

        mission = self._mission_for_task(
            task
        )

        if self._should_notify_task_event(
            text,
            task,
            mission,
        ):
            human = self._humanize_task_event(
                text
            )

            if human:
                self._append_notification(
                    human
                )

        self._refresh_mission(
            mission,
            trigger_task=task,
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
            mission,
            emit_notification=False,
        )

        return result

    # =========================================================
    # OPERATIONAL AWARENESS — V4.1 / TEAM LEAD V4.2
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

    def _mission_result_text(
        self,
        mission,
    ) -> str:
        results = self._mission_results(
            mission
        )

        intellectual = results.get(
            "intellectual_results",
            [],
        )

        if intellectual:
            return str(
                intellectual[-1]
            ).strip()

        for task_id in reversed(
            mission.task_ids
        ):
            task = self.tasks.get(
                task_id
            )

            if task is None:
                continue

            result = str(
                task.result
                or ""
            ).strip()

            if result:
                return result

        return (
            "Aucun résultat textuel n'est enregistré "
            "pour cette mission."
        )

    def _mission_result_response(
        self,
        message: str,
    ) -> str | None:
        value = self._normalize(
            message
        )

        if not any(
            marker in value
            for marker in self.RESULT_MARKERS
        ):
            return None

        reference = self._extract_mission_reference(
            message
        )

        if reference is None:
            return (
                "Précise la mission dont tu veux le résultat, "
                "par exemple M-024."
            )

        mission = self.missions.resolve(
            reference
        )

        if mission is None:
            return (
                f"Mission {reference} introuvable."
            )

        self.missions.refresh(
            mission,
            self.tasks,
        )

        return (
            f"{mission.human_id} — {mission.title}\n"
            f"Statut : {self._status_label(mission.status)}\n\n"
            "Résultat enregistré :\n"
            f"{self._mission_result_text(mission)}"
        )

    def _attention_summary(
        self,
    ) -> str:
        snapshot = self._operational_snapshot()

        pending = snapshot[
            "pending_approvals"
        ]

        paused = [
            mission
            for mission in snapshot["active"]
            if mission.status == "paused"
        ]

        active = snapshot[
            "active"
        ]

        busy = [
            worker
            for worker in snapshot["workers"]
            if worker["status"] == "busy"
        ]

        lines: list[str] = []

        if pending:
            lines.append(
                "Ton intervention est requise :"
            )

            for task in pending:
                mission = self._mission_for_task(
                    task
                )

                ref = (
                    mission.human_id
                    if mission is not None
                    else "Mission inconnue"
                )

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

                suffix = (
                    " — " + ", ".join(files)
                    if files
                    else ""
                )

                lines.append(
                    f"- {ref} : approbation requise{suffix}"
                )

        if paused:
            if lines:
                lines.append("")

            lines.append(
                "Missions en pause :"
            )
            lines.extend(
                "- " + self._mission_context_line(
                    mission
                )
                for mission in paused
            )

        if not lines:
            if not active:
                return (
                    "Rien ne demande ton attention actuellement. "
                    "Aucune mission n'est active."
                )

            return (
                "Rien ne demande ton intervention actuellement. "
                f"{len(active)} mission(s) active(s) continuent "
                f"en arrière-plan avec {len(busy)} worker(s) occupé(s)."
            )

        return "\n".join(
            lines
        )

    def _team_briefing(
        self,
    ) -> str:
        snapshot = self._operational_snapshot()
        counts = snapshot[
            "counts"
        ]

        busy = [
            worker
            for worker in snapshot["workers"]
            if worker["status"] == "busy"
        ]

        lines = [
            "POINT ÉQUIPE",
            (
                f"{counts['active']} mission(s) active(s) | "
                f"{len(busy)}/4 worker(s) occupé(s) | "
                f"{len(snapshot['pending_approvals'])} "
                "approbation(s) en attente"
            ),
        ]

        if snapshot[
            "pending_approvals"
        ]:
            lines.extend(
                [
                    "",
                    "À TON ATTENTION",
                    self._attention_summary(),
                ]
            )

        lines.extend(
            [
                "",
                "EN COURS",
            ]
        )

        if snapshot[
            "active"
        ]:
            lines.extend(
                "- " + self._mission_context_line(
                    mission
                )
                for mission in snapshot["active"]
            )
        else:
            lines.append(
                "Aucune mission active."
            )

        if busy:
            lines.extend(
                [
                    "",
                    "WORKERS OCCUPÉS",
                ]
            )

            for worker in busy:
                mission_refs = (
                    ", ".join(
                        worker["missions"]
                    )
                    or "mission inconnue"
                )

                task_text = (
                    " / ".join(
                        worker["task_titles"][:2]
                    )
                    or "tâche en cours"
                )

                lines.append(
                    f"- {worker['name']} : "
                    f"{mission_refs} — {task_text}"
                )

        return "\n".join(
            lines
        )

    def _direct_team_lead_response(
        self,
        message: str,
    ) -> str | None:
        value = self._normalize(
            message
        )

        result = self._mission_result_response(
            message
        )

        if result is not None:
            return result

        if any(
            marker in value
            for marker in self.ATTENTION_MARKERS
        ):
            return self._attention_summary()

        if any(
            marker in value
            for marker in self.BRIEFING_MARKERS
        ):
            return self._team_briefing()

        return None

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

La MÉMOIRE est structurée. Respecte strictement sa nature :
- PROFIL et SOUVENIRS DURABLES décrivent des informations relativement stables ;
- ÉVÉNEMENTS PERSONNELS décrivent des épisodes datés, jamais des traits permanents ;
- ÉTAT ÉMOTIONNEL ACTUEL est une estimation temporaire dont la confiance décroît ;
- l'historique des missions est OPÉRATIONNEL et n'est pas une mémoire personnelle ;
- CONVERSATION RÉCENTE sert seulement au contexte immédiat.

Quand l'utilisateur pose une question sur ses goûts, habitudes ou souvenirs,
utilise tous les souvenirs pertinents fournis dans le contexte, sans en inventer.
N'invente jamais une expérience vécue, une anecdote, une émotion passée, un
souvenir commun ou une activité qui n'est pas explicitement présente dans la mémoire.

Adapte légèrement ta manière de répondre à l'état émotionnel quand il est
suffisamment fiable :
- énergie ou motivation basse : réponse plus concise, une prochaine action au maximum ;
- frustration élevée : réponse factuelle, précise, sans phrases de réassurance génériques ;
- énergie ou motivation haute : ton plus orienté action.
Ne dramatise jamais et ne présente jamais cette estimation comme une certitude.
Ne dis pas « je sais que tu es... » pour une humeur : préfère une formulation
prudente fondée sur ce que l'utilisateur a exprimé.

Comporte-toi comme un chef d'équipe : ne surcharge pas l'utilisateur
avec des détails opérationnels inutiles. Fais remonter en priorité ce qui
requiert une décision humaine, un échec final, un blocage, puis les
résultats terminés. Les étapes intermédiaires normales peuvent rester
en arrière-plan.

Réponds naturellement en français et utilise toujours le tutoiement.
Pour une question simple, réponds de façon courte et directe.
N'ajoute pas de formule du type « n'hésite pas » ou de proposition générique
à la fin si l'utilisateur ne l'a pas demandée.
"""

        prompt = f"""
MÉMOIRE :

{self.memory.relevant_context(message)}

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
    # MEMORY ENGINE V4.5
    # =========================================================

    def _direct_memory_response(
        self,
        message: str,
    ) -> str | None:
        value = self._normalize(
            message
        )

        if any(
            marker in value
            for marker in self.MEMORY_SUMMARY_MARKERS
        ):
            return self.memory.personal_summary()

        if any(
            marker in value
            for marker in self.EMOTIONAL_MEMORY_MARKERS
        ):
            return self.memory.emotional_summary()

        if any(
            marker in value
            for marker in self.MEMORY_TOPIC_MARKERS
        ):
            factual = self.memory.relevant_personal_summary(message)
            if factual is not None:
                return factual

        return None

    # =========================================================
    # EMOTIONAL ACKNOWLEDGEMENT V4.6.2
    # =========================================================

    def _emotional_acknowledgement(
        self,
        signals: dict,
    ) -> str:
        """Réponse courte aux simples mises à jour d'état personnel.

        On évite ici les réponses LLM trop enthousiastes, les propositions de
        missions non demandées et les phrases génériques. L'état reste une
        estimation temporaire, pas un trait de personnalité.
        """
        mood = str(signals.get("mood", {}).get("value", ""))
        energy = str(signals.get("energy", {}).get("value", ""))
        motivation = str(signals.get("motivation", {}).get("value", ""))
        stress = str(signals.get("stress", {}).get("value", ""))
        frustration = str(signals.get("frustration", {}).get("value", ""))

        if mood == "positive" and motivation == "high":
            return "Ça marche. Je retiens que ça va mieux et que tu es motivé."

        if frustration == "high":
            return "Compris. Je vais rester factuel et aller droit au but pour le moment."

        if stress == "high":
            return "Compris. Je vais rester concis et éviter de te charger inutilement pour le moment."

        if energy == "low" and motivation == "low":
            return "Compris. Je vais garder les échanges courts et éviter de te surcharger pour le moment."

        if motivation == "high":
            return "Compris. Je retiens que tu es motivé pour le moment."

        if motivation == "low":
            return "Compris. Je retiens que ta motivation est basse pour le moment."

        if energy == "high":
            return "Compris. Je retiens que tu as de l'énergie pour le moment."

        if energy == "low":
            return "Compris. Je retiens que ton énergie est basse pour le moment."

        if mood == "positive":
            return "Compris. Je retiens que ça va plutôt bien pour le moment."

        if mood == "negative":
            return "Compris. Je garde ça comme un état temporaire et j'adapte mes réponses."

        return "Compris. Je garde cet état comme temporaire."

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

        if command in {
            "memory",
            "/memory",
        }:
            return self.memory.concise_summary()

        if command in {
            "memory operations",
            "memory operational",
            "memory missions",
            "/memory_ops",
        }:
            return self.memory.operational_summary()

        if command in {
            "emotion",
            "emotions",
            "humeur",
            "mood",
            "/emotion",
        }:
            return self.memory.emotional_summary()

        if command in {
            "memory debug",
            "memory full",
            "/memory_debug",
        }:
            return self.memory.format()

        if command == "status":
            return self._status()

        if command in {
            "briefing",
            "brief",
            "point",
        }:
            return self._team_briefing()

        # V4.2 — politique de reporting par mission
        reporting_response = (
            self._reporting_command_response(
                value
            )
        )

        if reporting_response is not None:
            return reporting_response

        # V4.2 — faits de chef d'équipe : résultat, attention, briefing
        team_lead_response = (
            self._direct_team_lead_response(
                value
            )
        )

        if team_lead_response is not None:
            return team_lead_response

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
        explicit_memory_fact = (
            self.memory.explicit_memory_fact(
                value
            )
        )

        emotional_signals = self.memory.maybe_remember(
            value
        )

        if explicit_memory_fact is not None:
            response = (
                "C'est retenu : "
                + explicit_memory_fact
            )
            self.memory.add_session(
                "assistant",
                response,
            )
            return response

        direct_memory = (
            self._direct_memory_response(
                value
            )
        )

        if direct_memory is not None:
            self.memory.add_session(
                "assistant",
                direct_memory,
            )
            return direct_memory

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

        # Une simple mise à jour émotionnelle reçoit une réponse courte et
        # déterministe. Si le même message contient une vraie tâche, la tâche
        # garde la priorité et suit le workflow normal.
        if route.kind == "conversation" and emotional_signals:
            answer = self._emotional_acknowledgement(
                emotional_signals
            )
            self.memory.add_session(
                "assistant",
                answer,
            )
            return answer

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

        self.memory.remember_working(
            key=f"mission:{mission.id}",
            content=(
                f"{mission.human_id} — {mission.title} "
                f"({self._status_label(mission.status)})"
            ),
            kind="mission",
            source="agentos",
        )
        self.memory.remember_operational(
            f"{mission.human_id} créée : {mission.title}",
            kind="mission_created",
            source="agentos",
            confidence=1.0,
        )

        requested_reporting = (
            self._reporting_mode_from_text(
                value
            )
        )

        if requested_reporting is not None:
            self._set_mission_reporting_mode(
                mission,
                requested_reporting,
            )

        response = (
            f"Mission {mission.human_id}\n\n"
            + self.orchestrator.format_created(
                mission
            )
        )

        if requested_reporting is not None:
            response += (
                "\n\nSuivi : "
                + self.REPORTING_MODE_LABELS[
                    requested_reporting
                ]
                + "."
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
