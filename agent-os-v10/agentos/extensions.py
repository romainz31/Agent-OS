"""Points d'extension synchrones pour Agent-OS V7.

Le principe est inspiré du système d'extensions d'Agent Zero : le cœur publie
des événements stables et des modules spécialisés peuvent observer ou enrichir
leur contexte sans modifier le moteur. L'implémentation reste volontairement
légère et sans dépendance externe pour conserver la compatibilité d'Agent-OS.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


ExtensionCallback = Callable[["ExtensionEvent"], None]


@dataclass
class ExtensionEvent:
    """Événement mutable transmis aux extensions dans l'ordre de priorité."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class ExtensionFailure:
    event: str
    extension: str
    error: str
    created_at: str


@dataclass(frozen=True)
class _Registration:
    priority: int
    order: int
    name: str
    callback: ExtensionCallback


class ExtensionBus:
    """Registre thread-safe avec priorité et isolation des erreurs.

    Une extension défaillante est mémorisée dans ``failures()`` mais ne casse
    pas une mission. Le mode ``strict`` est réservé aux tests et extensions qui
    doivent explicitement interrompre le traitement.
    """

    def __init__(self, *, max_failures: int = 100) -> None:
        self._lock = threading.RLock()
        self._registrations: dict[str, list[_Registration]] = {}
        self._failures: list[ExtensionFailure] = []
        self._next_order = 0
        self._max_failures = max(1, int(max_failures))

    @staticmethod
    def _event_name(value: str) -> str:
        name = str(value or "").strip().lower()
        if not name:
            raise ValueError("Le nom d'événement ne peut pas être vide.")
        return name

    def register(
        self,
        event: str,
        callback: ExtensionCallback,
        *,
        name: str | None = None,
        priority: int = 100,
    ) -> str:
        event_name = self._event_name(event)
        if not callable(callback):
            raise TypeError("Une extension doit être appelable.")

        extension_name = str(name or getattr(callback, "__name__", "extension"))
        with self._lock:
            self._next_order += 1
            registration = _Registration(
                priority=int(priority),
                order=self._next_order,
                name=extension_name,
                callback=callback,
            )
            values = self._registrations.setdefault(event_name, [])
            values.append(registration)
            values.sort(key=lambda item: (item.priority, item.order))
        return extension_name

    def unregister(self, event: str, name: str) -> bool:
        event_name = self._event_name(event)
        with self._lock:
            current = self._registrations.get(event_name, [])
            filtered = [item for item in current if item.name != name]
            if len(filtered) == len(current):
                return False
            if filtered:
                self._registrations[event_name] = filtered
            else:
                self._registrations.pop(event_name, None)
            return True

    def emit(
        self,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> ExtensionEvent:
        event_name = self._event_name(event)
        emitted = ExtensionEvent(event_name, data if data is not None else {})
        with self._lock:
            callbacks = list(self._registrations.get(event_name, []))
            callbacks += list(self._registrations.get("*", []))
            callbacks.sort(key=lambda item: (item.priority, item.order))

        for registration in callbacks:
            try:
                registration.callback(emitted)
            except Exception as exc:
                failure = ExtensionFailure(
                    event=event_name,
                    extension=registration.name,
                    error=str(exc),
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                with self._lock:
                    self._failures.append(failure)
                    self._failures = self._failures[-self._max_failures :]
                if strict:
                    raise
        return emitted

    def failures(self) -> list[dict[str, str]]:
        with self._lock:
            return [failure.__dict__.copy() for failure in self._failures]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = {
                event: [item.name for item in registrations]
                for event, registrations in sorted(self._registrations.items())
            }
            return {
                "events": events,
                "extension_count": sum(len(items) for items in events.values()),
                "failure_count": len(self._failures),
                "failures": self.failures(),
            }

