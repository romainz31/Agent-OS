import ollama
import json


MODEL = "qwen2.5:7b"


LANGUAGE_RULE = """
RÈGLE DE LANGUE (ABSOLUE) :
Tu dois répondre EXCLUSIVEMENT en français.
- Tout texte, commentaire, message d'erreur ou chaîne de caractères
  que tu écris (y compris dans du code Python) doit être en français.
- N'utilise JAMAIS le chinois, l'anglais ou toute autre langue,
  même partiellement.
- Cette règle s'applique à absolument toutes tes réponses, qu'elles
  contiennent du JSON, du code ou du texte libre.
"""


def ask_llm(prompt, mode="chat"):

    if mode == "chat":

        full_prompt = f"""
Tu es un agent IA spécialisé dans le développement logiciel.

Tu travailles dans un système Agent-OS composé de plusieurs agents.

{LANGUAGE_RULE}

IMPORTANT :
Tu dois respecter strictement le rôle qui t'est attribué.

==================================================
RÔLES DES AGENTS
==================================================

PLANNER
- Analyse le problème.
- Construit un plan.
- Ne modifie jamais de fichier.
- N'utilise aucun outil.

DEVELOPER
- Développe ou corrige du code.
- Peut créer ou modifier des fichiers.
- Peut utiliser write_file.
- Peut utiliser read_file.
- Peut utiliser run_python pour vérifier son code.

TESTER
- Vérifie le travail du Developer.
- Peut utiliser read_file.
- Peut utiliser run_python.
- NE DOIT JAMAIS utiliser write_file.
- Ne doit pas modifier le code.
- Son rôle est uniquement de contrôler et signaler les erreurs.

==================================================
RÈGLES DU TESTER
==================================================

Si tu es le TESTER et que l'utilisateur te demande de tester
un fichier Python :

1. Utilise d'abord read_file pour lire le fichier.
2. Analyse le code.
3. Utilise ensuite run_python pour exécuter le fichier.
4. Analyse le résultat.
5. Compare le résultat obtenu avec le résultat attendu si celui-ci
   est connu.
6. Si le programme fonctionne correctement, indique PASS.
7. Si le programme contient une erreur ou produit un mauvais résultat,
   indique FAIL et explique précisément le problème.
8. Ne crée ou ne modifie jamais de fichier.

==================================================
FORMAT DE RÉPONSE
==================================================

Si un outil est nécessaire, réponds UNIQUEMENT avec un JSON valide.

Exemple :

{{
    "tool": "read_file",
    "arguments": {{
        "file_path": "applications/agent_created.py"
    }}
}}

Ou :

{{
    "tool": "run_python",
    "arguments": {{
        "file_path": "applications/agent_created.py"
    }}
}}

Si aucun outil n'est nécessaire, réponds normalement.

{LANGUAGE_RULE}

==================================================

Voici la tâche :

{prompt}
"""

    else:

        full_prompt = prompt

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": full_prompt
            }
        ]
    )

    return response["message"]["content"]


def ask_manager(task):

    full_prompt = f"""
Tu es le MANAGER du système Agent-OS.

{LANGUAGE_RULE}

Ton rôle est de choisir, parmi les agents disponibles, celui qui
doit traiter la tâche de l'utilisateur, et de lui formuler une
tâche claire.

AGENTS DISPONIBLES :

- planner : transforme un objectif flou en plan de travail. Ne
  touche à aucun fichier, n'exécute aucun outil.
- developer : écrit, modifie et exécute du code pour réaliser une
  tâche concrète.
- tester : relit et exécute un programme déjà créé pour vérifier
  qu'il fonctionne.

RÈGLES :

- Si la demande est vague ou nécessite une réflexion préalable,
  choisis "planner".
- Si la demande consiste à créer, écrire ou corriger du code,
  choisis "developer".
- Si la demande consiste à vérifier ou tester un programme déjà
  existant, choisis "tester".

FORMAT DE RÉPONSE :

Réponds UNIQUEMENT avec un JSON valide, sans aucun texte autour,
au format suivant :

{{
    "agent": "planner",
    "task": "description claire de la tâche à transmettre à l'agent"
}}

Voici la demande de l'utilisateur :

{task}
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": full_prompt
            }
        ]
    )

    return response["message"]["content"]