from __future__ import annotations
import hashlib, os, tempfile
from dataclasses import dataclass
from pathlib import Path
from agentos.config import WORKSPACE_DIR
from agentos.permissions import Decision, PermissionEngine

class ProjectFileError(RuntimeError): pass

@dataclass
class ReadResult:
    path:str; content:str
    def to_dict(self): return {"path":self.path,"content":self.content}

@dataclass
class WritePlan:
    path:str; content:str; existing:bool; original_sha256:str|None; approval_required:bool; created:bool=False
    def to_dict(self): return {"path":self.path,"content":self.content,"existing":self.existing,"original_sha256":self.original_sha256,"approval_required":self.approval_required,"created":self.created}

class ProjectFiles:
    def __init__(self,permissions:PermissionEngine,root:Path=WORKSPACE_DIR)->None:
        self.permissions=permissions; self.root=root.resolve(); self.root.mkdir(parents=True,exist_ok=True)
    def _resolve(self,relative_path):
        value=relative_path.strip().replace("\\","/")
        if not value: raise ProjectFileError("Chemin vide.")
        path=(self.root/value).resolve()
        try:path.relative_to(self.root)
        except ValueError as exc: raise ProjectFileError("Accès hors workspace interdit.") from exc
        return path
    def _relative(self,path): return path.relative_to(self.root).as_posix()
    def _sha256(self,path): return hashlib.sha256(path.read_bytes()).hexdigest()
    def tree(self,max_entries=300):
        if self.permissions.check("read_workspace").decision!=Decision.ALLOWED: raise ProjectFileError("Lecture interdite.")
        entries=[]
        for p in sorted(self.root.rglob("*")):
            if "__pycache__" in p.parts: continue
            if p.is_file(): entries.append(self._relative(p))
            if len(entries)>=max_entries: break
        return "\n".join(entries) if entries else "(workspace vide)"
    def read(self,relative_path):
        if self.permissions.check("read_workspace").decision!=Decision.ALLOWED: raise ProjectFileError("Lecture interdite.")
        p=self._resolve(relative_path)
        if not p.exists() or not p.is_file(): raise ProjectFileError(f"Fichier introuvable : {relative_path}")
        return ReadResult(self._relative(p),p.read_text(encoding="utf-8"))
    def prepare_write(self,relative_path,content):
        p=self._resolve(relative_path); rel=self._relative(p)
        if p.exists():
            perm=self.permissions.check("modify_file")
            if perm.decision==Decision.BLOCKED: raise ProjectFileError(perm.reason)
            return WritePlan(rel,content,True,self._sha256(p),perm.decision==Decision.APPROVAL_REQUIRED)
        perm=self.permissions.check("create_file")
        if perm.decision!=Decision.ALLOWED: raise ProjectFileError(perm.reason)
        self._atomic_write(p,content)
        return WritePlan(rel,content,False,None,False,True)
    def apply_approved_write(self,*,relative_path,content,expected_sha256):
        p=self._resolve(relative_path)
        if not p.exists() or not p.is_file(): raise ProjectFileError("Le fichier approuvé n'existe plus.")
        if expected_sha256 and self._sha256(p)!=expected_sha256: raise ProjectFileError("Le fichier a changé depuis la proposition. Nouvelle proposition nécessaire.")
        self._atomic_write(p,content)
    @staticmethod
    def _atomic_write(path,content):
        path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(dir=str(path.parent),prefix=f".{path.name}.",suffix=".tmp",text=True)
        try:
            with os.fdopen(fd,"w",encoding="utf-8",newline="") as f:f.write(content)
            Path(name).replace(path)
        finally:
            Path(name).unlink(missing_ok=True)
