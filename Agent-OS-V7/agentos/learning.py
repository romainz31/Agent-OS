from __future__ import annotations

import re
import threading
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from agentos.config import DATA_DIR
from agentos.storage import JsonStore
from agentos.tasks import TaskStatus


class SkillLearningManager:
    """Apprentissage technique autonome Agent-OS V5.4.1.

    Le contrôleur intervient avant le lancement réel d'un worker :
    - il infère des skills techniques évidents depuis la demande ;
    - il vérifie si les skills requis sont présents, frais et assez fiables ;
    - il transfère un skill fiable à un nouveau worker sans refaire le Web ;
    - il crée une tâche Researcher si un skill manque ou doit être rafraîchi ;
    - la tâche métier attend alors cette recherche comme une dépendance réelle.
    """

    TERMINAL = {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }

    EXTENSION_SKILLS = {
        ".py": "python",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".js": "javascript",
        ".ts": "typescript",
        ".html": "html",
        ".css": "css",
        ".sql": "sql",
        ".ps1": "powershell",
        ".sh": "linux_shell",
        ".dockerfile": "docker",
    }

    # Détection volontairement conservatrice. Les technologies non reconnues
    # peuvent toujours être déclarées avec ``skill require`` ; les prochaines
    # versions pourront confier cette détection au Planner.
    TECH_ALIASES = {
        "home_assistant": (
            "home assistant",
            "home-assistant",
            "homeassistant",
        ),
        "yaml": (" yaml", "yaml ", ".yaml", ".yml"),
        "python": (" python", "python ", ".py"),
        "javascript": ("javascript", " java script", ".js"),
        "typescript": ("typescript", ".ts"),
        "docker": ("docker", "dockerfile", "docker compose", "compose.yml"),
        "mqtt": ("mqtt",),
        "zha": ("zha",),
        "frigate": ("frigate",),
        "fastapi": ("fastapi",),
        "telegram": ("telegram", "botfather"),
        "ollama": ("ollama",),
        "github": ("github",),
        "git": (" git ", "git commit", "git push", "git pull"),
        "linux": (" linux", "linux ", "ubuntu", "debian"),
        "powershell": ("powershell", ".ps1"),
        "sql": (" sql", "sql ", ".sql"),
        "html": (" html", "html ", ".html"),
        "css": (" css", "css ", ".css"),
        "api_rest": ("api rest", "rest api", "api http", "endpoint api"),
    }

    OFFICIAL_A_DOMAINS = {
        "yaml.org",
        "python.org",
        "docs.python.org",
        "home-assistant.io",
        "www.home-assistant.io",
        "developers.home-assistant.io",
        "frigate.video",
        "docs.frigate.video",
        "docker.com",
        "docs.docker.com",
        "mqtt.org",
        "fastapi.tiangolo.com",
        "telegram.org",
        "core.telegram.org",
        "developer.mozilla.org",
        "w3.org",
        "www.w3.org",
        "ietf.org",
        "www.ietf.org",
        "rfc-editor.org",
        "www.rfc-editor.org",
        "learn.microsoft.com",
        "docs.github.com",
        "git-scm.com",
        "nodejs.org",
        "typescriptlang.org",
        "www.typescriptlang.org",
        "kubernetes.io",
        "docs.ollama.com",
        "ollama.com",
    }

    C_DOMAINS = {
        "stackoverflow.com",
        "www.stackoverflow.com",
        "reddit.com",
        "www.reddit.com",
        "medium.com",
        "dev.to",
    }

    # Une source de bonne réputation n'est utile que si elle parle réellement
    # du skill ciblé. Ces alias servent au filtre déterministe de pertinence.
    SKILL_RELEVANCE_ALIASES = {
        "home_assistant": ("home assistant", "home-assistant", "homeassistant"),
        "yaml": ("yaml",),
        "python": ("python",),
        "javascript": ("javascript",),
        "typescript": ("typescript",),
        "docker": ("docker",),
        "mqtt": ("mqtt",),
        "zha": ("zha", "zigbee home automation"),
        "frigate": ("frigate",),
        "fastapi": ("fastapi",),
        "telegram": ("telegram", "bot api"),
        "ollama": ("ollama",),
        "github": ("github",),
        "git": ("git",),
        "linux": ("linux",),
        "powershell": ("powershell",),
        "sql": ("sql",),
        "html": ("html",),
        "css": ("css",),
        "api_rest": ("rest api", "api rest", "http api"),
    }

    # Certains noms techniques sont ambigus dans le Web général. Par exemple
    # « frigate » peut désigner un navire. On exige alors aussi un contexte
    # technique pour éviter de valider une recherche hors sujet.
    AMBIGUOUS_CONTEXT = {
        "frigate": (
            "nvr", "camera", "cameras", "video", "mqtt", "docker",
            "home assistant", "home-assistant", "configuration",
            "docs.frigate.video", "frigate.video",
            "blakeblackshear/frigate",
        ),
    }

    NEGATIVE_KNOWLEDGE_MARKERS = (
        "aucune source pertinente",
        "aucune des sources",
        "ne contient aucune information",
        "ne contiennent aucune information",
        "sources fournies ne sont pas pertinentes",
        "sources ne sont pas pertinentes",
        "incoherence dans la tache et les sources",
        "incohérence dans la tâche et les sources",
        "aucune information pertinente",
        "impossible d'etablir",
        "impossible d’établir",
        "pas suffisamment de sources",
        "sources insuffisantes",
        "je suis desole, mais aucune",
        "je suis désolé, mais aucune",
    )

    LEARNING_SEARCH_HINTS = {
        "frigate": "Frigate NVR official documentation configuration Home Assistant MQTT",
        "home_assistant": "Home Assistant official documentation YAML automations integrations",
        "mqtt": "MQTT official specification documentation configuration",
        "yaml": "YAML official specification syntax",
        "docker": "Docker official documentation configuration Docker Compose",
        "python": "Python official documentation language reference",
        "fastapi": "FastAPI official documentation API",
        "zha": "Home Assistant ZHA official documentation Zigbee",
        "telegram": "Telegram Bot API official documentation",
        "ollama": "Ollama official documentation API",
    }

    def __init__(
        self,
        manager,
        skills,
        hierarchy=None,
        *,
        max_parallel_learning_per_task: int = 4,
    ) -> None:
        self.manager = manager
        self.skills = skills
        self.hierarchy = hierarchy
        self.engine = manager.engine
        self.max_parallel_learning_per_task = max(
            1,
            int(max_parallel_learning_per_task),
        )

        self.state_store = JsonStore(
            DATA_DIR / "learning_state.json",
            {"enabled": True},
        )
        self.history_store = JsonStore(
            DATA_DIR / "learning.json",
            {"version": 1, "history": []},
        )
        self.lock = threading.RLock()

        raw_state = self.state_store.load()
        self.state = raw_state if isinstance(raw_state, dict) else {}
        self.state.setdefault("enabled", True)

        raw_history = self.history_store.load()
        if not isinstance(raw_history, dict):
            raw_history = {}
        history = raw_history.get("history", [])
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

        # Correctif V5.4.1.1 : invalide les apprentissages historiques qui ont
        # été promus malgré des sources hors sujet ou une synthèse qui disait
        # explicitement qu'aucune connaissance n'avait été établie.
        self._quarantine_invalid_existing_skills()

    # =========================================================
    # GENERIC
    # =========================================================

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _ascii(text: str) -> str:
        value = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(
            char
            for char in value
            if not unicodedata.combining(char)
        ).lower()

    @staticmethod
    def _task_metadata(task) -> dict[str, Any]:
        if isinstance(task, dict):
            raw = task.get("metadata", {})
        else:
            raw = getattr(task, "metadata", {})
        return dict(raw) if isinstance(raw, dict) else {}

    @staticmethod
    def _task_value(task, key: str, default=None):
        if isinstance(task, dict):
            return task.get(key, default)
        return getattr(task, key, default)

    def _record(
        self,
        action: str,
        *,
        skill: str | None = None,
        mission: str | None = None,
        task_id: str | None = None,
        detail: str = "",
        success: bool | None = None,
    ) -> None:
        item = {
            "at": self._now(),
            "action": str(action),
            "skill": skill,
            "mission": mission,
            "task_id": task_id,
            "detail": str(detail or ""),
        }
        if success is not None:
            item["success"] = bool(success)
        with self.lock:
            self.data["history"].append(item)
            self.data["history"] = self.data["history"][-1000:]
            self.history_store.save(self.data)

    def _mission_for_task(self, task):
        metadata = self._task_metadata(task)
        mission_id = metadata.get("mission_id")
        if not mission_id:
            return None
        return self.manager.missions.get(mission_id)

    # =========================================================
    # REQUIREMENT INFERENCE
    # =========================================================

    @staticmethod
    def _path_extensions(text: str) -> list[str]:
        values = re.findall(
            r"[A-Za-z0-9_./\\-]+\.[A-Za-z][A-Za-z0-9_-]*",
            str(text or ""),
        )
        result = []
        for value in values:
            lowered = value.lower().replace("\\", "/")
            if lowered.endswith("dockerfile"):
                ext = ".dockerfile"
            else:
                dot = lowered.rfind(".")
                ext = lowered[dot:] if dot >= 0 else ""
            if ext and ext not in result:
                result.append(ext)
        return result

    def infer_requirements(self, task) -> list[str]:
        metadata = self._task_metadata(task)
        text = " ".join(
            str(value or "")
            for value in (
                metadata.get("user_original_message"),
                metadata.get("original_message"),
                self._task_value(task, "description", ""),
                self._task_value(task, "title", ""),
            )
            if str(value or "").strip()
        )
        normalized = " " + self._ascii(text) + " "

        result: list[str] = []

        for extension in self._path_extensions(text):
            skill = self.EXTENSION_SKILLS.get(extension)
            if skill and skill not in result:
                result.append(skill)

        for skill, aliases in self.TECH_ALIASES.items():
            if any(self._ascii(alias) in normalized for alias in aliases):
                if skill not in result:
                    result.append(skill)

        # Tout skill déjà connu peut être auto-détecté par son nom/slug.
        try:
            known = self.skills.list()
        except Exception:
            known = []
        for item in known:
            key = str(item.get("key", "") or "").strip()
            name = str(item.get("name", "") or "").strip()
            candidates = [
                self._ascii(key.replace("_", " ")),
                self._ascii(name),
            ]
            for candidate in candidates:
                candidate = candidate.strip()
                if len(candidate) < 3:
                    continue
                if re.search(
                    rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])",
                    normalized,
                ):
                    if key and key not in result:
                        result.append(key)
                    break

        return result[:8]

    # =========================================================
    # SOURCE QUALITY / LEARNING COMMIT
    # =========================================================

    @staticmethod
    def _hostname(url: str) -> str:
        try:
            return (urlparse(str(url or "")).hostname or "").lower()
        except Exception:
            return ""

    @classmethod
    def source_tier(cls, source: dict[str, Any]) -> str:
        url = str(source.get("url", "") or "").strip()
        title = cls._ascii(source.get("title", ""))
        host = cls._hostname(url)

        if host in cls.OFFICIAL_A_DOMAINS:
            return "A"

        if any(
            host.endswith("." + domain)
            for domain in cls.OFFICIAL_A_DOMAINS
            if "." in domain
        ):
            return "A"

        if host in cls.C_DOMAINS:
            return "C"

        if (
            host == "github.com"
            or host == "gitlab.com"
            or host.endswith("readthedocs.io")
            or host.startswith("docs.")
            or host.startswith("developer.")
            or host.startswith("developers.")
        ):
            return "B"

        if any(
            marker in title
            for marker in (
                "official documentation",
                "documentation officielle",
                "official docs",
                "reference manual",
            )
        ):
            return "B"

        return "C"

    @classmethod
    def _skill_aliases(cls, skill_key: str) -> tuple[str, ...]:
        key = str(skill_key or "").strip().lower()
        aliases = cls.SKILL_RELEVANCE_ALIASES.get(key)
        if aliases:
            return tuple(cls._ascii(item).strip() for item in aliases if item)
        fallback = cls._ascii(key.replace("_", " ")).strip()
        return (fallback,) if fallback else ()

    @classmethod
    def _source_relevant(
        cls,
        source: dict[str, Any],
        skill_key: str,
    ) -> bool:
        text = cls._ascii(
            " ".join(
                str(source.get(field, "") or "")
                for field in ("title", "body", "url")
            )
        )
        aliases = cls._skill_aliases(skill_key)
        if not aliases or not any(alias and alias in text for alias in aliases):
            return False

        context_markers = cls.AMBIGUOUS_CONTEXT.get(
            str(skill_key or "").strip().lower()
        )
        if context_markers:
            normalized_markers = [cls._ascii(item) for item in context_markers]
            if not any(marker and marker in text for marker in normalized_markers):
                return False

        return True

    @classmethod
    def _knowledge_reject_reason(
        cls,
        knowledge: str,
    ) -> str | None:
        clean = cls._ascii(knowledge)
        for marker in cls.NEGATIVE_KNOWLEDGE_MARKERS:
            if cls._ascii(marker) in clean:
                return (
                    "la synthèse Researcher indique elle-même que les "
                    "sources sont insuffisantes ou hors sujet"
                )
        return None

    def _quarantine_invalid_existing_skills(self) -> int:
        changed = 0
        registry_data = getattr(self.skills, "data", None)
        if not isinstance(registry_data, dict):
            return 0
        skill_map = registry_data.get("skills", {})
        if not isinstance(skill_map, dict):
            return 0

        lock = getattr(self.skills, "lock", self.lock)
        with lock:
            for key, skill in skill_map.items():
                if not isinstance(skill, dict):
                    continue
                tags = list(skill.get("tags", []) or [])
                if "autonomous_learning" not in tags:
                    continue

                knowledge = str(skill.get("knowledge", "") or "")
                raw_sources = [
                    dict(item)
                    for item in (skill.get("sources", []) or [])
                    if isinstance(item, dict)
                ]
                relevant_sources = [
                    source
                    for source in raw_sources
                    if self._source_relevant(source, str(key))
                ]
                reject_reason = self._knowledge_reject_reason(knowledge)
                if reject_reason is None and (
                    not raw_sources or len(relevant_sources) == len(raw_sources)
                ):
                    continue

                if reject_reason is None and relevant_sources:
                    # On retire seulement les sources hors sujet, sans
                    # invalider un apprentissage qui possède encore une base
                    # documentaire pertinente.
                    skill["sources"] = relevant_sources
                    changed += 1
                    continue

                skill["level"] = "novice"
                skill["confidence"] = min(
                    0.20,
                    float(skill.get("confidence", 0.0) or 0.0),
                )
                skill["knowledge"] = ""
                skill["sources"] = relevant_sources
                skill["last_verified_at"] = None
                if "quarantined_learning" not in tags:
                    tags.append("quarantined_learning")
                skill["tags"] = tags
                notes = list(skill.get("notes", []) or [])
                notes.append({
                    "at": self._now(),
                    "content": (
                        "Apprentissage V5.4.1 invalidé automatiquement : "
                        "sources non pertinentes ou synthèse non concluante."
                    ),
                })
                skill["notes"] = notes[-100:]
                changed += 1

            if changed and hasattr(self.skills, "_save"):
                self.skills._save()

        if changed:
            self._record(
                "legacy_learning_quarantined",
                detail=f"{changed} skill(s) historique(s) corrigé(s)",
                success=True,
            )
        return changed

    @classmethod
    def _quality_ok(
        cls,
        sources: list[dict[str, Any]],
    ) -> bool:
        high = sum(
            1 for source in sources
            if str(source.get("tier")) in {"A", "B"}
        )
        if high >= 1:
            return True

        c_domains = {
            cls._hostname(str(source.get("url", "")))
            for source in sources
            if str(source.get("tier")) == "C"
        }
        c_domains.discard("")
        return len(c_domains) >= 2

    @staticmethod
    def _confidence_and_level(
        sources: list[dict[str, Any]],
    ) -> tuple[float, str]:
        weights = {
            "A": 1.00,
            "B": 0.80,
            "C": 0.45,
            "D": 0.20,
        }
        score = sum(
            weights.get(str(item.get("tier", "C")), 0.30)
            for item in sources[:6]
        )
        confidence = min(0.90, 0.55 + 0.12 * score)
        if confidence >= 0.78:
            level = "intermediate"
        elif confidence >= 0.58:
            level = "basic"
        else:
            level = "novice"
        return confidence, level

    def commit_learning(self, task, result) -> dict[str, Any]:
        metadata = self._task_metadata(task)
        skill_key = str(metadata.get("learning_skill", "") or "").strip()
        target_worker = str(metadata.get("learning_for_worker", "") or "").strip()
        mission = self._mission_for_task(task)
        mission_ref = mission.human_id if mission is not None else None

        if not skill_key:
            raise ValueError("Tâche d'apprentissage sans skill cible.")

        data = getattr(result, "data", {})
        if not isinstance(data, dict):
            data = {}
        raw_sources = data.get("sources", [])
        if not isinstance(raw_sources, list):
            raw_sources = []

        sources: list[dict[str, Any]] = []
        seen = set()
        for source in raw_sources:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url", "") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            clean = {
                "url": url,
                "title": str(source.get("title", "") or "").strip(),
                "body": str(source.get("body", "") or "").strip(),
            }
            clean["tier"] = self.source_tier(clean)
            sources.append(clean)

        if not sources:
            raise RuntimeError(
                "Apprentissage refusé : aucune source Web exploitable."
            )

        relevant_sources = [
            source
            for source in sources
            if self._source_relevant(source, skill_key)
        ]
        if not relevant_sources:
            raise RuntimeError(
                "Apprentissage refusé : aucune source pertinente pour "
                f"la compétence « {skill_key} »."
            )

        if not self._quality_ok(relevant_sources):
            raise RuntimeError(
                "Apprentissage refusé : qualité des sources pertinentes "
                "insuffisante (aucune source A/B et moins de deux sources C "
                "indépendantes)."
            )

        confidence, level = self._confidence_and_level(relevant_sources)
        knowledge = str(getattr(result, "message", "") or "").strip()
        if not knowledge:
            raise RuntimeError(
                "Apprentissage refusé : synthèse technique vide."
            )
        reject_reason = self._knowledge_reject_reason(knowledge)
        if reject_reason is not None:
            raise RuntimeError(
                "Apprentissage refusé : " + reject_reason + "."
            )

        learned = self.skills.apply_learning(
            skill_key,
            knowledge=knowledge[:12000],
            sources=relevant_sources,
            worker=target_worker or None,
            confidence=confidence,
            level=level,
            mission=mission_ref,
        )

        self._record(
            "skill_learned",
            skill=skill_key,
            mission=mission_ref,
            task_id=str(self._task_value(task, "id", "") or ""),
            detail=(
                f"niveau={learned.get('level')} | "
                f"confiance={float(learned.get('confidence', 0.0)):.2f} | "
                f"sources={len(relevant_sources)} | worker={target_worker or '-'}"
            ),
            success=True,
        )

        return {
            "skill": learned,
            "sources": relevant_sources,
            "confidence": confidence,
            "level": level,
        }

    # =========================================================
    # PRE-LAUNCH PREPARATION
    # =========================================================

    def _add_auxiliary_task_to_mission(self, mission, task_id: str) -> None:
        missions = self.manager.missions
        with missions.lock:
            if task_id not in mission.task_ids:
                mission.task_ids.append(task_id)
                mission.updated_at = missions._now()
                missions._save()

    def _learning_search_query(
        self,
        skill_key: str,
        original_task,
    ) -> str:
        key = str(skill_key or "").strip().lower()
        base = self.LEARNING_SEARCH_HINTS.get(
            key,
            key.replace("_", " ") + " official documentation",
        )
        description = self._ascii(
            self._task_value(original_task, "description", "")
        )
        extras = []
        for marker, label in (
            ("home assistant", "Home Assistant"),
            ("mqtt", "MQTT"),
            ("docker", "Docker"),
            ("yaml", "YAML"),
            ("api", "API"),
        ):
            if marker in description and self._ascii(label) not in self._ascii(base):
                extras.append(label)
        return " ".join([base] + extras[:3]).strip()

    def _learning_query(
        self,
        skill_key: str,
        target_worker: str,
        original_task,
    ) -> str:
        description = str(
            self._task_value(original_task, "description", "") or ""
        ).strip()
        return (
            f"Apprends la compétence technique « {skill_key} » pour permettre "
            f"au worker {target_worker} d'accomplir sa tâche.\n\n"
            "Recherche en priorité la documentation officielle, les normes, "
            "la documentation du projet et son dépôt officiel. Évite de baser "
            "la synthèse sur un seul blog ou forum.\n\n"
            "Établis uniquement à partir des sources : concepts essentiels, "
            "syntaxe/API/configuration actuelle, bonnes pratiques, pièges, "
            "changements de version importants et exemples utiles. Cite les "
            "sources [Sx]. N'invente rien. Ne modifie aucun fichier.\n\n"
            f"Tâche métier finale : {description}"
        )

    def _schedule_learning(
        self,
        mission,
        original_task,
        skill_key: str,
    ):
        target_worker = str(
            self._task_value(original_task, "worker", "") or ""
        )
        original_metadata = self._task_metadata(original_task)
        mapping = original_metadata.get("skill_learning_tasks", {})
        if not isinstance(mapping, dict):
            mapping = {}

        existing_id = str(mapping.get(skill_key, "") or "")
        if existing_id:
            existing = self.manager.tasks.get(existing_id)
            if existing is not None and existing.status not in self.TERMINAL:
                return existing

        # Mutualisation V5.4.1 : deux tâches d'une même mission qui découvrent
        # simultanément le même manque technique partagent le même Researcher.
        # On évite volontairement le partage entre missions différentes pour
        # ne pas créer de dépendance de cycle de vie entre deux projets.
        shared = None
        for candidate in self.manager.tasks.list():
            candidate_meta = self._task_metadata(candidate)
            if not candidate_meta.get("skill_learning"):
                continue
            if candidate.status in self.TERMINAL:
                continue
            if candidate_meta.get("mission_id") != mission.id:
                continue
            if str(candidate_meta.get("learning_skill", "")) != skill_key:
                continue
            shared = candidate
            break

        if shared is not None:
            mapping[skill_key] = shared.id
            dependencies = list(
                dict.fromkeys(
                    list(self._task_value(original_task, "depends_on", []) or [])
                    + [shared.id]
                )
            )
            original_metadata["skill_learning_tasks"] = mapping
            original_metadata["skill_learning_pending"] = True
            self.manager.tasks.update(
                str(self._task_value(original_task, "id")),
                metadata=original_metadata,
                depends_on=dependencies,
                status=TaskStatus.WAITING_DEPENDENCY.value,
                error=None,
            )
            self._record(
                "learning_joined",
                skill=skill_key,
                mission=mission.human_id,
                task_id=shared.id,
                detail=(
                    "recherche déjà en cours partagée avec tâche métier "
                    f"{self._task_value(original_task, 'id', '')}"
                ),
            )
            return shared

        learning_task = self.manager.tasks.create(
            title=f"Apprentissage autonome — {skill_key}",
            description=self._learning_query(
                skill_key,
                target_worker,
                original_task,
            ),
            worker="researcher",
            depends_on=[],
            metadata={
                "mission_id": mission.id,
                "skill_learning": True,
                "learning_skill": skill_key,
                "learning_for_task": str(
                    self._task_value(original_task, "id", "") or ""
                ),
                "learning_for_worker": target_worker,
                "learning_search_query": self._learning_search_query(
                    skill_key,
                    original_task,
                ),
                "original_message": self._learning_query(
                    skill_key,
                    target_worker,
                    original_task,
                ),
                "user_original_message": str(
                    original_metadata.get("user_original_message")
                    or original_metadata.get("original_message")
                    or mission.description
                ),
                "router_reason": "autonomous_skill_learning",
                "auto_repair_enabled": False,
            },
        )

        self._add_auxiliary_task_to_mission(
            mission,
            learning_task.id,
        )

        mapping[skill_key] = learning_task.id
        dependencies = list(
            dict.fromkeys(
                list(self._task_value(original_task, "depends_on", []) or [])
                + [learning_task.id]
            )
        )
        original_metadata["skill_learning_tasks"] = mapping
        original_metadata["skill_learning_pending"] = True

        self.manager.tasks.update(
            str(self._task_value(original_task, "id")),
            metadata=original_metadata,
            depends_on=dependencies,
            status=TaskStatus.WAITING_DEPENDENCY.value,
            error=None,
        )

        self._record(
            "learning_scheduled",
            skill=skill_key,
            mission=mission.human_id,
            task_id=learning_task.id,
            detail=(
                f"pour {target_worker} | tâche métier "
                f"{self._task_value(original_task, 'id', '')}"
            ),
        )

        self.engine.submit(learning_task.id)
        return learning_task

    def _transfer_good_skill(
        self,
        key: str,
        worker_name: str,
        mission_ref: str,
    ) -> bool:
        skill = self.skills.get(key)
        if skill is None:
            return False
        workers = list(skill.get("workers", []) or [])
        if not workers or worker_name in workers:
            return False
        confidence = self.skills.effective_confidence(skill)
        freshness = self.skills.freshness(skill)
        if (
            confidence < 0.50
            or str(freshness.get("status")) != "fresh"
        ):
            return False
        self.skills.assign_worker(key, worker_name)
        self._record(
            "skill_transferred",
            skill=key,
            mission=mission_ref,
            detail=f"worker={worker_name}",
            success=True,
        )
        return True

    def prepare_task(self, task) -> dict[str, Any]:
        if not bool(self.state.get("enabled", True)):
            return {"ready": True, "learning": False}

        metadata = self._task_metadata(task)
        if metadata.get("skill_learning"):
            return {"ready": True, "learning": True}

        # Le Researcher n'a pas besoin de connaître le domaine avant de le
        # rechercher. On ne lui crée donc pas une recherche avant sa recherche.
        worker_name = str(self._task_value(task, "worker", "") or "")
        if worker_name == "researcher":
            return {"ready": True, "learning": False}

        mission = self._mission_for_task(task)
        if mission is None:
            return {"ready": True, "learning": False}

        inferred = self.infer_requirements(task)
        current = self.skills.effective_requirements(mission)
        new_requirements = [
            key for key in inferred
            if key not in current
        ]
        if new_requirements:
            self.skills.set_mission_requirements(
                mission,
                new_requirements,
                replace=False,
            )
            self._record(
                "requirements_inferred",
                mission=mission.human_id,
                task_id=str(self._task_value(task, "id", "") or ""),
                detail=", ".join(new_requirements),
            )

        context = self.skills.context_for_task(
            task,
            record_usage=False,
        )

        # Un skill déjà fiable peut être transmis à un autre worker sans
        # repasser par le Web : le savoir technique est commun à l'équipe.
        transferred = False
        for item in list(context.get("available", []) or []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "") or "")
            if key and self._transfer_good_skill(
                key,
                worker_name,
                mission.human_id,
            ):
                transferred = True
        if transferred:
            context = self.skills.context_for_task(
                task,
                record_usage=False,
            )

        needs: list[str] = []
        for key in list(context.get("missing", []) or []):
            if key not in needs:
                needs.append(key)

        for item in list(context.get("available", []) or []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "") or "")
            confidence = float(
                item.get("effective_confidence", 0.0) or 0.0
            )
            freshness = item.get("freshness", {}) or {}
            status = str(freshness.get("status", "unknown"))
            workers = [
                str(value)
                for value in (item.get("workers", []) or [])
            ]
            unassigned = bool(workers) and worker_name not in workers
            if (
                confidence < 0.50
                or status in {"stale", "undocumented", "unknown"}
                or unassigned
            ):
                if key and key not in needs:
                    needs.append(key)

        if not needs:
            if metadata.get("skill_learning_pending"):
                metadata["skill_learning_pending"] = False
                self.manager.tasks.update(
                    str(self._task_value(task, "id")),
                    metadata=metadata,
                )
            return {
                "ready": True,
                "learning": False,
                "requirements": context.get("required", []),
            }

        created = []
        for key in needs[:self.max_parallel_learning_per_task]:
            learned_task = self._schedule_learning(
                mission,
                task,
                key,
            )
            created.append(learned_task.id)

        return {
            "ready": False,
            "learning": True,
            "reason": "skill_learning_scheduled",
            "skills": needs,
            "learning_tasks": created,
        }

    # =========================================================
    # STATUS / COMMANDS
    # =========================================================

    def _active_learning_tasks(self) -> list[dict[str, Any]]:
        rows = []
        for task in self.manager.tasks.list():
            metadata = self._task_metadata(task)
            if not metadata.get("skill_learning"):
                continue
            if task.status in self.TERMINAL:
                continue
            mission = self._mission_for_task(task)
            rows.append(
                {
                    "task": task.id,
                    "mission": mission.human_id if mission else None,
                    "skill": metadata.get("learning_skill"),
                    "for_worker": metadata.get("learning_for_worker"),
                    "status": task.status,
                }
            )
        return rows

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            history = list(self.data.get("history", []))
        learned = sum(
            1 for item in history
            if item.get("action") == "skill_learned"
            and item.get("success") is True
        )
        failed = sum(
            1 for item in history
            if item.get("action") == "learning_failed"
        )
        return {
            "version": 1,
            "enabled": bool(self.state.get("enabled", True)),
            "active": self._active_learning_tasks(),
            "learned": learned,
            "failed": failed,
            "history": len(history),
            "recent": history[-20:],
        }

    def summary(self) -> str:
        snap = self.snapshot()
        lines = [
            "APPRENTISSAGE AUTONOME V5.4.1",
            "Mode : " + ("actif" if snap["enabled"] else "désactivé"),
            f"Apprentissages en cours : {len(snap['active'])}",
            f"Skills appris/rafraîchis : {snap['learned']}",
            f"Échecs d'apprentissage : {snap['failed']}",
        ]
        for item in snap["active"][:8]:
            lines.append(
                f"- {item.get('mission') or '-'} | {item.get('skill')} | "
                f"Researcher → {item.get('for_worker')} | {item.get('status')}"
            )
        return "\n".join(lines)

    def history_summary(self, limit: int = 20) -> str:
        with self.lock:
            items = list(self.data.get("history", []))[-max(1, int(limit)):]
        if not items:
            return "Aucun apprentissage autonome enregistré."
        lines = ["HISTORIQUE APPRENTISSAGE V5.4.1"]
        for item in reversed(items):
            lines.append(
                "- "
                + str(item.get("mission") or "-")
                + " | "
                + str(item.get("skill") or "-")
                + " | "
                + str(item.get("action") or "action")
                + (" — " + str(item.get("detail")) if item.get("detail") else "")
            )
        return "\n".join(lines)

    def command_response(self, message: str) -> str | None:
        value = " ".join(str(message or "").strip().lower().split())
        if value in {
            "learning status",
            "learning",
            "apprentissage status",
            "apprentissage autonome",
            "apprentissage",
        }:
            return self.summary()

        if value in {
            "learning history",
            "historique learning",
            "historique apprentissage",
        }:
            return self.history_summary()

        if value in {
            "learning on",
            "apprentissage on",
            "active apprentissage",
        }:
            self.state["enabled"] = True
            self.state_store.save(self.state)
            self._record("learning_enabled", detail="Apprentissage autonome activé.")
            return "Apprentissage autonome activé."

        if value in {
            "learning off",
            "apprentissage off",
            "desactive apprentissage",
            "désactive apprentissage",
        }:
            self.state["enabled"] = False
            self.state_store.save(self.state)
            self._record("learning_disabled", detail="Apprentissage autonome désactivé.")
            return "Apprentissage autonome désactivé."

        return None


class LearningResearcherAdapter:
    """Persiste dans le Skill Registry les recherches marquées apprentissage."""

    def __init__(self, worker, learning: SkillLearningManager) -> None:
        self.worker = worker
        self.learning = learning
        self.name = worker.name
        self.lock = threading.RLock()

    def __getattr__(self, name: str):
        return getattr(self.worker, name)

    def execute(self, task):
        metadata = self.learning._task_metadata(task)
        if not metadata.get("skill_learning"):
            return self.worker.execute(task)

        research_task = task
        search_query = str(metadata.get("learning_search_query", "") or "").strip()
        if search_query:
            if isinstance(task, dict):
                research_task = dict(task)
                research_task["description"] = search_query
            else:
                research_task = task

        # Pour l'apprentissage technique, les moteurs Web généraux sont plus
        # utiles que Wikipedia, surtout pour les noms ambigus comme Frigate.
        searcher = getattr(self.worker, "searcher", None)
        old_backends = getattr(searcher, "BACKENDS", None) if searcher is not None else None
        if searcher is not None:
            searcher.BACKENDS = (
                "brave", "bing", "duckduckgo", "yahoo", "mojeek", "wikipedia"
            )
        try:
            result = self.worker.execute(research_task)
        finally:
            if searcher is not None and old_backends is not None:
                searcher.BACKENDS = old_backends

        success = bool(getattr(result, "success", False))
        skill_key = str(metadata.get("learning_skill", "") or "")
        mission = self.learning._mission_for_task(task)
        mission_ref = mission.human_id if mission is not None else None

        if not success:
            self.learning._record(
                "learning_failed",
                skill=skill_key,
                mission=mission_ref,
                task_id=str(self.learning._task_value(task, "id", "") or ""),
                detail=str(getattr(result, "error", None) or getattr(result, "message", "")),
                success=False,
            )
            return result

        try:
            committed = self.learning.commit_learning(
                task,
                result,
            )
        except Exception as exc:
            try:
                result.success = False
                result.error = str(exc)
                result.message = "Apprentissage technique non validé : " + str(exc)
                data = getattr(result, "data", None)
                if isinstance(data, dict):
                    data["learning_success"] = False
                    data["learning_error"] = str(exc)
            except Exception:
                pass
            self.learning._record(
                "learning_failed",
                skill=skill_key,
                mission=mission_ref,
                task_id=str(self.learning._task_value(task, "id", "") or ""),
                detail=str(exc),
                success=False,
            )
            return result

        data = getattr(result, "data", None)
        if isinstance(data, dict):
            data["learning_success"] = True
            data["learned_skill"] = committed["skill"]
            data["learning_sources"] = committed["sources"]

        return result
