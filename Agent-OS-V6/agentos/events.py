from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any


class NotificationHub:
    """
    Journal de notifications multi-clients.

    Le Manager produit une notification une seule fois. Le hub la conserve
    ensuite temporairement afin que plusieurs interfaces (Web, CLI,
    Telegram, Discord...) puissent chacune la lire une fois sans se la voler.
    """

    def __init__(
        self,
        *,
        max_events: int = 1000,
        max_clients: int = 200,
    ) -> None:
        self.max_events = max(
            50,
            int(max_events),
        )
        self.max_clients = max(
            10,
            int(max_clients),
        )

        self.lock = threading.RLock()
        self._events: deque[dict[str, Any]] = deque(
            maxlen=self.max_events
        )
        self._clients: dict[str, dict[str, Any]] = {}
        self._next_id = 1

    # =========================================================
    # INGESTION
    # =========================================================

    def ingest(
        self,
        messages: list[str] | tuple[str, ...],
    ) -> int:
        added = 0

        with self.lock:
            for raw in messages:
                text = str(
                    raw
                    or ""
                ).strip()

                if not text:
                    continue

                event = {
                    "id": self._next_id,
                    "text": text,
                    "created_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }

                self._next_id += 1
                self._events.append(
                    event
                )
                added += 1

        return added

    # =========================================================
    # CLIENT CURSORS
    # =========================================================

    def _prune_clients(
        self,
        keep_client_id: str,
    ) -> None:
        if len(self._clients) < self.max_clients:
            return

        candidates = sorted(
            (
                (
                    client_id,
                    float(
                        state.get(
                            "last_seen",
                            0.0,
                        )
                    ),
                )
                for client_id, state
                in self._clients.items()
                if client_id != keep_client_id
            ),
            key=lambda item: item[1],
        )

        remove_count = max(
            1,
            len(self._clients)
            - self.max_clients
            + 1,
        )

        for client_id, _ in candidates[
            :remove_count
        ]:
            self._clients.pop(
                client_id,
                None,
            )

    def _cursor_for(
        self,
        client_id: str,
    ) -> int:
        state = self._clients.get(
            client_id
        )

        if state is None:
            self._prune_clients(
                client_id
            )
            self._clients[
                client_id
            ] = {
                "cursor": 0,
                "last_seen": time.monotonic(),
            }
            return 0

        state[
            "last_seen"
        ] = time.monotonic()

        return int(
            state.get(
                "cursor",
                0,
            )
        )

    # =========================================================
    # READ
    # =========================================================

    def read_for_client(
        self,
        client_id: str,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        client_id = str(
            client_id
            or ""
        ).strip()

        if not client_id:
            raise ValueError(
                "client_id vide"
            )

        limit = max(
            1,
            min(
                int(limit),
                500,
            ),
        )

        with self.lock:
            cursor = self._cursor_for(
                client_id
            )

            latest = (
                self._events[-1]["id"]
                if self._events
                else 0
            )

            oldest = (
                self._events[0]["id"]
                if self._events
                else 0
            )

            truncated = bool(
                self._events
                and cursor < oldest - 1
            )

            effective_cursor = cursor

            if truncated:
                effective_cursor = (
                    oldest - 1
                )

            selected = [
                dict(event)
                for event in self._events
                if event["id"]
                > effective_cursor
            ][:limit]

            if selected:
                cursor = int(
                    selected[-1]["id"]
                )
            elif truncated:
                cursor = effective_cursor

            self._clients[
                client_id
            ] = {
                "cursor": cursor,
                "last_seen": time.monotonic(),
            }

            return {
                "client_id": client_id,
                "items": [
                    event["text"]
                    for event in selected
                ],
                "events": selected,
                "cursor": cursor,
                "latest": latest,
                "pending": max(
                    0,
                    latest - cursor,
                ),
                "truncated": truncated,
            }

    # =========================================================
    # DEBUG / STATUS
    # =========================================================

    def status(
        self,
    ) -> dict[str, int]:
        with self.lock:
            return {
                "events_retained": len(
                    self._events
                ),
                "clients": len(
                    self._clients
                ),
                "latest": (
                    self._events[-1]["id"]
                    if self._events
                    else 0
                ),
            }
