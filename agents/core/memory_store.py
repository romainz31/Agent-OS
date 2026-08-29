import json
import os
from datetime import datetime


# ============================================================
# MÉMOIRE DES AGENTS
# ============================================================
#
# Deux types de mémoire :
#
# - MÉMOIRE INDIVIDUELLE : propre à un agent (ex: Developer),
#   un fichier JSON par agent dans data/memory/<agent>.json
#
# - MÉMOIRE PARTAGÉE : commune à tous les agents, utilisée pour
#   les projets de groupe où plusieurs agents doivent se
#   souvenir des mêmes échanges. Fichier unique :
#   data/memory/shared.json

MEMORY_DIR = "data/memory"

SHARED_MEMORY_FILE = os.path.join(MEMORY_DIR, "shared.json")

# Nombre de tours de conversation (question + réponse) rappelés
# à l'agent à chaque nouveau message, pour ne pas faire exploser
# la taille du prompt envoyé au LLM.
MAX_HISTORY_TURNS = 10


def _agent_memory_file(agent_name):

    safe_name = agent_name.lower().replace(" ", "_")

    return os.path.join(MEMORY_DIR, f"{safe_name}.json")


def _load_json(path):

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_json(path, data):

    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


# ============================================================
# MÉMOIRE INDIVIDUELLE
# ============================================================

def load_agent_memory(agent_name):

    return _load_json(_agent_memory_file(agent_name))


def save_agent_memory(agent_name, memory):

    _save_json(_agent_memory_file(agent_name), memory)


def append_agent_memory(agent_name, role, content):

    memory = load_agent_memory(agent_name)

    memory.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(timespec="seconds")
    })

    save_agent_memory(agent_name, memory)

    return memory


# ============================================================
# MÉMOIRE PARTAGÉE (projets de groupe)
# ============================================================

def load_shared_memory():

    return _load_json(SHARED_MEMORY_FILE)


def save_shared_memory(memory):

    _save_json(SHARED_MEMORY_FILE, memory)


def append_shared_memory(agent_name, role, content):

    memory = load_shared_memory()

    memory.append({
        "agent": agent_name,
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(timespec="seconds")
    })

    save_shared_memory(memory)

    return memory


# ============================================================
# FORMATAGE POUR INJECTION DANS UN PROMPT
# ============================================================

def format_history(history, max_turns=MAX_HISTORY_TURNS):
    """
    Transforme une liste d'entrées mémoire en texte lisible,
    en ne gardant que les derniers échanges pour limiter la
    taille du prompt.
    """

    if not history:
        return "(aucun historique)"

    recent = history[-max_turns:]

    lines = []

    for entry in recent:

        speaker = entry.get("agent", entry.get("role", "?"))
        content = entry.get("content", "")

        lines.append(f"[{speaker}] {content}")

    return "\n".join(lines)