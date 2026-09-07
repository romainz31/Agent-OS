from __future__ import annotations
import json,re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from agentos.llm import LLM,LLMError
from agentos.permissions import PermissionEngine
from agentos.project_files import ProjectFiles,ProjectFileError
from agentos.python_runner import PythonRunner

@dataclass
class WorkerResult:
    success:bool; message:str; data:dict[str,Any]; error:str|None=None
class Worker:
    name="worker"
    def execute(self,task): raise NotImplementedError

class AIWorker(Worker):
    name="ai_worker"
    def __init__(self,llm): self.llm=llm
    def execute(self,task):
        try:a=self.llm.chat(f"Tu es un collaborateur Agent-OS.\nDEMANDE COURANTE:\n{task['description']}\n\nCONTEXTE:\n{task.get('dependency_context') or '(aucun)'}\nRéponds en français, sans inventer d'outils utilisés.")
        except LLMError as exc:return WorkerResult(False,"Erreur LLM.",{},str(exc))
        return WorkerResult(True,a,{"worker":self.name})

class ResearcherWorker(Worker):
    name="researcher"
    def __init__(self,llm,permissions): self.llm=llm; self.permissions=permissions
    def execute(self,task):
        if self.permissions.check("web_search").decision.value!="allowed": return WorkerResult(False,"Recherche Web interdite.",{},"permission")
        try: from ddgs import DDGS
        except ImportError:return WorkerResult(False,"Le package ddgs n'est pas installé.",{},"pip install -r requirements.txt")
        try: raw=list(DDGS().text(task['description'],max_results=5))
        except Exception as exc:return WorkerResult(False,"Recherche Web échouée.",{},str(exc))
        sources=[{"id":f"S{i}","title":str(x.get('title','')),"url":str(x.get('href','')),"body":str(x.get('body',''))} for i,x in enumerate(raw,1)]
        ctx="\n\n".join(f"[{s['id']}] {s['title']}\n{s['body']}\n{s['url']}" for s in sources)
        try:a=self.llm.chat(f"QUESTION:\n{task['description']}\n\nRÉSULTATS WEB RÉELS:\n{ctx}\n\nSynthétise en français et cite [S1], [S2]. N'invente aucune source.")
        except LLMError as exc:return WorkerResult(False,"Synthèse impossible.",{"sources":sources},str(exc))
        return WorkerResult(True,a,{"worker":self.name,"sources":sources})

class DeveloperWorker(Worker):
    name="developer"
    FILE_RE=re.compile(r"(?:(?:workspace/)?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)")
    CREATE=("crée","cree","créer","creer"); MODIFY=("modifie","modifier","corrige","corriger","ajoute","ajouter","remplace","remplacer")
    def __init__(self,llm,files,runner): self.llm=llm; self.files=files; self.runner=runner
    @staticmethod
    def _clean_path(p):
        p=p.replace("\\","/").strip("`'\".,;:()[]{} ")
        return p[len("workspace/"):] if p.startswith("workspace/") else p
    def _paths(self,msg):
        out=[]
        for x in self.FILE_RE.findall(msg.replace("\\","/")):
            p=self._clean_path(x)
            if p and p not in out:out.append(p)
        return out
    def _operation(self,msg):
        x=msg.lower()
        if any(w in x for w in self.CREATE): return "create"
        if any(w in x for w in self.MODIFY): return "modify"
        return "analysis"
    @staticmethod
    def _clean_content(raw):
        t=raw.strip()
        if t.startswith("```"):
            n=t.find("\n"); t=t[n+1:] if n!=-1 else t
            if t.rstrip().endswith("```"):t=t.rstrip()[:-3]
        return t.strip()
    def execute(self,task):
        msg=task["metadata"]["original_message"]; op=self._operation(msg); paths=self._paths(msg)
        if op=="analysis":
            try:a=self.llm.chat(f"DEMANDE COURANTE:\n{msg}\n\nARBORESCENCE RÉELLE:\n{self.files.tree()}\n\nAnalyse seulement. Ne prétends pas modifier.")
            except LLMError as exc:return WorkerResult(False,"Erreur Developer.",{},str(exc))
            return WorkerResult(True,a,{"worker":self.name,"operation":"analysis"})
        if not paths:return WorkerResult(False,"Aucun chemin explicite trouvé.",{"operation":op},"explicit_path_missing")
        plans=[]; created=[]; approval=[]
        for path in paths:
            current=""
            if op=="modify":
                try:current=self.files.read(path).content
                except Exception as exc:return WorkerResult(False,"Lecture impossible.",{},str(exc))
            instr=(f"CONTENU ACTUEL:\n{current}\n\nApplique uniquement la modification. Conserve le reste. Retourne le FICHIER COMPLET final." if op=="modify" else "Crée le contenu complet demandé.")
            prompt=f"DEMANDE COURANTE EXACTE:\n{msg}\n\nFICHIER CIBLE:\n{path}\n\n{instr}\n\nFORMAT: contenu brut uniquement, aucun JSON, aucun Markdown, aucune explication."
            try:gen=self._clean_content(self.llm.chat(prompt,system="Tu es le Developer Agent-OS."))
            except LLMError as exc:return WorkerResult(False,"Génération impossible.",{},str(exc))
            if not gen:return WorkerResult(False,"Contenu généré vide.",{},"empty_generation")
            pre={"checked":False,"success":True,"error":""}
            if Path(path).suffix.lower()==".py":
                ok,err=self.runner.validate_source(gen,path); pre={"checked":True,"success":ok,"error":err}
                if not ok:return WorkerResult(False,"Proposition Python refusée avant approbation : erreur de syntaxe.",{"path":path,"prevalidation":pre},err)
            try:plan=self.files.prepare_write(path,gen)
            except ProjectFileError as exc:return WorkerResult(False,"Écriture impossible.",{},str(exc))
            item=plan.to_dict(); item["prevalidation"]=pre; plans.append(item)
            if plan.created:created.append(path)
            if plan.approval_required:approval.append(path)
        if approval:return WorkerResult(True,"Modification préparée et pré-validée. Approbation humaine requise.",{"worker":self.name,"operation":op,"plans":plans,"approval_required_files":approval,"created_files":created,"modified_files":[]})
        return WorkerResult(True,"Fichier(s) créé(s) avec succès.",{"worker":self.name,"operation":op,"plans":plans,"approval_required_files":[],"created_files":created,"modified_files":[]})

class TesterWorker(Worker):
    name="tester"; FILE_RE=DeveloperWorker.FILE_RE
    SYNTAX=("syntaxe","syntax","erreur python","erreurs python","compile","compilation","py_compile")
    def __init__(self,llm,files,runner): self.llm=llm; self.files=files; self.runner=runner
    def _paths(self,task):
        out=[]
        for dep in task.get("dependency_context") or []:
            data=dep.get("result_data") or {}
            for key in ("modified_files","created_files"):
                for p in data.get(key,[]) or []:
                    if p not in out:out.append(p)
        if out:return out
        for x in self.FILE_RE.findall(task["metadata"]["original_message"].replace("\\","/")):
            p=DeveloperWorker._clean_path(x)
            if p not in out:out.append(p)
        return out
    def execute(self,task):
        paths=self._paths(task)
        if not paths:return WorkerResult(False,"Aucun fichier à tester.",{},"target_missing")
        syntax_only=any(m in task["metadata"]["original_message"].lower() for m in self.SYNTAX); reads=[]; tests=[]
        for path in paths:
            try:reads.append(self.files.read(path).to_dict())
            except Exception as exc:return WorkerResult(True,f"VERDICT : NON VALIDÉ\n\nLecture impossible : {path}\n{exc}",{"worker":self.name,"verdict":"NON_VALIDÉ","targets":paths,"tests":tests})
            if Path(path).suffix.lower()==".py":
                try:c=self.runner.compile_file(path)
                except Exception as exc:return WorkerResult(True,f"VERDICT : NON VALIDÉ\n\nTest impossible : {exc}",{"worker":self.name,"verdict":"NON_VALIDÉ","targets":paths,"tests":tests})
                tests.append(c.to_dict())
                if not c.success:return WorkerResult(True,"VERDICT : NON VALIDÉ\n\nLa compilation Python réelle a échoué.",{"worker":self.name,"verdict":"NON_VALIDÉ","targets":paths,"tests":tests})
                if path.replace("\\","/").startswith(("tests/","applications/")) and not syntax_only:
                    r=self.runner.run_file(path); tests.append(r.to_dict())
                    if not r.success:return WorkerResult(True,"VERDICT : NON VALIDÉ\n\nL'exécution réelle a échoué.",{"worker":self.name,"verdict":"NON_VALIDÉ","targets":paths,"tests":tests})
        if syntax_only:return WorkerResult(True,"VERDICT : VALIDÉ\n\nLa compilation Python réelle a réussi pour tous les fichiers ciblés.\nAucune erreur de syntaxe Python n'a été détectée.",{"worker":self.name,"verdict":"VALIDÉ","test_mode":"syntax","targets":paths,"tests":tests})
        evidence=json.dumps({"reads":reads,"tests":tests},ensure_ascii=False,indent=2)
        try:a=self.llm.chat(f"DEMANDE:\n{task['description']}\n\nPREUVES RÉELLES:\n{evidence}\n\nN'invente aucun échec. Ne confonds pas non testé et incorrect. Tout NON VALIDÉ doit citer une preuve concrète. Commence par VERDICT : VALIDÉ ou VERDICT : NON VALIDÉ.")
        except LLMError as exc:return WorkerResult(False,"Revue LLM impossible.",{},str(exc))
        verdict="NON_VALIDÉ" if a.upper().startswith("VERDICT : NON VALIDÉ") else "VALIDÉ"
        return WorkerResult(True,a,{"worker":self.name,"verdict":verdict,"test_mode":"general","targets":paths,"tests":tests})
