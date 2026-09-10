from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore
from agentos.tasks import TaskStatus


@dataclass
class CollaborationWorkerResult:
    success: bool
    message: str
    data: dict[str, Any]
    error: str | None = None


class CollaborationRequested(RuntimeError):
    def __init__(self, request: dict[str, Any]) -> None:
        super().__init__("Collaboration inter-agent demandée.")
        self.request = dict(request)


class CollaborationLLMProxy:
    """Ajoute le protocole de demande de renfort à un LLM existant.

    Le worker continue d'utiliser son LLM habituel. S'il estime qu'un collègue
    est réellement nécessaire, il peut retourner une enveloppe JSON stricte.
    Le proxy l'intercepte et remonte la demande au moteur sans consommer un
    second appel LLM de préflight.
    """

    REQUEST_KEY = "__agentos_collaboration_request__"

    def __init__(
        self,
        base_llm,
        *,
        worker_name: str,
        assistance_context: str = "",
        allow_requests: bool = True,
    ) -> None:
        self.base_llm = base_llm
        self.worker_name = str(worker_name or "worker")
        self.assistance_context = str(assistance_context or "").strip()
        self.allow_requests = bool(allow_requests)

    @staticmethod
    def _clean_json(raw: str) -> str:
        text = str(raw or "").strip()
        if text.startswith("```"):
            first = text.find("\n")
            if first != -1:
                text = text[first + 1:]
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
        return text.strip()

    @classmethod
    def parse_request(cls, raw: str) -> dict[str, Any] | None:
        text = cls._clean_json(raw)
        if not text.startswith("{") or not text.endswith("}"):
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        request = parsed.get(cls.REQUEST_KEY)
        if not isinstance(request, dict):
            return None
        worker = str(request.get("worker", "") or "").strip().lower()
        question = " ".join(str(request.get("question", "") or "").split())
        reason = " ".join(str(request.get("reason", "") or "").split())
        if not worker or not question:
            return None
        return {
            "worker": worker,
            "question": question[:1200],
            "reason": reason[:500],
        }

    def _protocol(self) -> str:
        peers = [
            name
            for name in ("researcher", "developer", "tester", "ai_worker")
            if name != self.worker_name
        ]
        lines = [
            "COLLABORATION INTER-AGENTS AGENT-OS V5.5",
            "Tu peux demander UN renfort uniquement si cela améliore matériellement la fiabilité de la tâche.",
            "Ne demande pas de renfort pour une tâche simple que tu peux accomplir correctement seul.",
            "Ne demande jamais ton propre worker.",
            "Choisis researcher pour documentation/faits/API actuels, developer pour avis d'implémentation, tester pour stratégie de vérification, ai_worker pour analyse/synthèse.",
            "La question doit être autonome, précise et contenir le contexte indispensable.",
            "Si aucun renfort n'est nécessaire, réponds normalement au prompt courant.",
        ]
        if self.allow_requests:
            lines.extend([
                "Si un renfort est réellement nécessaire, réponds UNIQUEMENT avec ce JSON et rien d'autre :",
                '{"__agentos_collaboration_request__":{"worker":"researcher","question":"question précise","reason":"raison courte"}}',
                "Collaborateurs disponibles : " + ", ".join(peers) + ".",
            ])
        else:
            lines.append(
                "La limite de renfort est atteinte ou un renfort équivalent a déjà été fourni : tu dois maintenant poursuivre avec les éléments disponibles et signaler explicitement toute limite restante."
            )
        if self.assistance_context:
            lines.extend([
                "",
                "RENFORTS DÉJÀ REÇUS :",
                self.assistance_context,
                "Utilise ces réponses. Ne redemande pas la même information.",
            ])
        return "\n".join(lines).strip()

    def chat(self, user: str, system: str = "") -> str:
        parts = [self._protocol()]
        if str(system or "").strip():
            parts.append(str(system).strip())
        raw = self.base_llm.chat(
            user,
            system="\n\n".join(parts),
        )
        if self.allow_requests:
            request = self.parse_request(raw)
            if request is not None:
                raise CollaborationRequested(request)
        return raw

    def __getattr__(self, name: str):
        return getattr(self.base_llm, name)


class CollaborationManager:
    """Coordonne les demandes de renfort entre workers Agent-OS V5.5."""

    ALLOWED_WORKERS = {
        "researcher",
        "developer",
        "tester",
        "ai_worker",
    }

    TERMINAL = {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }

    def __init__(
        self,
        manager,
        *,
        max_requests_per_task: int = 2,
    ) -> None:
        self.manager = manager
        self.engine = manager.engine
        self.max_requests_per_task = max(1, int(max_requests_per_task))
        self.state_store = JsonStore(
            DATA_DIR / "collaboration_state.json",
            {"enabled": True},
        )
        self.history_store = JsonStore(
            DATA_DIR / "collaboration.json",
            {"version": 1, "history": []},
        )
        self.lock = threading.RLock()

        raw_state = self.state_store.load()
        self.state = raw_state if isinstance(raw_state, dict) else {}
        self.state.setdefault("enabled", True)

        raw = self.history_store.load()
        if not isinstance(raw, dict):
            raw = {}
        history = raw.get("history", [])
        if not isinstance(history, list):
            history = []
        self.data = {
            "version": 1,
            "history": [
                dict(item)
                for item in history[-1000:]
                if isinstance(item, dict)
            ],
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _ascii(text: str) -> str:
        value = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(
            char for char in value
            if not unicodedata.combining(char)
        ).lower()

    @staticmethod
    def _task_value(task, key: str, default=None):
        if isinstance(task, dict):
            return task.get(key, default)
        return getattr(task, key, default)

    @classmethod
    def _task_metadata(cls, task) -> dict[str, Any]:
        value = cls._task_value(task, "metadata", {}) or {}
        return dict(value) if isinstance(value, dict) else {}

    def _mission_for_task(self, task):
        metadata = self._task_metadata(task)
        mission_id = metadata.get("mission_id")
        if not mission_id:
            return None
        return self.manager.missions.get(mission_id)

    def _record(
        self,
        action: str,
        *,
        mission: str | None = None,
        task_id: str | None = None,
        from_worker: str | None = None,
        to_worker: str | None = None,
        detail: str = "",
        success: bool | None = None,
    ) -> None:
        item = {
            "at": self._now(),
            "action": str(action),
            "mission": mission,
            "task_id": task_id,
            "from_worker": from_worker,
            "to_worker": to_worker,
            "detail": str(detail or "")[:1600],
        }
        if success is not None:
            item["success"] = bool(success)
        with self.lock:
            self.data["history"].append(item)
            self.data["history"] = self.data["history"][-1000:]
            self.history_store.save(self.data)

    def _requests(self, task) -> list[dict[str, Any]]:
        metadata = self._task_metadata(task)
        raw = metadata.get("collaboration_requests", [])
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def can_request(
        self,
        task,
        request: dict[str, Any],
    ) -> tuple[bool, str]:
        if not bool(self.state.get("enabled", True)):
            return False, "collaboration_disabled"

        metadata = self._task_metadata(task)
        if metadata.get("collaboration_help"):
            return False, "helper_cannot_delegate"
        if metadata.get("skill_learning"):
            return False, "learning_task_cannot_delegate"

        from_worker = str(self._task_value(task, "worker", "") or "").strip()
        to_worker = str(request.get("worker", "") or "").strip().lower()
        question = " ".join(str(request.get("question", "") or "").split())

        if to_worker not in self.ALLOWED_WORKERS:
            return False, "unknown_helper"
        if to_worker == from_worker:
            return False, "self_delegation"
        if not question:
            return False, "empty_question"

        requests = self._requests(task)
        if len(requests) >= self.max_requests_per_task:
            return False, "request_limit"

        signature = (
            to_worker,
            self._ascii(question)[:500],
        )
        for item in requests:
            previous = (
                str(item.get("to_worker", "") or "").lower(),
                self._ascii(str(item.get("question", "") or ""))[:500],
            )
            if previous == signature:
                return False, "duplicate_request"

        return True, "ok"

    def assistance_context(self, task) -> str:
        rows = []
        changed = False
        metadata = self._task_metadata(task)
        requests = self._requests(task)

        for item in requests:
            helper_id = str(item.get("help_task_id", "") or "")
            if not helper_id:
                continue
            helper = self.manager.tasks.get(helper_id)
            if helper is None or helper.status != TaskStatus.COMPLETED.value:
                continue
            result = str(helper.result or "").strip()
            if not result:
                continue
            rows.append(
                "- "
                + str(item.get("to_worker") or helper.worker)
                + " | question: "
                + str(item.get("question") or "")
                + "\n  réponse: "
                + result[:5000]
            )
            if item.get("status") != "received":
                item["status"] = "received"
                item["received_at"] = self._now()
                changed = True

        if changed:
            metadata["collaboration_requests"] = requests
            metadata["collaboration_pending"] = False
            try:
                self.manager.tasks.update(
                    str(self._task_value(task, "id")),
                    metadata=metadata,
                )
            except Exception:
                pass

        return "\n".join(rows).strip()

    def _add_auxiliary_task_to_mission(self, mission, task_id: str) -> None:
        missions = self.manager.missions
        with missions.lock:
            current = missions.get(mission.id)
            if current is None:
                return
            if task_id not in current.task_ids:
                current.task_ids.append(task_id)
                current.updated_at = missions._now()
                missions._save()

    @staticmethod
    def _helper_title(from_worker: str, to_worker: str) -> str:
        return f"Renfort {to_worker} pour {from_worker}"

    def handle_request(self, task, result) -> dict[str, Any]:
        data = getattr(result, "data", {})
        if not isinstance(data, dict):
            return {"scheduled": False, "reason": "missing_request_data"}
        request = data.get("collaboration_request")
        if not isinstance(request, dict):
            return {"scheduled": False, "reason": "missing_request"}

        allowed, reason = self.can_request(task, request)
        if not allowed:
            return {"scheduled": False, "reason": reason}

        mission = self._mission_for_task(task)
        if mission is None:
            return {"scheduled": False, "reason": "mission_missing"}

        task_id = str(self._task_value(task, "id", "") or "")
        from_worker = str(self._task_value(task, "worker", "") or "")
        to_worker = str(request.get("worker", "") or "").strip().lower()
        question = " ".join(str(request.get("question", "") or "").split())[:1200]
        why = " ".join(str(request.get("reason", "") or "").split())[:500]

        old_dependencies = list(self._task_value(task, "depends_on", []) or [])
        metadata = self._task_metadata(task)

        helper = self.manager.tasks.create(
            title=self._helper_title(from_worker, to_worker),
            description=question,
            worker=to_worker,
            depends_on=old_dependencies,
            metadata={
                "mission_id": mission.id,
                "collaboration_help": True,
                "collaboration_for_task": task_id,
                "collaboration_from_worker": from_worker,
                "collaboration_to_worker": to_worker,
                "collaboration_question": question,
                "collaboration_reason": why,
                "original_message": question,
                "user_original_message": str(
                    metadata.get("user_original_message")
                    or metadata.get("original_message")
                    or mission.description
                ),
                "router_reason": "inter_agent_collaboration",
                "auto_repair_enabled": False,
            },
        )
        self._add_auxiliary_task_to_mission(mission, helper.id)

        requests = self._requests(task)
        requests.append({
            "help_task_id": helper.id,
            "from_worker": from_worker,
            "to_worker": to_worker,
            "question": question,
            "reason": why,
            "status": "scheduled",
            "requested_at": self._now(),
        })

        metadata["collaboration_requests"] = requests
        metadata["collaboration_rounds"] = len(requests)
        metadata["collaboration_pending"] = True

        dependencies = list(dict.fromkeys(old_dependencies + [helper.id]))
        self.manager.tasks.update(
            task_id,
            metadata=metadata,
            depends_on=dependencies,
            status=TaskStatus.WAITING_DEPENDENCY.value,
            error=None,
        )

        self._record(
            "help_requested",
            mission=mission.human_id,
            task_id=task_id,
            from_worker=from_worker,
            to_worker=to_worker,
            detail=(question + (" | " + why if why else "")),
        )
        self.engine.submit(helper.id)
        return {
            "scheduled": True,
            "helper_task": helper.id,
            "worker": to_worker,
            "question": question,
        }

    def record_helper_result(self, task, result) -> None:
        metadata = self._task_metadata(task)
        if not metadata.get("collaboration_help"):
            return
        mission = self._mission_for_task(task)
        self._record(
            "help_completed" if bool(getattr(result, "success", False)) else "help_failed",
            mission=mission.human_id if mission is not None else None,
            task_id=str(self._task_value(task, "id", "") or ""),
            from_worker=str(metadata.get("collaboration_from_worker") or ""),
            to_worker=str(metadata.get("collaboration_to_worker") or self._task_value(task, "worker", "")),
            detail=str(getattr(result, "message", "") or getattr(result, "error", ""))[:1200],
            success=bool(getattr(result, "success", False)),
        )

    def record_assistance_used(self, task, result, context: str) -> None:
        if not context:
            return
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            data["collaboration_used"] = True
            data["collaboration_context"] = context[:8000]
        mission = self._mission_for_task(task)
        self._record(
            "help_used",
            mission=mission.human_id if mission is not None else None,
            task_id=str(self._task_value(task, "id", "") or ""),
            from_worker=str(self._task_value(task, "worker", "") or ""),
            detail="Le worker a repris sa tâche avec le renfort reçu.",
            success=bool(getattr(result, "success", False)),
        )

    def _active_helpers(self) -> list[dict[str, Any]]:
        rows = []
        for task in self.manager.tasks.list():
            metadata = self._task_metadata(task)
            if not metadata.get("collaboration_help"):
                continue
            if task.status in self.TERMINAL:
                continue
            mission = self._mission_for_task(task)
            rows.append({
                "task": task.id,
                "mission": mission.human_id if mission is not None else None,
                "from_worker": metadata.get("collaboration_from_worker"),
                "to_worker": metadata.get("collaboration_to_worker") or task.worker,
                "question": metadata.get("collaboration_question"),
                "status": task.status,
            })
        return rows

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            history = list(self.data.get("history", []))
        return {
            "version": 1,
            "enabled": bool(self.state.get("enabled", True)),
            "max_requests_per_task": self.max_requests_per_task,
            "active": self._active_helpers(),
            "requests": sum(1 for item in history if item.get("action") == "help_requested"),
            "completed": sum(1 for item in history if item.get("action") == "help_completed"),
            "failed": sum(1 for item in history if item.get("action") == "help_failed"),
            "history": len(history),
            "recent": history[-20:],
        }

    def summary(self) -> str:
        snap = self.snapshot()
        lines = [
            "COLLABORATION INTER-AGENTS V5.5",
            "Mode : " + ("actif" if snap["enabled"] else "désactivé"),
            f"Renforts en cours : {len(snap['active'])}",
            f"Demandes enregistrées : {snap['requests']}",
            f"Renforts terminés : {snap['completed']}",
            f"Échecs : {snap['failed']}",
            f"Limite : {snap['max_requests_per_task']} renfort(s) par tâche",
        ]
        for item in snap["active"][:8]:
            lines.append(
                f"- {item.get('mission') or '-'} | {item.get('from_worker')} → "
                f"{item.get('to_worker')} | {item.get('status')}"
            )
        return "\n".join(lines)

    def history_summary(self, limit: int = 25) -> str:
        with self.lock:
            items = list(self.data.get("history", []))[-max(1, int(limit)):]
        if not items:
            return "Aucune collaboration inter-agent enregistrée."
        lines = ["HISTORIQUE COLLABORATION V5.5"]
        for item in reversed(items):
            line = (
                f"- {item.get('mission') or '-'} | "
                f"{item.get('from_worker') or '-'} → {item.get('to_worker') or '-'} | "
                f"{item.get('action') or 'action'}"
            )
            if item.get("detail"):
                line += " — " + str(item.get("detail"))[:350]
            lines.append(line)
        return "\n".join(lines)

    def mission_summary(self, reference: str) -> str:
        mission = self.manager.missions.resolve(str(reference or "").strip())
        if mission is None:
            raise KeyError(f"Mission {reference} introuvable.")
        rows = []
        for task_id in mission.task_ids:
            task = self.manager.tasks.get(task_id)
            if task is None:
                continue
            metadata = self._task_metadata(task)
            if metadata.get("collaboration_help"):
                rows.append(
                    f"- {metadata.get('collaboration_from_worker')} → "
                    f"{metadata.get('collaboration_to_worker') or task.worker} | "
                    f"{task.status} | {metadata.get('collaboration_question') or task.description}"
                )
        if not rows:
            return f"{mission.human_id} — aucune collaboration inter-agent."
        return "\n".join([
            f"COLLABORATION — {mission.human_id}",
            *rows,
        ])

    def command_response(self, message: str) -> str | None:
        raw = " ".join(str(message or "").strip().split())
        value = self._ascii(raw)
        if value in {
            "collaboration", "collaboration status", "teamwork", "entraide",
        }:
            return self.summary()
        if value in {
            "collaboration history", "historique collaboration", "historique entraide",
        }:
            return self.history_summary()
        if value in {"collaboration on", "entraide on"}:
            self.state["enabled"] = True
            self.state_store.save(self.state)
            self._record("collaboration_enabled", detail="Collaboration activée.")
            return "Collaboration inter-agents activée."
        if value in {"collaboration off", "entraide off"}:
            self.state["enabled"] = False
            self.state_store.save(self.state)
            self._record("collaboration_disabled", detail="Collaboration désactivée.")
            return "Collaboration inter-agents désactivée."
        match = re.match(r"^(?:collaboration|entraide)\s+(M-\d{1,6})$", raw, flags=re.IGNORECASE)
        if match:
            try:
                return self.mission_summary(match.group(1))
            except KeyError as exc:
                return str(exc)
        return None


class CollaborativeWorkerAdapter:
    """Ajoute le protocole V5.5 à un worker existant sans changer ses outils."""

    ROLE_LABELS = {
        "researcher": "Researcher",
        "developer": "Developer",
        "tester": "Tester",
        "ai_worker": "AI Worker",
    }

    def __init__(self, worker, collaboration: CollaborationManager) -> None:
        self.worker = worker
        self.collaboration = collaboration
        self.name = worker.name
        self.lock = threading.RLock()

    def __getattr__(self, name: str):
        return getattr(self.worker, name)

    @staticmethod
    def _find_llm_owner(worker):
        current = worker
        seen = set()
        for _ in range(12):
            if id(current) in seen:
                break
            seen.add(id(current))
            if "llm" in getattr(current, "__dict__", {}):
                return current
            nested = getattr(current, "worker", None)
            if nested is None:
                break
            current = nested
        return None

    def _helper_execute(self, task):
        metadata = self.collaboration._task_metadata(task)
        # Le Researcher conserve son vrai moteur Web : un renfort Researcher
        # doit fournir des sources réelles, pas une réponse de mémoire du LLM.
        if self.name == "researcher":
            result = self.worker.execute(task)
            self.collaboration.record_helper_result(task, result)
            return result

        owner = self._find_llm_owner(self.worker)
        if owner is None:
            result = self.worker.execute(task)
            self.collaboration.record_helper_result(task, result)
            return result

        question = str(
            metadata.get("collaboration_question")
            or CollaborationManager._task_value(task, "description", "")
            or ""
        ).strip()
        dependency_context = CollaborationManager._task_value(
            task, "dependency_context", []
        ) or []
        skill_context = CollaborationManager._task_value(
            task, "skill_context", {}
        ) or {}
        role = self.ROLE_LABELS.get(self.name, self.name)
        prompt = (
            "QUESTION DU COLLÈGUE :\n"
            + question
            + "\n\nCONTEXTE DE DÉPENDANCES :\n"
            + json.dumps(dependency_context, ensure_ascii=False, indent=2)[:12000]
            + "\n\nCONTEXTE TECHNIQUE :\n"
            + str(skill_context.get("text", "") or "")[:12000]
            + "\n\nRéponds uniquement comme conseiller. Donne les éléments précis utiles au collègue."
        )
        try:
            answer = owner.llm.chat(
                prompt,
                system=(
                    f"Tu es le {role} d'Agent-OS consulté comme renfort par un autre worker. "
                    "Tu ne prends pas le contrôle de la mission et tu ne modifies aucun fichier. "
                    "Signale clairement les incertitudes."
                ),
            )
            result = CollaborationWorkerResult(
                True,
                str(answer or "").strip(),
                {
                    "worker": self.name,
                    "collaboration_help": True,
                    "for_task": metadata.get("collaboration_for_task"),
                },
            )
        except Exception as exc:
            result = CollaborationWorkerResult(
                False,
                "Renfort inter-agent impossible.",
                {
                    "worker": self.name,
                    "collaboration_help": True,
                },
                str(exc),
            )
        self.collaboration.record_helper_result(task, result)
        return result

    def _execute_with_proxy(
        self,
        task,
        *,
        assistance: str,
        allow_requests: bool,
    ):
        owner = self._find_llm_owner(self.worker)
        if owner is None:
            return self.worker.execute(task)

        with self.lock:
            original_llm = owner.llm
            owner.llm = CollaborationLLMProxy(
                original_llm,
                worker_name=self.name,
                assistance_context=assistance,
                allow_requests=allow_requests,
            )
            try:
                return self.worker.execute(task)
            finally:
                owner.llm = original_llm

    def execute(self, task):
        metadata = self.collaboration._task_metadata(task)
        if metadata.get("collaboration_help"):
            return self._helper_execute(task)

        assistance = self.collaboration.assistance_context(task)
        enabled = bool(self.collaboration.state.get("enabled", True))
        allow = enabled and not metadata.get("skill_learning")

        try:
            result = self._execute_with_proxy(
                task,
                assistance=assistance,
                allow_requests=allow,
            )
        except CollaborationRequested as exc:
            allowed, _reason = self.collaboration.can_request(
                task,
                exc.request,
            )
            if allowed:
                return CollaborationWorkerResult(
                    True,
                    "Demande de renfort inter-agent.",
                    {
                        "worker": self.name,
                        "collaboration_request": dict(exc.request),
                    },
                )

            # Demande invalide, dupliquée ou limite atteinte : on relance une
            # seule fois le worker avec le protocole de demande désactivé.
            result = self._execute_with_proxy(
                task,
                assistance=assistance,
                allow_requests=False,
            )

        self.collaboration.record_assistance_used(
            task,
            result,
            assistance,
        )
        return result
