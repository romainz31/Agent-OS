from agents.core.team import planner, developer, tester

print("\n=== PLANNER ===")
print(planner.run("Nous voulons créer une calculatrice Python."))

print("\n=== DEVELOPER ===")
print(developer.run("Nous voulons créer une calculatrice Python."))

print("\n=== TESTER ===")
print(tester.run("Nous voulons créer une calculatrice Python."))