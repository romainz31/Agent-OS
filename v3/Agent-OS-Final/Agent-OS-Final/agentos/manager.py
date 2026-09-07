from __future__ import annotations
import threading
from agentos.approvals import ApprovalManager
from agentos.engine import WorkerEngine
from agentos.llm import LLM,LLMError
from agentos.memory import Memory
from agentos.permissions import PermissionEngine
from agentos.project_files import ProjectFiles
from agentos.python_runner import PythonRunner
from agentos.router import Router
from agentos.tasks import TaskManager
from agentos.workers import AIWorker,DeveloperWorker,ResearcherWorker,TesterWorker

class Manager:
    def __init__(self)->None:
        self.llm=LLM();self.memory=Memory();self.permissions=PermissionEngine();self.tasks=TaskManager();self.router=Router();self.files=ProjectFiles(self.permissions);self.runner=PythonRunner(self.permissions)
        self._lock=threading.RLock();self._notifications=[]
        self.engine=WorkerEngine(self.tasks,self.notify)
        for w in (AIWorker(self.llm),ResearcherWorker(self.llm,self.permissions),DeveloperWorker(self.llm,self.files,self.runner),TesterWorker(self.llm,self.files,self.runner)):self.engine.register(w)
        self.approvals=ApprovalManager(self.tasks,self.files,self.runner,self.engine.resume_dependents)
    def notify(self,text):
        with self._lock:self._notifications.append(text)
    def drain_notifications(self):
        with self._lock:v=list(self._notifications);self._notifications.clear();return v
    @staticmethod
    def _task_title(message):
        clean=" ".join(message.strip().split())
        return clean if len(clean)<=90 else clean[:87].rstrip()+"..."
    def _conversation(self,message):
        try:return self.llm.chat(f"Tu es le Manager d'Agent-OS, interlocuteur principal de l'utilisateur.\n\nCONTEXTE MÉMOIRE:\n{self.memory.context()}\n\nMESSAGE COURANT:\n{message}\n\nRéponds naturellement en français. Ne prétends pas qu'un worker a travaillé si aucune tâche ne l'a fait.")
        except LLMError as exc:return f"Ollama inaccessible : {exc}"
    def handle(self,message):
        value=message.strip();cmd=value.lower()
        if not value:return ""
        if cmd=="tasks":return self.tasks.format()
        if cmd=="approvals":return self.approvals.format()
        if cmd=="memory":return self.memory.format()
        if cmd=="status":return f"Workers : {', '.join(self.engine.workers)}\nTâches en cours : {len(self.engine.running)}\nApprobations : {len(self.approvals.pending())}"
        if cmd in {"oui","yes","y","approve","autorise"}:return self.approvals.approve_latest()
        if cmd in {"non","no","n","reject","refuse"}:return self.approvals.reject_latest()
        self.memory.add_session("user",value);self.memory.maybe_remember(value);route=self.router.route(value)
        if route.kind=="conversation":
            answer=self._conversation(value);self.memory.add_session("assistant",answer);return answer
        task=self.tasks.create(title=self._task_title(value),description=value,worker=route.worker or "ai_worker",metadata={"original_message":value,"router_reason":route.reason})
        self.engine.submit(task.id)
        return f"Tâche créée : {task.id}\nWorker : {task.worker}\nStatut : {self.tasks.get(task.id).status}"
    def shutdown(self):self.engine.shutdown()
