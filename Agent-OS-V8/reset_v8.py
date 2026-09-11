from __future__ import annotations

from agentos.config import LANGGRAPH_DB_PATH
from agentos.manager import PersonalManager


def main() -> None:
    manager = PersonalManager()
    manager.reset_all()
    for suffix in ("", "-shm", "-wal"):
        path = LANGGRAPH_DB_PATH.with_name(LANGGRAPH_DB_PATH.name + suffix)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    print("Agent-OS V8 remis à zéro.")
    print("Mémoire, conversation, agenda, missions et checkpoints LangGraph vidés.")


if __name__ == "__main__":
    main()
