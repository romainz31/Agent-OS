from __future__ import annotations

import sqlite3
from typing import Any


class ClosingSQLiteConnection(sqlite3.Connection):
    """sqlite3.Connection that really closes when leaving a ``with`` block.

    The standard sqlite3 context manager commits/rolls back but does not close
    the connection. On Windows this can keep .db files locked until garbage
    collection. Agent-OS uses this subclass so temporary/test databases and
    live database files are released deterministically.
    """

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def connect(database: str, *, timeout: float = 10.0) -> ClosingSQLiteConnection:
    return sqlite3.connect(
        database,
        timeout=timeout,
        factory=ClosingSQLiteConnection,
    )
