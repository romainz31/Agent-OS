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

    def to_dict(self):
        return asdict(self)


class Planner:

    ALLOWED_WORKERS = {
        "researcher",
        "developer",
        "tester",
        "ai_worker",
    }

    # Extension obligatoirement commencée par une lettre.
    #
    # hello.py       -> OUI
    # config.json    -> OUI
    # dashboard.yaml -> OUI
    # V3.4           -> NON
    # 1.25           -> NON
    FILE_RE = re.compile(
        r"(?:(?:workspace/)?"
        r"(?:[A-Za-z0-9_.-]+/)*"
        r"[A-Za-z0-9_.-]+"
        r"\.[A-Za-z][A-Za-z0-9_-]*)"
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

        if text.startswith("```"):

            first_newline = (
                text.find("\n")
            )

            if first_newline != -1:

                text = text[
                    first_newline + 1:
                ]

            if (
                text.rstrip()
                .endswith("```")
            ):

                text = (
                    text.rstrip()[:-3]
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
        Cas simple et déterministe :

        Une demande Developer portant sur exactement
        un fichier explicite donne :

        Developer -> Tester

        Le LLM ne décide pas du workflow.
        """

        if (
            initial_worker
            != "developer"
        ):

            return None

        files = (
            self._explicit_files(
                message
            )
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
                    "Tester réellement "
                    f"le fichier {target} "
                    "après la modification "
                    "demandée par l'utilisateur."
                ),
                worker="tester",
                depends_on=[0],
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
    # REMOVE USELESS LOCAL RESEARCH
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
            step.worker == "developer"
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
            ] = len(result)

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
                    depends_on=[0],
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
                    depends_on=[0],
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

        # -----------------------------------------------------
        # SIMPLE CASE
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # COMPLEX CASE
        # -----------------------------------------------------

        prompt = f"""
Tu es le Planner d'Agent-OS.

Ta responsabilité est uniquement de découper
une mission complexe en tâches utiles.

DEMANDE :

{message}

WORKER INITIAL :

{initial_worker}

WORKERS :

researcher
- recherche Internet réelle.

developer
- lit, crée et modifie des fichiers locaux.
- sait lire lui-même les fichiers qu'il modifie.

tester
- vérifie réellement le résultat.

ai_worker
- analyse et synthétise.

RÈGLES :

1. Utilise uniquement ces workers.
2. Maximum 8 étapes.
3. Ne crée pas plusieurs Developers pour une
   seule modification simple.
4. Lire puis modifier un même fichier est UNE tâche.
5. Ne crée pas de Researcher pour localiser un fichier
   dont le chemin est déjà fourni.
6. Un Developer doit normalement être suivi d'un Tester.
7. Les approbations utilisateur ne sont jamais une tâche.
8. Retourne uniquement du JSON valide.

FORMAT :

[
  {{
    "title": "Titre",
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
                    "JSON uniquement."
                ),
            )

            cleaned = (
                self._clean_json(
                    raw
                )
            )

            parsed = (
                json.loads(
                    cleaned
                )
            )

            if isinstance(
                parsed,
                dict,
            ):

                parsed = parsed.get(
                    "steps",
                    [],
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

            steps = (
                self.fallback(
                    message,
                    initial_worker,
                )
            )

        steps = (
            self._remove_useless_local_research(
                steps,
                message,
            )
        )

        return (
            self._ensure_workflow_rules(
                steps
            )
        )