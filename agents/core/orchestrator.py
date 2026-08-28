from agents.core.team import planner, developer, tester


class Orchestrator:

    def __init__(self):
        self.planner = planner
        self.developer = developer
        self.tester = tester

    def run(self, objective):

        print()
        print("=" * 60)
        print("                 ORCHESTRATOR")
        print("=" * 60)

        print()
        print("OBJECTIF :")
        print(objective)

        # =====================================================
        # 1. PLANNER
        # =====================================================

        print()
        print("=" * 60)
        print("                    PLANNER")
        print("=" * 60)

        plan = self.planner.run(objective)

        print()
        print("PLAN DU PLANNER :")
        print(plan)

        # =====================================================
        # 2. DEVELOPER
        # =====================================================

        print()
        print("=" * 60)
        print("                   DEVELOPER")
        print("=" * 60)

        developer_task = f"""
Objectif :

{objective}

Plan du Planner :

{plan}

Tu es maintenant chargé de réaliser ce plan.
Crée le programme nécessaire et vérifie qu'il fonctionne.
"""

        developer_result = self.developer.run(developer_task)

        print()
        print("RÉSULTAT DU DEVELOPER :")
        print(developer_result)

        # =====================================================
        # 3. TESTER
        # =====================================================

        print()
        print("=" * 60)
        print("                    TESTER")
        print("=" * 60)

        tester_task = f"""
Objectif initial :

{objective}

Le Developer vient de travailler sur le projet.

Résultat du Developer :

{developer_result}

Teste le programme créé par le Developer.
Vérifie qu'il fonctionne correctement et que l'objectif
initial est respecté.

Si le test réussit, indique clairement PASS.
Si le test échoue, indique clairement FAIL et explique
le problème.
"""

        tester_result = self.tester.run(tester_task)

        print()
        print("RÉSULTAT DU TESTER :")
        print(tester_result)

        # =====================================================
        # 4. RESULTAT FINAL
        # =====================================================

        print()
        print("=" * 60)
        print("                 FIN DU PROCESSUS")
        print("=" * 60)

        print()
        print("Résultat final :")
        print(tester_result)

        return tester_result