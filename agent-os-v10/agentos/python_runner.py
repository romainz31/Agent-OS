from __future__ import annotations
import subprocess, sys
from dataclasses import dataclass
from pathlib import Path
from agentos.config import WORKSPACE_DIR
from agentos.permissions import Decision, PermissionEngine

class PythonRunnerError(RuntimeError): pass
@dataclass
class TestResult:
    path:str; mode:str; success:bool; returncode:int|None; stdout:str=""; stderr:str=""; timed_out:bool=False
    def to_dict(self): return self.__dict__.copy()

class PythonRunner:
    RUNTIME_PREFIXES=("tests/","applications/")
    def __init__(self,permissions,root=WORKSPACE_DIR): self.permissions=permissions; self.root=root.resolve()
    def _resolve(self,relative_path):
        p=(self.root/relative_path.replace("\\","/")).resolve()
        try:p.relative_to(self.root)
        except ValueError as exc: raise PythonRunnerError("Chemin hors workspace interdit.") from exc
        if not p.exists() or not p.is_file() or p.suffix.lower()!=".py": raise PythonRunnerError("Fichier Python introuvable.")
        return p
    def _permission(self):
        if self.permissions.check("run_python_test").decision!=Decision.ALLOWED: raise PythonRunnerError("Tests interdits.")
    @staticmethod
    def validate_source(source,filename="<proposal>"):
        try:compile(source,filename,"exec"); return True,""
        except SyntaxError as exc:return False,f"{exc.__class__.__name__}: {exc}"
    def compile_file(self,relative_path,timeout=10):
        self._permission(); p=self._resolve(relative_path); rel=p.relative_to(self.root).as_posix(); cmd=[sys.executable,"-m","py_compile",str(p)]
        try:r=subprocess.run(cmd,cwd=str(self.root),capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=max(1,min(timeout,20)),shell=False)
        except subprocess.TimeoutExpired as exc:return TestResult(rel,"compile",False,None,exc.stdout or "",exc.stderr or "",True)
        return TestResult(rel,"compile",r.returncode==0,r.returncode,r.stdout,r.stderr)
    def run_file(self,relative_path,timeout=10):
        self._permission(); p=self._resolve(relative_path); rel=p.relative_to(self.root).as_posix()
        if not any(rel.startswith(x) for x in self.RUNTIME_PREFIXES): raise PythonRunnerError("Runtime limité à tests/ et applications/.")
        try:r=subprocess.run([sys.executable,str(p)],cwd=str(self.root),capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=max(1,min(timeout,20)),shell=False)
        except subprocess.TimeoutExpired as exc:return TestResult(rel,"run",False,None,exc.stdout or "",exc.stderr or "",True)
        return TestResult(rel,"run",r.returncode==0,r.returncode,r.stdout,r.stderr)
