from agentos.tasks import TaskStatus
class ApprovalManager:
    def __init__(self,tasks,files,runner,resume): self.tasks=tasks; self.files=files; self.runner=runner; self.resume=resume
    def pending(self): return [t for t in self.tasks.list() if t.status==TaskStatus.WAITING_APPROVAL.value]
    def latest(self): return self.pending()[0] if self.pending() else None
    def format(self): return "Aucune approbation en attente." if not self.pending() else "\n".join(f"{t.id} | {t.title} | "+", ".join(t.result_data.get("approval_required_files",[])) for t in self.pending())
    def approve_latest(self):
        t=self.latest()
        if not t:return "Aucune approbation en attente."
        modified=[]
        try:
            for p in t.result_data.get("plans",[]):
                if not p.get("approval_required"):continue
                if p["path"].lower().endswith(".py"):
                    ok,err=self.runner.validate_source(p["content"],p["path"])
                    if not ok:raise RuntimeError("Proposition Python invalide : "+err)
                self.files.apply_approved_write(relative_path=p["path"],content=p["content"],expected_sha256=p.get("original_sha256")); modified.append(p["path"])
        except Exception as exc:self.tasks.update(t.id,status=TaskStatus.FAILED.value,error=str(exc));self.resume(t.id);return f"Approbation non appliquée : {exc}"
        data=dict(t.result_data);data["approval_required_files"]=[];data["modified_files"]=modified;data["approval_status"]="approved"
        self.tasks.update(t.id,status=TaskStatus.COMPLETED.value,result=(t.result or "")+"\n\nModification approuvée et appliquée.",result_data=data,error=None);self.resume(t.id)
        return "Modification autorisée.\n"+"\n".join(f"- {p}" for p in modified)+f"\nTâche {t.id} terminée."
    def reject_latest(self):
        t=self.latest()
        if not t:return "Aucune approbation en attente."
        data=dict(t.result_data);data["approval_status"]="rejected";self.tasks.update(t.id,status=TaskStatus.CANCELLED.value,result=(t.result or "")+"\n\nModification refusée.",result_data=data,error="approval_rejected");self.resume(t.id)
        return f"Modification refusée.\nAucun fichier n'a été modifié.\nTâche {t.id} annulée."
