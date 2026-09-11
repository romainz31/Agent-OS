from agent import LoopData
from helpers.extension import Extension


class SemanticPersonalIntake(Extension):
    """Compatibilité V11.2.

    L'intake s'exécute désormais avant AgentContext._process_chain afin de pouvoir
    court-circuiter le LLM principal quand la mémoire a déjà traité le message.
    Cette ancienne extension reste volontairement vide pour écraser le fichier
    V11.2 lors d'une mise à jour sans nettoyage du dossier plugin.
    """

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        return None
