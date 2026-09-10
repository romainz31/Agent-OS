from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore
from agentos.tasks import TaskStatus


class AutonomyController:
    """Supervision autonome et prudente des missions Agent-OS.

    Principes :
    - aucune approbation sensible n'est accordée automatiquement ;
    - une tâche échouée est retentée une fois telle quelle ;
    - au second échec, un diagnostic AI Worker est injecté avant une nouvelle
      tentative ;
    - après épuisement du budget, l'utilisateur est prévenu ;
    - les décisions sont persistées dans ``data/manager_decisions.json``.
    """

    PRIORITIES = {
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

    PRIORITY_ALIASES = {
        "basse": "low",
        "bas": "low",
        "faible": "low",
        "low": "low",
        "normale": "normal",
        "normal": "normal",
        "moyenne": "normal",
        "moyen": "normal",
        "haute": "high",
        "haut": "high",
        "elevee": "high",
        "élevée": "high",
        "high": "high",
        "critique": "critical",
        "urgente": "critical",
        "urgent": "critical",
        "critical": "critical",
    }

    MISSION_RE = re.compile(
        r"\bM-\d{1,6}\b",
        flags=re.IGNORECASE,
    )

    TASK_RE = re.compile(
        r"\btask_[A-Za-z0-9]+\b",
    )

    def __init__(
        self,
        manager,
        *,
        check_interval: float = 5.0,
        approval_reminder_seconds: float = 900.0,
    ) -> None:
        self.manager = manager
        self.check_interval = max(
            1.0,
            float(check_interval),
        )
        self.approval_reminder_seconds = max(
            60.0,
            float(approval_reminder_seconds),
        )

        self.decision_store = JsonStore(
            DATA_DIR / "manager_decisions.json",
            [],
        )
        self.state_store = JsonStore(
            DATA_DIR / "manager_state.json",
            {
                "enabled": True,
            },
        )

        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_check_at: str | None = None

        raw_state = self.state_store.load()
        self.state = (
            raw_state
            if isinstance(raw_state, dict)
            else {"enabled": True}
        )
        self.state.setdefault("enabled", True)

        raw_decisions = self.decision_store.load()
        self.decisions: list[dict[str, Any]] = (
            raw_decisions
            if isinstance(raw_decisions, list)
            else []
        )
        self.decisions = [
            item
            for item in self.decisions[-500:]
            if isinstance(item, dict)
        ]

    # =========================================================
    # GENERIC HELPERS
    # =========================================================

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _local_now() -> datetime:
        return datetime.now().astimezone()

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed

    @classmethod
    def _display_time(cls, value: Any) -> str:
        parsed = cls._parse_dt(value)
        if parsed is None:
            return "--:--:--"
        return parsed.astimezone().strftime("%H:%M:%S")

    @classmethod
    def _display_datetime(cls, value: Any) -> str:
        parsed = cls._parse_dt(value)
        if parsed is None:
            return "inconnue"
        return parsed.astimezone().strftime("%d/%m/%Y %H:%M")

    @classmethod
    def _deadline_human(cls, value: Any) -> str:
        deadline = cls._parse_dt(value)
        if deadline is None:
            return "aucune"
        local_deadline = deadline.astimezone()
        now = cls._local_now()
        seconds = (local_deadline - now).total_seconds()
        absolute = local_deadline.strftime("%d/%m %H:%M")
        if abs(seconds) < 60:
            return absolute + " (maintenant)"
        overdue = seconds < 0
        seconds = abs(seconds)
        minutes = int(seconds // 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        if days:
            relative = f"{days} j {hours} h"
        elif hours:
            relative = f"{hours} h {minutes:02d}"
        else:
            relative = f"{minutes} min"
        return (
            f"{absolute} (dépassée de {relative})"
            if overdue
            else f"{absolute} (dans {relative})"
        )

    @staticmethod
    def _ascii(text: str) -> str:
        import unicodedata

        value = unicodedata.normalize(
            "NFKD",
            str(text or ""),
        )
        return "".join(
            char
            for char in value
            if not unicodedata.combining(char)
        ).lower()

    @classmethod
    def _mission_ref(
        cls,
        text: str,
    ) -> str | None:
        match = cls.MISSION_RE.search(
            str(text or "")
        )
        if match is None:
            return None
        raw = match.group(0).upper()
        number = int(raw.split("-")[1])
        return f"M-{number:03d}"

    def _mission_metadata(
        self,
        mission,
    ) -> dict[str, Any]:
        return dict(
            mission.metadata
            if isinstance(mission.metadata, dict)
            else {}
        )

    def _task_metadata(
        self,
        task,
    ) -> dict[str, Any]:
        return dict(
            task.metadata
            if isinstance(task.metadata, dict)
            else {}
        )

    def _save_state(self) -> None:
        self.state_store.save(
            dict(self.state)
        )

    def _save_decisions(self) -> None:
        self.decisions = self.decisions[-500:]
        self.decision_store.save(
            list(self.decisions)
        )

    # =========================================================
    # DECISION LOG
    # =========================================================

    def record(
        self,
        action: str,
        *,
        mission=None,
        task=None,
        detail: str = "",
        level: str = "info",
        notify: bool = False,
    ) -> dict[str, Any]:
        item = {
            "id": "decision_" + uuid.uuid4().hex[:10],
            "at": self._now().isoformat(),
            "action": str(action),
            "level": str(level),
            "mission_id": (
                mission.human_id
                if mission is not None
                else None
            ),
            "task_id": (
                task.id
                if task is not None
                else None
            ),
            "detail": str(detail or ""),
        }

        with self.lock:
            self.decisions.append(item)
            self._save_decisions()

        if notify:
            prefix = (
                f"{mission.human_id} — "
                if mission is not None
                else "Manager — "
            )
            self.manager._append_notification(
                prefix + str(detail or action)
            )

        return item

    def decisions_summary(
        self,
        limit: int = 12,
    ) -> str:
        with self.lock:
            items = list(
                self.decisions[-max(1, int(limit)):]
            )

        if not items:
            return "Aucune décision autonome enregistrée."

        lines = [
            "DÉCISIONS RÉCENTES DU MANAGER",
        ]

        for item in reversed(items):
            mission = item.get("mission_id") or "-"
            action = item.get("action") or "action"
            detail = item.get("detail") or ""
            at = self._display_time(item.get("at"))
            lines.append(
                f"- {at} | {mission} | {action}"
                + (f" — {detail}" if detail else "")
            )

        return "\n".join(lines)

    # =========================================================
    # MISSION POLICY
    # =========================================================

    def _priority_from_text(
        self,
        text: str,
    ) -> str | None:
        value = self._ascii(text)

        if "urgent" in value:
            return "critical"

        for alias, canonical in self.PRIORITY_ALIASES.items():
            alias_ascii = self._ascii(alias)
            if re.search(
                rf"\bpriorit(?:e|é)\s+{re.escape(alias_ascii)}\b",
                value,
            ):
                return canonical

        # Commande avec référence intercalée : "priorité M-042 haute".
        if "priorite" in value:
            for alias, canonical in self.PRIORITY_ALIASES.items():
                alias_ascii = self._ascii(alias)
                if re.search(
                    rf"\bpriorite\b.{{0,24}}\b{re.escape(alias_ascii)}\b",
                    value,
                ):
                    return canonical

        # Commande inversée : "haute priorité"
        for alias, canonical in self.PRIORITY_ALIASES.items():
            alias_ascii = self._ascii(alias)
            if re.search(
                rf"\b{re.escape(alias_ascii)}\s+priorit(?:e|é)\b",
                value,
            ):
                return canonical

        return None

    def parse_deadline(
        self,
        text: str,
    ) -> datetime | None:
        raw = str(text or "")
        value = self._ascii(raw)
        now = self._local_now()

        # Formats absolus : 2026-09-08 20:30 / 2026-09-08T20:30
        match = re.search(
            r"\b(20\d{2})-(\d{2})-(\d{2})[ t](\d{1,2})(?::(\d{2}))?\b",
            value,
        )
        if match:
            year, month, day, hour, minute = match.groups()
            try:
                return datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour),
                    int(minute or 0),
                    tzinfo=now.tzinfo,
                )
            except ValueError:
                return None

        # dans 30 min / dans 2 heures / dans 3 jours
        match = re.search(
            r"\bdans\s+(\d+(?:[.,]\d+)?)\s*(minute|min|minutes|heure|heures|h|jour|jours|j)\b",
            value,
        )
        if match:
            number = float(match.group(1).replace(",", "."))
            unit = match.group(2)
            if unit.startswith("min"):
                delta = timedelta(minutes=number)
            elif unit in {"heure", "heures", "h"}:
                delta = timedelta(hours=number)
            else:
                delta = timedelta(days=number)
            return now + delta

        # demain 18h / demain 18:30
        match = re.search(
            r"\bdemain(?:\s+(?:a|à))?\s*(\d{1,2})(?::(\d{2})|h(?:(\d{2}))?)?\b",
            value,
        )
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or match.group(3) or 0)
            if hour > 23 or minute > 59:
                return None
            target = now + timedelta(days=1)
            return target.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )

        # aujourd'hui 18h
        match = re.search(
            r"\baujourd(?:'hui| hui)(?:\s+(?:a|à))?\s*(\d{1,2})(?::(\d{2})|h(?:(\d{2}))?)?\b",
            value,
        )
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or match.group(3) or 0)
            if hour > 23 or minute > 59:
                return None
            return now.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )

        # avant 18h / deadline 18:30
        if any(
            marker in value
            for marker in (
                "deadline",
                "echeance",
                "échéance",
                "avant ",
                "pour ",
            )
        ):
            match = re.search(
                r"(?:deadline|echeance|avant|pour)\s+(?:a|à\s+)?(\d{1,2})(?::(\d{2})|h(?:(\d{2}))?)?\b",
                value,
            )
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2) or match.group(3) or 0)
                if hour > 23 or minute > 59:
                    return None
                target = now.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0,
                )
                if target <= now:
                    target += timedelta(days=1)
                return target

        return None

    def policy_for(
        self,
        mission,
    ) -> dict[str, Any]:
        metadata = self._mission_metadata(mission)
        priority = str(
            metadata.get("priority", "normal")
        ).lower()
        if priority not in self.PRIORITIES:
            priority = "normal"

        return {
            "enabled": bool(
                metadata.get("autonomy_enabled", True)
            ),
            "priority": priority,
            "deadline": metadata.get("deadline"),
            "overdue_notified": bool(
                metadata.get("autonomy_overdue_notified", False)
            ),
            "deadline_warning_notified": bool(
                metadata.get("autonomy_deadline_warning_notified", False)
            ),
        }

    def set_priority(
        self,
        mission,
        priority: str,
        *,
        record: bool = True,
    ) -> None:
        canonical = self.PRIORITY_ALIASES.get(
            self._ascii(priority),
            str(priority).lower(),
        )
        if canonical not in self.PRIORITIES:
            raise ValueError(
                "Priorité inconnue : basse, normale, haute ou critique."
            )

        self.manager.missions.set_status(
            mission.id,
            mission.status,
            metadata_patch={
                "priority": canonical,
            },
        )

        if record:
            self.record(
                "priority_changed",
                mission=mission,
                detail=(
                    "Priorité "
                    + self.PRIORITY_LABELS[canonical]
                ),
            )

    def set_deadline(
        self,
        mission,
        deadline: datetime | None,
        *,
        record: bool = True,
    ) -> None:
        patch = {
            "deadline": (
                deadline.isoformat()
                if deadline is not None
                else None
            ),
            "autonomy_overdue_notified": False,
            "autonomy_deadline_warning_notified": False,
        }

        self.manager.missions.set_status(
            mission.id,
            mission.status,
            metadata_patch=patch,
        )

        if record:
            detail = (
                "Échéance supprimée"
                if deadline is None
                else "Échéance " + deadline.isoformat(timespec="minutes")
            )
            self.record(
                "deadline_changed",
                mission=mission,
                detail=detail,
            )

    def set_mission_enabled(
        self,
        mission,
        enabled: bool,
    ) -> None:
        self.manager.missions.set_status(
            mission.id,
            mission.status,
            metadata_patch={
                "autonomy_enabled": bool(enabled),
            },
        )
        self.record(
            "mission_autonomy_changed",
            mission=mission,
            detail=(
                "Autonomie activée"
                if enabled
                else "Autonomie désactivée"
            ),
        )

    def apply_creation_policy(
        self,
        mission,
        message: str,
    ) -> dict[str, Any]:
        priority = self._priority_from_text(message)
        deadline = self.parse_deadline(message)

        patch: dict[str, Any] = {
            "autonomy_enabled": True,
        }

        if priority is not None:
            patch["priority"] = priority
        elif "priority" not in self._mission_metadata(mission):
            patch["priority"] = "normal"

        if deadline is not None:
            patch["deadline"] = deadline.isoformat()
            patch["autonomy_overdue_notified"] = False
            patch["autonomy_deadline_warning_notified"] = False

        self.manager.missions.set_status(
            mission.id,
            mission.status,
            metadata_patch=patch,
        )

        if priority is not None or deadline is not None:
            bits = []
            if priority is not None:
                bits.append(
                    "priorité " + self.PRIORITY_LABELS[priority]
                )
            if deadline is not None:
                bits.append(
                    "échéance " + deadline.isoformat(timespec="minutes")
                )
            self.record(
                "mission_policy_detected",
                mission=mission,
                detail=" | ".join(bits),
            )

        return {
            "priority": priority,
            "deadline": deadline,
        }

    # =========================================================
    # FAILURE RECOVERY
    # =========================================================

    def _mission_for_task(self, task):
        metadata = self._task_metadata(task)
        mission_id = metadata.get("mission_id")
        if not mission_id:
            return None
        return self.manager.missions.get(mission_id)

    def _autonomy_allowed(self, mission) -> bool:
        if not bool(self.state.get("enabled", True)):
            return False
        if mission is None:
            return False
        policy = self.policy_for(mission)
        return bool(policy["enabled"])

    def _retry_same_task(
        self,
        mission,
        task,
    ) -> bool:
        metadata = self._task_metadata(task)
        count = int(
            metadata.get("autonomy_retry_count", 0)
            or 0
        )
        if count >= 1:
            return False

        metadata["autonomy_retry_count"] = count + 1
        metadata["autonomy_last_error"] = str(
            task.error or task.result or ""
        )
        metadata["autonomy_last_action"] = "retry_same_task"

        self.manager.tasks.update(
            task.id,
            metadata=metadata,
        )
        self.manager.tasks.reset_for_execution(
            task.id
        )

        submitted = self.manager.engine.submit(
            task.id
        )

        self.record(
            "automatic_retry",
            mission=mission,
            task=task,
            detail=(
                "Nouvelle tentative automatique du même worker"
                + (" lancée" if submitted else " préparée")
            ),
        )
        return True

    def _diagnostic_then_retry(
        self,
        mission,
        task,
    ) -> bool:
        metadata = self._task_metadata(task)
        count = int(
            metadata.get("autonomy_strategy_count", 0)
            or 0
        )
        if count >= 1:
            return False

        error = str(
            task.error or task.result or "erreur inconnue"
        )

        diagnostic = self.manager.tasks.create(
            title=(
                "Diagnostic autonome — "
                + task.title[:90]
            ),
            description=(
                "Analyse l'échec suivant et fournis au worker suivant une "
                "stratégie de reprise concrète, concise et exploitable.\n\n"
                f"Mission : {mission.title}\n"
                f"Étape : {task.title}\n"
                f"Worker : {task.worker}\n"
                f"Erreur : {error}\n\n"
                "Ne modifie aucun fichier : diagnostique seulement la cause, "
                "les vérifications à faire et la meilleure stratégie de reprise."
            ),
            worker="ai_worker",
            depends_on=list(task.depends_on),
            metadata={
                "mission_id": mission.id,
                "autonomy_diagnostic": True,
                "autonomy_for_task": task.id,
                "original_message": mission.description,
                "user_original_message": mission.description,
                "router_reason": "autonomy_diagnostic",
                "auto_repair_enabled": False,
            },
        )

        metadata["autonomy_strategy_count"] = count + 1
        metadata["autonomy_last_error"] = error
        metadata["autonomy_last_action"] = "diagnostic_then_retry"
        metadata["autonomy_diagnostic_task"] = diagnostic.id

        dependencies = list(
            dict.fromkeys(
                list(task.depends_on)
                + [diagnostic.id]
            )
        )

        self.manager.tasks.update(
            task.id,
            metadata=metadata,
            depends_on=dependencies,
            error=None,
            status=TaskStatus.WAITING_DEPENDENCY.value,
        )

        submitted = self.manager.engine.submit(
            diagnostic.id
        )

        self.record(
            "strategy_changed",
            mission=mission,
            task=task,
            detail=(
                "Diagnostic AI Worker injecté avant une nouvelle tentative"
                + ("" if submitted else " (en attente de dépendances)")
            ),
        )
        return True

    def handle_failed_task(
        self,
        task,
    ) -> bool:
        mission = self._mission_for_task(task)

        if not self._autonomy_allowed(mission):
            return False

        # Les refus/approbations ne sont jamais contournés.
        error_text = str(task.error or "")
        if error_text in {
            "approval_rejected",
            "approval_rejected_dependency",
        }:
            return False

        # Une dépendance cassée se traite sur la tâche source, pas en
        # relançant en boucle tous ses dépendants.
        if error_text.startswith((
            "Dépendance échouée",
            "Dépendance annulée",
            "Dépendance introuvable",
        )):
            return False

        if self._retry_same_task(
            mission,
            task,
        ):
            return True

        task_metadata = self._task_metadata(task)
        if task_metadata.get("autonomy_diagnostic"):
            original_id = str(
                task_metadata.get("autonomy_for_task", "")
                or ""
            )
            original = (
                self.manager.tasks.get(original_id)
                if original_id
                else None
            )
            if original is not None and original.status not in {
                TaskStatus.COMPLETED.value,
                TaskStatus.CANCELLED.value,
            }:
                self.manager.tasks.update(
                    original.id,
                    status=TaskStatus.FAILED.value,
                    error=(
                        "Le diagnostic autonome nécessaire à la reprise "
                        "a lui-même échoué."
                    ),
                )

            self.record(
                "diagnostic_escalation",
                mission=mission,
                task=task,
                level="warning",
                detail=(
                    "Le diagnostic autonome a lui-même échoué après une "
                    "nouvelle tentative ; intervention humaine requise."
                ),
            )
            return False

        if self._diagnostic_then_retry(
            mission,
            task,
        ):
            return True

        self.record(
            "escalation_required",
            mission=mission,
            task=task,
            level="warning",
            detail=(
                "Budget de récupération automatique épuisé ; "
                "intervention humaine requise."
            ),
        )
        return False

    def on_worker_event(
        self,
        text: str,
    ) -> bool:
        value = str(text or "")
        if not value.startswith("✗"):
            return False

        match = self.TASK_RE.search(value)
        if match is None:
            return False

        task = self.manager.tasks.get(
            match.group(0)
        )
        if task is None:
            return False

        if task.status != TaskStatus.FAILED.value:
            return False

        return self.handle_failed_task(task)

    # =========================================================
    # PERIODIC SUPERVISION
    # =========================================================

    def _sort_key(self, mission) -> tuple[int, float, str]:
        policy = self.policy_for(mission)
        priority = self.PRIORITIES.get(
            policy["priority"],
            20,
        )
        deadline = self._parse_dt(policy["deadline"])
        deadline_ts = (
            deadline.timestamp()
            if deadline is not None
            else float("inf")
        )

        # Une échéance dépassée devient prioritaire pour la supervision sans
        # écraser la priorité explicitement choisie par l'utilisateur.
        if deadline is not None:
            try:
                if (
                    deadline.astimezone(timezone.utc)
                    <= self._now()
                ):
                    priority = max(priority, 50)
            except (ValueError, OSError):
                pass
        return (
            -priority,
            deadline_ts,
            mission.created_at,
        )

    def _check_deadline(
        self,
        mission,
    ) -> int:
        policy = self.policy_for(mission)
        deadline = self._parse_dt(
            policy["deadline"]
        )
        if deadline is None:
            return 0

        now = self._local_now()
        if deadline.tzinfo is None:
            deadline = deadline.replace(
                tzinfo=now.tzinfo
            )

        remaining = (
            deadline.astimezone(timezone.utc)
            - now.astimezone(timezone.utc)
        ).total_seconds()

        if remaining <= 0:
            if not policy["overdue_notified"]:
                self.manager.missions.set_status(
                    mission.id,
                    mission.status,
                    metadata_patch={
                        "autonomy_overdue_notified": True,
                    },
                )
                self.record(
                    "deadline_overdue",
                    mission=mission,
                    level="warning",
                    detail=(
                        "Échéance dépassée. La mission reste supervisée "
                        "et passe au premier niveau d'attention."
                    ),
                    notify=True,
                )
                return 1
            return 0

        if remaining <= 900 and not policy[
            "deadline_warning_notified"
        ]:
            self.manager.missions.set_status(
                mission.id,
                mission.status,
                metadata_patch={
                    "autonomy_deadline_warning_notified": True,
                },
            )
            minutes = max(1, int(remaining // 60))
            self.record(
                "deadline_warning",
                mission=mission,
                detail=(
                    f"Échéance dans environ {minutes} minute(s)."
                ),
                notify=True,
            )
            return 1

        return 0

    def _check_tasks(
        self,
        mission,
    ) -> dict[str, int]:
        result = {
            "submitted": 0,
            "orphan_recovered": 0,
            "approval_reminders": 0,
        }

        for task_id in list(mission.task_ids):
            task = self.manager.tasks.get(task_id)
            if task is None:
                continue

            if task.status == TaskStatus.RUNNING.value:
                if not self.manager.engine.is_running(task.id):
                    self.manager.tasks.reset_for_execution(task.id)
                    if self.manager.engine.submit(task.id):
                        result["orphan_recovered"] += 1
                    self.record(
                        "orphan_task_recovered",
                        mission=mission,
                        task=task,
                        detail=(
                            "Tâche marquée running sans worker actif : relancée."
                        ),
                    )
                continue

            if task.status == TaskStatus.PENDING.value:
                if self.manager.engine.submit(task.id):
                    result["submitted"] += 1
                continue

            if task.status == TaskStatus.WAITING_DEPENDENCY.value:
                if self.manager.tasks.dependencies_satisfied_ids(
                    list(task.depends_on)
                ):
                    self.manager.tasks.reset_for_execution(task.id)
                    if self.manager.engine.submit(task.id):
                        result["submitted"] += 1
                continue

            if task.status == TaskStatus.WAITING_APPROVAL.value:
                updated = self._parse_dt(task.updated_at)
                if updated is None:
                    continue
                age = (
                    self._now()
                    - updated.astimezone(timezone.utc)
                ).total_seconds()
                metadata = self._task_metadata(task)
                reminded = bool(
                    metadata.get("autonomy_approval_reminded", False)
                )
                if (
                    age >= self.approval_reminder_seconds
                    and not reminded
                ):
                    metadata["autonomy_approval_reminded"] = True
                    self.manager.tasks.update(
                        task.id,
                        metadata=metadata,
                    )
                    self.record(
                        "approval_reminder",
                        mission=mission,
                        task=task,
                        detail=(
                            "Une autorisation est toujours requise ; "
                            "aucune validation automatique n'a été faite."
                        ),
                        notify=True,
                    )
                    result["approval_reminders"] += 1

        return result

    def check_once(self) -> dict[str, Any]:
        summary = {
            "checked": 0,
            "submitted": 0,
            "orphan_recovered": 0,
            "approval_reminders": 0,
            "deadline_events": 0,
        }

        self.last_check_at = self._now().isoformat()

        if not bool(self.state.get("enabled", True)):
            return summary

        missions = self.manager.missions.active(
            self.manager.tasks
        )
        missions = sorted(
            missions,
            key=self._sort_key,
        )

        for mission in missions:
            policy = self.policy_for(mission)
            if not policy["enabled"]:
                continue

            summary["checked"] += 1
            summary["deadline_events"] += self._check_deadline(
                mission
            )

            task_summary = self._check_tasks(
                mission
            )
            for key in (
                "submitted",
                "orphan_recovered",
                "approval_reminders",
            ):
                summary[key] += int(task_summary[key])

        return summary

    def _loop(self) -> None:
        while not self.stop_event.wait(
            self.check_interval
        ):
            try:
                self.check_once()
            except Exception as exc:
                self.record(
                    "supervision_error",
                    level="warning",
                    detail=str(exc),
                )

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="agentos-autonomy-supervisor",
        )
        self.thread.start()
        self.record(
            "supervisor_started",
            detail="Supervision autonome démarrée.",
        )

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        self.record(
            "supervisor_stopped",
            detail="Supervision autonome arrêtée.",
        )

    # =========================================================
    # STATUS / COMMANDS
    # =========================================================

    def _recent_terminal_missions(
        self,
        *,
        minutes: int = 10,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        cutoff = self._now() - timedelta(minutes=max(1, int(minutes)))
        rows = []

        for mission in self.manager.missions.list():
            self.manager.missions.refresh(
                mission,
                self.manager.tasks,
            )
            if mission.status not in {
                "completed",
                "failed",
                "cancelled",
                "rejected",
            }:
                continue
            updated = self._parse_dt(mission.updated_at)
            if updated is None:
                continue
            if updated.astimezone(timezone.utc) < cutoff:
                continue
            policy = self.policy_for(mission)
            rows.append({
                "mission": mission.human_id,
                "status": mission.status,
                "priority": policy["priority"],
                "deadline": policy["deadline"],
                "updated_at": mission.updated_at,
            })

        rows.sort(
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )
        return rows[:max(1, int(limit))]

    def snapshot(self) -> dict[str, Any]:
        # Calculé à la demande : le statut ne dépend pas du dernier passage de
        # la boucle de supervision. Une mission qui vient de se terminer est
        # affichée séparément dans ``recent_missions`` au lieu de donner un 0
        # ambigu juste avant la notification de fin.
        active = self.manager.missions.active(
            self.manager.tasks
        )
        rows = []

        for mission in sorted(active, key=self._sort_key):
            policy = self.policy_for(mission)
            rows.append(
                {
                    "mission": mission.human_id,
                    "status": mission.status,
                    "priority": policy["priority"],
                    "deadline": policy["deadline"],
                    "autonomy_enabled": policy["enabled"],
                }
            )

        recoveries = sum(
            1
            for item in self.decisions
            if item.get("action") in {
                "automatic_retry",
                "strategy_changed",
                "orphan_task_recovered",
            }
        )
        escalations = sum(
            1
            for item in self.decisions
            if item.get("action") in {
                "escalation_required",
                "diagnostic_escalation",
            }
        )

        return {
            "enabled": bool(self.state.get("enabled", True)),
            "running": bool(
                self.thread is not None
                and self.thread.is_alive()
            ),
            "last_check_at": self.last_check_at,
            "active_missions": rows,
            "recent_missions": self._recent_terminal_missions(),
            "recoveries": recoveries,
            "escalations": escalations,
            "decisions": len(self.decisions),
        }

    def status_summary(self) -> str:
        snapshot = self.snapshot()
        lines = [
            "MANAGER AUTONOME",
            (
                "Supervision : "
                + ("active" if snapshot["enabled"] else "désactivée")
            ),
            (
                "Boucle : "
                + ("en cours" if snapshot["running"] else "arrêtée")
            ),
            (
                "Missions actives supervisées : "
                + str(len(snapshot["active_missions"]))
            ),
        ]

        for item in snapshot["active_missions"]:
            priority = self.PRIORITY_LABELS.get(
                str(item["priority"]),
                str(item["priority"]),
            )
            deadline = self._deadline_human(item.get("deadline"))
            enabled = (
                "auto"
                if item.get("autonomy_enabled")
                else "manuel"
            )
            lines.append(
                f"- {item['mission']} | {item['status']} | "
                f"priorité {priority} | échéance {deadline} | {enabled}"
            )

        if snapshot["recent_missions"]:
            latest = snapshot["recent_missions"][0]
            priority = self.PRIORITY_LABELS.get(
                str(latest.get("priority")),
                str(latest.get("priority") or "normale"),
            )
            lines.extend([
                "",
                (
                    "Dernière mission récente : "
                    f"{latest['mission']} | {latest['status']} | "
                    f"priorité {priority} | "
                    f"mise à jour {self._display_time(latest.get('updated_at'))}"
                ),
            ])

        lines.extend([
            "",
            f"Récupérations automatiques : {snapshot['recoveries']}",
            f"Escalades : {snapshot['escalations']}",
            f"Décisions enregistrées : {snapshot['decisions']}",
        ])

        return "\n".join(lines)

    def _resolve_mission_for_command(
        self,
        message: str,
    ):
        reference = self._mission_ref(message)
        if reference:
            return self.manager.missions.resolve(reference)

        active = self.manager.missions.active(
            self.manager.tasks
        )
        if len(active) == 1:
            return active[0]
        return None

    def command_response(
        self,
        message: str,
    ) -> str | None:
        raw = str(message or "").strip()
        value = self._ascii(raw)

        if value in {
            "manager status",
            "autonomy status",
            "autonomie status",
            "statut manager",
            "etat du manager",
            "etat manager",
        }:
            return self.status_summary()

        if value in {
            "manager decisions",
            "decisions manager",
            "decisions du manager",
            "journal manager",
            "manager journal",
        }:
            return self.decisions_summary()

        if value in {
            "manager check",
            "autonomy check",
            "autonomie check",
            "verifie les missions",
            "verifie toutes les missions",
        }:
            result = self.check_once()
            return (
                "Contrôle terminé : "
                f"{result['checked']} mission(s) vérifiée(s), "
                f"{result['submitted']} tâche(s) relancée(s), "
                f"{result['orphan_recovered']} tâche(s) orpheline(s) récupérée(s), "
                f"{result['deadline_events']} événement(s) d'échéance."
            )

        if value in {
            "autonomie on",
            "autonomy on",
            "manager on",
        }:
            self.state["enabled"] = True
            self._save_state()
            self.record(
                "global_autonomy_enabled",
                detail="Autonomie globale activée.",
            )
            return "Autonomie globale activée."

        if value in {
            "autonomie off",
            "autonomy off",
            "manager off",
        }:
            self.state["enabled"] = False
            self._save_state()
            self.record(
                "global_autonomy_disabled",
                detail="Autonomie globale désactivée.",
            )
            return "Autonomie globale désactivée."

        reference = self._mission_ref(raw)

        if "priorit" in value and reference:
            mission = self.manager.missions.resolve(reference)
            if mission is None:
                return f"Mission {reference} introuvable."
            priority = self._priority_from_text(raw)
            if priority is None:
                return "Précise : priorité basse, normale, haute ou critique."
            self.set_priority(mission, priority)
            return (
                f"{mission.human_id} — priorité "
                f"{self.PRIORITY_LABELS[priority]}."
            )

        if (
            ("deadline" in value or "echeance" in value)
            and reference
        ):
            mission = self.manager.missions.resolve(reference)
            if mission is None:
                return f"Mission {reference} introuvable."

            if any(
                marker in value
                for marker in (
                    "supprime deadline",
                    "retire deadline",
                    "sans deadline",
                    "supprime echeance",
                    "retire echeance",
                )
            ):
                self.set_deadline(mission, None)
                return f"{mission.human_id} — échéance supprimée."

            deadline = self.parse_deadline(raw)
            if deadline is None:
                return (
                    "Je n'ai pas compris l'échéance. Exemples : "
                    f"deadline {reference} dans 2h ; "
                    f"deadline {reference} demain 18h ; "
                    f"deadline {reference} 2026-09-09 18:30."
                )
            self.set_deadline(mission, deadline)
            return (
                f"{mission.human_id} — échéance "
                f"{deadline.isoformat(timespec='minutes')}."
            )

        if reference and "autonomie" in value:
            mission = self.manager.missions.resolve(reference)
            if mission is None:
                return f"Mission {reference} introuvable."
            if re.search(r"\b(off|desactive|désactive|manuel)\b", value):
                self.set_mission_enabled(mission, False)
                return f"{mission.human_id} — autonomie désactivée."
            if re.search(r"\b(on|active|activee|activée|auto)\b", value):
                self.set_mission_enabled(mission, True)
                return f"{mission.human_id} — autonomie activée."

        return None
