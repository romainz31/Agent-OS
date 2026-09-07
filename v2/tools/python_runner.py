"""
Python Runner sécurisé Agent-OS V2.3.6.

Objectif :
- vérifier réellement la syntaxe Python ;
- permettre une exécution Python contrôlée
  uniquement dans certains dossiers ;
- ne jamais utiliser shell=True ;
- imposer un timeout ;
- interdire les chemins hors du projet.

IMPORTANT :
Ce runner est contraint, mais ce n'est pas
une sandbox de sécurité complète.

Un script Python exécuté peut théoriquement
accéder aux ressources permises au processus Python.

Pour cette raison :
- v2/ est limité à la compilation ;
- agents/ est limité à la compilation ;
- l'exécution runtime est limitée à
  applications/ et tests/.
"""

from __future__ import annotations

import subprocess
import sys

from dataclasses import (
    dataclass,
)

from pathlib import (
    Path,
)

from typing import (
    Any,
)

from v2.config import (
    BASE_DIR,
)

from v2.permissions.permissions import (
    PermissionEngine,
    PermissionResult,
)


# ============================================================
# EXCEPTIONS
# ============================================================


class PythonRunnerError(
    Exception
):
    """
    Erreur du Python Runner.
    """


# ============================================================
# RESULT
# ============================================================


@dataclass
class PythonRunResult:

    path: str

    mode: str

    success: bool

    returncode: int | None

    stdout: str

    stderr: str

    timed_out: bool = False

    command: list[str] | None = None

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "path": self.path,
            "mode": self.mode,
            "success": self.success,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "command": (
                self.command
                or []
            ),
        }


# ============================================================
# RUNNER
# ============================================================


class PythonRunner:

    DEFAULT_TIMEOUT = 8

    MAX_TIMEOUT = 20

    MAX_OUTPUT_CHARS = 20_000

    RUNTIME_ALLOWED_PREFIXES = (
        "applications/",
        "tests/",
    )

    def __init__(
        self,
        permissions: PermissionEngine,
        project_root: Path | None = None,
    ) -> None:

        self.permissions = (
            permissions
        )

        self.project_root = (
            project_root
            or BASE_DIR
        ).resolve()

    # ========================================================
    # SECURITY
    # ========================================================

    def _require_permission(
        self,
    ) -> None:

        permission = (
            self.permissions.check(
                "run_tests"
            )
        )

        if (
            permission.result
            != PermissionResult.ALLOWED
        ):

            raise PythonRunnerError(
                (
                    "Exécution de tests interdite : "
                    f"{permission.reason}"
                )
            )

    def _resolve_python_file(
        self,
        relative_path: str,
    ) -> Path:

        value = (
            relative_path
            .strip()
            .replace(
                "\\",
                "/",
            )
        )

        if not value:

            raise PythonRunnerError(
                "Chemin vide."
            )

        path = (
            self.project_root
            / value
        ).resolve()

        try:

            path.relative_to(
                self.project_root
            )

        except ValueError as exc:

            raise PythonRunnerError(
                "Chemin hors projet interdit."
            ) from exc

        if not path.exists():

            raise PythonRunnerError(
                (
                    "Fichier introuvable : "
                    f"{relative_path}"
                )
            )

        if not path.is_file():

            raise PythonRunnerError(
                (
                    "La cible n'est pas "
                    "un fichier."
                )
            )

        if (
            path.suffix.lower()
            != ".py"
        ):

            raise PythonRunnerError(
                (
                    "Le Python Runner accepte "
                    "uniquement les fichiers .py."
                )
            )

        return path

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

    @classmethod
    def _limit_output(
        cls,
        value: str,
    ) -> str:

        if (
            len(value)
            <= cls.MAX_OUTPUT_CHARS
        ):

            return value

        return (
            value[
                :cls.MAX_OUTPUT_CHARS
            ]
            + "\n\n[SORTIE TRONQUÉE]"
        )

    @classmethod
    def _safe_timeout(
        cls,
        timeout: int | None,
    ) -> int:

        if timeout is None:

            return (
                cls.DEFAULT_TIMEOUT
            )

        try:

            timeout = int(
                timeout
            )

        except (
            TypeError,
            ValueError,
        ):

            return (
                cls.DEFAULT_TIMEOUT
            )

        return max(
            1,
            min(
                timeout,
                cls.MAX_TIMEOUT,
            ),
        )

    # ========================================================
    # COMPILE
    # ========================================================

    def compile_file(
        self,
        relative_path: str,
        timeout: int | None = None,
    ) -> PythonRunResult:

        self._require_permission()

        path = (
            self._resolve_python_file(
                relative_path
            )
        )

        relative = (
            self._relative(
                path
            )
        )

        safe_timeout = (
            self._safe_timeout(
                timeout
            )
        )

        command = [
            sys.executable,
            "-m",
            "py_compile",
            str(path),
        ]

        try:

            process = (
                subprocess.run(
                    command,
                    cwd=str(
                        self.project_root
                    ),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=safe_timeout,

                    # IMPORTANT :
                    # aucune commande shell.
                    shell=False,
                )
            )

        except subprocess.TimeoutExpired as exc:

            return PythonRunResult(
                path=relative,
                mode="compile",
                success=False,
                returncode=None,
                stdout=(
                    self._limit_output(
                        exc.stdout
                        if isinstance(
                            exc.stdout,
                            str,
                        )
                        else ""
                    )
                ),
                stderr=(
                    self._limit_output(
                        exc.stderr
                        if isinstance(
                            exc.stderr,
                            str,
                        )
                        else ""
                    )
                ),
                timed_out=True,
                command=command,
            )

        return PythonRunResult(
            path=relative,
            mode="compile",
            success=(
                process.returncode
                == 0
            ),
            returncode=(
                process.returncode
            ),
            stdout=(
                self._limit_output(
                    process.stdout
                    or ""
                )
            ),
            stderr=(
                self._limit_output(
                    process.stderr
                    or ""
                )
            ),
            timed_out=False,
            command=command,
        )

    # ========================================================
    # RUNTIME SECURITY
    # ========================================================

    def _runtime_allowed(
        self,
        relative_path: str,
    ) -> bool:

        normalized = (
            relative_path
            .replace(
                "\\",
                "/",
            )
        )

        return any(
            normalized.startswith(
                prefix
            )
            for prefix
            in self.RUNTIME_ALLOWED_PREFIXES
        )

    # ========================================================
    # RUN
    # ========================================================

    def run_file(
        self,
        relative_path: str,
        input_data: str = "",
        timeout: int | None = None,
    ) -> PythonRunResult:

        self._require_permission()

        path = (
            self._resolve_python_file(
                relative_path
            )
        )

        relative = (
            self._relative(
                path
            )
        )

        if not (
            self._runtime_allowed(
                relative
            )
        ):

            raise PythonRunnerError(
                (
                    "Exécution runtime interdite "
                    "pour ce chemin. "
                    "Seuls applications/ et tests/ "
                    "peuvent être exécutés."
                )
            )

        safe_timeout = (
            self._safe_timeout(
                timeout
            )
        )

        command = [
            sys.executable,
            str(path),
        ]

        try:

            process = (
                subprocess.run(
                    command,
                    cwd=str(
                        self.project_root
                    ),
                    input=(
                        input_data
                        or ""
                    ),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=safe_timeout,
                    shell=False,
                )
            )

        except subprocess.TimeoutExpired as exc:

            return PythonRunResult(
                path=relative,
                mode="run",
                success=False,
                returncode=None,
                stdout=(
                    self._limit_output(
                        exc.stdout
                        if isinstance(
                            exc.stdout,
                            str,
                        )
                        else ""
                    )
                ),
                stderr=(
                    self._limit_output(
                        exc.stderr
                        if isinstance(
                            exc.stderr,
                            str,
                        )
                        else ""
                    )
                ),
                timed_out=True,
                command=command,
            )

        return PythonRunResult(
            path=relative,
            mode="run",
            success=(
                process.returncode
                == 0
            ),
            returncode=(
                process.returncode
            ),
            stdout=(
                self._limit_output(
                    process.stdout
                    or ""
                )
            ),
            stderr=(
                self._limit_output(
                    process.stderr
                    or ""
                )
            ),
            timed_out=False,
            command=command,
        )