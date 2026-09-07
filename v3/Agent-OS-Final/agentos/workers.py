from __future__ import annotations

import json
import re

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentos.llm import (
    LLM,
    LLMError,
)

from agentos.permissions import (
    PermissionEngine,
)

from agentos.project_files import (
    ProjectFiles,
    ProjectFileError,
)

from agentos.python_runner import (
    PythonRunner,
)


# ============================================================
# RESULT
# ============================================================


@dataclass
class WorkerResult:

    success: bool
    message: str
    data: dict[str, Any]
    error: str | None = None


# ============================================================
# BASE WORKER
# ============================================================


class Worker:

    name = "worker"

    def execute(
        self,
        task,
    ):

        raise NotImplementedError


# ============================================================
# AI WORKER
# ============================================================


class AIWorker(
    Worker
):

    name = "ai_worker"

    def __init__(
        self,
        llm: LLM,
    ) -> None:

        self.llm = llm

    def execute(
        self,
        task,
    ) -> WorkerResult:

        try:

            answer = (
                self.llm.chat(
                    (
                        "Tu es un collaborateur "
                        "Agent-OS.\n\n"
                        "DEMANDE COURANTE:\n"
                        f"{task['description']}\n\n"
                        "CONTEXTE:\n"
                        f"{task.get('dependency_context') or '(aucun)'}\n\n"
                        "Réponds en français. "
                        "N'invente jamais "
                        "d'outil utilisé."
                    )
                )
            )

        except LLMError as exc:

            return WorkerResult(
                False,
                "Erreur LLM.",
                {},
                str(exc),
            )

        return WorkerResult(
            True,
            answer,
            {
                "worker": self.name,
            },
        )


# ============================================================
# RESEARCHER
# ============================================================


class ResearcherWorker(
    Worker
):

    name = "researcher"

    def __init__(
        self,
        llm: LLM,
        permissions: PermissionEngine,
    ) -> None:

        self.llm = llm
        self.permissions = permissions

    def execute(
        self,
        task,
    ) -> WorkerResult:

        permission = (
            self.permissions.check(
                "web_search"
            )
        )

        if (
            permission.decision.value
            != "allowed"
        ):

            return WorkerResult(
                False,
                "Recherche Web interdite.",
                {},
                "permission",
            )

        try:

            from ddgs import DDGS

        except ImportError:

            return WorkerResult(
                False,
                (
                    "Le package ddgs "
                    "n'est pas installé."
                ),
                {},
                (
                    "pip install "
                    "-r requirements.txt"
                ),
            )

        try:

            raw = list(
                DDGS().text(
                    task[
                        "description"
                    ],
                    max_results=5,
                )
            )

        except Exception as exc:

            return WorkerResult(
                False,
                "Recherche Web échouée.",
                {},
                str(exc),
            )

        sources = []

        for index, item in enumerate(
            raw,
            1,
        ):

            sources.append(
                {
                    "id": f"S{index}",
                    "title": str(
                        item.get(
                            "title",
                            "",
                        )
                    ),
                    "url": str(
                        item.get(
                            "href",
                            "",
                        )
                    ),
                    "body": str(
                        item.get(
                            "body",
                            "",
                        )
                    ),
                }
            )

        context = "\n\n".join(
            (
                f"[{source['id']}] "
                f"{source['title']}\n"
                f"{source['body']}\n"
                f"{source['url']}"
            )
            for source
            in sources
        )

        try:

            answer = (
                self.llm.chat(
                    (
                        "QUESTION:\n"
                        f"{task['description']}\n\n"
                        "RÉSULTATS WEB RÉELS:\n"
                        f"{context}\n\n"
                        "Synthétise en français "
                        "et cite [S1], [S2]. "
                        "N'invente aucune source."
                    )
                )
            )

        except LLMError as exc:

            return WorkerResult(
                False,
                "Synthèse impossible.",
                {
                    "sources": sources,
                },
                str(exc),
            )

        return WorkerResult(
            True,
            answer,
            {
                "worker": self.name,
                "sources": sources,
            },
        )


# ============================================================
# DEVELOPER
# ============================================================


class DeveloperWorker(
    Worker
):

    name = "developer"

    # --------------------------------------------------------
    # FILE DETECTION
    #
    # L'extension doit commencer par une lettre.
    #
    # hello.py -> valide
    # V3.4     -> ignoré
    # 1.5      -> ignoré
    # --------------------------------------------------------

    FILE_RE = re.compile(
        r"(?:(?:workspace/)?"
        r"(?:[A-Za-z0-9_.-]+/)*"
        r"[A-Za-z0-9_.-]+"
        r"\.[A-Za-z][A-Za-z0-9_-]*)"
    )

    CREATE = (
        "crée",
        "cree",
        "créer",
        "creer",
    )

    MODIFY = (
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
        files: ProjectFiles,
        runner: PythonRunner,
    ) -> None:

        self.llm = llm
        self.files = files
        self.runner = runner

    # ========================================================
    # PATH
    # ========================================================

    @staticmethod
    def _clean_path(
        path: str,
    ) -> str:

        path = (
            path
            .replace(
                "\\",
                "/",
            )
            .strip(
                "`'\".,;:()[]{} "
            )
        )

        if path.startswith(
            "workspace/"
        ):

            return path[
                len("workspace/"):
            ]

        return path

    def _paths(
        self,
        message: str,
    ) -> list[str]:

        results = []

        normalized = (
            message.replace(
                "\\",
                "/",
            )
        )

        for match in (
            self.FILE_RE.findall(
                normalized
            )
        ):

            path = (
                self._clean_path(
                    match
                )
            )

            if (
                path
                and path not in results
            ):

                results.append(
                    path
                )

        return results

    # ========================================================
    # OPERATION
    # ========================================================

    def _operation(
        self,
        message: str,
    ) -> str:

        lower = (
            message.lower()
        )

        if any(
            marker in lower
            for marker
            in self.CREATE
        ):

            return "create"

        if any(
            marker in lower
            for marker
            in self.MODIFY
        ):

            return "modify"

        return "analysis"

    # ========================================================
    # CLEAN GENERATED CONTENT
    # ========================================================

    @staticmethod
    def _clean_content(
        raw: str,
    ) -> str:

        text = raw.strip()

        if text.startswith(
            "```"
        ):

            first_newline = (
                text.find("\n")
            )

            if (
                first_newline
                != -1
            ):

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

    # ========================================================
    # EXECUTE
    # ========================================================

    def execute(
        self,
        task,
    ) -> WorkerResult:

        metadata = (
            task.get(
                "metadata",
                {},
            )
            or {}
        )

        message = str(
            metadata.get(
                "original_message",
                task.get(
                    "description",
                    "",
                ),
            )
        )

        operation = (
            self._operation(
                message
            )
        )

        paths = (
            self._paths(
                message
            )
        )

        # ----------------------------------------------------
        # ANALYSIS ONLY
        # ----------------------------------------------------

        if operation == "analysis":

            try:

                answer = (
                    self.llm.chat(
                        (
                            "DEMANDE COURANTE:\n"
                            f"{message}\n\n"
                            "ARBORESCENCE RÉELLE:\n"
                            f"{self.files.tree()}\n\n"
                            "Analyse seulement. "
                            "Ne prétends pas modifier."
                        )
                    )
                )

            except LLMError as exc:

                return WorkerResult(
                    False,
                    "Erreur Developer.",
                    {},
                    str(exc),
                )

            return WorkerResult(
                True,
                answer,
                {
                    "worker": self.name,
                    "operation": (
                        "analysis"
                    ),
                },
            )

        # ----------------------------------------------------
        # NO TARGET
        # ----------------------------------------------------

        if not paths:

            return WorkerResult(
                False,
                (
                    "Aucun chemin de fichier "
                    "explicite trouvé."
                ),
                {
                    "operation": operation,
                },
                "explicit_path_missing",
            )

        plans = []
        created = []
        approval = []

        # ----------------------------------------------------
        # FILE LOOP
        # ----------------------------------------------------

        for path in paths:

            current = ""

            if operation == "modify":

                try:

                    current = (
                        self.files.read(
                            path
                        ).content
                    )

                except Exception as exc:

                    return WorkerResult(
                        False,
                        (
                            "Lecture impossible."
                        ),
                        {
                            "path": path,
                        },
                        str(exc),
                    )

            if operation == "modify":

                instruction = (
                    "CONTENU ACTUEL:\n"
                    f"{current}\n\n"
                    "Applique uniquement "
                    "la modification demandée. "
                    "Conserve le reste du fichier. "
                    "Retourne le FICHIER COMPLET final."
                )

            else:

                instruction = (
                    "Crée le contenu complet demandé."
                )

            prompt = (
                "DEMANDE COURANTE EXACTE:\n"
                f"{message}\n\n"
                "FICHIER CIBLE:\n"
                f"{path}\n\n"
                f"{instruction}\n\n"
                "FORMAT : contenu brut uniquement. "
                "Aucun JSON. "
                "Aucun Markdown. "
                "Aucune explication."
            )

            try:

                generated = (
                    self._clean_content(
                        self.llm.chat(
                            prompt,
                            system=(
                                "Tu es le Developer "
                                "d'Agent-OS."
                            ),
                        )
                    )
                )

            except LLMError as exc:

                return WorkerResult(
                    False,
                    (
                        "Génération impossible."
                    ),
                    {
                        "path": path,
                    },
                    str(exc),
                )

            if not generated:

                return WorkerResult(
                    False,
                    "Contenu généré vide.",
                    {
                        "path": path,
                    },
                    "empty_generation",
                )

            # ------------------------------------------------
            # PYTHON PREVALIDATION
            # ------------------------------------------------

            prevalidation = {
                "checked": False,
                "success": True,
                "error": "",
            }

            if (
                Path(path)
                .suffix
                .lower()
                == ".py"
            ):

                ok, error = (
                    self.runner
                    .validate_source(
                        generated,
                        path,
                    )
                )

                prevalidation = {
                    "checked": True,
                    "success": ok,
                    "error": error,
                }

                if not ok:

                    return WorkerResult(
                        False,
                        (
                            "Proposition Python "
                            "refusée avant approbation : "
                            "erreur de syntaxe."
                        ),
                        {
                            "path": path,
                            "prevalidation": (
                                prevalidation
                            ),
                        },
                        error,
                    )

            # ------------------------------------------------
            # PREPARE WRITE
            # ------------------------------------------------

            try:

                plan = (
                    self.files
                    .prepare_write(
                        path,
                        generated,
                    )
                )

            except ProjectFileError as exc:

                return WorkerResult(
                    False,
                    "Écriture impossible.",
                    {
                        "path": path,
                    },
                    str(exc),
                )

            item = (
                plan.to_dict()
            )

            item[
                "prevalidation"
            ] = prevalidation

            plans.append(
                item
            )

            if plan.created:

                created.append(
                    path
                )

            if plan.approval_required:

                approval.append(
                    path
                )

        # ----------------------------------------------------
        # APPROVAL REQUIRED
        # ----------------------------------------------------

        if approval:

            return WorkerResult(
                True,
                (
                    "Modification préparée "
                    "et pré-validée. "
                    "Approbation humaine requise."
                ),
                {
                    "worker": self.name,
                    "operation": operation,
                    "plans": plans,
                    "approval_required_files": (
                        approval
                    ),
                    "created_files": (
                        created
                    ),
                    "modified_files": [],
                },
            )

        # ----------------------------------------------------
        # CREATED WITHOUT APPROVAL
        # ----------------------------------------------------

        return WorkerResult(
            True,
            (
                "Fichier(s) créé(s) "
                "avec succès."
            ),
            {
                "worker": self.name,
                "operation": operation,
                "plans": plans,
                "approval_required_files": [],
                "created_files": created,
                "modified_files": [],
            },
        )


# ============================================================
# TESTER
# ============================================================


class TesterWorker(
    Worker
):

    name = "tester"

    FILE_RE = (
        DeveloperWorker.FILE_RE
    )

    SYNTAX = (
        "syntaxe",
        "syntax",
        "erreur python",
        "erreurs python",
        "compile",
        "compilation",
        "py_compile",
    )

    def __init__(
        self,
        llm: LLM,
        files: ProjectFiles,
        runner: PythonRunner,
    ) -> None:

        self.llm = llm
        self.files = files
        self.runner = runner

    # ========================================================
    # TARGETS
    # ========================================================

    def _paths(
        self,
        task,
    ) -> list[str]:

        results = []

        # ----------------------------------------------------
        # DEPENDENCY OUTPUT FIRST
        # ----------------------------------------------------

        for dependency in (
            task.get(
                "dependency_context"
            )
            or []
        ):

            data = (
                dependency.get(
                    "result_data"
                )
                or {}
            )

            for key in (
                "modified_files",
                "created_files",
            ):

                for path in (
                    data.get(
                        key,
                        [],
                    )
                    or []
                ):

                    if path not in results:

                        results.append(
                            path
                        )

        if results:

            return results

        # ----------------------------------------------------
        # FALLBACK TO USER MESSAGE
        # ----------------------------------------------------

        metadata = (
            task.get(
                "metadata",
                {},
            )
            or {}
        )

        message = str(
            metadata.get(
                "original_message",
                "",
            )
        )

        normalized = (
            message.replace(
                "\\",
                "/",
            )
        )

        for match in (
            self.FILE_RE.findall(
                normalized
            )
        ):

            path = (
                DeveloperWorker
                ._clean_path(
                    match
                )
            )

            if (
                path
                and path not in results
            ):

                results.append(
                    path
                )

        return results

    # ========================================================
    # EXECUTE
    # ========================================================

    def execute(
        self,
        task,
    ) -> WorkerResult:

        paths = (
            self._paths(
                task
            )
        )

        if not paths:

            return WorkerResult(
                False,
                "Aucun fichier à tester.",
                {},
                "target_missing",
            )

        metadata = (
            task.get(
                "metadata",
                {},
            )
            or {}
        )

        original_message = str(
            metadata.get(
                "original_message",
                "",
            )
        )

        syntax_only = any(
            marker
            in original_message.lower()
            for marker
            in self.SYNTAX
        )

        reads = []
        tests = []

        for path in paths:

            try:

                reads.append(
                    self.files.read(
                        path
                    ).to_dict()
                )

            except Exception as exc:

                return WorkerResult(
                    True,
                    (
                        "VERDICT : NON VALIDÉ\n\n"
                        "Lecture impossible : "
                        f"{path}\n"
                        f"{exc}"
                    ),
                    {
                        "worker": self.name,
                        "verdict": (
                            "NON_VALIDÉ"
                        ),
                        "targets": paths,
                        "tests": tests,
                    },
                )

            # ------------------------------------------------
            # PYTHON
            # ------------------------------------------------

            if (
                Path(path)
                .suffix
                .lower()
                == ".py"
            ):

                try:

                    compilation = (
                        self.runner
                        .compile_file(
                            path
                        )
                    )

                except Exception as exc:

                    return WorkerResult(
                        True,
                        (
                            "VERDICT : NON VALIDÉ\n\n"
                            "Test impossible : "
                            f"{exc}"
                        ),
                        {
                            "worker": self.name,
                            "verdict": (
                                "NON_VALIDÉ"
                            ),
                            "targets": paths,
                            "tests": tests,
                        },
                    )

                tests.append(
                    compilation.to_dict()
                )

                if not compilation.success:

                    return WorkerResult(
                        True,
                        (
                            "VERDICT : NON VALIDÉ\n\n"
                            "La compilation Python "
                            "réelle a échoué."
                        ),
                        {
                            "worker": self.name,
                            "verdict": (
                                "NON_VALIDÉ"
                            ),
                            "targets": paths,
                            "tests": tests,
                        },
                    )

                # --------------------------------------------
                # EXECUTION
                # --------------------------------------------

                if (
                    path
                    .replace(
                        "\\",
                        "/",
                    )
                    .startswith(
                        (
                            "tests/",
                            "applications/",
                        )
                    )
                    and not syntax_only
                ):

                    execution = (
                        self.runner
                        .run_file(
                            path
                        )
                    )

                    tests.append(
                        execution.to_dict()
                    )

                    if not execution.success:

                        return WorkerResult(
                            True,
                            (
                                "VERDICT : NON VALIDÉ\n\n"
                                "L'exécution réelle "
                                "a échoué."
                            ),
                            {
                                "worker": self.name,
                                "verdict": (
                                    "NON_VALIDÉ"
                                ),
                                "targets": paths,
                                "tests": tests,
                            },
                        )

        # ----------------------------------------------------
        # SYNTAX ONLY
        # ----------------------------------------------------

        if syntax_only:

            return WorkerResult(
                True,
                (
                    "VERDICT : VALIDÉ\n\n"
                    "La compilation Python réelle "
                    "a réussi pour tous "
                    "les fichiers ciblés."
                ),
                {
                    "worker": self.name,
                    "verdict": "VALIDÉ",
                    "test_mode": "syntax",
                    "targets": paths,
                    "tests": tests,
                },
            )

        # ----------------------------------------------------
        # GENERAL REVIEW
        # ----------------------------------------------------

        evidence = json.dumps(
            {
                "reads": reads,
                "tests": tests,
            },
            ensure_ascii=False,
            indent=2,
        )

        try:

            answer = (
                self.llm.chat(
                    (
                        "DEMANDE:\n"
                        f"{task['description']}\n\n"
                        "PREUVES RÉELLES:\n"
                        f"{evidence}\n\n"
                        "N'invente aucun échec. "
                        "Ne confonds pas "
                        "non testé et incorrect. "
                        "Tout NON VALIDÉ doit citer "
                        "une preuve concrète. "
                        "Commence par "
                        "VERDICT : VALIDÉ "
                        "ou VERDICT : NON VALIDÉ."
                    )
                )
            )

        except LLMError as exc:

            return WorkerResult(
                False,
                "Revue LLM impossible.",
                {},
                str(exc),
            )

        if (
            answer.upper()
            .startswith(
                "VERDICT : NON VALIDÉ"
            )
        ):

            verdict = "NON_VALIDÉ"

        else:

            verdict = "VALIDÉ"

        return WorkerResult(
            True,
            answer,
            {
                "worker": self.name,
                "verdict": verdict,
                "test_mode": "general",
                "targets": paths,
                "tests": tests,
            },
        )