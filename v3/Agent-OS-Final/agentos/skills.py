from __future__ import annotations

import re
import threading
import unicodedata
from datetime import datetime, timezone
from typing import Any

from agentos.config import DATA_DIR
from agentos.storage import JsonStore


class SkillRegistry:
    """Registre persistant de compétences Agent-OS V5.2.

    Le registre est volontairement distinct de la mémoire personnelle :
    - la mémoire décrit l'utilisateur et le contexte relationnel ;
    - les skills décrivent ce que l'équipe sait faire et sur quelles sources ;
    - une mission peut déclarer des compétences requises ;
    - le moteur peut injecter le contexte correspondant au worker au lancement.

    V5.2 construit le registre et le pipeline. L'apprentissage autonome par le
    Researcher sera ajouté en V5.4, une fois les spécialistes dynamiques V5.3
    branchés dessus.
    """

    LEVEL_ORDER = {
        "unknown": 0,
        "novice": 1,
        "basic": 2,
        "intermediate": 3,
        "advanced": 4,
        "expert": 5,
    }

    LEVEL_LABELS = {
        "unknown": "inconnu",
        "novice": "novice",
        "basic": "basique",
        "intermediate": "intermédiaire",
        "advanced": "avancé",
        "expert": "expert",
    }

    LEVEL_ALIASES = {
        "inconnu": "unknown",
        "unknown": "unknown",
        "novice": "novice",
        "debutant": "novice",
        "débutant": "novice",
        "basic": "basic",
        "basique": "basic",
        "intermediaire": "intermediate",
        "intermédiaire": "intermediate",
        "intermediate": "intermediate",
        "avance": "advanced",
        "avancé": "advanced",
        "advanced": "advanced",
        "expert": "expert",
    }

    SOURCE_TIERS = {"A", "B", "C", "D"}

    MISSION_RE = re.compile(
        r"\bM-\d{1,6}\b",
        flags=re.IGNORECASE,
    )

    def __init__(
        self,
        manager=None,
        hierarchy=None,
    ) -> None:
        self.manager = manager
        self.hierarchy = hierarchy
        self.store = JsonStore(
            DATA_DIR / "skills.json",
            {
                "version": 1,
                "skills": {},
                "history": [],
            },
        )
        self.lock = threading.RLock()
        self.data = self._load()

    # =========================================================
    # GENERIC HELPERS
    # =========================================================

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _ascii(
        text: str,
    ) -> str:
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
    def _slug(
        cls,
        text: str,
    ) -> str:
        value = cls._ascii(text)
        value = re.sub(
            r"[^a-z0-9]+",
            "_",
            value,
        ).strip("_")
        return value[:80]

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
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )
        return parsed

    @classmethod
    def _normalize_level(
        cls,
        value: str,
    ) -> str:
        key = cls._ascii(value).strip()
        canonical = cls.LEVEL_ALIASES.get(
            key,
            key,
        )
        if canonical not in cls.LEVEL_ORDER:
            raise ValueError(
                "Niveau inconnu : novice, basique, intermédiaire, avancé ou expert."
            )
        return canonical

    @staticmethod
    def _clamp_confidence(
        value: float,
    ) -> float:
        return max(
            0.0,
            min(1.0, float(value)),
        )

    @staticmethod
    def _metadata(
        mission,
    ) -> dict[str, Any]:
        return dict(
            mission.metadata
            if isinstance(
                mission.metadata,
                dict,
            )
            else {}
        )

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
        return f"M-{int(raw.split('-')[1]):03d}"

    # =========================================================
    # STORAGE / MIGRATION
    # =========================================================

    def _load(self) -> dict[str, Any]:
        loaded = self.store.load()
        if not isinstance(loaded, dict):
            loaded = {}

        skills = loaded.get("skills")
        if not isinstance(skills, dict):
            skills = {}

        history = loaded.get("history")
        if not isinstance(history, list):
            history = []

        clean: dict[str, dict[str, Any]] = {}

        for raw_key, raw_skill in skills.items():
            if not isinstance(raw_skill, dict):
                continue
            key = self._slug(
                raw_skill.get("key")
                or raw_key
                or raw_skill.get("name")
                or ""
            )
            if not key:
                continue

            skill = dict(raw_skill)
            skill["key"] = key
            skill.setdefault(
                "name",
                str(raw_key or key),
            )
            skill.setdefault("description", "")
            skill.setdefault("level", "novice")
            if skill["level"] not in self.LEVEL_ORDER:
                skill["level"] = "novice"
            try:
                skill["confidence"] = self._clamp_confidence(
                    float(skill.get("confidence", 0.25))
                )
            except (TypeError, ValueError):
                skill["confidence"] = 0.25
            skill.setdefault("workers", [])
            skill.setdefault("tags", [])
            skill.setdefault("sources", [])
            skill.setdefault("notes", [])
            skill.setdefault("knowledge", "")
            skill.setdefault("freshness_days", 90)
            skill.setdefault("created_at", self._now())
            skill.setdefault("updated_at", skill["created_at"])
            skill.setdefault("last_verified_at", None)
            skill.setdefault("last_used_at", None)
            skill.setdefault("uses", 0)
            skill.setdefault("successes", 0)
            skill.setdefault("failures", 0)

            clean[key] = skill

        result = {
            "version": 1,
            "skills": clean,
            "history": [
                dict(item)
                for item in history[-1000:]
                if isinstance(item, dict)
            ],
        }
        self.store.save(result)
        return result

    def _save(self) -> None:
        self.data["history"] = list(
            self.data.get("history", [])
        )[-1000:]
        self.store.save(
            self.data
        )

    def _record(
        self,
        action: str,
        *,
        skill: str | None = None,
        detail: str = "",
        mission: str | None = None,
    ) -> None:
        history = self.data.setdefault(
            "history",
            [],
        )
        history.append(
            {
                "at": self._now(),
                "action": str(action),
                "skill": skill,
                "mission": mission,
                "detail": str(detail or ""),
            }
        )

    # =========================================================
    # SKILL CRUD
    # =========================================================

    def register(
        self,
        name: str,
        *,
        description: str = "",
        level: str = "novice",
        confidence: float = 0.25,
        workers: list[str] | None = None,
        tags: list[str] | None = None,
        freshness_days: int = 90,
        knowledge: str = "",
    ) -> dict[str, Any]:
        key = self._slug(name)
        if not key:
            raise ValueError(
                "Nom de compétence vide."
            )

        canonical_level = self._normalize_level(
            level
        )

        with self.lock:
            existing = self.data[
                "skills"
            ].get(key)

            if existing is None:
                now = self._now()
                skill = {
                    "key": key,
                    "name": str(name).strip(),
                    "description": str(description or "").strip(),
                    "level": canonical_level,
                    "confidence": self._clamp_confidence(
                        confidence
                    ),
                    "workers": list(dict.fromkeys(
                        str(item).strip()
                        for item in (workers or [])
                        if str(item).strip()
                    )),
                    "tags": list(dict.fromkeys(
                        self._slug(item)
                        for item in (tags or [])
                        if self._slug(item)
                    )),
                    "sources": [],
                    "notes": [],
                    "knowledge": str(knowledge or "").strip(),
                    "freshness_days": max(
                        1,
                        int(freshness_days),
                    ),
                    "created_at": now,
                    "updated_at": now,
                    "last_verified_at": None,
                    "last_used_at": None,
                    "uses": 0,
                    "successes": 0,
                    "failures": 0,
                }
                self.data["skills"][key] = skill
                self._record(
                    "skill_registered",
                    skill=key,
                    detail=skill["name"],
                )
            else:
                skill = existing
                if description:
                    skill["description"] = str(description).strip()
                skill["level"] = canonical_level
                skill["confidence"] = self._clamp_confidence(
                    confidence
                )
                if workers:
                    current = list(
                        skill.get("workers", [])
                    )
                    skill["workers"] = list(
                        dict.fromkeys(
                            current
                            + [
                                str(item).strip()
                                for item in workers
                                if str(item).strip()
                            ]
                        )
                    )
                if tags:
                    current_tags = list(
                        skill.get("tags", [])
                    )
                    skill["tags"] = list(
                        dict.fromkeys(
                            current_tags
                            + [
                                self._slug(item)
                                for item in tags
                                if self._slug(item)
                            ]
                        )
                    )
                if knowledge:
                    skill["knowledge"] = str(knowledge).strip()
                skill["updated_at"] = self._now()
                self._record(
                    "skill_updated",
                    skill=key,
                )

            self._save()
            return dict(skill)

    def get(
        self,
        name: str,
    ) -> dict[str, Any] | None:
        key = self._slug(name)
        with self.lock:
            skill = self.data[
                "skills"
            ].get(key)
            return (
                dict(skill)
                if isinstance(skill, dict)
                else None
            )

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            skills = [
                dict(item)
                for item in self.data[
                    "skills"
                ].values()
                if isinstance(item, dict)
            ]

        return sorted(
            skills,
            key=lambda item: (
                -self.LEVEL_ORDER.get(
                    str(item.get("level")),
                    0,
                ),
                -float(item.get("confidence", 0.0) or 0.0),
                str(item.get("name", "")).lower(),
            ),
        )

    def set_level(
        self,
        name: str,
        level: str,
    ) -> dict[str, Any]:
        key = self._slug(name)
        canonical = self._normalize_level(
            level
        )
        with self.lock:
            skill = self.data[
                "skills"
            ].get(key)
            if skill is None:
                raise KeyError(
                    f"Compétence {name} introuvable."
                )
            skill["level"] = canonical
            skill["updated_at"] = self._now()
            self._record(
                "skill_level_changed",
                skill=key,
                detail=canonical,
            )
            self._save()
            return dict(skill)

    def set_confidence(
        self,
        name: str,
        confidence: float,
    ) -> dict[str, Any]:
        key = self._slug(name)
        with self.lock:
            skill = self.data[
                "skills"
            ].get(key)
            if skill is None:
                raise KeyError(
                    f"Compétence {name} introuvable."
                )
            skill["confidence"] = self._clamp_confidence(
                confidence
            )
            skill["updated_at"] = self._now()
            self._record(
                "skill_confidence_changed",
                skill=key,
                detail=f"{skill['confidence']:.2f}",
            )
            self._save()
            return dict(skill)

    def assign_worker(
        self,
        name: str,
        worker: str,
    ) -> dict[str, Any]:
        key = self._slug(name)
        worker_name = str(worker or "").strip()
        if not worker_name:
            raise ValueError("Worker vide.")

        with self.lock:
            skill = self.data[
                "skills"
            ].get(key)
            if skill is None:
                raise KeyError(
                    f"Compétence {name} introuvable."
                )
            workers = list(
                skill.get("workers", [])
            )
            if worker_name not in workers:
                workers.append(worker_name)
            skill["workers"] = workers
            skill["updated_at"] = self._now()
            self._record(
                "skill_worker_assigned",
                skill=key,
                detail=worker_name,
            )
            self._save()
            return dict(skill)

    def add_source(
        self,
        name: str,
        url: str,
        *,
        title: str = "",
        tier: str = "C",
    ) -> dict[str, Any]:
        key = self._slug(name)
        tier_value = str(tier or "C").upper()
        if tier_value not in self.SOURCE_TIERS:
            raise ValueError(
                "Niveau de source inconnu : A, B, C ou D."
            )

        clean_url = str(url or "").strip()
        if not clean_url:
            raise ValueError("URL de source vide.")

        with self.lock:
            skill = self.data[
                "skills"
            ].get(key)
            if skill is None:
                raise KeyError(
                    f"Compétence {name} introuvable."
                )

            sources = list(
                skill.get("sources", [])
            )
            now = self._now()
            existing = next(
                (
                    item
                    for item in sources
                    if isinstance(item, dict)
                    and str(item.get("url", "")) == clean_url
                ),
                None,
            )

            if existing is None:
                sources.append(
                    {
                        "url": clean_url,
                        "title": str(title or "").strip(),
                        "tier": tier_value,
                        "verified_at": now,
                    }
                )
            else:
                existing["title"] = (
                    str(title or existing.get("title", "")).strip()
                )
                existing["tier"] = tier_value
                existing["verified_at"] = now

            skill["sources"] = sources
            skill["last_verified_at"] = now
            skill["updated_at"] = now
            self._record(
                "skill_source_added",
                skill=key,
                detail=f"{tier_value} {clean_url}",
            )
            self._save()
            return dict(skill)

    def add_note(
        self,
        name: str,
        note: str,
    ) -> dict[str, Any]:
        key = self._slug(name)
        clean = str(note or "").strip()
        if not clean:
            raise ValueError("Note vide.")

        with self.lock:
            skill = self.data[
                "skills"
            ].get(key)
            if skill is None:
                raise KeyError(
                    f"Compétence {name} introuvable."
                )
            notes = list(
                skill.get("notes", [])
            )
            notes.append(
                {
                    "at": self._now(),
                    "content": clean,
                }
            )
            skill["notes"] = notes[-100:]
            skill["updated_at"] = self._now()
            self._record(
                "skill_note_added",
                skill=key,
                detail=clean[:120],
            )
            self._save()
            return dict(skill)

    # =========================================================
    # FRESHNESS / EFFECTIVE KNOWLEDGE
    # =========================================================

    def freshness(
        self,
        skill: dict[str, Any],
    ) -> dict[str, Any]:
        if not (
            skill.get("sources")
            or str(skill.get("knowledge", "") or "").strip()
            or skill.get("notes")
        ):
            return {
                "status": "undocumented",
                "age_days": None,
                "max_days": max(
                    1,
                    int(skill.get("freshness_days", 90) or 90),
                ),
            }

        reference = (
            skill.get("last_verified_at")
            or skill.get("updated_at")
        )
        parsed = self._parse_dt(
            reference
        )
        max_days = max(
            1,
            int(skill.get("freshness_days", 90) or 90),
        )

        if parsed is None:
            return {
                "status": "unknown",
                "age_days": None,
                "max_days": max_days,
            }

        age_seconds = (
            datetime.now(timezone.utc)
            - parsed.astimezone(timezone.utc)
        ).total_seconds()
        age_days = max(
            0,
            int(age_seconds // 86400),
        )

        return {
            "status": (
                "fresh"
                if age_days <= max_days
                else "stale"
            ),
            "age_days": age_days,
            "max_days": max_days,
        }

    def effective_confidence(
        self,
        skill: dict[str, Any],
    ) -> float:
        base = self._clamp_confidence(
            float(skill.get("confidence", 0.0) or 0.0)
        )
        fresh = self.freshness(skill)
        if fresh["status"] != "stale":
            return base

        age_days = int(
            fresh.get("age_days")
            or 0
        )
        max_days = int(
            fresh.get("max_days")
            or 1
        )
        overdue = max(
            0,
            age_days - max_days,
        )
        decay = min(
            0.50,
            overdue / max_days * 0.15,
        )
        return self._clamp_confidence(
            base - decay
        )

    # =========================================================
    # MISSION REQUIREMENTS
    # =========================================================

    @classmethod
    def _parse_skill_list(
        cls,
        raw: str,
    ) -> list[str]:
        value = str(raw or "")
        parts = re.split(
            r"[,;+]",
            value,
        )
        result: list[str] = []
        for part in parts:
            clean = part.strip()
            if not clean:
                continue
            key = cls._slug(clean)
            if key and key not in result:
                result.append(key)
        return result

    def set_mission_requirements(
        self,
        mission,
        skills: list[str],
        *,
        replace: bool = False,
    ) -> list[str]:
        if self.manager is None:
            raise RuntimeError(
                "Le Skill Registry n'est pas relié au Manager."
            )

        clean = []
        for item in skills:
            key = self._slug(item)
            if key and key not in clean:
                clean.append(key)

        metadata = self._metadata(
            mission
        )
        current = [] if replace else list(
            metadata.get("required_skills", [])
            if isinstance(
                metadata.get("required_skills", []),
                list,
            )
            else []
        )
        merged = list(
            dict.fromkeys(
                current + clean
            )
        )

        self.manager.missions.set_status(
            mission.id,
            mission.status,
            metadata_patch={
                "required_skills": merged,
            },
        )

        with self.lock:
            self._record(
                "mission_skills_changed",
                mission=mission.human_id,
                detail=", ".join(merged),
            )
            self._save()

        return merged

    def _requirements_direct(
        self,
        mission,
    ) -> list[str]:
        metadata = self._metadata(
            mission
        )
        raw = metadata.get(
            "required_skills",
            [],
        )
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        for item in raw:
            key = self._slug(item)
            if key and key not in result:
                result.append(key)
        return result

    def effective_requirements(
        self,
        mission,
    ) -> list[str]:
        chain = []

        if (
            self.hierarchy is not None
            and hasattr(
                self.hierarchy,
                "parent_of",
            )
        ):
            try:
                cursor = mission
                parents = []
                seen = set()
                while cursor is not None:
                    parent = self.hierarchy.parent_of(
                        cursor
                    )
                    if parent is None or parent.id in seen:
                        break
                    parents.append(parent)
                    seen.add(parent.id)
                    cursor = parent
                chain.extend(
                    reversed(parents)
                )
            except Exception:
                pass

        chain.append(mission)

        result: list[str] = []
        for item in chain:
            for key in self._requirements_direct(
                item
            ):
                if key not in result:
                    result.append(key)

        return result

    # =========================================================
    # TASK CONTEXT
    # =========================================================

    def context_for_task(
        self,
        task,
        *,
        record_usage: bool = False,
    ) -> dict[str, Any]:
        metadata = (
            dict(task.metadata)
            if isinstance(
                task.metadata,
                dict,
            )
            else {}
        )
        mission_id = metadata.get(
            "mission_id"
        )

        if (
            not mission_id
            or self.manager is None
        ):
            return {
                "required": [],
                "available": [],
                "missing": [],
                "text": "",
            }

        mission = self.manager.missions.get(
            mission_id
        )
        if mission is None:
            return {
                "required": [],
                "available": [],
                "missing": [],
                "text": "",
            }

        required = self.effective_requirements(
            mission
        )
        available = []
        missing = []
        text_parts = []

        with self.lock:
            for key in required:
                skill = self.data[
                    "skills"
                ].get(key)
                if not isinstance(skill, dict):
                    missing.append(key)
                    continue

                fresh = self.freshness(skill)
                effective_confidence = self.effective_confidence(
                    skill
                )
                available.append(
                    {
                        "key": key,
                        "name": skill.get("name", key),
                        "level": skill.get("level", "unknown"),
                        "confidence": skill.get("confidence", 0.0),
                        "effective_confidence": effective_confidence,
                        "freshness": fresh,
                        "workers": list(skill.get("workers", [])),
                        "sources": list(skill.get("sources", [])),
                        "knowledge": str(skill.get("knowledge", "") or ""),
                        "notes": list(skill.get("notes", []))[-8:],
                    }
                )

                source_lines = []
                for source in list(
                    skill.get("sources", [])
                )[:6]:
                    if not isinstance(source, dict):
                        continue
                    source_lines.append(
                        "- ["
                        + str(source.get("tier", "C"))
                        + "] "
                        + str(source.get("title") or source.get("url") or "source")
                        + " — "
                        + str(source.get("url") or "")
                    )

                note_lines = []
                for note in list(
                    skill.get("notes", [])
                )[-5:]:
                    if isinstance(note, dict):
                        content = str(note.get("content", "")).strip()
                    else:
                        content = str(note).strip()
                    if content:
                        note_lines.append("- " + content)

                block = [
                    f"SKILL {skill.get('name', key)} ({key})",
                    "niveau=" + self.LEVEL_LABELS.get(
                        str(skill.get("level", "unknown")),
                        str(skill.get("level", "unknown")),
                    ),
                    f"confiance_effective={effective_confidence:.2f}",
                    "fraicheur=" + str(fresh.get("status")),
                ]
                description = str(skill.get("description", "")).strip()
                knowledge = str(skill.get("knowledge", "")).strip()
                if description:
                    block.append("description=" + description)
                if knowledge:
                    block.extend([
                        "CONNAISSANCES:",
                        knowledge,
                    ])
                if note_lines:
                    block.extend([
                        "NOTES:",
                        *note_lines,
                    ])
                if source_lines:
                    block.extend([
                        "SOURCES:",
                        *source_lines,
                    ])
                text_parts.append(
                    "\n".join(block)
                )

                if record_usage:
                    skill["uses"] = int(
                        skill.get("uses", 0)
                        or 0
                    ) + 1
                    skill["last_used_at"] = self._now()

            if record_usage and required:
                self._record(
                    "skills_injected",
                    mission=mission.human_id,
                    detail=", ".join(required),
                )
                self._save()

        return {
            "required": required,
            "available": available,
            "missing": missing,
            "text": "\n\n".join(text_parts),
        }

    # =========================================================
    # SNAPSHOTS / TEXT
    # =========================================================

    def snapshot(self) -> dict[str, Any]:
        skills = self.list()
        stale = 0
        source_count = 0
        worker_count: dict[str, int] = {}

        for skill in skills:
            if self.freshness(skill)["status"] == "stale":
                stale += 1
            source_count += len(
                skill.get("sources", [])
            )
            for worker in skill.get("workers", []):
                worker_count[worker] = (
                    worker_count.get(worker, 0)
                    + 1
                )

        return {
            "version": 1,
            "skills": len(skills),
            "stale": stale,
            "sources": source_count,
            "workers": worker_count,
            "history": len(
                self.data.get("history", [])
            ),
        }

    def list_summary(self) -> str:
        skills = self.list()
        if not skills:
            return (
                "SKILL REGISTRY V5.2\n"
                "Aucune compétence enregistrée.\n\n"
                "Exemple : skill add yaml"
            )

        lines = [
            "SKILL REGISTRY V5.2",
            f"Compétences : {len(skills)}",
            "",
        ]

        for skill in skills[:30]:
            fresh = self.freshness(skill)
            label = self.LEVEL_LABELS.get(
                str(skill.get("level")),
                str(skill.get("level")),
            )
            workers = ", ".join(
                skill.get("workers", [])
            ) or "aucun"
            lines.append(
                "- "
                + str(skill.get("name", skill.get("key")))
                + " | "
                + label
                + " | confiance "
                + f"{self.effective_confidence(skill):.2f}"
                + " | "
                + str(fresh.get("status"))
                + " | workers "
                + workers
            )

        return "\n".join(lines)

    def skill_summary(
        self,
        name: str,
    ) -> str:
        skill = self.get(name)
        if skill is None:
            return (
                f"Compétence « {name} » introuvable."
            )

        fresh = self.freshness(skill)
        lines = [
            "SKILL " + str(skill.get("name", skill.get("key"))),
            "Clé : " + str(skill.get("key")),
            "Niveau : " + self.LEVEL_LABELS.get(
                str(skill.get("level")),
                str(skill.get("level")),
            ),
            "Confiance : " + f"{float(skill.get('confidence', 0.0)):.2f}",
            "Confiance effective : " + f"{self.effective_confidence(skill):.2f}",
            "Fraîcheur : " + str(fresh.get("status"))
            + (
                f" ({fresh['age_days']} j / {fresh['max_days']} j)"
                if fresh.get("age_days") is not None
                else ""
            ),
            "Workers : " + (
                ", ".join(skill.get("workers", []))
                or "aucun"
            ),
            "Utilisations : " + str(skill.get("uses", 0)),
        ]

        description = str(skill.get("description", "")).strip()
        if description:
            lines.extend(["", description])

        knowledge = str(skill.get("knowledge", "")).strip()
        if knowledge:
            lines.extend([
                "",
                "CONNAISSANCES",
                knowledge,
            ])

        notes = list(
            skill.get("notes", [])
        )[-8:]
        if notes:
            lines.extend(["", "NOTES"])
            for note in notes:
                content = (
                    str(note.get("content", ""))
                    if isinstance(note, dict)
                    else str(note)
                )
                lines.append("- " + content)

        sources = list(
            skill.get("sources", [])
        )
        if sources:
            lines.extend(["", "SOURCES"])
            for source in sources[:12]:
                if not isinstance(source, dict):
                    continue
                lines.append(
                    "- ["
                    + str(source.get("tier", "C"))
                    + "] "
                    + str(source.get("title") or source.get("url") or "source")
                    + " — "
                    + str(source.get("url") or "")
                )

        return "\n".join(lines)

    def requirements_summary(
        self,
        mission,
    ) -> str:
        effective = self.effective_requirements(
            mission
        )
        direct = self._requirements_direct(
            mission
        )

        if not effective:
            return (
                f"{mission.human_id} — aucune compétence requise."
            )

        lines = [
            f"COMPÉTENCES — {mission.human_id}",
            "Directes : " + (
                ", ".join(direct)
                if direct
                else "aucune (héritage seulement)"
            ),
            "Effectives : " + ", ".join(effective),
            "",
        ]

        for key in effective:
            skill = self.get(key)
            if skill is None:
                lines.append(
                    f"- {key} | MANQUANTE"
                )
            else:
                fresh = self.freshness(skill)
                lines.append(
                    f"- {key} | "
                    + self.LEVEL_LABELS.get(
                        str(skill.get("level")),
                        str(skill.get("level")),
                    )
                    + f" | confiance {self.effective_confidence(skill):.2f}"
                    + " | "
                    + str(fresh.get("status"))
                )

        return "\n".join(lines)

    # =========================================================
    # COMMANDS
    # =========================================================

    @staticmethod
    def _split_name_value(
        raw: str,
    ) -> tuple[str, str]:
        value = str(raw or "").strip()
        if ":" in value:
            left, right = value.split(
                ":",
                1,
            )
            return left.strip(), right.strip()

        parts = value.split()
        if len(parts) < 2:
            return value, ""
        return parts[0], " ".join(parts[1:])

    def command_response(
        self,
        message: str,
    ) -> str | None:
        raw = str(message or "").strip()
        normalized = " ".join(
            self._ascii(raw).split()
        )

        if normalized in {
            "skills",
            "skill list",
            "skills list",
            "skill registry",
            "skills status",
        }:
            return self.list_summary()

        if normalized in {
            "skill status",
            "skill registry status",
        }:
            snapshot = self.snapshot()
            return (
                "SKILL REGISTRY V5.2\n"
                f"Compétences : {snapshot['skills']}\n"
                f"Périmées : {snapshot['stale']}\n"
                f"Sources : {snapshot['sources']}\n"
                f"Événements : {snapshot['history']}"
            )

        if normalized.startswith("skill add ") or normalized.startswith(
            "skill register "
        ):
            prefix = (
                "skill add "
                if normalized.startswith("skill add ")
                else "skill register "
            )
            name = raw[len(prefix):].strip()
            if not name:
                return "Usage : skill add yaml"
            skill = self.register(name)
            return (
                "Compétence enregistrée : "
                + str(skill["name"])
                + " | niveau novice | confiance 0.25."
            )

        if normalized.startswith("skill level "):
            body = raw[len("skill level "):].strip()
            name, level = self._split_name_value(body)
            if not name or not level:
                return "Usage : skill level yaml intermediate"
            try:
                skill = self.set_level(name, level)
            except (KeyError, ValueError) as exc:
                return str(exc)
            return (
                f"{skill['name']} — niveau "
                + self.LEVEL_LABELS.get(
                    skill["level"],
                    skill["level"],
                )
                + "."
            )

        if normalized.startswith("skill confidence "):
            body = raw[len("skill confidence "):].strip()
            name, confidence_raw = self._split_name_value(body)
            if not name or not confidence_raw:
                return "Usage : skill confidence yaml 0.80"
            try:
                clean = confidence_raw.strip().replace(",", ".")
                if clean.endswith("%"):
                    confidence = float(clean[:-1]) / 100.0
                else:
                    confidence = float(clean)
                    if confidence > 1:
                        confidence /= 100.0
                skill = self.set_confidence(
                    name,
                    confidence,
                )
            except (KeyError, ValueError) as exc:
                return str(exc)
            return (
                f"{skill['name']} — confiance "
                f"{skill['confidence']:.2f}."
            )

        if normalized.startswith("skill worker "):
            body = raw[len("skill worker "):].strip()
            name, worker = self._split_name_value(body)
            if not name or not worker:
                return "Usage : skill worker yaml developer"
            try:
                skill = self.assign_worker(
                    name,
                    worker,
                )
            except (KeyError, ValueError) as exc:
                return str(exc)
            return (
                f"{skill['name']} — worker ajouté : {worker}."
            )

        if normalized.startswith("skill source "):
            body = raw[len("skill source "):].strip()
            parts = body.split()
            if len(parts) < 2:
                return "Usage : skill source yaml A https://example.com/docs"
            name = parts[0]
            if len(parts) >= 3 and parts[1].upper() in self.SOURCE_TIERS:
                tier = parts[1].upper()
                url = parts[2]
            else:
                tier = "C"
                url = parts[1]
            try:
                skill = self.add_source(
                    name,
                    url,
                    tier=tier,
                )
            except (KeyError, ValueError) as exc:
                return str(exc)
            return (
                f"{skill['name']} — source {tier} ajoutée."
            )

        if normalized.startswith("skill note "):
            body = raw[len("skill note "):].strip()
            name, note = self._split_name_value(body)
            if not name or not note:
                return "Usage : skill note yaml : les listes utilisent un tiret"
            try:
                skill = self.add_note(
                    name,
                    note,
                )
            except (KeyError, ValueError) as exc:
                return str(exc)
            return f"{skill['name']} — note ajoutée."

        if normalized.startswith("skill require "):
            reference = self._mission_ref(raw)
            if reference is None:
                return "Usage : skill require M-043 yaml, home_assistant"
            if self.manager is None:
                return "Skill Registry non relié au Manager."
            mission = self.manager.missions.resolve(
                reference
            )
            if mission is None:
                return f"Mission {reference} introuvable."

            match = self.MISSION_RE.search(raw)
            remainder = (
                raw[match.end():]
                if match is not None
                else ""
            ).strip(" :,-")
            skills = self._parse_skill_list(
                remainder
            )
            if not skills:
                return "Précise au moins une compétence."
            merged = self.set_mission_requirements(
                mission,
                skills,
            )
            return (
                f"{mission.human_id} — compétences requises : "
                + ", ".join(merged)
                + "."
            )

        if normalized.startswith("skill requirements"):
            reference = self._mission_ref(raw)
            if reference is None:
                return "Usage : skill requirements M-043"
            if self.manager is None:
                return "Skill Registry non relié au Manager."
            mission = self.manager.missions.resolve(
                reference
            )
            if mission is None:
                return f"Mission {reference} introuvable."
            return self.requirements_summary(
                mission
            )

        if normalized.startswith("skill "):
            name = raw[len("skill "):].strip()
            if name:
                return self.skill_summary(name)

        return None
