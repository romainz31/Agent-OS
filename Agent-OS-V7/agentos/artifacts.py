from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentos.config import WORKSPACE_DIR
from agentos.permissions import Decision, PermissionEngine


class ArtifactError(RuntimeError):
    pass


@dataclass
class BuildResult:
    success: bool
    source_path: str
    artifact_path: str
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ArtifactInspection:
    path: str
    exists: bool
    size: int
    sha256: str
    mz_header: bool
    pe_signature: bool

    @property
    def valid_windows_executable(self) -> bool:
        return (
            self.exists
            and self.size > 0
            and self.mz_header
            and self.pe_signature
        )

    def to_dict(self) -> dict[str, Any]:
        result = self.__dict__.copy()
        result["valid_windows_executable"] = (
            self.valid_windows_executable
        )
        return result


@dataclass
class ArtifactRunResult:
    path: str
    success: bool
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class ArtifactBuilder:
    """Builder V5.5 volontairement étroit.

    Il ne fournit aucun shell générique. Il sait uniquement :
    - transformer un fichier Python du workspace en .exe Windows via PyInstaller ;
    - inspecter un .exe du workspace ;
    - lancer un .exe du workspace dans le cadre d'un test borné.
    """

    SELF_TEST_MARKER = "AGENTOS_SELF_TEST_OK"

    def __init__(
        self,
        permissions: PermissionEngine,
        root: Path = WORKSPACE_DIR,
    ) -> None:
        self.permissions = permissions
        self.root = root.resolve()
        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _resolve(
        self,
        relative_path: str,
    ) -> Path:
        value = str(relative_path).strip().replace(
            "\\",
            "/",
        )

        if not value:
            raise ArtifactError(
                "Chemin vide."
            )

        path = (
            self.root / value
        ).resolve()

        try:
            path.relative_to(
                self.root
            )
        except ValueError as exc:
            raise ArtifactError(
                "Chemin hors workspace interdit."
            ) from exc

        return path

    def _relative(
        self,
        path: Path,
    ) -> str:
        return path.relative_to(
            self.root
        ).as_posix()

    def exists(
        self,
        relative_path: str,
    ) -> bool:
        return self._resolve(
            relative_path
        ).exists()

    def unique_source_path(
        self,
        stem: str,
    ) -> str:
        clean_stem = (
            stem.strip()
            or "application"
        )

        index = 1

        while True:
            suffix = (
                ""
                if index == 1
                else f"_{index}"
            )

            candidate = (
                f"applications/"
                f"{clean_stem}{suffix}.py"
            )

            if not self.exists(
                candidate
            ):
                return candidate

            index += 1

    def unique_artifact_path(
        self,
        stem: str,
    ) -> str:
        clean_stem = (
            stem.strip()
            or "application"
        )

        index = 1

        while True:
            suffix = (
                ""
                if index == 1
                else f"_{index}"
            )

            candidate = (
                f"dist/"
                f"{clean_stem}{suffix}.exe"
            )

            if not self.exists(
                candidate
            ):
                return candidate

            index += 1

    def build_windows_executable(
        self,
        *,
        source_path: str,
        artifact_path: str,
        windowed: bool = False,
        timeout: int = 180,
    ) -> BuildResult:
        permission = self.permissions.check(
            "build_artifact"
        )

        if (
            permission.decision
            != Decision.ALLOWED
        ):
            return BuildResult(
                False,
                source_path,
                artifact_path,
                None,
                error=permission.reason,
            )

        if os.name != "nt":
            return BuildResult(
                False,
                source_path,
                artifact_path,
                None,
                error=(
                    "La création d'un .exe Windows "
                    "doit être exécutée sur Windows."
                ),
            )

        source = self._resolve(
            source_path
        )
        artifact = self._resolve(
            artifact_path
        )

        if (
            not source.exists()
            or not source.is_file()
            or source.suffix.lower()
            != ".py"
        ):
            return BuildResult(
                False,
                source_path,
                artifact_path,
                None,
                error=(
                    "Source Python introuvable."
                ),
            )

        if artifact.suffix.lower() != ".exe":
            return BuildResult(
                False,
                source_path,
                artifact_path,
                None,
                error=(
                    "La cible de build doit "
                    "être un fichier .exe."
                ),
            )

        if artifact.exists():
            return BuildResult(
                False,
                source_path,
                artifact_path,
                None,
                error=(
                    "L'exécutable cible existe déjà. "
                    "Agent-OS refuse de l'écraser "
                    "automatiquement."
                ),
            )

        if (
            importlib.util.find_spec(
                "PyInstaller"
            )
            is None
        ):
            return BuildResult(
                False,
                source_path,
                artifact_path,
                None,
                error=(
                    "PyInstaller n'est pas installé. "
                    "Exécute : pip install -r requirements.txt"
                ),
            )

        artifact.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        build_root = (
            self.root
            / ".agentos_build"
            / artifact.stem
        )
        work_dir = build_root / "work"
        spec_dir = build_root / "spec"

        work_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        spec_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            artifact.stem,
            "--distpath",
            str(
                artifact.parent
            ),
            "--workpath",
            str(
                work_dir
            ),
            "--specpath",
            str(
                spec_dir
            ),
        ]

        if windowed:
            command.append(
                "--windowed"
            )

        command.append(
            str(source)
        )

        try:
            result = subprocess.run(
                command,
                cwd=str(
                    self.root
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(
                    30,
                    min(
                        int(timeout),
                        300,
                    ),
                ),
                shell=False,
            )

        except subprocess.TimeoutExpired as exc:
            return BuildResult(
                False,
                self._relative(
                    source
                ),
                self._relative(
                    artifact
                ),
                None,
                stdout=(
                    exc.stdout
                    or ""
                ),
                stderr=(
                    exc.stderr
                    or ""
                ),
                timed_out=True,
                error=(
                    "Build PyInstaller expiré."
                ),
            )

        success = (
            result.returncode == 0
            and artifact.exists()
            and artifact.is_file()
        )

        build_result = BuildResult(
            success,
            self._relative(
                source
            ),
            self._relative(
                artifact
            ),
            result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            error=(
                None
                if success
                else (
                    "PyInstaller n'a pas produit "
                    "l'exécutable attendu."
                )
            ),
        )

        if success:
            shutil.rmtree(
                build_root,
                ignore_errors=True,
            )

        return build_result

    def inspect_executable(
        self,
        relative_path: str,
    ) -> ArtifactInspection:
        path = self._resolve(
            relative_path
        )

        if (
            not path.exists()
            or not path.is_file()
        ):
            return ArtifactInspection(
                self._relative(path),
                False,
                0,
                "",
                False,
                False,
            )

        data = path.read_bytes()

        mz_header = (
            len(data) >= 2
            and data[:2] == b"MZ"
        )

        pe_signature = False

        if (
            mz_header
            and len(data) >= 0x40
        ):
            pe_offset = int.from_bytes(
                data[0x3C:0x40],
                byteorder="little",
                signed=False,
            )

            if (
                pe_offset >= 0
                and pe_offset + 4
                <= len(data)
            ):
                pe_signature = (
                    data[
                        pe_offset:
                        pe_offset + 4
                    ]
                    == b"PE\x00\x00"
                )

        return ArtifactInspection(
            self._relative(path),
            True,
            len(data),
            hashlib.sha256(
                data
            ).hexdigest(),
            mz_header,
            pe_signature,
        )

    def run_executable_test(
        self,
        relative_path: str,
        *,
        timeout: int = 15,
    ) -> ArtifactRunResult:
        permission = self.permissions.check(
            "run_artifact_test"
        )

        if (
            permission.decision
            != Decision.ALLOWED
        ):
            raise ArtifactError(
                permission.reason
            )

        if os.name != "nt":
            raise ArtifactError(
                "Test .exe disponible uniquement sur Windows."
            )

        path = self._resolve(
            relative_path
        )

        if (
            not path.exists()
            or not path.is_file()
            or path.suffix.lower()
            != ".exe"
        ):
            raise ArtifactError(
                "Exécutable introuvable."
            )

        try:
            result = subprocess.run(
                [
                    str(path),
                    "--self-test",
                ],
                cwd=str(
                    self.root
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(
                    3,
                    min(
                        int(timeout),
                        30,
                    ),
                ),
                shell=False,
            )

        except subprocess.TimeoutExpired as exc:
            return ArtifactRunResult(
                self._relative(path),
                False,
                None,
                stdout=(
                    exc.stdout
                    or ""
                ),
                stderr=(
                    exc.stderr
                    or ""
                ),
                timed_out=True,
            )

        # Un exécutable PyInstaller construit avec --windowed n'a pas
        # forcément de stdout sous Windows. Le contrat du self-test repose
        # donc sur un code retour 0 ; le marqueur stdout reste une preuve
        # supplémentaire lorsqu'une console est disponible.
        success = (
            result.returncode == 0
        )

        return ArtifactRunResult(
            self._relative(path),
            success,
            result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
