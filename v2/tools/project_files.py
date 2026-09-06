"""
Outils fichiers Agent-OS V2.3.1.

Permet aux workers de :
- voir l'arborescence du projet ;
- lire des fichiers texte ;
- créer de nouveaux fichiers ;
- détecter qu'une modification nécessite une approbation.

IMPORTANT :
Les permissions sont contrôlées ici,
hors du LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v2.config import BASE_DIR

from v2.permissions.permissions import (
    PermissionEngine,
    PermissionResult,
)


# ============================================================
# EXCEPTIONS
# ============================================================


class ProjectToolError(Exception):
    """
    Erreur générique d'un outil projet.
    """


class ProjectPermissionError(ProjectToolError):
    """
    Permission refusée ou approbation nécessaire.
    """

    def __init__(
        self,
        action: str,
        result: PermissionResult,
        reason: str,
    ) -> None:

        self.action = action
        self.result = result
        self.reason = reason

        super().__init__(
            f"{action}: {result.value} - {reason}"
        )


# ============================================================
# DATA
# ============================================================


@dataclass
class FileReadResult:

    path: str

    content: str

    truncated: bool = False

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "path": self.path,
            "content": self.content,
            "truncated": self.truncated,
        }


@dataclass
class FileWriteResult:

    path: str

    created: bool = False

    modified: bool = False

    approval_required: bool = False

    message: str = ""

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "path": self.path,
            "created": self.created,
            "modified": self.modified,
            "approval_required": (
                self.approval_required
            ),
            "message": self.message,
        }


# ============================================================
# TOOL
# ============================================================


class ProjectFilesTool:
    """
    Outils fichiers limités au répertoire Agent-OS.
    """

    IGNORED_DIRECTORIES = {
        ".git",
        ".idea",
        ".vscode",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
    }

    IGNORED_PREFIXES = (
        "data/v2/",
    )

    DEFAULT_MAX_READ_CHARS = 30_000

    def __init__(
        self,
        permissions: PermissionEngine,
        project_root: Path | None = None,
    ) -> None:

        self.permissions = permissions

        self.project_root = (
            project_root
            or BASE_DIR
        ).resolve()

    # ========================================================
    # PERMISSIONS
    # ========================================================

    def _require_allowed(
        self,
        action: str,
    ) -> None:

        permission = (
            self.permissions.check(
                action
            )
        )

        if (
            permission.result
            == PermissionResult.ALLOWED
        ):
            return

        raise ProjectPermissionError(
            action=action,
            result=permission.result,
            reason=permission.reason,
        )

    # ========================================================
    # PATH SECURITY
    # ========================================================

    def _resolve_path(
        self,
        relative_path: str,
    ) -> Path:

        relative_path = (
            relative_path
            .strip()
            .replace("\\", "/")
        )

        if not relative_path:

            raise ProjectToolError(
                "Chemin vide."
            )

        candidate = (
            self.project_root
            / relative_path
        ).resolve()

        try:

            candidate.relative_to(
                self.project_root
            )

        except ValueError as exc:

            raise ProjectToolError(
                "Accès hors du projet interdit."
            ) from exc

        return candidate

    def _relative(
        self,
        path: Path,
    ) -> str:

        return (
            path
            .resolve()
            .relative_to(
                self.project_root
            )
            .as_posix()
        )

    # ========================================================
    # TREE
    # ========================================================

    def list_project(
        self,
        max_depth: int = 4,
        max_entries: int = 300,
    ) -> list[str]:

        self._require_allowed(
            "read_project"
        )

        entries: list[str] = []

        def walk(
            directory: Path,
            depth: int,
        ) -> None:

            if (
                depth
                > max_depth
            ):
                return

            try:

                children = sorted(
                    directory.iterdir(),
                    key=lambda p: (
                        p.is_file(),
                        p.name.lower(),
                    ),
                )

            except OSError:
                return

            for child in children:

                if (
                    len(entries)
                    >= max_entries
                ):
                    return

                relative = (
                    self._relative(
                        child
                    )
                )

                if (
                    child.is_dir()
                    and child.name
                    in self.IGNORED_DIRECTORIES
                ):
                    continue

                if any(
                    relative.startswith(
                        prefix
                    )
                    for prefix
                    in self.IGNORED_PREFIXES
                ):
                    continue

                if child.is_dir():

                    entries.append(
                        f"{relative}/"
                    )

                    walk(
                        child,
                        depth + 1,
                    )

                else:

                    entries.append(
                        relative
                    )

        walk(
            self.project_root,
            0,
        )

        return entries

    def format_tree(
        self,
        max_depth: int = 4,
        max_entries: int = 300,
    ) -> str:

        entries = (
            self.list_project(
                max_depth=max_depth,
                max_entries=max_entries,
            )
        )

        if not entries:

            return (
                "(projet vide)"
            )

        return "\n".join(
            entries
        )

    # ========================================================
    # READ
    # ========================================================

    def read_file(
        self,
        relative_path: str,
        max_chars: int | None = None,
    ) -> FileReadResult:

        self._require_allowed(
            "read_file"
        )

        path = (
            self._resolve_path(
                relative_path
            )
        )

        if not path.exists():

            raise ProjectToolError(
                f"Fichier introuvable : "
                f"{relative_path}"
            )

        if not path.is_file():

            raise ProjectToolError(
                f"Ce chemin n'est pas "
                f"un fichier : {relative_path}"
            )

        try:

            content = path.read_text(
                encoding="utf-8"
            )

        except UnicodeDecodeError as exc:

            raise ProjectToolError(
                "Le fichier n'est pas "
                "un fichier texte UTF-8."
            ) from exc

        except OSError as exc:

            raise ProjectToolError(
                f"Lecture impossible : {exc}"
            ) from exc

        limit = (
            max_chars
            or self.DEFAULT_MAX_READ_CHARS
        )

        truncated = (
            len(content)
            > limit
        )

        if truncated:

            content = (
                content[:limit]
                + "\n\n[CONTENU TRONQUÉ]"
            )

        return FileReadResult(
            path=self._relative(
                path
            ),
            content=content,
            truncated=truncated,
        )

    # ========================================================
    # WRITE
    # ========================================================

    def write_file(
        self,
        relative_path: str,
        content: str,
    ) -> FileWriteResult:

        path = (
            self._resolve_path(
                relative_path
            )
        )

        relative = (
            self._relative(
                path
            )
        )

        # ----------------------------------------------------
        # EXISTING FILE
        # ----------------------------------------------------

        if path.exists():

            permission = (
                self.permissions.check(
                    "modify_code"
                )
            )

            if (
                permission.result
                == PermissionResult.APPROVAL_REQUIRED
            ):

                return FileWriteResult(
                    path=relative,
                    approval_required=True,
                    message=(
                        "Modification non exécutée : "
                        "approbation utilisateur requise."
                    ),
                )

            if (
                permission.result
                != PermissionResult.ALLOWED
            ):

                raise ProjectPermissionError(
                    action="modify_code",
                    result=permission.result,
                    reason=permission.reason,
                )

            try:

                path.write_text(
                    content,
                    encoding="utf-8",
                )

            except OSError as exc:

                raise ProjectToolError(
                    f"Écriture impossible : {exc}"
                ) from exc

            return FileWriteResult(
                path=relative,
                modified=True,
                message=(
                    "Fichier existant modifié."
                ),
            )

        # ----------------------------------------------------
        # NEW FILE
        # ----------------------------------------------------

        self._require_allowed(
            "create_file"
        )

        try:

            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            path.write_text(
                content,
                encoding="utf-8",
            )

        except OSError as exc:

            raise ProjectToolError(
                f"Création impossible : {exc}"
            ) from exc

        return FileWriteResult(
            path=relative,
            created=True,
            message=(
                "Nouveau fichier créé."
            ),
        )