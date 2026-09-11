from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "overlay" / "usr" / "plugins"))

from agent_os_memory.helpers.store import PersonalMemoryStore  # noqa: E402


def migrate(target: Path) -> dict[str, object]:
    """Open the existing V11 database so the store performs the V12 upgrade."""
    store = PersonalMemoryStore(target)
    with sqlite3.connect(str(target)) as db:
        version = db.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
    return {
        "target": str(target),
        "schema_version": version[0] if version else str(store.SCHEMA_VERSION),
        "idempotent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Upgrade Agent-OS V11 memory to V12.")
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    result = migrate(args.target)
    print(
        f"Migration V11 -> V12 terminée : {result['target']} "
        f"(schema {result['schema_version']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
