from __future__ import annotations

from typing import Any

from agentos.autonomy import AutonomyController
from agentos.runtime import AgentOSRuntime as CoreRuntime


class AutonomousRuntime(CoreRuntime):
    """Runtime Agent-OS avec superviseur autonome V4.8."""

    VERSION = "4.8"

    def __init__(self) -> None:
        super().__init__()

        self.autonomy = AutonomyController(
            self.manager
        )

        if hasattr(
            self.manager,
            "set_autonomy_controller",
        ):
            self.manager.set_autonomy_controller(
                self.autonomy
            )

        # Une passe immédiate après la récupération du runtime permet de
        # détecter les tâches orphelines avant même le premier intervalle.
        self.autonomy.check_once()
        self.autonomy.start()

    def status(self) -> dict[str, Any]:
        result = dict(
            super().status()
        )
        if hasattr(self, "autonomy"):
            result["autonomy"] = (
                self.autonomy.snapshot()
            )
        return result

    def autonomy_status(self) -> dict[str, Any]:
        return self.autonomy.snapshot()

    def autonomy_decisions(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.autonomy.lock:
            return list(
                self.autonomy.decisions[
                    -max(1, int(limit)):
                ]
            )

    def autonomy_check(self) -> dict[str, Any]:
        return self.autonomy.check_once()

    def conversation_status(self) -> dict[str, Any]:
        tracker = getattr(
            self.manager,
            "conversation_tracker",
            None,
        )
        if tracker is None:
            return {
                "available": False,
            }
        result = tracker.snapshot()
        result["available"] = True
        return result

    def conversation_history(self) -> list[dict[str, Any]]:
        tracker = getattr(
            self.manager,
            "conversation_tracker",
            None,
        )
        if tracker is None:
            return []
        with tracker.lock:
            return [
                dict(item)
                for item in tracker.data.get("history", [])
                if isinstance(item, dict)
            ]

    def shutdown(self) -> None:
        if hasattr(self, "autonomy"):
            self.autonomy.stop()
        super().shutdown()
