from __future__ import annotations

import importlib.util
import os
import tempfile

from pathlib import Path

from agentos.artifacts import ArtifactBuilder
from agentos.permissions import Decision, PermissionEngine
from agentos.planner import Planner
from agentos.project_files import ProjectFiles
from agentos.python_runner import PythonRunner
from agentos.workers import DeveloperWorker


class FakeLLM:
    def __init__(self):
        self.calls = []

    def chat(self, prompt, system=None):
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
            }
        )
        raise AssertionError(
            "Le LLM ne devait pas être appelé dans ce test."
        )


CHECKS = 0


def check(condition, message):
    global CHECKS
    CHECKS += 1

    if not condition:
        raise AssertionError(
            f"ÉCHEC #{CHECKS}: {message}"
        )

    print(
        f"[OK {CHECKS:02d}] {message}"
    )


def main():
    permissions = PermissionEngine()

    check(
        permissions.check(
            "build_artifact"
        ).decision
        == Decision.ALLOWED,
        "build_artifact est autorisé",
    )
    check(
        permissions.check(
            "run_artifact_test"
        ).decision
        == Decision.ALLOWED,
        "run_artifact_test est autorisé",
    )
    check(
        permissions.check(
            "shell_command"
        ).decision
        == Decision.BLOCKED,
        "le shell arbitraire reste bloqué",
    )

    fake = FakeLLM()
    planner = Planner(fake)

    message = (
        'crée un .exe qui ouvre une boite de dialogue '
        'avec ecris "coucou coralie"'
    )

    plan = planner.plan(
        message=message,
        initial_worker="developer",
    )

    check(
        len(plan) == 2,
        "la création d'un .exe produit 2 étapes",
    )
    check(
        plan[0].worker == "developer",
        "la première étape va au Developer",
    )
    check(
        plan[1].worker == "tester",
        "la seconde étape va au Tester",
    )
    check(
        plan[1].depends_on == [0],
        "le Tester dépend du Developer",
    )
    check(
        len(fake.calls) == 0,
        "le Planner n'appelle pas le LLM pour ce cas simple",
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        files = ProjectFiles(
            permissions,
            root=root,
        )
        runner = PythonRunner(
            permissions,
            root=root,
        )
        developer = DeveloperWorker(
            fake,
            files,
            runner,
        )

        paths = developer._paths(
            message
        )

        check(
            paths == [],
            "'.exe' seul n'est toujours pas un faux chemin explicite",
        )

        target, explicit = (
            developer._artifact_target(
                message=message,
                paths=paths,
                task={
                    "id": "task_v55",
                },
            )
        )

        check(
            target == "dist/coucou_coralie.exe",
            "un nom d'exécutable raisonnable est inféré",
        )
        check(
            explicit is False,
            "la cible inférée est marquée non explicite",
        )

        source = developer._deterministic_dialog_source(
            message
        )

        check(
            source is not None,
            "le cas boîte de dialogue utilise un source déterministe",
        )
        check(
            "coucou coralie" in source,
            "le texte demandé est présent dans le source",
        )
        check(
            "AGENTOS_SELF_TEST_OK" in source,
            "le source contient le marqueur de self-test",
        )

        ok, error = runner.validate_source(
            source,
            "applications/coucou_coralie.py",
        )

        check(
            ok,
            f"le source déterministe compile : {error}",
        )

        explicit_paths = developer._paths(
            "crée workspace/mon_programme.exe"
        )
        explicit_target, explicit_flag = (
            developer._artifact_target(
                message=(
                    "crée workspace/mon_programme.exe"
                ),
                paths=explicit_paths,
                task={
                    "id": "task_v55",
                },
            )
        )

        check(
            explicit_target == "mon_programme.exe",
            "un nom .exe explicite est conservé",
        )
        check(
            explicit_flag is True,
            "la cible explicite est reconnue",
        )

        builder = ArtifactBuilder(
            permissions,
            root=root,
        )

        fake_exe = root / "dist" / "fake.exe"
        fake_exe.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        fake_exe.write_text(
            "pas un exe",
            encoding="utf-8",
        )

        inspection = builder.inspect_executable(
            "dist/fake.exe"
        )

        check(
            not inspection.valid_windows_executable,
            "un faux .exe texte est rejeté par le Tester V5.5",
        )

        if os.name == "nt":
            check(
                importlib.util.find_spec(
                    "PyInstaller"
                )
                is not None,
                "PyInstaller est installé",
            )

            build_source = (
                root
                / "applications"
                / "v55_smoke.py"
            )
            build_source.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            build_source.write_text(
                (
                    "import sys\n"
                    "if '--self-test' in sys.argv:\n"
                    "    print('AGENTOS_SELF_TEST_OK')\n"
                    "else:\n"
                    "    print('hello')\n"
                ),
                encoding="utf-8",
            )

            build = builder.build_windows_executable(
                source_path=(
                    "applications/v55_smoke.py"
                ),
                artifact_path=(
                    "dist/v55_smoke.exe"
                ),
                windowed=False,
                timeout=180,
            )

            check(
                build.success,
                (
                    "PyInstaller produit réellement "
                    f"un .exe : {build.error or build.stderr[-400:]}"
                ),
            )

            real_inspection = builder.inspect_executable(
                "dist/v55_smoke.exe"
            )

            check(
                real_inspection.valid_windows_executable,
                "le binaire produit possède les signatures MZ/PE",
            )

            execution = builder.run_executable_test(
                "dist/v55_smoke.exe"
            )

            check(
                execution.success,
                "le vrai .exe passe son --self-test",
            )
        else:
            print(
                "[INFO] Tests de build .exe ignorés : "
                "ils doivent être exécutés sur Windows."
            )

    print()
    print(
        f"V5.5 : {CHECKS} contrôles réussis."
    )


if __name__ == "__main__":
    main()
