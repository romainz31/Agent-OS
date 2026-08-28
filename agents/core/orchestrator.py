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

        print(f"\nOBJECTIF : {objective}")

        # =====================================================
        # 1. PLANNER
        # =====================================================

        print("\n[1/3] PLANNER")

        plan = self.planner.run(objective)

        print("\nPLAN :")
        print(plan)

        # =====================================================
        # 2. DEVELOPER
        # =====================================================

        print("\n[2/3] DEVELOPER")

        developer_task = f"""
Objectif :

{objective}

Plan fourni par le Planner :

{plan}

Réalise maintenant le plan.
Crée le programme nécessaire.
Teste ton programme avant de terminer.

IMPORTANT :
Lorsque tu crées un fichier, indique clairement son chemin.
"""

        developer_result = self.developer.run(developer_task)

        print("\nRÉSULTAT :")
        print(developer_result)

        # =====================================================
        # 3. TESTER
        # =====================================================

        print("\n[3/3] TESTER")

        tester_task = f"""
Objectif :

{objective}

Travail réalisé par le Developer :

{developer_result}

Tu dois maintenant tester le programme créé par le Developer.

Commence par identifier le fichier réellement créé par le
Developer.

Lis ce fichier puis exécute-le.

Vérifie que le résultat correspond bien à l'objectif.

Si le programme fonctionne :
réponds exactement avec :

PASS

Si le programme ne fonctionne pas :
réponds avec :

FAIL

puis explique brièvement pourquoi.
"""

        tester_result = self.tester.run(tester_task)

        print("\nRÉSULTAT DU TEST :")
        print(tester_result)

        # =====================================================
        # RESULTAT FINAL
        # =====================================================

        print()
        print("=" * 60)
        print("                 TERMINÉ")
        print("=" * 60)

        return tester_result