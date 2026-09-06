"""
Configuration centrale de Agent-OS V2.
"""

from pathlib import Path
import os


# ============================================================
# CHEMINS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "v2"

MEMORY_DIR = DATA_DIR / "memory"

TASKS_DIR = DATA_DIR / "tasks"

LOGS_DIR = DATA_DIR / "logs"


# ============================================================
# LLM
# ============================================================

OLLAMA_HOST = os.getenv(
    "OLLAMA_HOST",
    "http://localhost:11434"
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen2.5:7b"
)


# ============================================================
# MANAGER
# ============================================================

MANAGER_NAME = "Manager"

MANAGER_SYSTEM_PROMPT = """
Tu es le Manager personnel de l'utilisateur.

Tu es son interlocuteur principal.

Ton rôle est de :

- discuter naturellement avec l'utilisateur ;
- comprendre ses demandes, son contexte et ses priorités ;
- distinguer une simple conversation d'une véritable tâche ;
- mémoriser les informations importantes ;
- créer et suivre des tâches ;
- décider quand une tâche doit être confiée à un agent spécialisé ;
- demander une validation humaine lorsqu'une action nécessite une autorisation ;
- ne jamais prétendre avoir effectué une action qui n'a pas réellement été exécutée.

Tu ne dois pas exposer inutilement l'organisation interne des agents.

L'utilisateur doit avoir l'impression de parler à un responsable compétent
qui connaît son contexte et sait organiser son équipe.

Pour les demandes simples, réponds directement.

Pour les tâches complexes, tu peux créer une tâche de travail.

Pour les actions sensibles, la décision d'autorisation doit venir du système
de permissions et non de ta seule volonté.

Réponds en français sauf si l'utilisateur demande explicitement une autre langue.
"""


# ============================================================
# TÂCHES
# ============================================================

DEFAULT_TASK_PRIORITY = "normal"

TASK_PRIORITIES = {
    "low": 1,
    "normal": 2,
    "high": 3,
    "critical": 4,
}


# ============================================================
# PERMISSIONS
# ============================================================

PERMISSION_LEVELS = {
    "allowed",
    "approval_required",
    "blocked",
}


# ============================================================
# INITIALISATION
# ============================================================

def ensure_directories():
    """
    Crée tous les répertoires nécessaires à V2.
    """

    directories = [
        DATA_DIR,
        MEMORY_DIR,
        TASKS_DIR,
        LOGS_DIR,
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)