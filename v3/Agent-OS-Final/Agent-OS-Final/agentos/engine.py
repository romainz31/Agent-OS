from concurrent.futures import ThreadPoolExecutor
from agentos.config import MAX_WORKERS
from agentos.tasks import TaskStatus

class WorkerEngine:
    def __init__(self,tasks,notifier): self.tasks=tasks; self.notifier=notifier; self.pool=ThreadPoolExecutor(max_workers=MAX_WORKERS); self.workers={}; self.running={}
    def register(self,w): self.workers[w.name]=w
    def submit(self,task_id):
        task=self.tasks.get(task_id)
        if not task:return
        fail=self.tasks.dependency_failure(task)
        if fail:self.tasks.update(task.id,status=TaskStatus.FAILED.value,error=fail);self.notifier(f"✗ {task.id} : {fail}");return
        if task.depends_on and not self.tasks.dependencies_satisfied_ids(task.depends_on):self.tasks.update(task.id,status=TaskStatus.WAITING_DEPENDENCY.value);return
        worker=self.workers.get(task.worker)
        if not worker:self.tasks.update(task.id,status=TaskStatus.FAILED.value,error=f"Worker inconnu : {task.worker}");return
        self.tasks.update(task.id,status=TaskStatus.RUNNING.value); payload=task.to_dict(); payload["dependency_context"]=self.tasks.dependency_context(task)
        fut=self.pool.submit(worker.execute,payload); self.running[task.id]=fut; fut.add_done_callback(lambda f:self._finished(task.id,f))
    def _finished(self,task_id,fut):
        self.running.pop(task_id,None)
        try:r=fut.result()
        except Exception as exc:self.tasks.update(task_id,status=TaskStatus.FAILED.value,error=str(exc));self.notifier(f"✗ {task_id} : {exc}");self.resume_dependents(task_id);return
        if not r.success:self.tasks.update(task_id,status=TaskStatus.FAILED.value,result=r.message,result_data=r.data,error=r.error or r.message);self.notifier(f"✗ {task_id} : {r.error or r.message}");self.resume_dependents(task_id);return
        approval=r.data.get("approval_required_files",[])
        if approval:self.tasks.update(task_id,status=TaskStatus.WAITING_APPROVAL.value,result=r.message,result_data=r.data,error=None);self.notifier(f"⚠ {task_id} attend ton approbation : "+", ".join(approval));return
        self.tasks.update(task_id,status=TaskStatus.COMPLETED.value,result=r.message,result_data=r.data,error=None);self.notifier(f"✓ {task_id} terminée par {self.tasks.get(task_id).worker}");self.resume_dependents(task_id)
    def resume_dependents(self,task_id):
        for t in self.tasks.dependents_of(task_id):
            if t.status in {TaskStatus.PENDING.value,TaskStatus.WAITING_DEPENDENCY.value}:self.submit(t.id)
    def shutdown(self): self.pool.shutdown(wait=True,cancel_futures=False)
