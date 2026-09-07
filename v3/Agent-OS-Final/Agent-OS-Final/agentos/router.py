from dataclasses import dataclass
@dataclass(frozen=True)
class Route: kind:str; worker:str|None; reason:str
class Router:
    RESEARCH=("recherche","cherche","internet","documentation","source")
    TEST=("teste","tester","vérifie","verifie","test","compile","erreurs python","syntaxe")
    DEV=("crée","cree","créer","creer","modifie","modifier","corrige","corriger","ajoute","ajouter","code","fichier")
    WORK=("analyse","conçois","concois","planifie","architecture","propose","prépare","prepare")
    def route(self,message):
        x=message.lower().strip()
        if any(v in x for v in self.TEST): return Route("task","tester","demande de vérification")
        if any(v in x for v in self.RESEARCH): return Route("task","researcher","demande de recherche")
        if any(v in x for v in self.DEV): return Route("task","developer","travail sur fichier/code")
        if any(v in x for v in self.WORK): return Route("task","ai_worker","travail intellectuel")
        return Route("conversation",None,"conversation")
