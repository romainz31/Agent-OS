from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from agentos.config import MAX_WORKERS
from agentos.tasks import TaskStatus


class WorkerEngine:
    """Moteur d'exécution avec file d'attente pilotée V5.5.

    V5.0 ajoute :
    - une vraie file d'attente avant ThreadPoolExecutor ;
    - une limite de concurrence par type de worker ;
    - un ordonnancement priorité + échéance + ancienneté ;
    - un fournisseur de politique externe pour lire la priorité des missions ;
    - des snapshots de charge/backlog utilisables par Paul.

    ``submit()`` signifie désormais « demander l'exécution ». La tâche peut être
    lancée immédiatement ou rester dans le backlog jusqu'à ce qu'un slot adapté
    soit libre.
    """

    TERMINAL_STATUSES = {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.WAITING_APPROVAL.value,
        TaskStatus.PAUSED.value,
    }

    PRIORITY_VALUES = {
        "low": 10,
        "normal": 20,
        "high": 30,
        "critical": 40,
    }

    PRIORITY_LABELS = {
        "low": "basse",
        "normal": "normale",
        "high": "haute",
        "critical": "critique",
    }

    def __init__(
        self,
        tasks,
        notifier,
    ) -> None:
        self.tasks = tasks
        self.notifier = notifier

        self.pool = ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        )

        self.workers = {}
        self.running: dict[str, Future] = {}

        # Tâches acceptées par submit() mais pas encore confiées à un worker.
        self.requested: set[str] = set()

        self.lock = threading.RLock()
        self.condition = threading.Condition(
            self.lock
        )

        self.repair_handler: (
            Callable[[str], dict[str, Any]]
            | None
        ) = None

        self.schedule_provider: (
            Callable[[Any], dict[str, Any]]
            | None
        ) = None

        # V5.2 : fournisseur de contexte technique issu du Skill Registry.
        # Il est appelé uniquement au lancement réel d'une tâche.
        self.skill_provider: (
            Callable[[Any], dict[str, Any]]
            | None
        ) = None

        # V5.4 : préparation asynchrone avant l'exécution réelle. Le provider
        # peut créer des dépendances (par exemple un apprentissage Researcher)
        # et différer la tâche sans consommer de slot worker.
        self.preparation_provider: (
            Callable[[Any], dict[str, Any]]
            | None
        ) = None

        # V5.5 : lorsqu'un worker demande l'aide d'un collègue, le résultat
        # spécial est transformé en vraie tâche de renfort + dépendance.
        self.collaboration_handler: (
            Callable[[Any, Any], dict[str, Any]]
            | None
        ) = None

        self.stop_event = threading.Event()
        self.dispatch_thread = threading.Thread(
            target=self._dispatch_loop,
            daemon=True,
            name="agentos-workload-dispatcher",
        )
        self.dispatch_thread.start()

    # =========================================================
    # REGISTRATION / POLICY
    # =========================================================

    def register(
        self,
        worker,
    ) -> None:
        with self.condition:
            self.workers[
                worker.name
            ] = worker
            self.condition.notify_all()

    def set_repair_handler(
        self,
        handler: Callable[
            [str],
            dict[str, Any],
        ]
        | None,
    ) -> None:
        self.repair_handler = handler

    def set_schedule_provider(
        self,
        provider: Callable[
            [Any],
            dict[str, Any],
        ]
        | None,
    ) -> None:
        """Branche la politique de planification venant du Manager.

        Le provider reçoit l'objet Task courant et peut retourner :
        ``priority``, ``deadline``, ``mission`` et toute information utile au
        snapshot. La politique est relue à chaque arbitrage, donc changer la
        priorité d'une mission réordonne immédiatement les tâches encore en
        attente.
        """
        with self.condition:
            self.schedule_provider = provider
            self.condition.notify_all()

    def set_skill_provider(
        self,
        provider: Callable[
            [Any],
            dict[str, Any],
        ]
        | None,
    ) -> None:
        """Branche le Skill Registry V5.2 sur le moteur.

        Le provider reçoit la Task au moment exact où elle va être confiée au
        worker. Son résultat est ajouté au payload sous ``skill_context``.
        """
        with self.condition:
            self.skill_provider = provider

    def set_preparation_provider(
        self,
        provider: Callable[[Any], dict[str, Any]] | None,
    ) -> None:
        """Branche une étape de préparation V5.4 avant le worker.

        Retour attendu : ``{"ready": True}`` pour continuer ou
        ``{"ready": False}`` si le provider a préparé une dépendance et
        souhaite différer l'exécution.
        """
        with self.condition:
            self.preparation_provider = provider
            self.condition.notify_all()

    def set_collaboration_handler(
        self,
        handler: Callable[[Any, Any], dict[str, Any]] | None,
    ) -> None:
        """Branche le coordinateur de collaboration V5.5."""
        with self.condition:
            self.collaboration_handler = handler
            self.condition.notify_all()

    def wake_scheduler(self) -> None:
        with self.condition:
            self.condition.notify_all()

    # =========================================================
    # WORKER CAPACITY
    # =========================================================

    @staticmethod
    def _worker_limit_env_name(
        worker_name: str,
    ) -> str:
        clean = "".join(
            char if char.isalnum() else "_"
            for char in str(worker_name).upper()
        )
        return (
            "AGENT_OS_WORKER_LIMIT_"
            + clean
        )

    def worker_limit(
        self,
        worker_name: str,
    ) -> int:
        """Nombre maximal de tâches simultanées pour ce worker.

        Par défaut V5.0 : 1 par worker. On pourra plus tard rendre cela adaptatif
        selon les performances et le type de spécialiste.
        """
        specific = os.getenv(
            self._worker_limit_env_name(
                worker_name
            )
        )
        default = os.getenv(
            "AGENT_OS_WORKER_LIMIT_DEFAULT",
            "1",
        )

        raw = (
            specific
            if specific is not None
            else default
        )

        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 1

        return max(1, value)

    def _running_counts(
        self,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}

        for task_id in list(
            self.running
        ):
            task = self.tasks.get(
                task_id
            )
            if task is None:
                continue
            counts[task.worker] = (
                counts.get(
                    task.worker,
                    0,
                )
                + 1
            )

        return counts

    def is_running(
        self,
        task_id: str,
    ) -> bool:
        with self.lock:
            return (
                task_id
                in self.running
            )

    def is_queued(
        self,
        task_id: str,
    ) -> bool:
        with self.lock:
            return (
                task_id
                in self.requested
            )

    # =========================================================
    # SCHEDULING POLICY
    # =========================================================

    @staticmethod
    def _parse_dt(
        value: Any,
    ) -> datetime | None:
        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        except (TypeError, ValueError):
            return None

        if parsed.tzinfo is None:
            parsed = parsed.astimezone()

        return parsed

    def _schedule_info(
        self,
        task,
    ) -> dict[str, Any]:
        metadata = (
            dict(task.metadata)
            if isinstance(
                task.metadata,
                dict,
            )
            else {}
        )

        info: dict[str, Any] = {
            "priority": str(
                metadata.get(
                    "schedule_priority",
                    "normal",
                )
            ).lower(),
            "deadline": metadata.get(
                "schedule_deadline"
            ),
            "mission": metadata.get(
                "mission_human_id"
            ),
        }

        provider = self.schedule_provider

        if provider is not None:
            try:
                provided = provider(
                    task
                ) or {}
            except Exception:
                provided = {}

            if isinstance(
                provided,
                dict,
            ):
                for key, value in (
                    provided.items()
                ):
                    if value is not None:
                        info[key] = value

        priority = str(
            info.get(
                "priority",
                "normal",
            )
        ).lower()

        if priority not in self.PRIORITY_VALUES:
            priority = "normal"

        info["priority"] = priority

        return info

    def _effective_priority(
        self,
        task,
    ) -> tuple[int, float]:
        info = self._schedule_info(
            task
        )

        base = self.PRIORITY_VALUES.get(
            str(info.get("priority")),
            20,
        )

        deadline = self._parse_dt(
            info.get("deadline")
        )

        deadline_ts = (
            deadline.timestamp()
            if deadline is not None
            else float("inf")
        )

        # Une échéance proche peut faire remonter une mission sans écraser la
        # notion de priorité explicite. Une échéance dépassée devient urgente.
        if deadline is not None:
            now = datetime.now(
                timezone.utc
            )
            remaining = (
                deadline.astimezone(
                    timezone.utc
                )
                - now
            ).total_seconds()

            if remaining <= 0:
                base += 50
            elif remaining <= 3600:
                base += 15
            elif remaining <= 6 * 3600:
                base += 8
            elif remaining <= 24 * 3600:
                base += 3

        return (
            base,
            deadline_ts,
        )

    def _schedule_key(
        self,
        task,
    ) -> tuple[Any, ...]:
        effective, deadline_ts = (
            self._effective_priority(
                task
            )
        )

        return (
            -effective,
            deadline_ts,
            str(task.created_at),
            str(task.id),
        )

    # =========================================================
    # SUBMISSION / BACKLOG
    # =========================================================

    def _dependency_failure(
        self,
        task,
    ) -> bool:
        failure = (
            self.tasks
            .dependency_failure(
                task
            )
        )

        if not failure:
            return False

        self.tasks.update(
            task.id,
            status=(
                TaskStatus
                .FAILED
                .value
            ),
            error=failure,
        )

        self.notifier(
            f"✗ {task.id} : "
            f"{failure}"
        )

        self.resume_dependents(
            task.id
        )

        return True

    def submit(
        self,
        task_id: str,
    ) -> bool:
        """Demande l'exécution d'une tâche.

        Retourne True si la tâche vient d'entrer dans le backlog. Le démarrage
        effectif peut être différé par manque de capacité ou par une tâche plus
        prioritaire.
        """
        task = self.tasks.get(
            task_id
        )

        if task is None:
            return False

        with self.condition:
            if task_id in self.running:
                return False

            if task_id in self.requested:
                return False

        if (
            task.status
            in self.TERMINAL_STATUSES
        ):
            return False

        if self._dependency_failure(
            task
        ):
            return False

        if (
            task.depends_on
            and not (
                self.tasks
                .dependencies_satisfied_ids(
                    task.depends_on
                )
            )
        ):
            if (
                task.status
                != TaskStatus
                .WAITING_DEPENDENCY
                .value
            ):
                self.tasks.update(
                    task.id,
                    status=(
                        TaskStatus
                        .WAITING_DEPENDENCY
                        .value
                    ),
                )

            return False

        worker = self.workers.get(
            task.worker
        )

        if worker is None:
            error = (
                "Worker inconnu : "
                f"{task.worker}"
            )

            self.tasks.update(
                task.id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=error,
            )

            self.notifier(
                f"✗ {task.id} : "
                f"{error}"
            )

            self.resume_dependents(
                task.id
            )

            return False

        # Une tâche éligible reste PENDING jusqu'au vrai démarrage du worker.
        if (
            task.status
            != TaskStatus.PENDING.value
        ):
            self.tasks.update(
                task.id,
                status=TaskStatus.PENDING.value,
                error=None,
            )

        with self.condition:
            self.requested.add(
                task.id
            )
            self.condition.notify_all()

        return True

    def _eligible_requested(
        self,
    ) -> list:
        candidates = []
        stale = []

        for task_id in list(
            self.requested
        ):
            task = self.tasks.get(
                task_id
            )

            if task is None:
                stale.append(
                    task_id
                )
                continue

            if (
                task.status
                in self.TERMINAL_STATUSES
            ):
                stale.append(
                    task_id
                )
                continue

            failure = (
                self.tasks
                .dependency_failure(
                    task
                )
            )

            if failure:
                stale.append(
                    task_id
                )
                # Le traitement complet sera fait hors verrou au prochain
                # submit/check autonome. Ici on évite juste un démarrage faux.
                continue

            if (
                task.depends_on
                and not (
                    self.tasks
                    .dependencies_satisfied_ids(
                        task.depends_on
                    )
                )
            ):
                continue

            if (
                task.worker
                not in self.workers
            ):
                stale.append(
                    task_id
                )
                continue

            candidates.append(
                task
            )

        for task_id in stale:
            self.requested.discard(
                task_id
            )

        return sorted(
            candidates,
            key=self._schedule_key,
        )

    def _launch_task(
        self,
        task,
    ) -> bool:
        worker = self.workers.get(
            task.worker
        )

        if worker is None:
            return False

        # V5.4 : la préparation se fait avant de passer RUNNING et avant de
        # consommer un slot. Elle peut injecter une tâche Researcher comme
        # dépendance réelle puis renvoyer ready=False.
        if self.preparation_provider is not None:
            try:
                preparation = self.preparation_provider(task) or {}
            except Exception as exc:
                preparation = {
                    "ready": True,
                    "error": str(exc),
                }
            if isinstance(preparation, dict) and not bool(
                preparation.get("ready", True)
            ):
                return False

        # Le provider a pu modifier les dépendances ou le statut ; on relit la
        # Task persistée avant de poursuivre.
        refreshed = self.tasks.get(task.id)
        if refreshed is None:
            return False
        task = refreshed

        # La dépendance peut avoir changé depuis la sélection.
        if self._dependency_failure(
            task
        ):
            return False

        if (
            task.depends_on
            and not (
                self.tasks
                .dependencies_satisfied_ids(
                    task.depends_on
                )
            )
        ):
            self.tasks.update(
                task.id,
                status=(
                    TaskStatus
                    .WAITING_DEPENDENCY
                    .value
                ),
            )
            return False

        self.tasks.update(
            task.id,
            status=(
                TaskStatus
                .RUNNING
                .value
            ),
            error=None,
        )

        payload = task.to_dict()

        payload[
            "dependency_context"
        ] = (
            self.tasks
            .dependency_context(
                task
            )
        )

        # V5.2 : les connaissances techniques restent séparées des
        # dépendances de mission. Les workers V5.3 pourront exploiter ce bloc
        # directement ; le champ existe déjà dès maintenant dans le pipeline.
        skill_context: dict[str, Any] = {
            "required": [],
            "available": [],
            "missing": [],
            "text": "",
        }
        if self.skill_provider is not None:
            try:
                provided = self.skill_provider(
                    task
                ) or {}
                if isinstance(provided, dict):
                    skill_context.update(provided)
            except Exception as exc:
                skill_context["error"] = str(exc)

        payload["skill_context"] = skill_context

        try:
            future = self.pool.submit(
                worker.execute,
                payload,
            )

        except Exception as exc:
            error = str(exc)

            self.tasks.update(
                task.id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=error,
            )

            self.notifier(
                f"✗ {task.id} : "
                f"{error}"
            )

            self.resume_dependents(
                task.id
            )

            return False

        with self.condition:
            self.running[
                task.id
            ] = future

        future.add_done_callback(
            lambda finished_future: (
                self._finished(
                    task.id,
                    finished_future,
                )
            )
        )

        return True

    def _dispatch_available(
        self,
    ) -> int:
        launched = 0

        while True:
            with self.condition:
                total_free = (
                    MAX_WORKERS
                    - len(self.running)
                )

                if total_free <= 0:
                    return launched

                running_counts = (
                    self._running_counts()
                )

                candidates = (
                    self._eligible_requested()
                )

                selected = None

                for task in candidates:
                    used = running_counts.get(
                        task.worker,
                        0,
                    )
                    limit = self.worker_limit(
                        task.worker
                    )

                    if used < limit:
                        selected = task
                        break

                if selected is None:
                    return launched

                self.requested.discard(
                    selected.id
                )

            if self._launch_task(
                selected
            ):
                launched += 1
            else:
                # En cas de changement concurrent, on poursuit les autres.
                continue

    def _dispatch_loop(
        self,
    ) -> None:
        while not self.stop_event.is_set():
            try:
                self._dispatch_available()
            except Exception:
                # Le superviseur V4.8 récupérera les tâches qui resteraient en
                # PENDING. Le dispatcher ne doit jamais mourir sur une mission.
                pass

            with self.condition:
                if self.stop_event.is_set():
                    break
                self.condition.wait(
                    timeout=0.5
                )

    # =========================================================
    # RESULT HANDLING (V4.x COMPATIBLE)
    # =========================================================

    @staticmethod
    def _is_non_validated_test(
        task,
        result,
    ) -> bool:
        if task.worker != "tester":
            return False

        metadata = (
            task.metadata
            if isinstance(
                task.metadata,
                dict,
            )
            else {}
        )

        if not metadata.get(
            "auto_repair_enabled",
            False,
        ):
            return False

        data = (
            result.data
            if isinstance(
                result.data,
                dict,
            )
            else {}
        )

        return (
            str(
                data.get(
                    "verdict",
                    "",
                )
            ).upper()
            == "NON_VALIDÉ"
        )

    def _handle_non_validated_test(
        self,
        task_id: str,
        result,
    ) -> None:
        data = dict(
            result.data
            if isinstance(
                result.data,
                dict,
            )
            else {}
        )

        self.tasks.update(
            task_id,
            status=(
                TaskStatus
                .COMPLETED
                .value
            ),
            result=result.message,
            result_data=data,
            error=None,
        )

        if self.repair_handler is None:
            self.tasks.update(
                task_id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=(
                    "Test non validé et aucun "
                    "gestionnaire de correction "
                    "n'est disponible."
                ),
            )

            self.notifier(
                f"✗ {task_id} : "
                "test non validé"
            )

            self.resume_dependents(
                task_id
            )
            return

        try:
            outcome = (
                self.repair_handler(
                    task_id
                )
                or {}
            )

        except Exception as exc:
            outcome = {
                "scheduled": False,
                "reason": str(exc),
            }

        if outcome.get(
            "scheduled"
        ):
            attempt = outcome.get(
                "attempt",
                "?",
            )

            maximum = outcome.get(
                "maximum",
                "?",
            )

            current = self.tasks.get(
                task_id
            )

            current_data = dict(
                current.result_data
                if (
                    current is not None
                    and isinstance(
                        current.result_data,
                        dict,
                    )
                )
                else data
            )

            current_data[
                "auto_repair_scheduled"
            ] = True

            current_data[
                "auto_repair_attempt"
            ] = attempt

            current_data[
                "auto_repair_maximum"
            ] = maximum

            self.tasks.update(
                task_id,
                result=(
                    str(
                        result.message
                        or ""
                    ).rstrip()
                    + "\n\n"
                    + (
                        "Correction automatique "
                        f"{attempt}/{maximum} lancée."
                    )
                ).strip(),
                result_data=current_data,
                error=None,
            )

            self.notifier(
                f"✗ {task_id} : "
                "vérification non validée, "
                "correction automatique lancée"
            )

            return

        reason = str(
            outcome.get(
                "reason",
                "Test non validé.",
            )
        )

        current = self.tasks.get(
            task_id
        )

        current_data = dict(
            current.result_data
            if (
                current is not None
                and isinstance(
                    current.result_data,
                    dict,
                )
            )
            else data
        )

        if outcome.get(
            "exhausted"
        ):
            current_data[
                "auto_repair_exhausted"
            ] = True

        self.tasks.update(
            task_id,
            status=(
                TaskStatus
                .FAILED
                .value
            ),
            result=result.message,
            result_data=current_data,
            error=reason,
        )

        self.notifier(
            f"✗ {task_id} : "
            f"{reason}"
        )

        self.resume_dependents(
            task_id
        )

    def _finished(
        self,
        task_id: str,
        future: Future,
    ) -> None:
        with self.condition:
            self.running.pop(
                task_id,
                None,
            )
            self.condition.notify_all()

        current = self.tasks.get(
            task_id
        )

        if current is None:
            return

        if (
            current.status
            == TaskStatus.CANCELLED.value
        ):
            return

        try:
            result = future.result()

        except Exception as exc:
            current = self.tasks.get(
                task_id
            )

            if (
                current is not None
                and current.status
                == TaskStatus.CANCELLED.value
            ):
                return

            error = str(exc)

            self.tasks.update(
                task_id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                error=error,
            )

            self.notifier(
                f"✗ {task_id} : "
                f"{error}"
            )

            self.resume_dependents(
                task_id
            )

            return

        current = self.tasks.get(
            task_id
        )

        if (
            current is None
            or current.status
            == TaskStatus.CANCELLED.value
        ):
            return

        if not result.success:
            error = (
                result.error
                or result.message
            )

            self.tasks.update(
                task_id,
                status=(
                    TaskStatus
                    .FAILED
                    .value
                ),
                result=result.message,
                result_data=result.data,
                error=error,
            )

            self.notifier(
                f"✗ {task_id} : "
                f"{error}"
            )

            self.resume_dependents(
                task_id
            )

            return

        # V5.5 : un worker peut suspendre sa propre tâche pour demander un
        # renfort. Le coordinateur crée alors une tâche auxiliaire et remet la
        # tâche métier en WAITING_DEPENDENCY.
        result_data = (
            result.data
            if isinstance(getattr(result, "data", None), dict)
            else {}
        )
        collaboration_request = result_data.get("collaboration_request")
        if isinstance(collaboration_request, dict):
            if self.collaboration_handler is None:
                outcome = {
                    "scheduled": False,
                    "reason": "Aucun coordinateur de collaboration disponible.",
                }
            else:
                try:
                    outcome = self.collaboration_handler(
                        current,
                        result,
                    ) or {}
                except Exception as exc:
                    outcome = {
                        "scheduled": False,
                        "reason": str(exc),
                    }

            if outcome.get("scheduled"):
                self.wake_scheduler()
                return

            error = str(
                outcome.get(
                    "reason",
                    "Demande de collaboration impossible.",
                )
            )
            self.tasks.update(
                task_id,
                status=TaskStatus.FAILED.value,
                result=result.message,
                result_data=result_data,
                error=error,
            )
            self.notifier(
                f"✗ {task_id} : collaboration impossible ({error})"
            )
            self.resume_dependents(task_id)
            return

        if self._is_non_validated_test(
            current,
            result,
        ):
            self._handle_non_validated_test(
                task_id,
                result,
            )
            return

        approval = (
            result.data.get(
                "approval_required_files",
                [],
            )
            or []
        )

        if approval:
            self.tasks.update(
                task_id,
                status=(
                    TaskStatus
                    .WAITING_APPROVAL
                    .value
                ),
                result=result.message,
                result_data=result.data,
                error=None,
            )

            self.notifier(
                f"⚠ {task_id} "
                "attend ton approbation : "
                + ", ".join(
                    approval
                )
            )

            return

        self.tasks.update(
            task_id,
            status=(
                TaskStatus
                .COMPLETED
                .value
            ),
            result=result.message,
            result_data=result.data,
            error=None,
        )

        completed_task = (
            self.tasks.get(
                task_id
            )
        )

        worker_name = (
            completed_task.worker
            if completed_task
            else "worker"
        )

        self.notifier(
            f"✓ {task_id} "
            "terminée par "
            f"{worker_name}"
        )

        self.resume_dependents(
            task_id
        )

    def resume_dependents(
        self,
        task_id: str,
    ) -> None:
        for task in (
            self.tasks
            .dependents_of(
                task_id
            )
        ):
            if (
                task.status
                in {
                    TaskStatus.PENDING.value,
                    TaskStatus
                    .WAITING_DEPENDENCY
                    .value,
                }
            ):
                self.submit(
                    task.id
                )

        self.wake_scheduler()

    # =========================================================
    # CONTROL / RECOVERY
    # =========================================================

    def cancel(
        self,
        task_id: str,
    ) -> bool:
        with self.condition:
            if task_id in self.requested:
                self.requested.discard(
                    task_id
                )
                self.condition.notify_all()
                return True

            future = self.running.get(
                task_id
            )

        if future is None:
            return False

        future.cancel()
        return True

    def recover(
        self,
        task_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if task_ids is None:
            selected = [
                task.id
                for task
                in self.tasks.list()
                if (
                    isinstance(
                        task.metadata,
                        dict,
                    )
                    and task.metadata.get(
                        "mission_id"
                    )
                )
            ]

        else:
            selected = list(
                dict.fromkeys(
                    task_ids
                )
            )

        interrupted = (
            self.tasks
            .recover_interrupted(
                selected
            )
        )

        selected_set = set(
            selected
        )

        candidates = [
            task
            for task
            in reversed(
                self.tasks.list()
            )
            if (
                task.id in selected_set
                and task.status
                in {
                    TaskStatus.PENDING.value,
                    TaskStatus
                    .WAITING_DEPENDENCY
                    .value,
                }
            )
        ]

        submitted = []

        for task in candidates:
            if self.submit(
                task.id
            ):
                submitted.append(
                    task.id
                )

        waiting_approval = [
            task.id
            for task
            in self.tasks.list()
            if (
                task.id in selected_set
                and task.status
                == TaskStatus
                .WAITING_APPROVAL
                .value
            )
        ]

        paused = [
            task.id
            for task
            in self.tasks.list()
            if (
                task.id in selected_set
                and task.status
                == TaskStatus.PAUSED.value
            )
        ]

        return {
            "interrupted": interrupted,
            "submitted": submitted,
            "waiting_approval": (
                waiting_approval
            ),
            "paused": paused,
        }

    # =========================================================
    # V5.0 WORKLOAD VISIBILITY
    # =========================================================

    def workload_snapshot(
        self,
    ) -> dict[str, Any]:
        with self.lock:
            running_ids = list(
                self.running
            )
            requested_ids = list(
                self.requested
            )

        running_rows = []
        for task_id in running_ids:
            task = self.tasks.get(task_id)
            if task is None:
                continue
            info = self._schedule_info(task)
            running_rows.append({
                "task_id": task.id,
                "worker": task.worker,
                "title": task.title,
                "mission": info.get("mission"),
                "priority": info.get("priority", "normal"),
                "deadline": info.get("deadline"),
            })

        backlog_tasks = []
        for task_id in requested_ids:
            task = self.tasks.get(task_id)
            if task is None:
                continue
            if task.status in self.TERMINAL_STATUSES:
                continue
            backlog_tasks.append(task)

        backlog_tasks = sorted(
            backlog_tasks,
            key=self._schedule_key,
        )

        backlog_rows = []
        for index, task in enumerate(
            backlog_tasks,
            1,
        ):
            info = self._schedule_info(task)
            effective, _ = self._effective_priority(task)
            backlog_rows.append({
                "position": index,
                "task_id": task.id,
                "worker": task.worker,
                "title": task.title,
                "mission": info.get("mission"),
                "priority": info.get("priority", "normal"),
                "deadline": info.get("deadline"),
                "effective_priority": effective,
            })

        workers = []
        running_counts: dict[str, int] = {}
        queued_counts: dict[str, int] = {}

        for row in running_rows:
            worker = str(row["worker"])
            running_counts[worker] = (
                running_counts.get(worker, 0)
                + 1
            )

        for row in backlog_rows:
            worker = str(row["worker"])
            queued_counts[worker] = (
                queued_counts.get(worker, 0)
                + 1
            )

        for worker_name in self.workers:
            limit = self.worker_limit(
                worker_name
            )
            running = running_counts.get(
                worker_name,
                0,
            )
            workers.append({
                "worker": worker_name,
                "running": running,
                "limit": limit,
                "queued": queued_counts.get(
                    worker_name,
                    0,
                ),
                "status": (
                    "busy"
                    if running >= limit
                    else "available"
                ),
            })

        return {
            "capacity": MAX_WORKERS,
            "running": len(running_rows),
            "free_slots": max(
                0,
                MAX_WORKERS - len(running_rows),
            ),
            "backlog": len(backlog_rows),
            "running_tasks": running_rows,
            "backlog_tasks": backlog_rows,
            "workers": workers,
        }

    @staticmethod
    def _deadline_short(
        value: Any,
    ) -> str:
        parsed = WorkerEngine._parse_dt(
            value
        )
        if parsed is None:
            return "aucune"
        return parsed.astimezone().strftime(
            "%d/%m %H:%M"
        )

    def workload_summary(
        self,
    ) -> str:
        snap = self.workload_snapshot()

        lines = [
            "WORKLOAD V5.0",
            (
                "Capacité : "
                f"{snap['running']}/{snap['capacity']} slot(s) utilisé(s)"
            ),
            (
                "Backlog : "
                f"{snap['backlog']} tâche(s)"
            ),
            "",
            "WORKERS",
        ]

        for item in snap["workers"]:
            lines.append(
                "- "
                f"{item['worker']} | "
                f"{item['running']}/{item['limit']} actif | "
                f"{item['queued']} en attente | "
                + (
                    "occupé"
                    if item["status"] == "busy"
                    else "disponible"
                )
            )

        if snap["backlog_tasks"]:
            lines.extend([
                "",
                "PROCHAINES TÂCHES",
            ])
            for item in snap["backlog_tasks"][:8]:
                mission = item.get("mission") or "-"
                priority = self.PRIORITY_LABELS.get(
                    str(item.get("priority")),
                    str(item.get("priority")),
                )
                lines.append(
                    f"{item['position']}. {mission} | "
                    f"{item['worker']} | priorité {priority} | "
                    f"échéance {self._deadline_short(item.get('deadline'))} | "
                    f"{item['title']}"
                )

        return "\n".join(lines)

    def backlog_summary(
        self,
    ) -> str:
        snap = self.workload_snapshot()

        if not snap["backlog_tasks"]:
            return "BACKLOG V5.0\nAucune tâche en attente d'un worker."

        lines = [
            "BACKLOG V5.0",
        ]

        for item in snap["backlog_tasks"]:
            mission = item.get("mission") or "-"
            priority = self.PRIORITY_LABELS.get(
                str(item.get("priority")),
                str(item.get("priority")),
            )
            lines.append(
                f"{item['position']}. {mission} | {item['worker']} | "
                f"priorité {priority} | "
                f"échéance {self._deadline_short(item.get('deadline'))} | "
                f"{item['title']}"
            )

        return "\n".join(lines)

    def workers_summary(
        self,
    ) -> str:
        snap = self.workload_snapshot()
        lines = [
            "WORKERS V5.0",
        ]

        for item in snap["workers"]:
            lines.append(
                "- "
                f"{item['worker']} : "
                + (
                    "occupé"
                    if item["status"] == "busy"
                    else "disponible"
                )
                + f" | actif {item['running']}/{item['limit']}"
                + f" | backlog {item['queued']}"
            )

        return "\n".join(lines)

    # =========================================================
    # SHUTDOWN
    # =========================================================

    def shutdown(self) -> None:
        self.stop_event.set()

        with self.condition:
            self.condition.notify_all()

        if self.dispatch_thread.is_alive():
            self.dispatch_thread.join(
                timeout=2.0
            )

        self.pool.shutdown(
            wait=True,
            cancel_futures=False,
        )
