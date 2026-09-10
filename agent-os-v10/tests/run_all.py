"""Exécute chaque suite dans un processus et des données isolés."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    failures = []
    for suite in sorted((root / "tests").glob("test_*.py")):
        with tempfile.TemporaryDirectory(prefix="agentos-check-") as directory:
            env = dict(os.environ)
            env["AGENTOS_DATA_DIR"] = str(Path(directory) / "data")
            env["AGENTOS_WORKSPACE_DIR"] = str(Path(directory) / "workspace")
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            print(f"\n--- {suite.name} ---", flush=True)
            try:
                result = subprocess.run(
                    [sys.executable, "-m", f"tests.{suite.stem}"],
                    cwd=root, env=env, timeout=300, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                )
                print(result.stdout, end="", flush=True)
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="", flush=True)
                if result.returncode:
                    failures.append(suite.name)
            except subprocess.TimeoutExpired:
                failures.append(suite.name + " (timeout)")
    if failures:
        print("Échecs : " + ", ".join(failures))
        return 1
    print("Toutes les suites ont réussi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
