from agents.core.team import planner, developer, tester


class Workflow:

    def run(self, objective):

        print("\n========== PLANNER ==========")

        plan = planner.run(objective)

        print(plan)


        print("\n========== DEVELOPER ==========")

        development = developer.run(
            f"""
Objectif initial :
{objective}

Le Planner a produit le travail suivant :

{plan}

À partir de ce travail, réalise la partie développement.
"""
        )

        print(development)


        print("\n========== TESTER ==========")

        test = tester.run(
            f"""
Objectif initial :
{objective}

Travail du Planner :
{plan}

Travail du Developer :
{development}

Analyse et teste le résultat.
Identifie les éventuels problèmes.
"""
        )

        print(test)

        return test