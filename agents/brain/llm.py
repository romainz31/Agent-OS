import requests
from agents.tools.descriptions import TOOLS_DESCRIPTION


def ask_llm(prompt):

    full_prompt = f"""
Tu es un agent autonome.

Tu dois analyser la demande utilisateur.

Tu peux utiliser des outils.

{TOOLS_DESCRIPTION}

Demande utilisateur :
{prompt}

Réponds uniquement avec une décision JSON si un outil est nécessaire.
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


    data = response.json()

    return data["response"]