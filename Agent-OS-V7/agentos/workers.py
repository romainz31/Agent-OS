from __future__ import annotations

import json
import re
import unicodedata

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentos.artifacts import (
    ArtifactBuilder,
    ArtifactError,
)
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
            answer = self.llm.chat(
                (
                    "Tu es un collaborateur "
                    "Agent-OS.\n\n"
                    "DEMANDE COURANTE:\n"
                    f"{task['description']}\n\n"
                    "CONTEXTE:\n"
                    f"{task.get('dependency_context') or '(aucun)'}\n\n"
                    "Réponds en français. "
                    "N'invente jamais d'outil utilisé."
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
        permission = self.permissions.check(
            "web_search"
        )

        if permission.decision.value != "allowed":
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
                    task["description"],
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
            for source in sources
        )

        try:
            answer = self.llm.chat(
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

    EXECUTABLE_MARKERS = (
        ".exe",
        "exécutable",
        "executable",
        "application windows",
        "programme windows",
    )

    GUI_MARKERS = (
        "boîte de dialogue",
        "boite de dialogue",
        "fenêtre",
        "fenetre",
        "interface graphique",
        "gui",
        "tkinter",
        "messagebox",
        "popup",
        "pop-up",
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
        self.artifacts = ArtifactBuilder(
            files.permissions,
            files.root,
        )

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
        normalized = message.replace(
            "\\",
            "/",
        )

        for match in self.FILE_RE.findall(
            normalized
        ):
            path = self._clean_path(
                match
            )

            if path and path not in results:
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
        lower = message.lower()

        if any(
            marker in lower
            for marker in self.CREATE
        ):
            return "create"

        if any(
            marker in lower
            for marker in self.MODIFY
        ):
            return "modify"

        return "analysis"

    # ========================================================
    # ARTIFACT HELPERS — V5.5
    # ========================================================

    @classmethod
    def _is_executable_request(
        cls,
        message: str,
    ) -> bool:
        lower = message.lower()
        return any(
            marker in lower
            for marker in cls.EXECUTABLE_MARKERS
        )

    @classmethod
    def _is_gui_request(
        cls,
        message: str,
    ) -> bool:
        lower = message.lower()
        return any(
            marker in lower
            for marker in cls.GUI_MARKERS
        )

    @staticmethod
    def _slugify(
        value: str,
    ) -> str:
        ascii_value = (
            unicodedata
            .normalize(
                "NFKD",
                value,
            )
            .encode(
                "ascii",
                "ignore",
            )
            .decode(
                "ascii"
            )
            .lower()
        )

        ascii_value = re.sub(
            r"[^a-z0-9]+",
            "_",
            ascii_value,
        ).strip("_")

        if not ascii_value:
            return "application"

        return ascii_value[:48]

    @staticmethod
    def _quoted_texts(
        message: str,
    ) -> list[str]:
        values = []

        for pattern in (
            r'"([^"\r\n]{1,120})"',
            r"“([^”\r\n]{1,120})”",
        ):
            for match in re.findall(
                pattern,
                message,
            ):
                clean = " ".join(
                    str(match).split()
                ).strip()

                if clean and clean not in values:
                    values.append(
                        clean
                    )

        return values

    @classmethod
    def _dialog_text(
        cls,
        message: str,
    ) -> str | None:
        lower = message.lower()

        if not any(
            marker in lower
            for marker in (
                "boîte de dialogue",
                "boite de dialogue",
                "messagebox",
                "popup",
                "pop-up",
            )
        ):
            return None

        quoted = cls._quoted_texts(
            message
        )

        if quoted:
            return quoted[-1]

        patterns = (
            r"(?:affiche|affichant|écris|ecris|écrit|ecrit)\s+(.{1,80})$",
            r"(?:texte|message)\s+(.{1,80})$",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                message,
                flags=re.IGNORECASE,
            )

            if match:
                value = match.group(1).strip(
                    " .'\""
                )

                if value:
                    return value

        return None

    def _artifact_target(
        self,
        *,
        message: str,
        paths: list[str],
        task,
    ) -> tuple[str, bool]:
        for path in paths:
            if Path(path).suffix.lower() == ".exe":
                return path, True

        label = None
        quoted = self._quoted_texts(
            message
        )

        if quoted:
            label = quoted[-1]

        if not label:
            dialog_text = self._dialog_text(
                message
            )
            if dialog_text:
                label = dialog_text

        if label:
            stem = self._slugify(
                label
            )
        else:
            task_id = str(
                task.get(
                    "id",
                    "application",
                )
            )
            compact = re.sub(
                r"[^A-Za-z0-9]",
                "",
                task_id,
            )[-8:]
            stem = (
                f"application_{compact.lower()}"
                if compact
                else "application"
            )

        return (
            self.artifacts.unique_artifact_path(
                stem
            ),
            False,
        )

    @staticmethod
    def _clean_content(
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

    def _deterministic_dialog_source(
        self,
        message: str,
    ) -> str | None:
        text = self._dialog_text(
            message
        )

        if not text:
            return None

        encoded = json.dumps(
            text,
            ensure_ascii=False,
        )

        return (
            "import sys\n"
            "import tkinter as tk\n"
            "from tkinter import messagebox\n\n"
            f"MESSAGE = {encoded}\n\n"
            "def main():\n"
            "    if '--self-test' in sys.argv:\n"
            "        if not MESSAGE:\n"
            "            raise RuntimeError('Message vide')\n"
            "        print('AGENTOS_SELF_TEST_OK')\n"
            "        print(MESSAGE)\n"
            "        return\n\n"
            "    root = tk.Tk()\n"
            "    root.withdraw()\n"
            "    try:\n"
            "        messagebox.showinfo('Message', MESSAGE)\n"
            "    finally:\n"
            "        root.destroy()\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )

    def _generate_executable_source(
        self,
        *,
        message: str,
        source_path: str,
        artifact_path: str,
    ) -> str:
        deterministic = (
            self._deterministic_dialog_source(
                message
            )
        )

        if deterministic is not None:
            return deterministic

        prompt = (
            "DEMANDE UTILISATEUR EXACTE:\n"
            f"{message}\n\n"
            "OBJECTIF:\n"
            "Créer le source Python complet qui sera emballé "
            "en exécutable Windows par PyInstaller.\n\n"
            "SOURCE CIBLE:\n"
            f"{source_path}\n\n"
            "EXÉCUTABLE FINAL:\n"
            f"{artifact_path}\n\n"
            "RÈGLES OBLIGATOIRES:\n"
            "1. Retourne uniquement le code Python brut.\n"
            "2. Utilise de préférence la bibliothèque standard.\n"
            "3. Le programme doit réellement réaliser la demande.\n"
            "4. Ajoute un mode non interactif --self-test.\n"
            "5. Quand --self-test est présent, n'ouvre aucune fenêtre, "
            "n'attend aucune saisie et n'effectue aucun effet externe.\n"
            "6. Si le self-test réussit, imprime exactement une ligne "
            "contenant AGENTOS_SELF_TEST_OK puis quitte avec le code 0.\n"
            "7. Le test --self-test doit être traité avant tout comportement "
            "interactif ou effet de bord.\n"
            "8. Aucun Markdown, aucune explication."
        )

        generated = self.llm.chat(
            prompt,
            system=(
                "Tu es le Developer d'Agent-OS. "
                "Tu produis un source Python sûr, minimal, "
                "testable et emballable avec PyInstaller."
            ),
        )

        return self._clean_content(
            generated
        )

    def _execute_executable_creation(
        self,
        *,
        task,
        message: str,
        paths: list[str],
    ) -> WorkerResult:
        artifact_path, explicit = (
            self._artifact_target(
                message=message,
                paths=paths,
                task=task,
            )
        )

        if (
            explicit
            and self.artifacts.exists(
                artifact_path
            )
        ):
            return WorkerResult(
                False,
                (
                    "L'exécutable cible existe déjà. "
                    "Je refuse de l'écraser automatiquement."
                ),
                {
                    "worker": self.name,
                    "operation": "create_artifact",
                    "artifact_path": artifact_path,
                },
                "artifact_exists",
            )

        stem = Path(
            artifact_path
        ).stem

        source_path = (
            self.artifacts.unique_source_path(
                stem
            )
        )

        try:
            generated = (
                self._generate_executable_source(
                    message=message,
                    source_path=source_path,
                    artifact_path=artifact_path,
                )
            )
        except LLMError as exc:
            return WorkerResult(
                False,
                "Génération du source impossible.",
                {
                    "artifact_path": artifact_path,
                    "source_path": source_path,
                },
                str(exc),
            )

        if not generated:
            return WorkerResult(
                False,
                "Source généré vide.",
                {
                    "artifact_path": artifact_path,
                    "source_path": source_path,
                },
                "empty_generation",
            )

        ok, error = self.runner.validate_source(
            generated,
            source_path,
        )

        if not ok:
            return WorkerResult(
                False,
                (
                    "Le source Python de l'exécutable "
                    "contient une erreur de syntaxe."
                ),
                {
                    "artifact_path": artifact_path,
                    "source_path": source_path,
                    "prevalidation": {
                        "checked": True,
                        "success": False,
                        "error": error,
                    },
                },
                error,
            )

        try:
            source_plan = self.files.prepare_write(
                source_path,
                generated,
            )
        except ProjectFileError as exc:
            return WorkerResult(
                False,
                "Écriture du source impossible.",
                {
                    "artifact_path": artifact_path,
                    "source_path": source_path,
                },
                str(exc),
            )

        if source_plan.approval_required:
            return WorkerResult(
                True,
                (
                    "Le source est préparé mais nécessite "
                    "une approbation avant le build."
                ),
                {
                    "worker": self.name,
                    "operation": "create_artifact",
                    "plans": [
                        source_plan.to_dict()
                    ],
                    "approval_required_files": [
                        source_path
                    ],
                    "created_files": [],
                    "source_files": [
                        source_path
                    ],
                    "artifact_files": [],
                },
            )

        build = self.artifacts.build_windows_executable(
            source_path=source_path,
            artifact_path=artifact_path,
            windowed=self._is_gui_request(
                message
            ),
        )

        if not build.success:
            return WorkerResult(
                False,
                (
                    "Le source Python a été créé, "
                    "mais le build de l'exécutable a échoué."
                ),
                {
                    "worker": self.name,
                    "operation": "create_artifact",
                    "source_files": [
                        source_path
                    ],
                    "created_files": [
                        source_path
                    ],
                    "artifact_files": [],
                    "build": build.to_dict(),
                },
                (
                    build.error
                    or "artifact_build_failed"
                ),
            )

        return WorkerResult(
            True,
            (
                "Exécutable Windows créé avec succès : "
                f"{artifact_path}"
            ),
            {
                "worker": self.name,
                "operation": "create_artifact",
                "plans": [
                    source_plan.to_dict(),
                ],
                "approval_required_files": [],
                "source_files": [
                    source_path
                ],
                "artifact_files": [
                    artifact_path
                ],
                "created_files": [
                    source_path,
                    artifact_path,
                ],
                "modified_files": [],
                "build": build.to_dict(),
            },
        )

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

        operation = self._operation(
            message
        )
        paths = self._paths(
            message
        )

        # ----------------------------------------------------
        # V5.5 EXECUTABLE ARTIFACT
        # ----------------------------------------------------

        if (
            operation == "create"
            and self._is_executable_request(
                message
            )
        ):
            return self._execute_executable_creation(
                task=task,
                message=message,
                paths=paths,
            )

        # ----------------------------------------------------
        # ANALYSIS ONLY
        # ----------------------------------------------------

        if operation == "analysis":
            try:
                answer = self.llm.chat(
                    (
                        "DEMANDE COURANTE:\n"
                        f"{message}\n\n"
                        "ARBORESCENCE RÉELLE:\n"
                        f"{self.files.tree()}\n\n"
                        "Analyse seulement. "
                        "Ne prétends pas modifier."
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
                    "operation": "analysis",
                },
            )

        # ----------------------------------------------------
        # NO TARGET
        # ----------------------------------------------------

        if not paths:
            return WorkerResult(
                False,
                (
                    "Aucun chemin de fichier explicite trouvé. "
                    "Pour une modification, le fichier cible "
                    "doit être identifiable."
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
                    current = self.files.read(
                        path
                    ).content
                except Exception as exc:
                    return WorkerResult(
                        False,
                        "Lecture impossible.",
                        {
                            "path": path,
                        },
                        str(exc),
                    )

            if operation == "modify":
                instruction = (
                    "CONTENU ACTUEL:\n"
                    f"{current}\n\n"
                    "Applique uniquement la modification demandée. "
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
                "Aucun JSON. Aucun Markdown. "
                "Aucune explication."
            )

            try:
                generated = self._clean_content(
                    self.llm.chat(
                        prompt,
                        system=(
                            "Tu es le Developer "
                            "d'Agent-OS."
                        ),
                    )
                )
            except LLMError as exc:
                return WorkerResult(
                    False,
                    "Génération impossible.",
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

            prevalidation = {
                "checked": False,
                "success": True,
                "error": "",
            }

            if Path(path).suffix.lower() == ".py":
                ok, error = self.runner.validate_source(
                    generated,
                    path,
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
                            "Proposition Python refusée "
                            "avant approbation : erreur de syntaxe."
                        ),
                        {
                            "path": path,
                            "prevalidation": prevalidation,
                        },
                        error,
                    )

            try:
                plan = self.files.prepare_write(
                    path,
                    generated,
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

            item = plan.to_dict()
            item["prevalidation"] = prevalidation
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

        if approval:
            return WorkerResult(
                True,
                (
                    "Modification préparée et pré-validée. "
                    "Approbation humaine requise."
                ),
                {
                    "worker": self.name,
                    "operation": operation,
                    "plans": plans,
                    "approval_required_files": approval,
                    "created_files": created,
                    "modified_files": [],
                },
            )

        return WorkerResult(
            True,
            "Fichier(s) créé(s) avec succès.",
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

    FILE_RE = DeveloperWorker.FILE_RE

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
        self.artifacts = ArtifactBuilder(
            files.permissions,
            files.root,
        )

    # ========================================================
    # TARGETS
    # ========================================================

    def _paths(
        self,
        task,
    ) -> list[str]:
        results = []

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
                "artifact_files",
                "source_files",
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
        normalized = message.replace(
            "\\",
            "/",
        )

        for match in self.FILE_RE.findall(
            normalized
        ):
            path = DeveloperWorker._clean_path(
                match
            )

            if path and path not in results:
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
        paths = self._paths(
            task
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
            marker in original_message.lower()
            for marker in self.SYNTAX
        )

        reads = []
        tests = []

        for path in paths:
            suffix = Path(path).suffix.lower()

            # ------------------------------------------------
            # WINDOWS EXECUTABLE — V5.5
            # ------------------------------------------------

            if suffix == ".exe":
                try:
                    inspection = (
                        self.artifacts
                        .inspect_executable(
                            path
                        )
                    )
                except Exception as exc:
                    return WorkerResult(
                        True,
                        (
                            "VERDICT : NON VALIDÉ\n\n"
                            "Inspection de l'exécutable impossible : "
                            f"{path}\n{exc}"
                        ),
                        {
                            "worker": self.name,
                            "verdict": "NON_VALIDÉ",
                            "targets": paths,
                            "tests": tests,
                        },
                    )

                inspection_data = inspection.to_dict()
                reads.append(
                    {
                        "path": path,
                        "binary": True,
                        "inspection": inspection_data,
                    }
                )
                tests.append(
                    {
                        "mode": "pe_inspection",
                        **inspection_data,
                    }
                )

                if not inspection.valid_windows_executable:
                    return WorkerResult(
                        True,
                        (
                            "VERDICT : NON VALIDÉ\n\n"
                            "Le fichier produit n'est pas "
                            "un exécutable PE Windows valide."
                        ),
                        {
                            "worker": self.name,
                            "verdict": "NON_VALIDÉ",
                            "targets": paths,
                            "tests": tests,
                        },
                    )

                try:
                    execution = (
                        self.artifacts
                        .run_executable_test(
                            path
                        )
                    )
                except ArtifactError as exc:
                    return WorkerResult(
                        True,
                        (
                            "VERDICT : NON VALIDÉ\n\n"
                            "Le self-test de l'exécutable "
                            f"n'a pas pu être lancé : {exc}"
                        ),
                        {
                            "worker": self.name,
                            "verdict": "NON_VALIDÉ",
                            "targets": paths,
                            "tests": tests,
                        },
                    )

                test_data = execution.to_dict()
                test_data["mode"] = "exe_self_test"
                tests.append(
                    test_data
                )

                if not execution.success:
                    return WorkerResult(
                        True,
                        (
                            "VERDICT : NON VALIDÉ\n\n"
                            "L'exécutable existe réellement, "
                            "mais son --self-test a échoué."
                        ),
                        {
                            "worker": self.name,
                            "verdict": "NON_VALIDÉ",
                            "targets": paths,
                            "tests": tests,
                        },
                    )

                continue

            # ------------------------------------------------
            # TEXT FILE
            # ------------------------------------------------

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
                        f"{path}\n{exc}"
                    ),
                    {
                        "worker": self.name,
                        "verdict": "NON_VALIDÉ",
                        "targets": paths,
                        "tests": tests,
                    },
                )

            if suffix == ".py":
                try:
                    compilation = self.runner.compile_file(
                        path
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
                            "verdict": "NON_VALIDÉ",
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
                            "La compilation Python réelle a échoué."
                        ),
                        {
                            "worker": self.name,
                            "verdict": "NON_VALIDÉ",
                            "targets": paths,
                            "tests": tests,
                        },
                    )

                if (
                    path.replace(
                        "\\",
                        "/",
                    ).startswith(
                        (
                            "tests/",
                            "applications/",
                        )
                    )
                    and not syntax_only
                    and not DeveloperWorker._is_executable_request(
                        original_message
                    )
                ):
                    execution = self.runner.run_file(
                        path
                    )
                    tests.append(
                        execution.to_dict()
                    )

                    if not execution.success:
                        return WorkerResult(
                            True,
                            (
                                "VERDICT : NON VALIDÉ\n\n"
                                "L'exécution réelle a échoué."
                            ),
                            {
                                "worker": self.name,
                                "verdict": "NON_VALIDÉ",
                                "targets": paths,
                                "tests": tests,
                            },
                        )

        if syntax_only:
            return WorkerResult(
                True,
                (
                    "VERDICT : VALIDÉ\n\n"
                    "La compilation Python réelle a réussi "
                    "pour tous les fichiers Python ciblés."
                ),
                {
                    "worker": self.name,
                    "verdict": "VALIDÉ",
                    "test_mode": "syntax",
                    "targets": paths,
                    "tests": tests,
                },
            )

        evidence = json.dumps(
            {
                "reads": reads,
                "tests": tests,
            },
            ensure_ascii=False,
            indent=2,
        )

        try:
            answer = self.llm.chat(
                (
                    "DEMANDE:\n"
                    f"{task['description']}\n\n"
                    "PREUVES RÉELLES:\n"
                    f"{evidence}\n\n"
                    "N'invente aucun échec. "
                    "Ne confonds pas non testé et incorrect. "
                    "Pour un .exe, un PE valide et un self-test réussi "
                    "sont des preuves positives réelles. "
                    "Tout NON VALIDÉ doit citer une preuve concrète. "
                    "Commence par VERDICT : VALIDÉ "
                    "ou VERDICT : NON VALIDÉ."
                )
            )
        except LLMError as exc:
            return WorkerResult(
                False,
                "Revue LLM impossible.",
                {},
                str(exc),
            )

        if answer.upper().startswith(
            "VERDICT : NON VALIDÉ"
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
