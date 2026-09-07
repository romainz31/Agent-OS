"""
Tester Agent-OS V2.3.7.

Le Tester utilise des preuves réelles.

Principes :
- lire les vrais fichiers ;
- compiler réellement les fichiers Python ;
- exécuter uniquement les scripts runtime autorisés ;
- distinguer un test syntaxique d'une revue générale ;
- ne jamais laisser le LLM contredire
  une preuve déterministe sans preuve réelle contraire.
"""

from __future__ import annotations

import re

from pathlib import Path
from typing import Any, Dict

from v2.brain.llm import (
    LLM,
    LLMError,
)

from v2.permissions.permissions import (
    PermissionEngine,
)

from v2.tools.project_files import (
    ProjectFilesTool,
)

from v2.tools.python_runner import (
    PythonRunner,
    PythonRunnerError,
)

from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class TesterWorker(
    Worker
):

    name = "tester"

    description = (
        "Tester avec lecture réelle des fichiers "
        "et tests Python contrôlés."
    )

    FILE_PATTERN = re.compile(
        r"""
        (?:
            [A-Za-z0-9_.-]+/
        )*
        [A-Za-z0-9_.-]+
        \.
        [A-Za-z0-9_-]+
        """,
        flags=re.VERBOSE,
    )

    SYNTAX_MARKERS = (
        "syntaxe",
        "syntax",
        "erreur python",
        "erreurs python",
        "compile",
        "compilation",
        "py_compile",
        "se compile",
        "compilable",
    )

    def __init__(
        self,
        llm: LLM | None = None,
        permissions: PermissionEngine | None = None,
        project_tool: ProjectFilesTool | None = None,
        python_runner: PythonRunner | None = None,
    ) -> None:

        self.llm = (
            llm
            or LLM()
        )

        self.permissions = (
            permissions
            or PermissionEngine()
        )

        self.project_tool = (
            project_tool
            or ProjectFilesTool(
                permissions=self.permissions
            )
        )

        self.python_runner = (
            python_runner
            or PythonRunner(
                permissions=self.permissions
            )
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _unique(
        values: list[str],
    ) -> list[str]:

        result = []

        for value in values:

            value = str(
                value
            ).strip()

            if (
                value
                and value not in result
            ):

                result.append(
                    value
                )

        return result

    # ========================================================
    # TEST MODE
    # ========================================================

    @classmethod
    def _detect_test_mode(
        cls,
        text: str,
    ) -> str:

        lower = (
            text.lower()
        )

        if any(
            marker in lower
            for marker
            in cls.SYNTAX_MARKERS
        ):

            return "syntax"

        return "general"

    # ========================================================
    # PATHS FROM TEXT
    # ========================================================

    def _extract_paths_from_text(
        self,
        text: str,
    ) -> list[str]:

        normalized = (
            text
            .replace(
                "\\",
                "/",
            )
            .replace(
                "`",
                " ",
            )
            .replace(
                '"',
                " ",
            )
        )

        candidates = (
            self.FILE_PATTERN.findall(
                normalized
            )
        )

        paths = []

        for candidate in candidates:

            suffix = (
                Path(candidate)
                .suffix
                .lower()
            )

            if suffix in {
                ".py",
                ".json",
                ".yaml",
                ".yml",
                ".md",
                ".txt",
                ".toml",
            }:

                paths.append(
                    candidate
                )

        return (
            self._unique(
                paths
            )
        )

    # ========================================================
    # DEPENDENCY FILES
    # ========================================================

    def _extract_dependency_files(
        self,
        dependency_context: Any,
    ) -> list[str]:

        if not isinstance(
            dependency_context,
            list,
        ):

            return []

        paths = []

        for dependency in (
            dependency_context
        ):

            if not isinstance(
                dependency,
                dict,
            ):

                continue

            data = dependency.get(
                "result_data",
                {},
            )

            if not isinstance(
                data,
                dict,
            ):

                continue

            for key in (
                "modified_files",
                "created_files",
                "requested_paths",
            ):

                values = data.get(
                    key,
                    [],
                )

                if not isinstance(
                    values,
                    list,
                ):

                    continue

                for path in values:

                    if path:

                        paths.append(
                            str(
                                path
                            )
                        )

        return (
            self._unique(
                paths
            )
        )

    # ========================================================
    # TARGETS
    # ========================================================

    def _determine_targets(
        self,
        *,
        title: str,
        description: str,
        metadata: dict[str, Any],
        dependency_context: Any,
    ) -> list[str]:

        dependency_files = (
            self._extract_dependency_files(
                dependency_context
            )
        )

        if dependency_files:

            return dependency_files

        text = "\n".join(
            [
                title,
                description,
                str(
                    metadata.get(
                        "original_message",
                        "",
                    )
                ),
            ]
        )

        return (
            self._extract_paths_from_text(
                text
            )
        )

    # ========================================================
    # READ
    # ========================================================

    def _read_files(
        self,
        paths: list[str],
    ) -> list[
        dict[str, Any]
    ]:

        results = []

        for path in paths:

            try:

                result = (
                    self.project_tool
                    .read_file(
                        path,
                        max_chars=30_000,
                    )
                )

                results.append(
                    result.to_dict()
                )

            except Exception as exc:

                results.append(
                    {
                        "path": path,
                        "error": str(
                            exc
                        ),
                    }
                )

        return results

    # ========================================================
    # PYTHON TEST
    # ========================================================

    def _test_python_file(
        self,
        path: str,
    ) -> list[
        dict[str, Any]
    ]:

        results = []

        try:

            compile_result = (
                self.python_runner
                .compile_file(
                    path,
                    timeout=8,
                )
            )

            results.append(
                compile_result
                .to_dict()
            )

        except Exception as exc:

            results.append(
                {
                    "path": path,
                    "mode": "compile",
                    "success": False,
                    "error": str(
                        exc
                    ),
                }
            )

            return results

        if not compile_result.success:

            return results

        normalized = (
            path
            .replace(
                "\\",
                "/",
            )
        )

        if (
            normalized.startswith(
                "applications/"
            )
            or normalized.startswith(
                "tests/"
            )
        ):

            try:

                runtime_result = (
                    self.python_runner
                    .run_file(
                        path,
                        timeout=8,
                    )
                )

                results.append(
                    runtime_result
                    .to_dict()
                )

            except PythonRunnerError as exc:

                results.append(
                    {
                        "path": path,
                        "mode": "run",
                        "success": False,
                        "error": str(
                            exc
                        ),
                    }
                )

            except Exception as exc:

                results.append(
                    {
                        "path": path,
                        "mode": "run",
                        "success": False,
                        "error": str(
                            exc
                        ),
                    }
                )

        return results

    def _run_tests(
        self,
        paths: list[str],
    ) -> list[
        dict[str, Any]
    ]:

        results = []

        for path in paths:

            if (
                Path(path)
                .suffix
                .lower()
                != ".py"
            ):

                continue

            results.extend(
                self._test_python_file(
                    path
                )
            )

        return results

    # ========================================================
    # FAILURES
    # ========================================================

    @staticmethod
    def _has_test_failure(
        test_results: list[
            dict[str, Any]
        ],
    ) -> bool:

        return any(
            result.get(
                "success"
            )
            is False
            for result
            in test_results
        )

    @staticmethod
    def _has_read_failure(
        read_results: list[
            dict[str, Any]
        ],
    ) -> bool:

        return any(
            bool(
                result.get(
                    "error"
                )
            )
            for result
            in read_results
        )

    # ========================================================
    # COMPILE RESULTS
    # ========================================================

    @staticmethod
    def _compile_results(
        test_results: list[
            dict[str, Any]
        ],
    ) -> list[
        dict[str, Any]
    ]:

        return [
            result
            for result
            in test_results
            if (
                result.get(
                    "mode"
                )
                == "compile"
            )
        ]

    # ========================================================
    # SYNTAX VERDICT
    # ========================================================

    def _syntax_verdict(
        self,
        *,
        targets: list[str],
        test_results: list[
            dict[str, Any]
        ],
    ) -> str:

        python_targets = [
            path
            for path
            in targets
            if (
                Path(path)
                .suffix
                .lower()
                == ".py"
            )
        ]

        compile_results = (
            self._compile_results(
                test_results
            )
        )

        if not python_targets:

            return (
                "VERDICT : NON VALIDÉ\n\n"
                "Aucun fichier Python "
                "n'a été trouvé à compiler."
            )

        if (
            len(
                compile_results
            )
            != len(
                python_targets
            )
        ):

            return (
                "VERDICT : NON VALIDÉ\n\n"
                "Tous les fichiers Python "
                "n'ont pas pu être compilés."
            )

        failures = [
            result
            for result
            in compile_results
            if not result.get(
                "success"
            )
        ]

        if failures:

            lines = [
                "VERDICT : NON VALIDÉ",
                "",
                "La compilation Python réelle "
                "a détecté une erreur.",
                "",
            ]

            for result in failures:

                lines.append(
                    (
                        f"Fichier : "
                        f"{result.get('path')}"
                    )
                )

                stderr = str(
                    result.get(
                        "stderr",
                        "",
                    )
                ).strip()

                error = str(
                    result.get(
                        "error",
                        "",
                    )
                ).strip()

                if stderr:

                    lines.append(
                        stderr
                    )

                elif error:

                    lines.append(
                        error
                    )

            return "\n".join(
                lines
            )

        return (
            "VERDICT : VALIDÉ\n\n"
            "La compilation Python réelle "
            "a réussi pour tous les fichiers ciblés.\n\n"
            "Aucune erreur de syntaxe Python "
            "n'a été détectée."
        )

    # ========================================================
    # EVIDENCE
    # ========================================================

    @staticmethod
    def _format_evidence(
        read_results: list[
            dict[str, Any]
        ],
        test_results: list[
            dict[str, Any]
        ],
    ) -> str:

        sections = []

        for item in read_results:

            path = item.get(
                "path",
                "?",
            )

            if item.get(
                "error"
            ):

                sections.append(
                    (
                        f"LECTURE {path}\n"
                        f"ERREUR : "
                        f"{item.get('error')}"
                    )
                )

                continue

            sections.append(
                (
                    f"FICHIER RÉEL {path}\n"
                    "--------------------\n"
                    f"{item.get('content', '')}"
                )
            )

        for result in test_results:

            sections.append(
                (
                    "TEST RÉEL\n"
                    f"Fichier : "
                    f"{result.get('path')}\n"
                    f"Mode : "
                    f"{result.get('mode')}\n"
                    f"Succès : "
                    f"{result.get('success')}\n"
                    f"Return code : "
                    f"{result.get('returncode')}\n"
                    f"Timeout : "
                    f"{result.get('timed_out')}\n"
                    f"STDOUT :\n"
                    f"{result.get('stdout', '')}\n"
                    f"STDERR :\n"
                    f"{result.get('stderr', '')}\n"
                    f"Erreur outil : "
                    f"{result.get('error', '')}"
                )
            )

        return "\n\n".join(
            sections
        )

    # ========================================================
    # GENERAL REVIEW
    # ========================================================

    def _llm_verdict(
        self,
        *,
        title: str,
        description: str,
        dependency_context: Any,
        targets: list[str],
        evidence: str,
    ) -> str:

        prompt = f"""
Tu es le Tester d'Agent-OS V2.

Tu dois analyser uniquement les preuves
réelles ci-dessous.

============================================================
TÂCHE
============================================================

TITRE :
{title}

DESCRIPTION :
{description}

============================================================
CONTEXTE
============================================================

{dependency_context}

============================================================
FICHIERS
============================================================

{targets}

============================================================
PREUVES RÉELLES
============================================================

{evidence}

============================================================
RÈGLES ABSOLUES
============================================================

1. N'invente jamais l'absence d'une fonction,
   variable, classe ou méthode.

2. Si tu affirmes qu'un symbole n'existe pas,
   il doit être réellement absent du contenu
   fourni.

3. Une compilation réussie signifie :
   aucune erreur de syntaxe Python détectée.

4. Tu ne peux pas déclarer NON VALIDÉ
   simplement parce qu'une dépendance externe
   n'a pas été exécutée.

5. Pour déclarer NON VALIDÉ, cite une preuve
   concrète présente dans :
   - le code réel ;
   - stderr ;
   - stdout ;
   - un return code ;
   - une erreur outil réelle.

6. Ne confonds pas :
   "non testé"
   et
   "incorrect".

Réponds en français.

Commence obligatoirement par :

VERDICT : VALIDÉ

ou

VERDICT : NON VALIDÉ
"""

        return (
            self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Tester Agent-OS fondé "
                    "uniquement sur des preuves."
                ),
            )
        )

    # ========================================================
    # EXECUTE
    # ========================================================

    def execute(
        self,
        task: Dict[
            str,
            Any,
        ],
    ) -> WorkerResult:

        title = str(
            task.get(
                "title",
                "",
            )
        ).strip()

        description = str(
            task.get(
                "description",
                "",
            )
        ).strip()

        metadata = task.get(
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            dict,
        ):

            metadata = {}

        original_message = str(
            metadata.get(
                "original_message",
                "",
            )
        ).strip()

        dependency_context = (
            task.get(
                "dependency_context"
            )
            or metadata.get(
                "dependency_context"
            )
            or []
        )

        full_request = "\n".join(
            value
            for value in (
                original_message,
                title,
                description,
            )
            if value
        )

        test_mode = (
            self._detect_test_mode(
                full_request
            )
        )

        # ====================================================
        # TARGETS
        # ====================================================

        targets = (
            self._determine_targets(
                title=title,
                description=description,
                metadata=metadata,
                dependency_context=(
                    dependency_context
                ),
            )
        )

        if not targets:

            return WorkerResult(
                success=False,
                message=(
                    "Le Tester n'a trouvé "
                    "aucun fichier réel à vérifier."
                ),
                error=(
                    "tester_target_missing"
                ),
                data={
                    "worker": self.name,
                    "type": "testing",
                    "task_id": task.get(
                        "id"
                    ),
                    "test_mode": test_mode,
                },
            )

        # ====================================================
        # READ
        # ====================================================

        read_results = (
            self._read_files(
                targets
            )
        )

        if (
            self._has_read_failure(
                read_results
            )
        ):

            evidence = (
                self._format_evidence(
                    read_results,
                    [],
                )
            )

            return WorkerResult(
                success=True,
                message=(
                    "VERDICT : NON VALIDÉ\n\n"
                    "Un ou plusieurs fichiers "
                    "n'ont pas pu être lus.\n\n"
                    f"{evidence}"
                ),
                data={
                    "worker": self.name,
                    "type": "testing",
                    "task_id": task.get(
                        "id"
                    ),
                    "test_mode": test_mode,
                    "verdict": "NON_VALIDÉ",
                    "targets": targets,
                    "files_read": (
                        read_results
                    ),
                    "tests": [],
                },
            )

        # ====================================================
        # REAL TESTS
        # ====================================================

        test_results = (
            self._run_tests(
                targets
            )
        )

        # ====================================================
        # SYNTAX MODE = DETERMINISTIC
        # ====================================================

        if (
            test_mode
            == "syntax"
        ):

            verdict_text = (
                self._syntax_verdict(
                    targets=targets,
                    test_results=(
                        test_results
                    ),
                )
            )

            if (
                verdict_text
                .startswith(
                    "VERDICT : VALIDÉ"
                )
            ):

                verdict = "VALIDÉ"

            else:

                verdict = (
                    "NON_VALIDÉ"
                )

            return WorkerResult(
                success=True,
                message=verdict_text,
                data={
                    "worker": self.name,
                    "type": "testing",
                    "task_id": task.get(
                        "id"
                    ),
                    "test_mode": (
                        "syntax"
                    ),
                    "verdict": verdict,
                    "targets": targets,
                    "files_read": (
                        read_results
                    ),
                    "tests": (
                        test_results
                    ),
                },
            )

        # ====================================================
        # HARD REAL FAILURE
        # ====================================================

        evidence = (
            self._format_evidence(
                read_results,
                test_results,
            )
        )

        if (
            self._has_test_failure(
                test_results
            )
        ):

            return WorkerResult(
                success=True,
                message=(
                    "VERDICT : NON VALIDÉ\n\n"
                    "Au moins un test réel "
                    "a échoué.\n\n"
                    f"{evidence}"
                ),
                data={
                    "worker": self.name,
                    "type": "testing",
                    "task_id": task.get(
                        "id"
                    ),
                    "test_mode": (
                        "general"
                    ),
                    "verdict": (
                        "NON_VALIDÉ"
                    ),
                    "targets": targets,
                    "files_read": (
                        read_results
                    ),
                    "tests": (
                        test_results
                    ),
                },
            )

        # ====================================================
        # GENERAL LLM REVIEW
        # ====================================================

        try:

            verdict_text = (
                self._llm_verdict(
                    title=title,
                    description=description,
                    dependency_context=(
                        dependency_context
                    ),
                    targets=targets,
                    evidence=evidence,
                )
            )

        except LLMError as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Le Tester n'a pas pu "
                    "contacter le modèle."
                ),
                error=str(
                    exc
                ),
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Erreur du Tester."
                ),
                error=str(
                    exc
                ),
            )

        upper = (
            verdict_text
            .strip()
            .upper()
        )

        if upper.startswith(
            "VERDICT : NON VALIDÉ"
        ):

            verdict = (
                "NON_VALIDÉ"
            )

        elif upper.startswith(
            "VERDICT : VALIDÉ"
        ):

            verdict = (
                "VALIDÉ"
            )

        else:

            verdict = (
                "INDETERMINÉ"
            )

        return WorkerResult(
            success=True,
            message=(
                verdict_text.strip()
            ),
            data={
                "worker": self.name,
                "type": "testing",
                "task_id": task.get(
                    "id"
                ),
                "model": self.llm.model,
                "test_mode": "general",
                "verdict": verdict,
                "targets": targets,
                "files_read": (
                    read_results
                ),
                "tests": (
                    test_results
                ),
            },
        )