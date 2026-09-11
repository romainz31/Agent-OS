from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, TypedDict


class MissionState(TypedDict, total=False):
    mission_id: str
    objective: str
    plan: list[dict[str, Any]]
    results: list[str]
    final: str


class LangGraphEngine:
    def __init__(self, db_path: Path | str, enabled: bool = True) -> None:
        self.db_path = Path(db_path)
        self.enabled = enabled
        self._conn: sqlite3.Connection | None = None
        self._error = ""

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            import langgraph  # noqa: F401
            from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401
            return True
        except Exception as exc:
            self._error = str(exc)
            return False

    def status(self) -> dict:
        ok = self.available()
        return {
            "enabled": self.enabled,
            "installed": ok,
            "ok": ok,
            "checkpoint_db": str(self.db_path),
            **({"error": self._error} if self._error and not ok else {}),
        }

    def run(
        self,
        mission_id: str,
        objective: str,
        planner: Callable[[str], list[dict[str, Any]]],
        executor: Callable[[dict[str, Any]], str],
        synthesizer: Callable[[str, list[str]], str],
        plan_executor: Callable[[list[dict[str, Any]]], list[str]] | None = None,
    ) -> MissionState:
        if not self.available():
            plan = planner(objective)
            results = plan_executor(plan) if plan_executor else [executor(step) for step in plan]
            return {
                "mission_id": mission_id,
                "objective": objective,
                "plan": plan,
                "results": results,
                "final": synthesizer(objective, results),
            }

        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        saver = SqliteSaver(self._conn)

        def plan_node(state: MissionState) -> MissionState:
            return {**state, "plan": planner(state["objective"]), "results": []}

        def execute_node(state: MissionState) -> MissionState:
            plan = state.get("plan", [])
            results = plan_executor(plan) if plan_executor else [executor(step) for step in plan]
            return {**state, "results": results}

        def synth_node(state: MissionState) -> MissionState:
            final = synthesizer(state["objective"], state.get("results", []))
            return {**state, "final": final}

        builder = StateGraph(MissionState)
        builder.add_node("plan", plan_node)
        builder.add_node("execute", execute_node)
        builder.add_node("synthesize", synth_node)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "execute")
        builder.add_edge("execute", "synthesize")
        builder.add_edge("synthesize", END)
        graph = builder.compile(checkpointer=saver)
        return graph.invoke(
            {"mission_id": mission_id, "objective": objective},
            config={"configurable": {"thread_id": mission_id}},
        )
