from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore


class SpecialistLLMProxy:
    """Ajoute un contexte spécialiste au system prompt sans toucher à la demande."""

    def __init__(self, base_llm, specialist_system: str) -> None:
        self.base_llm = base_llm
        self.specialist_system = str(specialist_system or "").strip()

    def chat(self, user: str, system: str = "") -> str:
        parts = []
        if self.specialist_system:
            parts.append(self.specialist_system)
        if str(system or "").strip():
            parts.append(str(system).strip())
        return self.base_llm.chat(
            user,
            system="\n\n".join(parts),
        )

    def __getattr__(self, name: str):
        return getattr(self.base_llm, name)


class SpecialistManager:
    """Construit des spécialistes temporaires à partir du Skill Registry V5.3.

    Aucun nouvel agent permanent n'est créé. Le worker de base conserve ses
    outils et son code, mais son LLM reçoit temporairement un rôle spécialisé
    construit avec les skills requis par la mission.
    """

    WORKER_LABELS = {
        "developer": "Developer",
        "tester": "Tester",
        "researcher": "Researcher",
        "ai_worker": "AI Worker",
    }

    ACRONYMS = {
        "api": "API",
        "css": "CSS",
        "html": "HTML",
        "http": "HTTP",
        "https": "HTTPS",
        "json": "JSON",
        "js": "JS",
        "mqtt": "MQTT",
        "sql": "SQL",
        "ui": "UI",
        "ux": "UX",
        "yaml": "YAML",
        "zha": "ZHA",
    }

    def __init__(self, skills, manager=None) -> None:
        self.skills = skills
        self.manager = manager
        self.store = JsonStore(
            DATA_DIR / "specialists.json",
            {
                "version": 1,
                "history": [],
            },
        )
        self.lock = threading.RLock()
        raw = self.store.load()
        if not isinstance(raw, dict):
            raw = {}
        history = raw.get("history", [])
        if not isinstance(history, list):
            history = []
        self.data = {
            "version": 1,
            "history": [
                item for item in history[-500:]
                if isinstance(item, dict)
            ],
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _task_value(task, key: str, default=None):
        if isinstance(task, dict):
            return task.get(key, default)
        return getattr(task, key, default)

    @classmethod
    def _pretty_skill(cls, value: str) -> str:
        parts = str(value or "").replace("-", "_").split("_")
        rendered = []
        for part in parts:
            clean = part.strip()
            if not clean:
                continue
            lower = clean.lower()
            rendered.append(
                cls.ACRONYMS.get(
                    lower,
                    clean[:1].upper() + clean[1:],
                )
            )
        return " ".join(rendered) or str(value or "skill")

    def _mission_for_task(self, task):
        if self.manager is None:
            return None
        metadata = self._task_value(task, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            return None
        mission_id = metadata.get("mission_id")
        if not mission_id:
            return None
        return self.manager.missions.get(mission_id)

    def _skill_context(self, task) -> dict[str, Any]:
        if isinstance(task, dict):
            existing = task.get("skill_context")
            if isinstance(existing, dict):
                return dict(existing)
        try:
            return self.skills.context_for_task(
                task,
                record_usage=False,
            )
        except Exception:
            return {
                "required": [],
                "available": [],
                "missing": [],
                "text": "",
            }

    def build_profile(
        self,
        worker_name: str,
        task,
    ) -> dict[str, Any]:
        worker_name = str(worker_name or "").strip()
        worker_label = self.WORKER_LABELS.get(
            worker_name,
            self._pretty_skill(worker_name),
        )
        context = self._skill_context(task)
        required = list(context.get("required", []) or [])
        missing = list(context.get("missing", []) or [])
        available = [
            dict(item)
            for item in (context.get("available", []) or [])
            if isinstance(item, dict)
        ]

        compatible = []
        unassigned = []
        weak = []

        for item in available:
            key = str(item.get("key") or "").strip()
            workers = [
                str(value).strip()
                for value in (item.get("workers", []) or [])
                if str(value).strip()
            ]
            fit = (
                not workers
                or worker_name in workers
            )
            enriched = dict(item)
            enriched["worker_fit"] = fit

            if fit:
                compatible.append(enriched)
            else:
                unassigned.append(key)

            confidence = float(
                item.get("effective_confidence", 0.0)
                or 0.0
            )
            freshness = item.get("freshness", {}) or {}
            if (
                confidence < 0.50
                or str(freshness.get("status", "")) == "stale"
            ):
                weak.append(key)

        names = [
            self._pretty_skill(
                str(item.get("key") or item.get("name") or "")
            )
            for item in compatible
        ]
        names = [name for name in names if name]

        if names:
            if len(names) <= 3:
                prefix = " / ".join(names)
            else:
                prefix = " / ".join(names[:3]) + f" +{len(names) - 3}"
            label = f"{prefix} {worker_label}"
        elif required:
            label = f"{worker_label} — spécialisation à compléter"
        else:
            label = worker_label

        mission = self._mission_for_task(task)
        task_id = str(self._task_value(task, "id", "") or "")

        profile = {
            "id": "specialist_" + uuid.uuid4().hex[:10],
            "name": label,
            "worker": worker_name,
            "worker_label": worker_label,
            "mission": (
                mission.human_id
                if mission is not None
                else None
            ),
            "task_id": task_id or None,
            "activated": bool(required),
            "required": required,
            "skills": compatible,
            "missing": missing,
            "unassigned": unassigned,
            "weak": weak,
            "created_at": self._now(),
        }
        profile["system_prompt"] = self.system_prompt(
            profile,
            context,
        )
        return profile

    def system_prompt(
        self,
        profile: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        if not profile.get("activated"):
            return ""

        lines = [
            "PROFIL SPÉCIALISTE TEMPORAIRE AGENT-OS V5.3",
            f"Tu agis pour cette tâche comme : {profile['name']}.",
            f"Worker de base : {profile['worker']}.",
            "Ce rôle est temporaire et ne change pas tes outils ni tes permissions.",
            "Utilise les connaissances du Skill Registry comme contexte technique, pas comme vérité absolue.",
            "Priorise les sources de niveau A puis B. Les sources C/D servent surtout de pistes.",
            "Si une connaissance est ancienne, peu fiable, manquante ou non attribuée à ton worker, ne prétends pas la maîtriser.",
        ]

        skills = profile.get("skills", []) or []
        if skills:
            lines.append("COMPÉTENCES ACTIVES POUR CE WORKER:")
            for item in skills:
                freshness = item.get("freshness", {}) or {}
                lines.append(
                    "- "
                    + self._pretty_skill(str(item.get("key") or ""))
                    + " | niveau="
                    + str(item.get("level", "unknown"))
                    + " | confiance="
                    + f"{float(item.get('effective_confidence', 0.0) or 0.0):.2f}"
                    + " | fraîcheur="
                    + str(freshness.get("status", "unknown"))
                )

        missing = profile.get("missing", []) or []
        if missing:
            lines.append(
                "COMPÉTENCES ABSENTES DU REGISTRE : "
                + ", ".join(str(item) for item in missing)
                + ". Ne les invente pas."
            )

        unassigned = profile.get("unassigned", []) or []
        if unassigned:
            lines.append(
                "COMPÉTENCES CONNUES MAIS NON ATTRIBUÉES À CE WORKER : "
                + ", ".join(str(item) for item in unassigned)
                + ". Tu peux les signaler comme besoin de renfort, mais pas te déclarer spécialiste de ces domaines."
            )

        weak = profile.get("weak", []) or []
        if weak:
            lines.append(
                "COMPÉTENCES À CONFIANCE FAIBLE OU PÉRIMÉES : "
                + ", ".join(str(item) for item in weak)
                + ". Vérifie avant toute affirmation importante."
            )

        technical = str(context.get("text", "") or "").strip()
        if technical:
            lines.extend([
                "",
                "CONTEXTE TECHNIQUE DU SKILL REGISTRY:",
                technical,
            ])

        return "\n".join(lines).strip()

    def record_execution(
        self,
        profile: dict[str, Any],
        *,
        success: bool,
    ) -> None:
        if not profile.get("activated"):
            return
        item = {
            key: value
            for key, value in profile.items()
            if key != "system_prompt"
        }
        item["finished_at"] = self._now()
        item["success"] = bool(success)
        with self.lock:
            self.data["history"].append(item)
            self.data["history"] = self.data["history"][-500:]
            self.store.save(self.data)

    def profile_for_mission(
        self,
        reference: str,
    ) -> list[dict[str, Any]]:
        if self.manager is None:
            return []
        mission = self.manager.missions.resolve(
            str(reference or "").strip()
        )
        if mission is None:
            raise KeyError(
                f"Mission {reference} introuvable."
            )

        result = []
        seen = set()
        for task_id in list(mission.task_ids):
            task = self.manager.tasks.get(task_id)
            if task is None:
                continue
            profile = self.build_profile(
                task.worker,
                task,
            )
            signature = (
                profile.get("worker"),
                tuple(profile.get("required", []) or []),
            )
            if signature in seen:
                continue
            seen.add(signature)
            result.append(profile)
        return result

    def _active_profiles(self) -> list[dict[str, Any]]:
        if self.manager is None:
            return []
        engine = getattr(self.manager, "engine", None)
        if engine is None:
            return []
        with engine.lock:
            task_ids = list(engine.running)
        rows = []
        for task_id in task_ids:
            task = self.manager.tasks.get(task_id)
            if task is None:
                continue
            profile = self.build_profile(
                task.worker,
                task,
            )
            if profile.get("activated"):
                rows.append(profile)
        return rows

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            recent = list(self.data["history"][-20:])
        return {
            "version": 1,
            "active": self._active_profiles(),
            "recent": recent,
            "executions": len(self.data.get("history", [])),
        }

    def summary(self) -> str:
        snap = self.snapshot()
        lines = [
            "SPÉCIALISTES DYNAMIQUES V5.3",
            f"Actifs : {len(snap['active'])}",
            f"Exécutions spécialisées enregistrées : {snap['executions']}",
        ]
        for profile in snap["active"]:
            lines.append(
                f"- {profile.get('mission') or '-'} | {profile['name']} | {profile.get('task_id') or '-'}"
            )
        if not snap["active"] and snap["recent"]:
            last = snap["recent"][-1]
            lines.extend([
                "",
                "Dernier spécialiste :",
                f"- {last.get('mission') or '-'} | {last.get('name') or last.get('worker')} | "
                + ("succès" if last.get("success") else "échec"),
            ])
        return "\n".join(lines)

    def mission_summary(self, reference: str) -> str:
        profiles = self.profile_for_mission(reference)
        if not profiles:
            return f"{reference} — aucun profil spécialiste calculable."
        lines = [
            f"SPÉCIALISTES — {str(reference).upper()}",
        ]
        for profile in profiles:
            lines.append(
                f"- {profile['worker']} → {profile['name']}"
            )
            if profile.get("required"):
                lines.append(
                    "  requis : " + ", ".join(profile["required"])
                )
            active = [
                str(item.get("key"))
                for item in profile.get("skills", [])
                if item.get("key")
            ]
            if active:
                lines.append(
                    "  actifs : " + ", ".join(active)
                )
            if profile.get("unassigned"):
                lines.append(
                    "  non attribués : " + ", ".join(profile["unassigned"])
                )
            if profile.get("missing"):
                lines.append(
                    "  manquants : " + ", ".join(profile["missing"])
                )
        return "\n".join(lines)

    def command_response(self, message: str) -> str | None:
        raw = " ".join(str(message or "").strip().split())
        lower = raw.lower()
        if lower in {
            "specialists",
            "specialist status",
            "specialists status",
            "spécialistes",
            "specialistes",
        }:
            return self.summary()

        if lower in {
            "specialist",
            "spécialiste",
            "specialiste",
        }:
            return "Usage : specialist M-043"

        prefixes = (
            "specialist ",
            "spécialiste ",
            "specialiste ",
        )
        for prefix in prefixes:
            if lower.startswith(prefix):
                reference = raw[len(prefix):].strip()
                if not reference:
                    return "Usage : specialist M-043"
                try:
                    return self.mission_summary(reference)
                except KeyError as exc:
                    return str(exc)

        return None


class SpecializedWorkerAdapter:
    """Applique un profil spécialiste temporaire à un worker existant."""

    def __init__(self, worker, specialists: SpecialistManager) -> None:
        self.worker = worker
        self.specialists = specialists
        self.name = worker.name
        self.lock = threading.RLock()

    def __getattr__(self, name: str):
        return getattr(self.worker, name)

    def execute(self, task):
        profile = self.specialists.build_profile(
            self.name,
            task,
        )
        if not profile.get("activated"):
            return self.worker.execute(task)

        llm = getattr(self.worker, "llm", None)
        if llm is None:
            result = self.worker.execute(task)
            self.specialists.record_execution(
                profile,
                success=bool(getattr(result, "success", False)),
            )
            return result

        with self.lock:
            original_llm = self.worker.llm
            self.worker.llm = SpecialistLLMProxy(
                original_llm,
                str(profile.get("system_prompt", "") or ""),
            )
            try:
                result = self.worker.execute(task)
            finally:
                self.worker.llm = original_llm

        try:
            data = getattr(result, "data", None)
            if isinstance(data, dict):
                data["specialist_profile"] = {
                    key: value
                    for key, value in profile.items()
                    if key != "system_prompt"
                }
        except Exception:
            pass

        self.specialists.record_execution(
            profile,
            success=bool(getattr(result, "success", False)),
        )
        return result
