import requests
from agents.tools.descriptions import TOOLS_DESCRIPTION


def ask_llm(prompt, mode="chat"):

    full_prompt = f"""
Tu es un agent IA qui travaille dans un système d'agents logiciels.

Tu dois exécuter la tâche demandée en utilisant les outils disponibles.

REGLE ABSOLUE :
Tu dois répondre UNIQUEMENT avec un objet JSON valide.

Tu n'as PAS le droit :
- d'expliquer ta réponse
- d'écrire du texte avant le JSON
- d'écrire du texte après le JSON
- de proposer du code sans utiliser l'outil
- de demander à l'utilisateur d'exécuter quelque chose

Si tu dois utiliser un outil, réponds exactement avec :

{{
    "tool": "nom_de_l_outil",
    "arguments": {{
        ...
    }}
}}

Si la tâche est terminée sans outil, réponds exactement avec :

{{
    "action": "answer",
    "content": "réponse"
}}

OUTILS DISPONIBLES :

{TOOLS_DESCRIPTION}

TÂCHE :
{prompt}

CHOISIS MAINTENANT L'ACTION À EFFECTUER.

RÉPONDS UNIQUEMENT AVEC DU JSON.
"""

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "qwen2.5:7b",
            "prompt": full_prompt,
            "stream": False,
            "format": "json"
        }
    )

    response.raise_for_status()

    data = response.json()

    return data["response"]