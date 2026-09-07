"""
Developer Agent-OS V2.3.4.

Le Developer possède un accès réel aux fichiers du projet.

Principes :
- Python détermine l'opération demandée ;
- Python identifie les chemins explicites ;
- le LLM ne décide pas s'il faut ignorer une écriture explicite ;
- pour une création/modification, le contenu complet est généré
  en texte brut et non dans une grosse structure JSON ;
- le Permission Engine reste responsable de l'autorisation ;
- une modification existante peut donc produire
  approval_required sans être réellement appliquée.
"""

from __future__ import annotations

import json
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
    ProjectToolError,
)

from v2.workers.worker import (
    Worker,
    WorkerResult,
)


class DeveloperWorker(Worker):

    name = "developer"

    description = (
        "Developer avec accès réel aux fichiers "
        "du projet Agent-OS."
    )

    FILE_EXTENSIONS = {
        ".py",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".toml",
        ".ini",
        ".cfg",
        ".html",
        ".css",
        ".js",
        ".ts",
    }

    CREATE_WORDS = (
        "crée",
        "cree",
        "créer",
        "creer",
        "nouveau fichier",
        "nouvelle fichier",
    )

    MODIFY_WORDS = (
        "modifie",
        "modifier",
        "corrige",
        "corriger",
        "ajoute",
        "ajouter",
        "remplace",
        "remplacer",
        "mets à jour",
        "met à jour",
        "mise à jour",
    )

    def __init__(
        self,
        llm: LLM | None = None,
        permissions: PermissionEngine | None = None,
        project_tool: ProjectFilesTool | None = None,
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

    # ========================================================
    # JSON
    # ========================================================

    @staticmethod
    def _parse_json(
        raw: str,
    ) -> dict[str, Any]:

        text = raw.strip()

        if text.startswith("```json"):
            text = text[len("```json"):].strip()

        elif text.startswith("```"):
            text = text[len("```"):].strip()

        if text.endswith("```"):
            text = text[:-3].strip()

        try:

            data = json.loads(
                text
            )

            if isinstance(
                data,
                dict,
            ):
                return data

        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")

        if (
            start == -1
            or end == -1
            or end <= start
        ):
            return {}

        try:

            data = json.loads(
                text[start:end + 1]
            )

        except json.JSONDecodeError:
            return {}

        if not isinstance(
            data,
            dict,
        ):
            return {}

        return data

    # ========================================================
    # OPERATION
    # ========================================================

    @classmethod
    def _detect_operation(
        cls,
        text: str,
    ) -> str:

        lower = text.lower()

        if any(
            word in lower
            for word in cls.CREATE_WORDS
        ):
            return "create"

        if any(
            word in lower
            for word in cls.MODIFY_WORDS
        ):
            return "modify"

        return "analysis"

    # ========================================================
    # PATH EXTRACTION
    # ========================================================

    @classmethod
    def _extract_file_paths(
        cls,
        text: str,
    ) -> list[str]:

        normalized = (
            text
            .replace("\\", "/")
            .replace("`", " ")
            .replace('"', " ")
            .replace("'", " ")
        )

        candidates = re.findall(
            r"""
            (?:
                [A-Za-z0-9_.-]+/
            )*
            [A-Za-z0-9_.-]+
            \.
            [A-Za-z0-9_-]+
            """,
            normalized,
            flags=re.VERBOSE,
        )

        paths: list[str] = []

        for candidate in candidates:

            candidate = (
                candidate
                .strip()
                .strip(".,;:()[]{}")
            )

            suffix = (
                Path(candidate)
                .suffix
                .lower()
            )

            if suffix not in cls.FILE_EXTENSIONS:
                continue

            if candidate not in paths:
                paths.append(candidate)

        return paths

    # ========================================================
    # TREE
    # ========================================================

    @staticmethod
    def _prioritize_tree(
        tree: str,
        request: str,
    ) -> str:

        lower = request.lower()

        concerns_v2 = (
            "agent-os v2" in lower
            or "agent os v2" in lower
            or "v2/" in lower
            or "v2\\" in lower
        )

        if not concerns_v2:
            return tree

        lines = tree.splitlines()

        priority_lines = []
        other_lines = []

        for line in lines:

            if (
                line.startswith("v2/")
                or line == "v2/"
                or line.startswith("run_v2.py")
            ):
                priority_lines.append(line)

            else:
                other_lines.append(line)

        return "\n".join(
            priority_lines
            + [
                "",
                "===== AUTRES FICHIERS =====",
            ]
            + other_lines
        )

    # ========================================================
    # READ
    # ========================================================

    def _read_file(
        self,
        path: str,
    ) -> dict[str, Any]:

        try:

            result = (
                self.project_tool
                .read_file(path)
            )

            return result.to_dict()

        except ProjectToolError as exc:

            return {
                "path": path,
                "error": str(exc),
            }

        except Exception as exc:

            return {
                "path": path,
                "error": str(exc),
            }

    # ========================================================
    # FILE SELECTION FOR ANALYSIS
    # ========================================================

    def _select_analysis_files(
        self,
        *,
        title: str,
        description: str,
        dependency_context: Any,
        project_tree: str,
    ) -> list[str]:

        prompt = f"""
Tu es le Developer Agent-OS V2.

Tu dois sélectionner les fichiers existants
strictement utiles pour analyser cette tâche.

TITRE :
{title}

DESCRIPTION :
{description}

CONTEXTE :
{dependency_context or "(aucun)"}

ARBORESCENCE :
{project_tree}

RÈGLES :

- maximum 6 fichiers ;
- si la tâche concerne V2, privilégie v2/ ;
- n'utilise pas l'ancien dossier agents/
  sauf nécessité explicite ;
- ne choisis que des fichiers existants.

Retourne uniquement du JSON :

{{
    "files_to_read": [
        "v2/fichier.py"
    ]
}}
"""

        try:

            raw = self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Sélection de fichiers. "
                    "JSON uniquement."
                ),
            )

        except Exception:
            return []

        data = self._parse_json(raw)

        files = data.get(
            "files_to_read",
            [],
        )

        if not isinstance(files, list):
            return []

        result = []

        for item in files[:6]:

            path = str(item).strip()

            if path and path not in result:
                result.append(path)

        return result

    # ========================================================
    # FORMAT CONTEXT
    # ========================================================

    @staticmethod
    def _format_file_context(
        read_results: list[dict[str, Any]],
    ) -> str:

        if not read_results:
            return "(aucun fichier lu)"

        sections = []

        for item in read_results:

            path = item.get(
                "path",
                "?",
            )

            error = item.get(
                "error"
            )

            if error:

                sections.append(
                    (
                        f"===== {path} =====\n"
                        f"ERREUR : {error}"
                    )
                )

                continue

            sections.append(
                (
                    f"===== {path} =====\n"
                    f"{item.get('content', '')}"
                )
            )

        return "\n\n".join(sections)

    # ========================================================
    # RAW CONTENT
    # ========================================================

    @staticmethod
    def _clean_generated_content(
        raw: str,
    ) -> str:

        text = raw.strip()

        if not text:
            return ""

        if text.startswith("```"):

            first_newline = text.find("\n")

            if first_newline != -1:
                text = text[first_newline + 1:]

            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]

        return text.strip()

    # ========================================================
    # GENERATE FILE
    # ========================================================

    def _generate_file_content(
        self,
        *,
        operation: str,
        target_path: str,
        title: str,
        description: str,
        original_message: str,
        current_content: str,
        dependency_context: Any,
        project_tree: str,
    ) -> str:

        if operation == "modify":

            operation_instruction = f"""
Le fichier existe déjà.

Voici son CONTENU ACTUEL :

============================================================
CONTENU ACTUEL DE {target_path}
============================================================

{current_content}

============================================================
INSTRUCTION
============================================================

Applique uniquement la modification demandée.

Conserve tout le reste du fichier.

Tu dois retourner le FICHIER COMPLET
après modification.
"""

        else:

            operation_instruction = """
Le fichier n'existe pas encore.

Crée son contenu complet conformément
à la demande.
"""

        prompt = f"""
Tu es le Developer d'Agent-OS V2.

============================================================
DEMANDE ORIGINALE
============================================================

{original_message or description}

============================================================
TITRE
============================================================

{title}

============================================================
DESCRIPTION
============================================================

{description}

============================================================
FICHIER CIBLE
============================================================

{target_path}

============================================================
OPÉRATION
============================================================

{operation}

============================================================
CONTEXTE
============================================================

{dependency_context or "(aucun)"}

============================================================
ARBORESCENCE
============================================================

{project_tree}

============================================================

{operation_instruction}

============================================================
FORMAT OBLIGATOIRE
============================================================

Retourne UNIQUEMENT le contenu complet final
du fichier {target_path}.

Aucune explication.
Aucun JSON.
Aucun bloc Markdown.
"""

        raw = self.llm.simple_chat(
            prompt=prompt,
            system_prompt=(
                "Tu es le Developer Agent-OS. "
                "Retourne uniquement le contenu "
                "final du fichier demandé."
            ),
        )

        return self._clean_generated_content(
            raw
        )

    # ========================================================
    # ANALYSIS
    # ========================================================

    def _execute_analysis(
        self,
        *,
        task: Dict[str, Any],
        title: str,
        description: str,
        dependency_context: Any,
        project_tree: str,
    ) -> WorkerResult:

        files_to_read = (
            self._select_analysis_files(
                title=title,
                description=description,
                dependency_context=dependency_context,
                project_tree=project_tree,
            )
        )

        read_results = [
            self._read_file(path)
            for path in files_to_read
        ]

        file_context = (
            self._format_file_context(
                read_results
            )
        )

        prompt = f"""
Tu es le Developer Agent-OS V2.

Tu dois produire un rapport technique.

TITRE :
{title}

DESCRIPTION :
{description}

CONTEXTE :
{dependency_context or "(aucun)"}

ARBORESCENCE :
{project_tree}

FICHIERS RÉELLEMENT LUS :
{file_context}

Analyse uniquement les informations
réellement disponibles.

N'affirme jamais avoir modifié,
créé ou exécuté un fichier.

Produis un rapport technique clair en français.
"""

        try:

            report = self.llm.simple_chat(
                prompt=prompt,
                system_prompt=(
                    "Tu produis un rapport "
                    "technique Agent-OS."
                ),
            )

        except LLMError as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Le Developer ne peut pas "
                    "contacter le modèle."
                ),
                error=str(exc),
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Erreur d'analyse Developer."
                ),
                error=str(exc),
            )

        return WorkerResult(
            success=True,
            message=report.strip(),
            data={
                "worker": self.name,
                "type": "development",
                "task_id": task.get("id"),
                "model": self.llm.model,
                "operation": "analysis",
                "files_requested": files_to_read,
                "files_read": read_results,
                "writes": [],
                "created_files": [],
                "modified_files": [],
                "approval_required_files": [],
                "proposed_writes": [],
            },
        )

    # ========================================================
    # FILE OPERATION
    # ========================================================

    def _execute_file_operation(
        self,
        *,
        task: Dict[str, Any],
        title: str,
        description: str,
        original_message: str,
        operation: str,
        requested_paths: list[str],
        dependency_context: Any,
        project_tree: str,
    ) -> WorkerResult:

        if not requested_paths:

            return WorkerResult(
                success=False,
                message=(
                    "Une opération sur fichier a été "
                    "détectée mais aucun chemin "
                    "explicite n'a été trouvé."
                ),
                error="explicit_file_path_missing",
            )

        read_results = []
        generated_writes = []
        write_results = []

        created_files = []
        modified_files = []
        approval_required_files = []
        errors = []

        for target_path in requested_paths:

            current_content = ""

            if operation == "modify":

                read_result = (
                    self._read_file(
                        target_path
                    )
                )

                read_results.append(
                    read_result
                )

                if read_result.get("error"):

                    return WorkerResult(
                        success=False,
                        message=(
                            "Impossible de lire "
                            "le fichier à modifier."
                        ),
                        error=(
                            f"{target_path}: "
                            f"{read_result.get('error')}"
                        ),
                    )

                current_content = str(
                    read_result.get(
                        "content",
                        "",
                    )
                )

                if not current_content:

                    return WorkerResult(
                        success=False,
                        message=(
                            "Le fichier à modifier "
                            "est vide ou illisible."
                        ),
                        error="empty_target_file",
                    )

            try:

                generated_content = (
                    self._generate_file_content(
                        operation=operation,
                        target_path=target_path,
                        title=title,
                        description=description,
                        original_message=original_message,
                        current_content=current_content,
                        dependency_context=dependency_context,
                        project_tree=project_tree,
                    )
                )

            except LLMError as exc:

                return WorkerResult(
                    success=False,
                    message=(
                        "Le Developer ne peut "
                        "pas contacter le modèle."
                    ),
                    error=str(exc),
                )

            except Exception as exc:

                return WorkerResult(
                    success=False,
                    message=(
                        "Erreur pendant la génération "
                        "du fichier."
                    ),
                    error=str(exc),
                )

            if not generated_content:

                return WorkerResult(
                    success=False,
                    message=(
                        "Le modèle n'a généré "
                        "aucun contenu."
                    ),
                    error="generated_file_content_empty",
                )

            generated_writes.append(
                {
                    "path": target_path,
                    "content": generated_content,
                }
            )

            try:

                write_result = (
                    self.project_tool
                    .write_file(
                        relative_path=target_path,
                        content=generated_content,
                    )
                )

                serialized = (
                    write_result.to_dict()
                )

            except Exception as exc:

                serialized = {
                    "path": target_path,
                    "error": str(exc),
                }

            write_results.append(
                serialized
            )

            if serialized.get("created"):
                created_files.append(target_path)

            if serialized.get("modified"):
                modified_files.append(target_path)

            if serialized.get(
                "approval_required"
            ):
                approval_required_files.append(
                    target_path
                )

            if serialized.get("error"):
                errors.append(serialized)

        if operation == "create":

            missing = [
                path
                for path in requested_paths
                if path not in created_files
            ]

            if missing:

                return WorkerResult(
                    success=False,
                    message=(
                        "La création demandée "
                        "n'a pas été effectuée."
                    ),
                    error=(
                        "missing_created_files: "
                        + ", ".join(missing)
                    ),
                    data={
                        "worker": self.name,
                        "operation": operation,
                        "requested_paths": requested_paths,
                        "writes": write_results,
                        "proposed_writes": generated_writes,
                    },
                )

        if operation == "modify":

            handled = set(
                modified_files
                + approval_required_files
            )

            missing = [
                path
                for path in requested_paths
                if path not in handled
            ]

            if missing:

                return WorkerResult(
                    success=False,
                    message=(
                        "La modification n'a été "
                        "ni exécutée ni soumise "
                        "à approbation."
                    ),
                    error=(
                        "modification_not_handled: "
                        + ", ".join(missing)
                    ),
                    data={
                        "worker": self.name,
                        "operation": operation,
                        "requested_paths": requested_paths,
                        "writes": write_results,
                        "proposed_writes": generated_writes,
                    },
                )

        sections = [
            (
                "Opération détectée : "
                f"{operation}"
            ),
            (
                "Fichiers cibles :\n- "
                + "\n- ".join(
                    requested_paths
                )
            ),
        ]

        if created_files:

            sections.append(
                (
                    "Fichiers créés :\n- "
                    + "\n- ".join(
                        created_files
                    )
                )
            )

        if modified_files:

            sections.append(
                (
                    "Fichiers modifiés :\n- "
                    + "\n- ".join(
                        modified_files
                    )
                )
            )

        if approval_required_files:

            sections.append(
                (
                    "Autorisation utilisateur "
                    "requise :\n- "
                    + "\n- ".join(
                        approval_required_files
                    )
                )
            )

        if errors:

            sections.append(
                (
                    "Erreurs :\n"
                    + "\n".join(
                        (
                            f"- {item.get('path')} : "
                            f"{item.get('error')}"
                        )
                        for item in errors
                    )
                )
            )

        return WorkerResult(
            success=True,
            message="\n\n".join(
                sections
            ),
            data={
                "worker": self.name,
                "type": "development",
                "task_id": task.get("id"),
                "model": self.llm.model,
                "operation": operation,
                "requested_paths": requested_paths,
                "files_requested": (
                    requested_paths
                    if operation == "modify"
                    else []
                ),
                "files_read": read_results,
                "writes": write_results,
                "created_files": created_files,
                "modified_files": modified_files,
                "approval_required_files": (
                    approval_required_files
                ),
                "proposed_writes": (
                    generated_writes
                ),
            },
        )

    # ========================================================
    # EXECUTE
    # ========================================================

    def execute(
        self,
        task: Dict[str, Any],
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
            or ""
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

        operation = (
            self._detect_operation(
                full_request
            )
        )

        requested_paths = (
            self._extract_file_paths(
                full_request
            )
        )

        try:

            project_tree = (
                self.project_tool
                .format_tree(
                    max_depth=5,
                    max_entries=400,
                )
            )

        except Exception as exc:

            return WorkerResult(
                success=False,
                message=(
                    "Impossible de lire "
                    "l'arborescence du projet."
                ),
                error=str(exc),
            )

        project_tree = (
            self._prioritize_tree(
                project_tree,
                full_request,
            )
        )

        if operation in {
            "create",
            "modify",
        }:

            return (
                self._execute_file_operation(
                    task=task,
                    title=title,
                    description=description,
                    original_message=original_message,
                    operation=operation,
                    requested_paths=requested_paths,
                    dependency_context=dependency_context,
                    project_tree=project_tree,
                )
            )

        return (
            self._execute_analysis(
                task=task,
                title=title,
                description=description,
                dependency_context=dependency_context,
                project_tree=project_tree,
            )
        )