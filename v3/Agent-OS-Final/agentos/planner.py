from __future__ import annotations

import json
import re

from dataclasses import (
    asdict,
    dataclass,
)

from agentos.llm import (
    LLM,
    LLMError,
)


@dataclass
class PlanStep:
    title: str
    description: str
    worker: str
    depends_on: list[int]

    def to_dict(
        self,
    ):
        return asdict(
            self
        )


class Planner:
    ALLOWED_WORKERS = {
        "researcher",
        "developer",
        "tester",
        "ai_worker",
    }

    FILE_RE = re.compile(
        r"(?:(?:workspace/)?"
        r"(?:[A-Za-z0-9_.-]+/)*"
        r"[A-Za-z0-9_.-]+"
        r"\.[A-Za-z][A-Za-z0-9_-]*)"
    )

    EXECUTABLE_MARKERS = (
        ".exe",
        "exécutable",
        "executable",
        "application windows",
        "programme windows",
    )

    CREATE_MARKERS = (
        "crée",
        "cree",
        "créer",
        "creer",
        "fabrique",
        "fabriquer",
        "génère",
        "genere",
        "générer",
        "generer",
    )

    MODIFY_MARKERS = (
        "modifie",
        "modifier",
        "corrige",
        "corriger",
        "ajoute",
        "ajouter",
        "remplace",
        "remplacer",
    )

    def __init__(
        self,
        llm: LLM,
    ) -> None:
        self.llm = llm

    # =========================================================
    # JSON
    # =========================================================

    @staticmethod
    def _clean_json(
        raw: str,
    ) -> str:
        text = raw.strip()

        if text.startswith(
            "```"
        ):
            first_newline = text.find(
                "\n"
            )

            if first_newline != -1:
                text = text[
                    first_newline + 1:
                ]

            if text.rstrip().endswith(
                "```"
            ):
                text = text.rstrip()[:-3]

        return text.strip()

    # =========================================================
    # FILES
    # =========================================================

    def _explicit_files(
        self,
        message: str,
    ) -> list[str]:
        matches = self.FILE_RE.findall(
            message.replace(
                "\\",
                "/",
            )
        )

        files = []

        for path in matches:
            clean = path.strip(
                "`'\".,;:()[]{} "
            )

            if clean and clean not in files:
                files.append(
                    clean
                )

        return files

    @classmethod
    def _is_executable_creation(
        cls,
        message: str,
        initial_worker: str,
    ) -> bool:
        if initial_worker != "developer":
            return False

        lower = message.lower()

        has_executable = any(
            marker in lower
            for marker in cls.EXECUTABLE_MARKERS
        )

        has_create = any(
            marker in lower
            for marker in cls.CREATE_MARKERS
        )

        has_modify = any(
            marker in lower
            for marker in cls.MODIFY_MARKERS
        )

        return (
            has_executable
            and has_create
            and not has_modify
        )

    # =========================================================
    # SIMPLE ARTIFACT — V5.5
    # =========================================================

    def _simple_artifact_development(
        self,
        *,
        message: str,
        initial_worker: str,
    ) -> list[PlanStep] | None:
        if not self._is_executable_creation(
            message,
            initial_worker,
        ):
            return None

        return [
            PlanStep(
                title=(
                    "Créer l'exécutable Windows"
                ),
                description=(
                    "Créer réellement l'exécutable demandé. "
                    "Si aucun nom de fichier complet n'est fourni, "
                    "choisir automatiquement un nom raisonnable "
                    "dans le workspace. "
                    "Demande utilisateur : "
                    + message
                ),
                worker="developer",
                depends_on=[],
            ),
            PlanStep(
                title=(
                    "Vérifier l'exécutable Windows"
                ),
                description=(
                    "Tester réellement l'exécutable produit par le Developer : "
                    "vérifier qu'il s'agit d'un vrai binaire Windows, "
                    "puis exécuter son self-test borné."
                ),
                worker="tester",
                depends_on=[
                    0
                ],
            ),
        ]

    # =========================================================
    # SIMPLE DEVELOPMENT
    # =========================================================

    def _simple_local_development(
        self,
        *,
        message: str,
        initial_worker: str,
    ) -> list[PlanStep] | None:
        if initial_worker != "developer":
            return None

        files = self._explicit_files(
            message
        )

        if len(files) != 1:
            return None

        target = files[0]
        lower = message.lower()

        creating = any(
            marker in lower
            for marker in self.CREATE_MARKERS
        )

        verb = (
            "Créer"
            if creating
            else "Modifier"
        )

        return [
            PlanStep(
                title=(
                    f"{verb} {target}"
                ),
                description=message,
                worker="developer",
                depends_on=[],
            ),
            PlanStep(
                title=(
                    f"Vérifier {target}"
                ),
                description=(
                    "Tester réellement "
                    f"le fichier {target} "
                    "après le travail du Developer."
                ),
                worker="tester",
                depends_on=[
                    0
                ],
            ),
        ]

    # =========================================================
    # SIMPLE RESEARCH
    # =========================================================

    def _simple_research(
        self,
        *,
        message: str,
        initial_worker: str,
    ) -> list[PlanStep] | None:
        if initial_worker != "researcher":
            return None

        if self._explicit_files(
            message
        ):
            return None

        return [
            PlanStep(
                title=(
                    "Effectuer la recherche"
                ),
                description=message,
                worker="researcher",
                depends_on=[],
            ),
            PlanStep(
                title=(
                    "Synthétiser les résultats"
                ),
                description=(
                    "À partir uniquement des résultats "
                    "réels obtenus par le Researcher, "
                    "répondre clairement à la demande "
                    "initiale de l'utilisateur. "
                    "Ne pas inventer de sources."
                ),
                worker="ai_worker",
                depends_on=[
                    0
                ],
            ),
        ]

    # =========================================================
    # VALIDATION
    # =========================================================

    def _validate(
        self,
        raw_steps,
    ) -> list[PlanStep]:
        if not isinstance(
            raw_steps,
            list,
        ):
            raise ValueError(
                "Le plan doit être une liste."
            )

        steps: list[PlanStep] = []

        for item in raw_steps:
            if not isinstance(
                item,
                dict,
            ):
                continue

            title = str(
                item.get(
                    "title",
                    "",
                )
            ).strip()
            description = str(
                item.get(
                    "description",
                    "",
                )
            ).strip()
            worker = str(
                item.get(
                    "worker",
                    "",
                )
            ).strip()
            dependencies = item.get(
                "depends_on",
                [],
            )

            if (
                not title
                or not description
                or worker not in self.ALLOWED_WORKERS
            ):
                continue

            if not isinstance(
                dependencies,
                list,
            ):
                dependencies = []

            current_index = len(
                steps
            )
            cleaned_dependencies = []

            for dependency in dependencies:
                if not isinstance(
                    dependency,
                    int,
                ):
                    continue

                if (
                    dependency < 0
                    or dependency >= current_index
                ):
                    continue

                if dependency not in cleaned_dependencies:
                    cleaned_dependencies.append(
                        dependency
                    )

            steps.append(
                PlanStep(
                    title=title,
                    description=description,
                    worker=worker,
                    depends_on=cleaned_dependencies,
                )
            )

            if len(steps) >= 8:
                break

        if not steps:
            raise ValueError(
                "Aucune étape valide."
            )

        return steps

    # =========================================================
    # WORKFLOW RULES
    # =========================================================

    @staticmethod
    def _ensure_workflow_rules(
        steps: list[PlanStep],
    ) -> list[PlanStep]:
        result = list(
            steps
        )

        developer_indexes = [
            index
            for index, step in enumerate(
                result
            )
            if step.worker == "developer"
        ]

        for developer_index in developer_indexes:
            tester_exists = False

            for step in result:
                if (
                    step.worker == "tester"
                    and developer_index in step.depends_on
                ):
                    tester_exists = True
                    break

            if tester_exists:
                continue

            if len(result) >= 8:
                break

            developer_step = result[
                developer_index
            ]

            result.append(
                PlanStep(
                    title=(
                        "Vérifier le travail"
                    ),
                    description=(
                        "Tester réellement le résultat produit "
                        "par le Developer pour : "
                        + developer_step.description
                    ),
                    worker="tester",
                    depends_on=[
                        developer_index
                    ],
                )
            )

        return result

    # =========================================================
    # FALLBACK
    # =========================================================

    @staticmethod
    def fallback(
        message: str,
        initial_worker: str,
    ) -> list[PlanStep]:
        if initial_worker == "developer":
            return [
                PlanStep(
                    title=(
                        "Réaliser le travail"
                    ),
                    description=message,
                    worker="developer",
                    depends_on=[],
                ),
                PlanStep(
                    title=(
                        "Tester le résultat"
                    ),
                    description=(
                        "Tester réellement le travail "
                        "réalisé par le Developer."
                    ),
                    worker="tester",
                    depends_on=[
                        0
                    ],
                ),
            ]

        if initial_worker == "researcher":
            return [
                PlanStep(
                    title=(
                        "Effectuer la recherche"
                    ),
                    description=message,
                    worker="researcher",
                    depends_on=[],
                ),
                PlanStep(
                    title=(
                        "Synthétiser les résultats"
                    ),
                    description=(
                        "Analyser les résultats réels du Researcher "
                        "et produire la réponse finale."
                    ),
                    worker="ai_worker",
                    depends_on=[
                        0
                    ],
                ),
            ]

        if initial_worker == "tester":
            return [
                PlanStep(
                    title=(
                        "Effectuer les tests"
                    ),
                    description=message,
                    worker="tester",
                    depends_on=[],
                )
            ]

        return [
            PlanStep(
                title=(
                    "Traiter la demande"
                ),
                description=message,
                worker="ai_worker",
                depends_on=[],
            )
        ]

    # =========================================================
    # PLAN
    # =========================================================

    def plan(
        self,
        *,
        message: str,
        initial_worker: str,
    ) -> list[PlanStep]:
        artifact_dev = self._simple_artifact_development(
            message=message,
            initial_worker=initial_worker,
        )

        if artifact_dev is not None:
            return artifact_dev

        simple_dev = self._simple_local_development(
            message=message,
            initial_worker=initial_worker,
        )

        if simple_dev is not None:
            return simple_dev

        simple_research = self._simple_research(
            message=message,
            initial_worker=initial_worker,
        )

        if simple_research is not None:
            return simple_research

        prompt = f"""
Tu es le Planner d'Agent-OS.

Tu découpes uniquement les missions réellement complexes.

DEMANDE :

{message}

WORKER INITIAL :

{initial_worker}

WORKERS DISPONIBLES :

researcher
- recherche des informations réelles sur Internet.

developer
- travaille UNIQUEMENT sur de vrais fichiers du workspace.
- peut créer des artefacts locaux pris en charge par Agent-OS.
- ne sert jamais à rédiger une réponse textuelle simple.

tester
- teste de vrais fichiers, du code ou des artefacts produits.
- ne teste jamais une simple synthèse textuelle.

ai_worker
- analyse, synthétise et rédige des réponses.

RÈGLES :

1. Maximum 8 étapes.
2. Utilise uniquement les workers disponibles.
3. Developer est réservé aux opérations réelles sur des fichiers/artefacts.
4. Tester est réservé à la vérification de fichiers, code ou artefacts.
5. Pour une recherche simple : Researcher -> AIWorker.
6. Ne crée jamais Developer pour rédiger un rapport si aucun fichier n'est demandé.
7. Ne crée jamais Tester pour vérifier une simple réponse textuelle.
8. Si le chemin d'un fichier est déjà fourni, ne crée pas Researcher pour le chercher.
9. Pour la création d'un artefact dont le nom n'est pas donné, Developer peut choisir un nom raisonnable.
10. Les approbations utilisateur ne sont jamais des tâches.
11. Retourne uniquement du JSON valide.

FORMAT :

[
  {{
    "title": "Titre",
    "description": "Travail exact",
    "worker": "researcher",
    "depends_on": []
  }}
]
"""

        try:
            raw = self.llm.chat(
                prompt,
                system=(
                    "Tu es le Planner d'Agent-OS. "
                    "Retourne uniquement du JSON valide."
                ),
            )

            cleaned = self._clean_json(
                raw
            )
            parsed = json.loads(
                cleaned
            )

            if isinstance(
                parsed,
                dict,
            ):
                parsed = parsed.get(
                    "steps",
                    [],
                )

            steps = self._validate(
                parsed
            )

        except (
            LLMError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            steps = self.fallback(
                message,
                initial_worker,
            )

        return self._ensure_workflow_rules(
            steps
        )
