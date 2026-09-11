from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from agentos.db import Database
from agentos.integrations.registry import IntegrationRegistry
from agentos.llm import LLMError, OllamaLLM


TERMINAL = {"completed", "failed", "cancelled"}


class MissionCancelled(RuntimeError):
    pass


@dataclass
class Mission:
    human_id: str
    title: str
    description: str
    status: str
    progress: int
    total_steps: int
    result: str
    error: str
    control: str
    backend: str
    external_context_id: str
    created_at: str
    updated_at: str


class MissionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def reset(self) -> None:
        self.db.execute("DELETE FROM mission_steps")
        self.db.execute("DELETE FROM missions")

    def _next_human_id(self) -> str:
        row = self.db.one(
            "SELECT MAX(CAST(SUBSTR(human_id,3) AS INTEGER)) AS n FROM missions"
        )
        return f"M-{int((row or {}).get('n') or 0) + 1:03d}"

    def create(self, description: str, title: str = "") -> dict[str, Any]:
        human_id = self._next_human_id()
        title = title.strip() or " ".join(description.strip().split())[:72]
        self.db.execute(
            "INSERT INTO missions(human_id,title,description,status) VALUES(?,?,?,'queued')",
            (human_id, title, description.strip()),
        )
        return self.get(human_id) or {}

    def get(self, human_id: str) -> dict[str, Any] | None:
        ref = self.normalize_ref(human_id)
        return self.db.one("SELECT * FROM missions WHERE human_id=?", (ref,))

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        missions = self.db.query("SELECT * FROM missions ORDER BY id DESC LIMIT ?", (limit,))
        for mission in missions:
            mission["steps"] = self.steps(mission["human_id"])
        return missions

    def count(self) -> int:
        row = self.db.one("SELECT COUNT(*) AS n FROM missions")
        return int(row["n"] if row else 0)

    def steps(self, human_id: str) -> list[dict[str, Any]]:
        ref = self.normalize_ref(human_id)
        return self.db.query(
            "SELECT * FROM mission_steps WHERE mission_human_id=? ORDER BY step_index,id",
            (ref,),
        )

    def replace_steps(self, human_id: str, plan: list[dict[str, Any]]) -> None:
        ref = self.normalize_ref(human_id)
        self.db.execute("DELETE FROM mission_steps WHERE mission_human_id=?", (ref,))
        for index, step in enumerate(plan, start=1):
            self.db.execute(
                "INSERT INTO mission_steps(mission_human_id,step_index,title,worker,prompt,status) "
                "VALUES(?,?,?,?,?,'queued')",
                (
                    ref,
                    index,
                    str(step.get("title") or f"Étape {index}"),
                    str(step.get("worker") or "general"),
                    str(step.get("prompt") or step.get("title") or ""),
                ),
            )
        self.update(ref, total_steps=len(plan), progress=0)

    def update(self, human_id: str, **fields: Any) -> None:
        ref = self.normalize_ref(human_id)
        allowed = {
            "status", "progress", "total_steps", "result", "error", "control",
            "backend", "external_context_id", "title",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        if not values:
            return
        assignments = ",".join(f"{key}=?" for key in values)
        params = tuple(values.values()) + (ref,)
        self.db.execute(
            f"UPDATE missions SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE human_id=?",
            params,
        )

    def update_step(self, human_id: str, step_index: int, **fields: Any) -> None:
        ref = self.normalize_ref(human_id)
        allowed = {"status", "result", "error"}
        values = {k: v for k, v in fields.items() if k in allowed}
        if not values:
            return
        assignments = ",".join(f"{key}=?" for key in values)
        params = tuple(values.values()) + (ref, int(step_index))
        self.db.execute(
            f"UPDATE mission_steps SET {assignments},updated_at=CURRENT_TIMESTAMP "
            "WHERE mission_human_id=? AND step_index=?",
            params,
        )

    def control(self, human_id: str, action: str) -> dict[str, Any] | None:
        ref = self.normalize_ref(human_id)
        mission = self.get(ref)
        if not mission:
            return None
        if action == "pause" and mission["status"] not in TERMINAL:
            self.update(ref, control="pause", status="paused")
        elif action == "resume" and mission["status"] not in TERMINAL:
            self.update(ref, control="", status="running")
        elif action == "cancel" and mission["status"] not in TERMINAL:
            self.update(ref, control="cancel", status="cancelled")
        return self.get(ref)

    @staticmethod
    def normalize_ref(value: str) -> str:
        match = re.search(r"\bM-(\d{1,6})\b", value.strip(), flags=re.IGNORECASE)
        if not match:
            return value.strip().upper()
        return f"M-{int(match.group(1)):03d}"

    def format(self) -> str:
        items = self.list()
        if not items:
            return "Aucune mission."
        return "\n".join(
            f"{m['human_id']} | {m['status']} | {m['progress']}/{m['total_steps']} | {m['title']}"
            for m in items
        )


class MissionRunner:
    def __init__(
        self,
        store: MissionStore,
        llm: OllamaLLM,
        integrations: IntegrationRegistry,
    ) -> None:
        self.store = store
        self.llm = llm
        self.integrations = integrations
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def launch(self, objective: str) -> dict[str, Any]:
        mission = self.store.create(objective)
        ref = mission["human_id"]
        thread = threading.Thread(
            target=self._run,
            args=(ref, objective),
            daemon=True,
            name=f"agentos-{ref}",
        )
        with self._lock:
            self._threads[ref] = thread
        thread.start()
        return mission

    @staticmethod
    def _extract_json_array(text: str) -> list[dict[str, Any]]:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        result = []
        for item in data[:8]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            prompt = str(item.get("prompt") or title).strip()
            worker = str(item.get("worker") or "general").strip().lower()
            if title and prompt:
                result.append({"title": title, "prompt": prompt, "worker": worker})
        return result

    def _plan(self, ref: str, objective: str) -> list[dict[str, Any]]:
        system = (
            "Tu es le Planner d'Agent-OS. Découpe l'objectif en 1 à 5 étapes concrètes. "
            "Réponds UNIQUEMENT avec un tableau JSON. Chaque objet doit avoir title, prompt, worker. "
            "worker vaut general, research, coding ou review. N'invente pas d'étapes inutiles."
        )
        try:
            raw = self.llm.ask(objective, system=system)
            plan = self._extract_json_array(raw)
        except LLMError:
            plan = []
        if not plan:
            plan = [{"title": "Traiter la demande", "prompt": objective, "worker": "general"}]
        self.store.replace_steps(ref, plan)
        return [{**step, "step_index": i} for i, step in enumerate(plan, start=1)]

    def _wait_if_paused(self, ref: str) -> None:
        while True:
            mission = self.store.get(ref)
            if not mission:
                raise MissionCancelled("Mission introuvable")
            if mission["control"] == "cancel" or mission["status"] == "cancelled":
                raise MissionCancelled("Mission annulée")
            if mission["control"] != "pause":
                return
            time.sleep(0.25)

    def _execute(self, ref: str, step: dict[str, Any]) -> str:
        self._wait_if_paused(ref)
        index = int(step["step_index"])
        self.store.update_step(ref, index, status="running")
        self.store.update(ref, status="running")
        prompt = str(step["prompt"])
        worker = str(step.get("worker") or "general")
        try:
            if self.integrations.agent_zero.configured:
                mission = self.store.get(ref) or {}
                context_id = str(mission.get("external_context_id") or "")
                task_prompt = (
                    f"Tu travailles comme worker '{worker}' pour Agent-OS. "
                    f"Mission {ref}. Exécute uniquement cette étape :\n{prompt}"
                )
                data = self.integrations.agent_zero.send(task_prompt, context_id=context_id)
                result = data["response"]
                self.store.update(
                    ref,
                    backend="agent-zero",
                    external_context_id=data.get("context_id", ""),
                )
            else:
                result = self.llm.ask(
                    prompt,
                    system=(
                        f"Tu es un worker '{worker}' d'Agent-OS. Fournis un résultat concret, "
                        "utile au Manager. Ne parle pas de ton rôle sauf si nécessaire."
                    ),
                )
            self.store.update_step(ref, index, status="completed", result=result)
            self.store.update(ref, progress=index)
            return result
        except Exception as exc:
            self.store.update_step(ref, index, status="failed", error=str(exc))
            raise

    def _execute_plan(self, ref: str, objective: str, plan: list[dict[str, Any]]) -> list[str]:
        """Use MAF for true fan-out/fan-in when the plan is parallelizable.

        Agent Zero keeps priority when configured because it owns the richer sandbox/tool
        environment. Without Agent Zero, MAF can execute independent reasoning steps in
        parallel. If MAF is unavailable or incomplete, Agent-OS falls back to the stable
        sequential executor.
        """
        if len(plan) <= 1 or self.integrations.agent_zero.configured:
            return [self._execute(ref, step) for step in plan]

        maf_available = getattr(self.integrations.maf, "available", lambda: False)
        if not maf_available():
            return [self._execute(ref, step) for step in plan]

        roles: list[tuple[str, str]] = []
        name_to_step: dict[str, dict[str, Any]] = {}
        for step in plan:
            index = int(step["step_index"])
            worker = re.sub(r"[^a-z0-9_]+", "_", str(step.get("worker") or "general").lower())
            name = f"step_{index}_{worker}"
            instructions = (
                f"Tu es responsable UNIQUEMENT de l'étape {index} de la mission {ref}. "
                f"Objectif global: {objective}. Étape à produire: {step['prompt']}. "
                "Retourne un résultat concret et autonome, sans attendre les autres agents."
            )
            roles.append((name, instructions))
            name_to_step[name] = step
            self.store.update_step(ref, index, status="running")

        self.store.update(ref, status="running", backend="maf")
        try:
            outputs = self.integrations.maf.run(objective, roles=roles)
        except Exception:
            # Reset unfinished step states before the deterministic fallback.
            for step in plan:
                self.store.update_step(ref, int(step["step_index"]), status="queued", error="")
            self.store.update(ref, backend="local")
            return [self._execute(ref, step) for step in plan]

        by_name: dict[str, str] = {}
        for item in outputs:
            name = str(item.get("agent") or "").strip()
            text = str(item.get("text") or "").strip()
            if name and text:
                by_name[name] = text

        results: list[str] = []
        for step in plan:
            index = int(step["step_index"])
            expected = next((name for name, mapped in name_to_step.items() if int(mapped["step_index"]) == index), "")
            result = by_name.get(expected, "")
            if not result:
                # Preserve reliability if a participant did not yield a final AgentResponse.
                self.store.update_step(ref, index, status="queued", error="")
                result = self._execute(ref, step)
            else:
                self.store.update_step(ref, index, status="completed", result=result, error="")
                self.store.update(ref, progress=index)
            results.append(result)
        return results

    def _synthesize(self, objective: str, results: list[str]) -> str:
        if len(results) == 1:
            return results[0]
        payload = "\n\n".join(f"RÉSULTAT {i}:\n{r}" for i, r in enumerate(results, start=1))
        try:
            return self.llm.ask(
                f"OBJECTIF:\n{objective}\n\n{payload}",
                system="Synthétise les résultats des workers en une réponse finale cohérente et actionnable.",
            )
        except LLMError:
            return payload

    def _run(self, ref: str, objective: str) -> None:
        self.store.update(ref, status="planning", error="")

        def planner(obj: str) -> list[dict[str, Any]]:
            return self._plan(ref, obj)

        def executor(step: dict[str, Any]) -> str:
            return self._execute(ref, step)

        try:
            state = self.integrations.langgraph.run(
                mission_id=ref,
                objective=objective,
                planner=planner,
                executor=executor,
                synthesizer=self._synthesize,
                plan_executor=lambda plan: self._execute_plan(ref, objective, plan),
            )
            self._wait_if_paused(ref)
            self.store.update(ref, status="completed", result=str(state.get("final") or ""), control="")
        except MissionCancelled:
            self.store.update(ref, status="cancelled")
        except Exception as exc:
            self.store.update(ref, status="failed", error=str(exc))
        finally:
            with self._lock:
                self._threads.pop(ref, None)
