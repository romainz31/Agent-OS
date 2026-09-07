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

    # =========================================================
    # FILE DETECTION
    #
    # hello.py       -> oui
    # config.json    -> oui
    # dashboard.yaml -> oui
    #
    # V3.4           -> non
    # 1.25           -> non
    # =========================================================

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
    # FILES
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

            clean = path.strip(
                "`'\".,;:()[]{} "
            )

            if (
                clean
                and clean not in files
            ):

                files.append(
                    clean
                )

        return files

    # =========================================================
    # SIMPLE DEVELOPMENT
    # =========================================================

    def _simple_local_development(
        self,
        *,
        message: str,
        initial_worker: str,
    ) -> list[PlanStep] | None:

        """
        Une demande de développement portant
        sur exactement un fichier :

        Developer -> Tester
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
                    "après le travail "
                    "du Developer."
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

        """
        Recherche classique sans demande de fichier :

        Researcher
            ↓
        AIWorker

        Aucun Developer.
        Aucun Tester.
        """

        if (
            initial_worker
            != "researcher"
        ):

            return None

        # Si un fichier explicite est demandé,
        # la mission peut nécessiter une chaîne
        # plus complexe : recherche + production
        # d'un véritable fichier.
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

            for dependency in (
                dependencies
            ):

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
    # WORKFLOW RULES
    # =========================================================

    @staticmethod
    def _ensure_workflow_rules(
        steps: list[PlanStep],
    ) -> list[PlanStep]:

        """
        Un véritable Developer travaillant
        sur un fichier doit être testé.
        """

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
                        "Synthétiser les résultats"
                    ),
                    description=(
                        "Analyser les résultats "
                        "réels du Researcher "
                        "et produire la réponse finale."
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
        # DETERMINISTIC DEVELOPMENT
        # =====================================================

        simple_dev = (
            self._simple_local_development(
                message=message,
                initial_worker=(
                    initial_worker
                ),
            )
        )

        if simple_dev is not None:

            return simple_dev

        # =====================================================
        # DETERMINISTIC RESEARCH
        # =====================================================

        simple_research = (
            self._simple_research(
                message=message,
                initial_worker=(
                    initial_worker
                ),
            )
        )

        if simple_research is not None:

            return simple_research

        # =====================================================
        # COMPLEX MISSIONS
        # =====================================================

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
- ne sert jamais à rédiger une réponse textuelle simple.

tester
- teste de vrais fichiers ou du code.
- ne teste jamais une simple synthèse textuelle.

ai_worker
- analyse, synthétise et rédige des réponses.

RÈGLES :

1. Maximum 8 étapes.

2. Utilise uniquement les workers disponibles.

3. Developer est réservé aux opérations réelles
   sur des fichiers.

4. Tester est réservé à la vérification
   de fichiers ou de code.

5. Pour une recherche simple :
   Researcher -> AIWorker.

6. Ne crée jamais Developer pour
   "rédiger un rapport" si aucun fichier
   de rapport n'est explicitement demandé.

7. Ne crée jamais Tester pour vérifier
   une simple réponse textuelle.

8. Si le chemin d'un fichier est déjà fourni,
   ne crée pas Researcher pour le chercher.

9. Les approbations utilisateur
   ne sont jamais des tâches.

10. Retourne uniquement du JSON valide.

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

            steps = (
                self.fallback(
                    message,
                    initial_worker,
                )
            )

        return (
            self._ensure_workflow_rules(
                steps
            )
        )