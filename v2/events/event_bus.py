"""
Event Bus Agent-OS V2.

Permet aux composants de communiquer par événements.

Exemples :

- task.created
- task.started
- task.completed
- task.failed
- task.waiting_approval
- task.cancelled
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
import traceback


@dataclass
class Event:
    """
    Événement système.
    """

    type: str

    data: dict[str, Any] = field(
        default_factory=dict
    )

    created_at: str = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )


EventHandler = Callable[[Event], None]


class EventBus:
    """
    Bus d'événements local.

    Un composant publie un événement.
    Les composants intéressés peuvent s'y abonner.
    """

    def __init__(self):
        self._handlers: dict[
            str,
            list[EventHandler],
        ] = defaultdict(list)

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
    ) -> None:
        """
        Abonne une fonction à un type d'événement.
        """

        if handler not in self._handlers[event_type]:

            self._handlers[event_type].append(
                handler
            )

    def unsubscribe(
        self,
        event_type: str,
        handler: EventHandler,
    ) -> None:
        """
        Supprime un abonnement.
        """

        handlers = self._handlers.get(
            event_type,
            [],
        )

        if handler in handlers:

            handlers.remove(
                handler
            )

    def publish(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> Event:
        """
        Publie un événement.

        Les handlers reçoivent un objet Event.
        """

        event = Event(
            type=event_type,
            data=data or {},
        )

        handlers = list(
            self._handlers.get(
                event_type,
                [],
            )
        )

        # Une erreur dans un handler ne doit pas
        # empêcher les autres handlers de recevoir
        # l'événement.
        for handler in handlers:

            try:

                handler(event)

            except Exception:

                traceback.print_exc()

        return event

    def clear(
        self,
    ) -> None:
        """
        Supprime tous les abonnements.
        """

        self._handlers.clear()