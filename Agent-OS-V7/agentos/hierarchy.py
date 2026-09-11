from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any


class MissionHierarchy:
    """Arbre de missions Agent-OS V5.1.

    Les relations sont stockées dans ``mission.metadata`` afin de rester
    compatibles avec les JSON de missions existants :
    - parent_mission_id / parent_human_id ;
    - root_mission_id ;
    - hierarchy_depth ;
    - depends_on_mission_ids ;
    - hierarchy_priority_explicit / hierarchy_deadline_explicit.

    Une sous-mission est une vraie Mission Agent-OS avec son propre plan et ses
    propres tâches. Elle passe donc naturellement par le backlog V5.0.
    """

    MISSION_RE = re.compile(
        r"\bM-\d{1,6}\b",
        flags=re.IGNORECASE,
    )

    SUBMISSION_PREFIXES = (
        "sous-mission",
        "sous mission",
        "sub-mission",
        "sub mission",
        "child mission",
    )

    TREE_MARKERS = (
        "mission tree",
        "arbre mission",
        "arbre de mission",
        "arbre des missions",
        "mission arbre",
        "tree mission",
    )

    CHILD_MARKERS = (
        "enfants mission",
        "sous-missions",
        "sous missions",
        "children mission",
    )

    def __init__(
        self,
        manager,
        autonomy=None,
    ) -> None:
        self.manager = manager
        self.autonomy = autonomy

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
        value = "".join(
            char
            for char in value
            if not unicodedata.combining(char)
        )
        return " ".join(
            value.lower().strip().split()
        )

    @classmethod
    def _refs(
        cls,
        text: str,
    ) -> list[str]:
        result: list[str] = []

        for match in cls.MISSION_RE.finditer(
            str(text or "")
        ):
            raw = match.group(0).upper()
            number = int(
                raw.split("-")[1]
            )
            ref = f"M-{number:03d}"
            if ref not in result:
                result.append(ref)

        return result

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

    def _mission(
        self,
        reference: str,
    ):
        return self.manager.missions.resolve(
            str(reference or "")
        )

    # =========================================================
    # RELATIONSHIPS
    # =========================================================

    def parent_of(
        self,
        mission,
    ):
        metadata = self._metadata(
            mission
        )
        parent_id = metadata.get(
            "parent_mission_id"
        )
        if not parent_id:
            return None
        return self.manager.missions.get(
            str(parent_id)
        )

    def children_of(
        self,
        mission,
    ) -> list:
        result = []

        for candidate in self.manager.missions.list():
            metadata = self._metadata(
                candidate
            )
            if (
                metadata.get("parent_mission_id")
                == mission.id
            ):
                result.append(candidate)

        result.sort(
            key=lambda item: item.created_at
        )
        return result

    def descendants_of(
        self,
        mission,
    ) -> list:
        result = []
        stack = list(
            reversed(
                self.children_of(mission)
            )
        )

        while stack:
            current = stack.pop()
            result.append(current)
            children = self.children_of(
                current
            )
            stack.extend(
                reversed(children)
            )

        return result

    def root_of(
        self,
        mission,
    ):
        current = mission
        seen: set[str] = set()

        while current is not None:
            if current.id in seen:
                break
            seen.add(current.id)
            parent = self.parent_of(
                current
            )
            if parent is None:
                return current
            current = parent

        return mission

    def roots(
        self,
        *,
        only_with_children: bool = True,
    ) -> list:
        result = []

        for mission in self.manager.missions.list():
            if self.parent_of(mission) is not None:
                continue
            if (
                only_with_children
                and not self.children_of(mission)
            ):
                continue
            result.append(mission)

        return result

    # =========================================================
    # POLICY INHERITANCE
    # =========================================================

    def effective_policy(
        self,
        mission,
    ) -> dict[str, Any]:
        if self.autonomy is None:
            metadata = self._metadata(
                mission
            )
            return {
                "priority": metadata.get(
                    "priority",
                    "normal",
                ),
                "deadline": metadata.get(
                    "deadline"
                ),
            }

        own = dict(
            self.autonomy.policy_for(
                mission
            )
        )
        metadata = self._metadata(
            mission
        )
        parent = self.parent_of(
            mission
        )

        if parent is None:
            return own

        parent_policy = self.effective_policy(
            parent
        )

        if not bool(
            metadata.get(
                "hierarchy_priority_explicit",
                False,
            )
        ):
            own["priority"] = parent_policy.get(
                "priority",
                own.get("priority", "normal"),
            )

        if not bool(
            metadata.get(
                "hierarchy_deadline_explicit",
                False,
            )
        ):
            own["deadline"] = parent_policy.get(
                "deadline",
                own.get("deadline"),
            )

        return own

    # =========================================================
    # TASK / MISSION DEPENDENCIES
    # =========================================================

    def _terminal_task_ids(
        self,
        mission,
    ) -> list[str]:
        mission_task_ids = [
            task_id
            for task_id in mission.task_ids
            if self.manager.tasks.get(task_id)
            is not None
        ]
        mission_set = set(
            mission_task_ids
        )

        referenced: set[str] = set()

        for task_id in mission_task_ids:
            task = self.manager.tasks.get(
                task_id
            )
            if task is None:
                continue
            for dependency_id in list(
                task.depends_on
            ):
                if dependency_id in mission_set:
                    referenced.add(
                        dependency_id
                    )

        terminal = [
            task_id
            for task_id in mission_task_ids
            if task_id not in referenced
        ]

        return terminal or mission_task_ids[-1:]

    def _external_dependency_tasks(
        self,
        dependencies: list,
    ) -> list[str]:
        result: list[str] = []

        for mission in dependencies:
            for task_id in self._terminal_task_ids(
                mission
            ):
                if task_id not in result:
                    result.append(task_id)

        return result

    # =========================================================
    # CREATE CHILD MISSION
    # =========================================================

    def _initial_route(
        self,
        description: str,
    ) -> tuple[str, str]:
        try:
            route = self.manager.router.route(
                description
            )
        except Exception:
            return (
                "ai_worker",
                "hierarchy_default",
            )

        worker = getattr(
            route,
            "worker",
            None,
        )
        kind = str(
            getattr(
                route,
                "kind",
                "",
            )
        )

        if kind == "task" and worker:
            return (
                str(worker),
                str(
                    getattr(
                        route,
                        "reason",
                        "hierarchy_route",
                    )
                ),
            )

        return (
            "ai_worker",
            "sous-mission sans worker explicite",
        )

    def create_sub_mission(
        self,
        *,
        parent_reference: str,
        description: str,
        depends_on_references: list[str] | None = None,
    ):
        parent = self._mission(
            parent_reference
        )
        if parent is None:
            raise ValueError(
                f"Mission {parent_reference} introuvable."
            )

        description = " ".join(
            str(description or "")
            .strip()
            .split()
        )
        if not description:
            raise ValueError(
                "La sous-mission n'a pas de description."
            )

        dependencies = []
        for reference in (
            depends_on_references
            or []
        ):
            dependency = self._mission(
                reference
            )
            if dependency is None:
                raise ValueError(
                    f"Dépendance {reference} introuvable."
                )
            if dependency.id not in {
                item.id
                for item in dependencies
            }:
                dependencies.append(
                    dependency
                )

        parent_metadata = self._metadata(
            parent
        )
        parent_policy = self.effective_policy(
            parent
        )
        root = self.root_of(
            parent
        )

        explicit_priority = None
        explicit_deadline = None

        if self.autonomy is not None:
            explicit_priority = (
                self.autonomy
                ._priority_from_text(
                    description
                )
            )
            explicit_deadline = (
                self.autonomy
                .parse_deadline(
                    description
                )
            )

        initial_worker, router_reason = (
            self._initial_route(
                description
            )
        )

        metadata: dict[str, Any] = {
            "router_reason": router_reason,
            "initial_worker": initial_worker,
            "auto_repair": True,
            "parent_mission_id": parent.id,
            "parent_human_id": parent.human_id,
            "root_mission_id": root.id,
            "root_human_id": root.human_id,
            "hierarchy_depth": int(
                parent_metadata.get(
                    "hierarchy_depth",
                    0,
                )
                or 0
            ) + 1,
            "depends_on_mission_ids": [
                item.id
                for item in dependencies
            ],
            "depends_on_mission_refs": [
                item.human_id
                for item in dependencies
            ],
            "hierarchy_priority_explicit": (
                explicit_priority is not None
            ),
            "hierarchy_deadline_explicit": (
                explicit_deadline is not None
            ),
            "hierarchy_created_at": self._now(),
            "priority": (
                explicit_priority
                or parent_policy.get(
                    "priority",
                    "normal",
                )
            ),
            "deadline": (
                explicit_deadline.isoformat()
                if explicit_deadline is not None
                else parent_policy.get(
                    "deadline"
                )
            ),
            "autonomy_enabled": True,
        }

        mission = self.manager.missions.create(
            title=(
                description
                if len(description) <= 90
                else description[:87].rstrip()
                + "..."
            ),
            description=description,
            metadata=metadata,
        )

        try:
            plan = self.manager.planner.plan(
                message=description,
                initial_worker=initial_worker,
            )

            created_task_ids: list[str] = []
            plan_dicts = [
                step.to_dict()
                for step in plan
            ]
            external_dependencies = (
                self._external_dependency_tasks(
                    dependencies
                )
            )

            for step_index, step in enumerate(
                plan
            ):
                dependency_ids: list[str] = []

                for dependency_index in list(
                    step.depends_on
                ):
                    if (
                        0
                        <= dependency_index
                        < len(created_task_ids)
                    ):
                        dependency_ids.append(
                            created_task_ids[
                                dependency_index
                            ]
                        )

                # Les étapes racines de la sous-mission attendent les missions
                # externes demandées. Les dépendances internes prennent ensuite
                # naturellement le relais.
                if not dependency_ids:
                    dependency_ids.extend(
                        external_dependencies
                    )

                dependency_ids = list(
                    dict.fromkeys(
                        dependency_ids
                    )
                )

                task = self.manager.tasks.create(
                    title=step.title,
                    description=step.description,
                    worker=step.worker,
                    depends_on=dependency_ids,
                    metadata={
                        "mission_id": mission.id,
                        "plan_step": step_index,
                        "original_message": description,
                        "user_original_message": description,
                        "router_reason": router_reason,
                        "auto_repair_enabled": (
                            step.worker
                            == "tester"
                        ),
                        "repair_attempt": 0,
                        "hierarchy_parent_mission_id": (
                            parent.id
                        ),
                        "hierarchy_root_mission_id": (
                            root.id
                        ),
                    },
                )
                created_task_ids.append(
                    task.id
                )

            self.manager.missions.attach_plan(
                mission.id,
                plan=plan_dicts,
                task_ids=created_task_ids,
            )

            # Applique les éventuelles règles explicites présentes dans la
            # description sans écraser l'héritage déjà enregistré.
            if self.autonomy is not None:
                self.autonomy.apply_creation_policy(
                    mission,
                    description,
                )

                # apply_creation_policy ne connaît pas la notion d'héritage ;
                # on restaure donc les marqueurs structurants après son passage.
                current = self._metadata(
                    mission
                )
                current.update({
                    "hierarchy_priority_explicit": (
                        explicit_priority is not None
                    ),
                    "hierarchy_deadline_explicit": (
                        explicit_deadline is not None
                    ),
                })
                self.manager.missions.set_status(
                    mission.id,
                    mission.status,
                    metadata_patch=current,
                )

            self.manager.missions.set_status(
                parent.id,
                parent.status,
                metadata_patch={
                    "hierarchy_has_children": True,
                    "hierarchy_updated_at": self._now(),
                },
            )

            for task_id in created_task_ids:
                self.manager.engine.submit(
                    task_id
                )

            if hasattr(
                self.manager.engine,
                "wake_scheduler",
            ):
                self.manager.engine.wake_scheduler()

            return self.manager.missions.get(
                mission.id
            )

        except Exception as exc:
            self.manager.missions.set_status(
                mission.id,
                "failed",
                metadata_patch={
                    "planning_error": str(exc),
                },
            )
            raise

    # =========================================================
    # AGGREGATED STATUS / PROGRESS
    # =========================================================

    def _tree_nodes(
        self,
        root,
    ) -> list:
        return [
            root,
            *self.descendants_of(root),
        ]

    def aggregate_progress(
        self,
        mission,
    ) -> dict[str, int]:
        completed = 0
        total = 0

        for node in self._tree_nodes(
            mission
        ):
            self.manager.missions.refresh(
                node,
                self.manager.tasks,
            )
            node_completed, node_total = (
                self.manager.missions.progress(
                    node,
                    self.manager.tasks,
                )
            )
            completed += int(node_completed)
            total += int(node_total)

        return {
            "completed": completed,
            "total": total,
        }

    def aggregate_status(
        self,
        mission,
    ) -> str:
        statuses: list[str] = []

        for node in self._tree_nodes(
            mission
        ):
            self.manager.missions.refresh(
                node,
                self.manager.tasks,
            )
            statuses.append(
                str(node.status)
            )

        if any(
            status in {
                "failed",
                "rejected",
            }
            for status in statuses
        ):
            return "attention"

        if any(
            status == "waiting_approval"
            for status in statuses
        ):
            return "waiting_approval"

        if any(
            status == "running"
            for status in statuses
        ):
            return "running"

        if any(
            status in {
                "planning",
                "queued",
            }
            for status in statuses
        ):
            return "queued"

        if any(
            status == "paused"
            for status in statuses
        ):
            return "paused"

        if statuses and all(
            status == "completed"
            for status in statuses
        ):
            return "completed"

        if statuses and all(
            status == "cancelled"
            for status in statuses
        ):
            return "cancelled"

        if statuses and all(
            status in {
                "completed",
                "cancelled",
            }
            for status in statuses
        ):
            return "partial"

        return statuses[0] if statuses else "unknown"

    # =========================================================
    # SERIALIZATION / DISPLAY
    # =========================================================

    def node_payload(
        self,
        mission,
        *,
        recursive: bool = True,
    ) -> dict[str, Any]:
        self.manager.missions.refresh(
            mission,
            self.manager.tasks,
        )
        completed, total = (
            self.manager.missions.progress(
                mission,
                self.manager.tasks,
            )
        )
        metadata = self._metadata(
            mission
        )
        policy = self.effective_policy(
            mission
        )

        payload = {
            "id": mission.id,
            "human_id": mission.human_id,
            "title": mission.title,
            "status": mission.status,
            "progress": {
                "completed": completed,
                "total": total,
            },
            "priority": policy.get(
                "priority",
                "normal",
            ),
            "deadline": policy.get(
                "deadline"
            ),
            "parent": metadata.get(
                "parent_human_id"
            ),
            "depth": int(
                metadata.get(
                    "hierarchy_depth",
                    0,
                )
                or 0
            ),
            "depends_on": list(
                metadata.get(
                    "depends_on_mission_refs",
                    [],
                )
                or []
            ),
        }

        if recursive:
            payload["children"] = [
                self.node_payload(
                    child,
                    recursive=True,
                )
                for child in self.children_of(
                    mission
                )
            ]

        return payload

    def tree_payload(
        self,
        reference: str,
    ) -> dict[str, Any]:
        mission = self._mission(
            reference
        )
        if mission is None:
            raise KeyError(
                f"Mission {reference} introuvable."
            )

        root = self.root_of(
            mission
        )
        progress = self.aggregate_progress(
            root
        )

        return {
            "root": self.node_payload(
                root,
                recursive=True,
            ),
            "aggregate_status": (
                self.aggregate_status(root)
            ),
            "aggregate_progress": progress,
            "mission_count": 1 + len(
                self.descendants_of(root)
            ),
        }

    def snapshot(self) -> dict[str, Any]:
        roots = self.roots(
            only_with_children=True
        )
        children = sum(
            len(self.descendants_of(root))
            for root in roots
        )
        return {
            "available": True,
            "trees": len(roots),
            "sub_missions": children,
            "roots": [
                root.human_id
                for root in roots
            ],
        }

    def tree_summary(
        self,
        reference: str,
    ) -> str:
        mission = self._mission(
            reference
        )
        if mission is None:
            return f"Mission {reference} introuvable."

        root = self.root_of(
            mission
        )
        progress = self.aggregate_progress(
            root
        )
        aggregate = self.aggregate_status(
            root
        )

        lines = [
            f"ARBRE DE MISSION — {root.human_id}",
            (
                f"État global : {aggregate} | "
                f"progression {progress['completed']}/{progress['total']} tâche(s)"
            ),
            "",
        ]

        def append_node(
            node,
            prefix: str,
            is_last: bool,
            is_root: bool = False,
        ) -> None:
            self.manager.missions.refresh(
                node,
                self.manager.tasks,
            )
            completed, total = (
                self.manager.missions.progress(
                    node,
                    self.manager.tasks,
                )
            )
            policy = self.effective_policy(
                node
            )
            metadata = self._metadata(
                node
            )

            connector = (
                ""
                if is_root
                else (
                    "└─ "
                    if is_last
                    else "├─ "
                )
            )

            line = (
                f"{prefix}{connector}{node.human_id} | {node.status} | "
                f"{completed}/{total} | priorité {policy.get('priority', 'normal')} | "
                f"{node.title}"
            )

            dependency_refs = list(
                metadata.get(
                    "depends_on_mission_refs",
                    [],
                )
                or []
            )
            if dependency_refs:
                line += (
                    " | après "
                    + ", ".join(
                        dependency_refs
                    )
                )

            lines.append(line)

            children = self.children_of(
                node
            )
            child_prefix = (
                prefix
                if is_root
                else prefix
                + (
                    "   "
                    if is_last
                    else "│  "
                )
            )

            for index, child in enumerate(
                children
            ):
                append_node(
                    child,
                    child_prefix,
                    index == len(children) - 1,
                    False,
                )

        append_node(
            root,
            "",
            True,
            True,
        )

        return "\n".join(lines)

    def roots_summary(self) -> str:
        roots = self.roots(
            only_with_children=True
        )
        if not roots:
            return "Aucun arbre de missions pour le moment."

        lines = [
            "ARBRES DE MISSIONS",
        ]

        for root in roots[:20]:
            progress = self.aggregate_progress(
                root
            )
            descendants = len(
                self.descendants_of(root)
            )
            lines.append(
                f"- {root.human_id} | {self.aggregate_status(root)} | "
                f"{progress['completed']}/{progress['total']} tâche(s) | "
                f"{descendants} sous-mission(s) | {root.title}"
            )

        return "\n".join(lines)

    def children_summary(
        self,
        reference: str,
    ) -> str:
        mission = self._mission(
            reference
        )
        if mission is None:
            return f"Mission {reference} introuvable."

        children = self.children_of(
            mission
        )
        if not children:
            return (
                f"{mission.human_id} n'a aucune sous-mission."
            )

        lines = [
            f"SOUS-MISSIONS DE {mission.human_id}",
        ]

        for child in children:
            self.manager.missions.refresh(
                child,
                self.manager.tasks,
            )
            completed, total = (
                self.manager.missions.progress(
                    child,
                    self.manager.tasks,
                )
            )
            lines.append(
                f"- {child.human_id} | {child.status} | "
                f"{completed}/{total} | {child.title}"
            )

        return "\n".join(lines)

    # =========================================================
    # COMMAND PARSING
    # =========================================================

    @classmethod
    def _is_submission_command(
        cls,
        normalized: str,
    ) -> bool:
        return any(
            normalized.startswith(prefix)
            for prefix in cls.SUBMISSION_PREFIXES
        )

    @classmethod
    def _description_from_command(
        cls,
        raw: str,
        refs: list[str],
    ) -> str:
        if ":" in raw:
            return raw.split(
                ":",
                1,
            )[1].strip()

        value = str(raw or "")

        # Retire le préfixe et les références utilisées pour le pilotage.
        normalized = cls._ascii(value)
        for prefix in cls.SUBMISSION_PREFIXES:
            if normalized.startswith(prefix):
                # Les préfixes n'ont que de l'ASCII après normalisation ; on
                # coupe approximativement le même nombre de caractères, puis
                # on nettoie le reste avec les regex ci-dessous.
                value = value[len(prefix):]
                break

        value = cls.MISSION_RE.sub(
            " ",
            value,
        )
        value = re.sub(
            r"\b(?:après|apres|after|dépend(?:s|re)?\s+de|depend(?:s)?\s+on)\b",
            " ",
            value,
            flags=re.IGNORECASE,
        )
        return " ".join(
            value.strip(" :-—").split()
        )

    def command_response(
        self,
        message: str,
    ) -> str | None:
        raw = str(message or "").strip()
        normalized = self._ascii(
            raw
        )
        refs = self._refs(
            raw
        )

        if normalized in {
            "mission tree",
            "arbre mission",
            "arbre de mission",
            "arbre des missions",
            "mission arbre",
            "tree mission",
        }:
            return self.roots_summary()

        if any(
            normalized.startswith(marker)
            for marker in self.TREE_MARKERS
        ):
            if not refs:
                return self.roots_summary()
            return self.tree_summary(
                refs[0]
            )

        if any(
            normalized.startswith(marker)
            for marker in self.CHILD_MARKERS
        ):
            if not refs:
                return (
                    "Précise la mission, par exemple : "
                    "sous-missions M-043"
                )
            return self.children_summary(
                refs[0]
            )

        if self._is_submission_command(
            normalized
        ):
            if not refs:
                return (
                    "Précise la mission parente. Exemple : "
                    "sous-mission M-043 : Recherche la documentation Home Assistant."
                )

            parent_ref = refs[0]
            dependency_refs: list[str] = []

            if re.search(
                r"\b(?:après|apres|after|dépend|depend)\b",
                raw,
                flags=re.IGNORECASE,
            ):
                dependency_refs = refs[1:]

            description = self._description_from_command(
                raw,
                refs,
            )

            if not description:
                return (
                    "Précise le travail de la sous-mission après ':' ."
                )

            try:
                child = self.create_sub_mission(
                    parent_reference=parent_ref,
                    description=description,
                    depends_on_references=(
                        dependency_refs
                    ),
                )
            except Exception as exc:
                return (
                    "Sous-mission non créée : "
                    + str(exc)
                )

            if child is None:
                return "Sous-mission non créée."

            policy = self.effective_policy(
                child
            )
            bits = [
                f"{child.human_id} créée sous {parent_ref}."
            ]

            if dependency_refs:
                bits.append(
                    "Dépend de : "
                    + ", ".join(
                        dependency_refs
                    )
                    + "."
                )

            bits.append(
                "Pilotage : priorité "
                + str(
                    policy.get(
                        "priority",
                        "normal",
                    )
                )
                + (
                    " | échéance "
                    + str(policy.get("deadline"))
                    if policy.get("deadline")
                    else ""
                )
                + "."
            )

            return "\n".join(bits)

        return None
