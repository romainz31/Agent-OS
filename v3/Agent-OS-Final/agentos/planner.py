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
        r"[A-Za-z0-9_.-]+\."
        r"[A-Za-z0-9_-]+)"
    )

    def __init__(
        self,
        llm: LLM,
    ) -> None:

        self.llm = llm

    # =========================================================
    # JSON CLEANING
    # =========================================================

    @staticmethod
    def _clean_json(
        raw: str,
    ) -> str:

        text = raw.strip()

        if text.startswith(
            "```"
        ):

            first_newline = (
                text.find("\n")
            )

            if first_newline != -1:

                text = text[
                    first_newline + 1:
                ]

            if (
                text
                .rstrip()
                .endswith("```")
            ):

                text = (
                    text
                    .rstrip()[:-3]
                )

        return text.strip()

    # =========================================================
    # EXPLICIT FILES
    # =========================================================

    def _explicit_files(
        self,
        message: str,
    ) -> list[str]:

        matches = (
            self.FILE_RE.findall(
                message.replace(
                    "\\",
                    "/",
                )
            )
        )

        files = []

        for path in matches:

            path = path.strip(
                "`'\".,;:()[]{} "
            )

            if (
                path
                and path not in files
            ):

                files.append(
                    path
                )

        return files

    # =========================================================
    # SIMPLE LOCAL DEVELOPMENT
    # =========================================================

    def _simple_local_development(
        self,
        *,
        message: str,
        initial_worker: str,
    ) -> list[PlanStep] | None:

        """
        Cas déterministe :

        Si l'utilisateur demande directement à Developer
        de travailler sur UN fichier explicitement nommé,
        inutile de laisser le LLM inventer 2 Developers,
        un Researcher ou plusieurs Testers.

        Pipeline imposé :

        Developer -> Tester
        """

        if (
            initial_worker
            != "developer"
        ):

            return None

        files = self._explicit_files(
            message
        )

        if len(files) != 1:

            return None

        target = files[0]

        return [
            PlanStep(
                title=(
                    f"Modifier {target}"
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
                    "Tester réellement le fichier "
                    f"{target} après la modification "
                    "demandée par l'utilisateur."
                ),
                worker="tester",
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

        steps: list[
            PlanStep
        ] = []

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

            dependencies = (
                item.get(
                    "depends_on",
                    [],
                )
            )

            if (
                not title
                or not description
                or worker
                not in self.ALLOWED_WORKERS
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
                    or dependency
                    >= current_index
                ):

                    continue

                if dependency not in (
                    cleaned_dependencies
                ):

                    cleaned_dependencies.append(
                        dependency
                    )

            steps.append(
                PlanStep(
                    title=title,
                    description=description,
                    worker=worker,
                    depends_on=(
                        cleaned_dependencies
                    ),
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
    # REMOVE USELESS RESEARCH
    # =========================================================

    def _remove_useless_local_research(
        self,
        steps: list[PlanStep],
        message: str,
    ) -> list[PlanStep]:

        if not self._explicit_files(
            message
        ):

            return steps

        if not any(
            step.worker
            == "developer"
            for step
            in steps
        ):

            return steps

        useless_markers = (
            "emplacement",
            "localiser",
            "localisation",
            "trouver le fichier",
            "chercher le fichier",
            "rechercher le fichier",
            "trouver l'emplacement",
            "trouver l’emplacement",
        )

        removed_indexes = set()

        for index, step in enumerate(
            steps
        ):

            if (
                step.worker
                != "researcher"
            ):

                continue

            text = (
                step.title
                + " "
                + step.description
            ).lower()

            if any(
                marker in text
                for marker
                in useless_markers
            ):

                removed_indexes.add(
                    index
                )

        if not removed_indexes:

            return steps

        old_to_new = {}
        result = []

        for old_index, step in enumerate(
            steps
        ):

            if old_index in (
                removed_indexes
            ):

                continue

            old_to_new[
                old_index
            ] = len(
                result
            )

            result.append(
                PlanStep(
                    title=step.title,
                    description=(
                        step.description
                    ),
                    worker=step.worker,
                    depends_on=[],
                )
            )

        for old_index, step in enumerate(
            steps
        ):

            if old_index in (
                removed_indexes
            ):

                continue

            new_index = (
                old_to_new[
                    old_index
                ]
            )

            dependencies = []

            for dependency in (
                step.depends_on
            ):

                if dependency in (
                    removed_indexes
                ):

                    continue

                if dependency not in (
                    old_to_new
                ):

                    continue

                converted = (
                    old_to_new[
                        dependency
                    ]
                )

                if converted not in (
                    dependencies
                ):

                    dependencies.append(
                        converted
                    )

            result[
                new_index
            ].depends_on = (
                dependencies
            )

        return result

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
            for index, step
            in enumerate(result)
            if step.worker
            == "developer"
        ]

        for developer_index in (
            developer_indexes
        ):

            tester_exists = False

            for step in result:

                if (
                    step.worker
                    == "tester"
                    and developer_index
                    in step.depends_on
                ):

                    tester_exists = True
                    break

            if tester_exists:

                continue

            if len(result) >= 8:

                break

            developer_step = (
                result[
                    developer_index
                ]
            )

            result.append(
                PlanStep(
                    title=(
                        "Vérifier le travail"
                    ),
                    description=(
                        "Tester réellement "
                        "le résultat produit "
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

        if (
            initial_worker
            == "developer"
        ):

            return [
                PlanStep(
                    title=(
                        "Réaliser la modification"
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
                        "Tester réellement "
                        "le travail réalisé "
                        "par le Developer."
                    ),
                    worker="tester",
                    depends_on=[
                        0
                    ],
                ),
            ]

        if (
            initial_worker
            == "researcher"
        ):

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
                        "Analyser les résultats"
                    ),
                    description=(
                        "Analyser les résultats "
                        "de recherche et produire "
                        "une synthèse exploitable."
                    ),
                    worker="ai_worker",
                    depends_on=[
                        0
                    ],
                ),
            ]

        if (
            initial_worker
            == "tester"
        ):

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

        # =====================================================
        # DETERMINISTIC SIMPLE CASE
        # =====================================================

        simple = (
            self._simple_local_development(
                message=message,
                initial_worker=(
                    initial_worker
                ),
            )
        )

        if simple is not None:

            return simple

        # =====================================================
        # COMPLEX CASE -> LLM PLANNER
        # =====================================================

        prompt = f"""
Tu es le Planner d'Agent-OS.

Ton travail est UNIQUEMENT de découper une mission
en tâches concrètes pour les workers.

DEMANDE UTILISATEUR :

{message}

WORKER INITIAL SUGGÉRÉ :

{initial_worker}

WORKERS DISPONIBLES :

researcher
- recherche réellement des informations sur Internet.
- ne sert pas à trouver des fichiers locaux déjà nommés.

developer
- lit, crée et modifie les fichiers du workspace.
- une opération sur un fichier doit si possible
  être réalisée en UNE seule tâche Developer.

tester
- teste réellement le travail du Developer.

ai_worker
- analyse, réfléchit, rédige et synthétise.

RÈGLES :

1. Utilise uniquement ces workers.

2. Ne réalise jamais toi-même la mission.

3. Crée uniquement les étapes nécessaires.

4. Maximum 8 étapes.

5. Une dépendance référence l'index
   d'une étape précédente.

6. La première étape a l'index 0.

7. Ne découpe PAS artificiellement une modification
   de fichier en plusieurs tâches Developer.

8. "Lire le fichier" puis "modifier le fichier"
   ne doivent PAS être deux tâches séparées.
   Developer sait lire le fichier lui-même.

9. Un Developer doit normalement être suivi
   par un Tester.

10. Si le chemin d'un fichier est fourni,
    ne crée pas de Researcher pour le trouver.

11. Researcher sert uniquement pour une vraie
    recherche Internet ou documentaire.

12. Ne crée jamais une tâche pour demander
    l'autorisation utilisateur.

13. Retourne uniquement du JSON valide.

FORMAT EXACT :

[
  {{
    "title": "Titre court",
    "description": "Travail exact",
    "worker": "developer",
    "depends_on": []
  }}
]
"""

        try:

            raw = self.llm.chat(
                prompt,
                system=(
                    "Tu es le Planner "
                    "d'Agent-OS. "
                    "Retourne uniquement "
                    "du JSON valide."
                ),
            )

            cleaned = (
                self._clean_json(
                    raw
                )
            )

            parsed = json.loads(
                cleaned
            )

            if isinstance(
                parsed,
                dict,
            ):

                parsed = (
                    parsed.get(
                        "steps",
                        [],
                    )
                )

            steps = (
                self._validate(
                    parsed
                )
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

        steps = (
            self._remove_useless_local_research(
                steps,
                message,
            )
        )

        steps = (
            self._ensure_workflow_rules(
                steps
            )
        )

        return steps