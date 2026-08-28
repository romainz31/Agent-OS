from agents.core.team import planner, developer


print("=== PLANNER ===")

result = planner.run(
    "Prépare un plan très simple pour créer une fonction Python additionnant deux nombres."
)

print(result)


print("\n=== DEVELOPER ===")

result = developer.run(
    "À partir du travail effectué précédemment par le Planner, propose l'implémentation Python."
)

print(result)