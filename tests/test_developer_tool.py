from agents.core.team import developer
from agents.brain.llm import ask_llm
from agents.brain.decision import analyze_response
from agents.executor.executor import execute


task = """
Crée un fichier Python :

applications/agent_created.py

Le fichier doit contenir une fonction :

def multiply(a, b):
    return a * b

et afficher le résultat de multiply(6, 7).

Tu dois utiliser l'outil write_file.
"""


response = ask_llm(task, mode="chat")


print("=== RÉPONSE DU LLM ===")
print(response)


decision = analyze_response(response)


print("\n=== DÉCISION ===")
print(decision)


if decision["action"] == "tool":

    result = execute(decision)

    print("\n=== RÉSULTAT OUTIL ===")
    print(result)