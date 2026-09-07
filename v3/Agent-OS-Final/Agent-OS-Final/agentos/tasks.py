from __future__ import annotations
import threading, uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from agentos.config import DATA_DIR
from agentos.storage import JsonStore

class TaskStatus(str, Enum):
    PENDING="pending"; WAITING_DEPENDENCY="waiting_dependency"; RUNNING="running"; WAITING_APPROVAL="waiting_approval"; COMPLETED="completed"; FAILED="failed"; CANCELLED="cancelled"

@dataclass
class Task:
    id:str; title:str; description:str; worker:str; status:str; created_at:str; updated_at:str
    result:str|None=None; result_data:dict[str,Any]=field(default_factory=dict); error:str|None=None
    depends_on:list[str]=field(default_factory=list); metadata:dict[str,Any]=field(default_factory=dict)
    def to_dict(self): return asdict(self)

class TaskManager:
    def __init__(self) -> None:
        self.store=JsonStore(DATA_DIR/"tasks.json",[]); self.lock=threading.RLock(); self.tasks={}; self._load()
    def _now(self): return datetime.now(timezone.utc).isoformat()
    def _load(self):
        for item in self.store.load():
            try: task=Task(**item); self.tasks[task.id]=task
            except TypeError: pass
    def _save(self): self.store.save([x.to_dict() for x in self.tasks.values()])
    def create(self,*,title,description,worker,depends_on=None,metadata=None):
        with self.lock:
            deps=list(dict.fromkeys(depends_on or [])); now=self._now()
            status=TaskStatus.PENDING.value if not deps or self.dependencies_satisfied_ids(deps) else TaskStatus.WAITING_DEPENDENCY.value
            task=Task("task_"+uuid.uuid4().hex[:12],title,description,worker,status,now,now,depends_on=deps,metadata=metadata or {})
            self.tasks[task.id]=task; self._save(); return task
    def get(self,task_id): return self.tasks.get(task_id)
    def list(self): return sorted(self.tasks.values(),key=lambda x:x.created_at,reverse=True)
    def update(self,task_id,**changes):
        with self.lock:
            task=self.tasks[task_id]
            for k,v in changes.items():
                if not hasattr(task,k): raise ValueError(f"Champ inconnu : {k}")
                setattr(task,k,v)
            task.updated_at=self._now(); self._save(); return task
    def dependencies_satisfied_ids(self,ids): return all(self.tasks.get(i) and self.tasks[i].status==TaskStatus.COMPLETED.value for i in ids)
    def dependency_failure(self,task):
        for i in task.depends_on:
            dep=self.tasks.get(i)
            if dep is None:return f"Dépendance introuvable : {i}"
            if dep.status==TaskStatus.FAILED.value:return f"Dépendance échouée : {i}"
            if dep.status==TaskStatus.CANCELLED.value:return f"Dépendance annulée : {i}"
        return None
    def dependents_of(self,task_id): return [t for t in self.tasks.values() if task_id in t.depends_on]
    def dependency_context(self,task):
        return [{"task_id":d.id,"title":d.title,"worker":d.worker,"status":d.status,"result":d.result,"result_data":d.result_data} for i in task.depends_on if (d:=self.tasks.get(i))]
    def format(self):
        return "Aucune tâche." if not self.tasks else "\n".join(f"{t.id} | {t.status} | {t.worker} | {t.title}"+(f" | dépend de {','.join(t.depends_on)}" if t.depends_on else "") for t in self.list())
