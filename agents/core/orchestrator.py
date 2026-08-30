import json

from agents.core.team import (
    planner,
    researcher,
    developer,
    tester
)


class Orchestrator:

    def __init__(self):

        self.planner = planner
        self.researcher = researcher
        self.developer = developer
        self.tester = tester

        self.max_development_attempts = 3


    # ========================================================
    # UTILITAIRES
    # ========================================================

    @staticmethod
    def parse_json_result(result):

        if isinstance(result, dict):
            return result

        if not isinstance(result, str):
            return None

        text = result.strip()

        try:

            return json.loads(
                text
            )

        except json.JSONDecodeError:

            start = text.find("{")
            end = text.rfind("}")

            if start == -1 or end == -1:
                return None

            try:

                return json.loads(
                    text[start:end + 1]
                )

            except json.JSONDecodeError:

                return None


    # ========================================================
    # AFFICHAGE
    # ========================================================

    @staticmethod
    def print_section(title):

        print()
        print("=" * 60)
        print(title)
        print("=" * 60)


    # ========================================================
    # RUN
    # ========================================================

    def run(self, objective):

        self.print_section(
            "ORCHESTRATOR"
        )

        print(
            f"\nOBJECTIF : {objective}"
        )


        # ====================================================
        # 1. PLANNER
        # ====================================================

        self.print_section(
            "[1] PLANNER"
        )

        # Le Planner n'a aucun outil.
        # Un seul appel LLM suffit.
        plan_result = self.planner.run(
            objective,
            max_steps=1
        )

        print("\nPLAN BRUT :")
        print(plan_result)

        plan = self.parse_json_result(
            plan_result
        )

        if plan is None:

            return {

                "status":
                    "FAIL",

                "stage":
                    "planner",

                "message":
                    (
                        "Le Planner a retourné un résultat "
                        "qui n'est pas un JSON valide."
                    ),

                "result":
                    plan_result

            }


        print("\nPLAN STRUCTURÉ :")

        print(
            json.dumps(
                plan,
                indent=4,
                ensure_ascii=False
            )
        )


        # ====================================================
        # 2. RESEARCHER
        # ====================================================

        research_result = None

        research_required = (
            plan.get(
                "research_required",
                False
            )
        )

        self.print_section(
            "[2] RESEARCHER"
        )

        if research_required:

            research_task = plan.get(
                "research_task",
                ""
            )

            if not research_task:

                return {

                    "status":
                        "FAIL",

                    "stage":
                        "researcher",

                    "message":
                        (
                            "Le Planner a indiqué qu'une recherche "
                            "était nécessaire mais n'a fourni "
                            "aucune tâche de recherche."
                        )

                }


            print(
                "\n[TÂCHE RESEARCHER]"
            )

            print(
                research_task
            )

            research_result = (
                self.researcher.chat(
                    research_task,
                    shared=True,
                    max_steps=5
                )
            )

            print(
                "\nRÉSULTAT RESEARCHER :"
            )

            print(
                research_result
            )

        else:

            print(
                "Aucune recherche externe nécessaire."
            )


        # ====================================================
        # 3. DEVELOPER
        # ====================================================

        self.print_section(
            "[3] DEVELOPER"
        )

        developer_task = f"""

OBJECTIF INITIAL :

{objective}

============================================================

PLAN DU PLANNER :

{json.dumps(
    plan,
    indent=4,
    ensure_ascii=False
)}

============================================================

"""

        if research_result is not None:

            developer_task += f"""

RÉSULTATS DU RESEARCHER :

{json.dumps(
    research_result,
    indent=4,
    ensure_ascii=False
)}

============================================================

"""


        developer_task += """

Réalise maintenant l'implémentation.

Crée uniquement les fichiers réellement nécessaires.

Teste ton implémentation lorsque cela est possible.

Si le programme utilise input(), utilise input_data
pour effectuer un véritable test automatisé.

Analyse réellement le résultat du test.

Lorsque l'implémentation fonctionne, arrête-toi.

Ne retourne jamais PASS ou FAIL.

Retourne un compte-rendu JSON de ton travail.
"""


        developer_result = (
            self.developer.run(
                developer_task,
                max_steps=6
            )
        )

        print(
            "\nRÉSULTAT DEVELOPER :"
        )

        print(
            developer_result
        )


        # ====================================================
        # 4. TEST / CORRECTION
        # ====================================================

        for attempt in range(
            1,
            self.max_development_attempts + 1
        ):

            self.print_section(
                f"[4] TESTER — TENTATIVE "
                f"{attempt}/"
                f"{self.max_development_attempts}"
            )


            tester_task = f"""

OBJECTIF INITIAL :

{objective}

============================================================

PLAN DU PLANNER :

{json.dumps(
    plan,
    indent=4,
    ensure_ascii=False
)}

============================================================

TRAVAIL DU DEVELOPER :

{json.dumps(
    developer_result,
    indent=4,
    ensure_ascii=False
)}

============================================================

Tu dois maintenant valider l'implémentation.

Identifie les fichiers réellement créés ou modifiés.

Lis les fichiers concernés.

Exécute le programme lorsque cela est possible.

Si le programme utilise input(), utilise input_data.

Observe le résultat réel.

Compare-le avec l'objectif initial.

IMPORTANT :

Travaille de manière directe.

Pour un programme simple, le processus attendu est :

1. read_file
2. run_python avec input_data si nécessaire
3. analyse du résultat
4. verdict

Ne répète pas inutilement une lecture ou une exécution
qui fournit déjà les preuves nécessaires.

Dès que tu possèdes suffisamment de preuves pour conclure,
retourne immédiatement ton verdict.

Si tout fonctionne :

{{
    "status": "PASS",
    "file": "...",
    "result": "...",
    "message": "Le programme respecte l'objectif."
}}

Si quelque chose doit être corrigé :

{{
    "status": "FAIL",
    "file": "...",
    "error": "...",
    "message": "Correction nécessaire."
}}

Tu ne dois jamais modifier le programme.
"""


            tester_result = (
                self.tester.run(
                    tester_task,
                    max_steps=5
                )
            )


            print(
                "\nRÉSULTAT TESTER :"
            )

            print(
                tester_result
            )


            tester_decision = (
                self.parse_json_result(
                    tester_result
                )
            )


            # =================================================
            # PASS
            # =================================================

            if (

                isinstance(
                    tester_decision,
                    dict
                )

                and tester_decision.get(
                    "status"
                ) == "PASS"

            ):

                self.print_section(
                    "TERMINÉ — PASS"
                )

                return {

                    "status":
                        "PASS",

                    "objective":
                        objective,

                    "plan":
                        plan,

                    "research":
                        research_result,

                    "developer":
                        developer_result,

                    "tester":
                        tester_decision,

                    "attempts":
                        attempt

                }


            # =================================================
            # TESTER INVALIDE
            # =================================================

            if tester_decision is None:

                if attempt >= self.max_development_attempts:

                    self.print_section(
                        "ÉCHEC — TESTER INVALIDE"
                    )

                    return {

                        "status":
                            "FAIL",

                        "objective":
                            objective,

                        "plan":
                            plan,

                        "developer":
                            developer_result,

                        "tester":
                            tester_result,

                        "attempts":
                            attempt,

                        "message":
                            (
                                "Le Tester n'a pas retourné "
                                "un verdict JSON valide."
                            )

                    }


                # Le Tester n'a pas fourni de verdict valide.
                # On lui laisse une nouvelle tentative plutôt
                # que d'envoyer immédiatement le Developer.


                continue


            # =================================================
            # LIMITE
            # =================================================

            if attempt >= self.max_development_attempts:

                self.print_section(
                    "ÉCHEC — LIMITE DE CORRECTIONS ATTEINTE"
                )

                return {

                    "status":
                        "FAIL",

                    "objective":
                        objective,

                    "plan":
                        plan,

                    "research":
                        research_result,

                    "developer":
                        developer_result,

                    "tester":
                        tester_decision,

                    "attempts":
                        attempt,

                    "message":
                        (
                            "Le Tester a rejeté l'implémentation "
                            "après plusieurs tentatives."
                        )

                }


            # =================================================
            # RETOUR DEVELOPER
            # =================================================

            self.print_section(
                "RETOUR VERS DEVELOPER"
            )


            developer_task = f"""

OBJECTIF INITIAL :

{objective}

============================================================

PLAN :

{json.dumps(
    plan,
    indent=4,
    ensure_ascii=False
)}

============================================================

TON IMPLÉMENTATION PRÉCÉDENTE :

{json.dumps(
    developer_result,
    indent=4,
    ensure_ascii=False
)}

============================================================

VERDICT DU TESTER :

{json.dumps(
    tester_decision,
    indent=4,
    ensure_ascii=False
)}

============================================================

Le Tester a détecté un problème.

Analyse précisément son retour.

Corrige uniquement ce qui est nécessaire.

Lis les fichiers concernés avant de les modifier.

Exécute à nouveau le programme après correction.

Si le programme utilise input(), utilise input_data.

Analyse réellement le résultat obtenu.

Ne retourne jamais PASS ou FAIL.

Lorsque la correction fonctionne, arrête-toi
et retourne un compte-rendu JSON.
"""


            developer_result = (
                self.developer.run(
                    developer_task,
                    max_steps=6
                )
            )

            print(
                "\nRÉSULTAT DEVELOPER APRÈS CORRECTION :"
            )

            print(
                developer_result
            )


        # ====================================================
        # FIN INATTENDUE
        # ====================================================

        return {

            "status":
                "FAIL",

            "objective":
                objective,

            "message":
                "L'Orchestrator a atteint une fin inattendue."

        }
