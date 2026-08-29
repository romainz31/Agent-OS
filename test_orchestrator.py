import json

from agents.core.team import planner, developer, tester


def main():

    objective = """
Créer une fonction Python divide qui divise 10 par 0
et affiche le résultat.
"""

    print("=" * 60)
    print("                 ORCHESTRATOR")
    print("=" * 60)

    print()
    print("OBJECTIF :")
    print(objective)

    # ========================================================
    # 1. PLANNER
    # ========================================================

    print()
    print("[1/3] PLANNER")
    print("-" * 60)

    planner_task = f"""
OBJECTIF UTILISATEUR :

{objective}

TON ROLE :

Tu es le Planner.

Tu dois uniquement transformer l'objectif en plan de travail.

Tu dois déterminer :

- le fichier cible ;
- les étapes nécessaires ;
- le comportement exact attendu ;
- le résultat attendu.

Tu ne dois pas écrire le code.

Tu ne dois utiliser aucun outil.

IMPORTANT :

L'objectif demande explicitement de diviser 10 par 0.

Le comportement attendu doit donc correspondre au comportement réel
de Python face à une division par zéro.

Retourne UNIQUEMENT ce JSON :

{{
    "target_file": "applications/divide.py",
    "steps": [
        "étape 1",
        "étape 2"
    ],
    "expected_output": "description précise du comportement attendu"
}}
"""

    plan = planner.run(
        planner_task,
        max_steps=2
    )

    print()
    print("PLAN :")
    print(json.dumps(plan, ensure_ascii=False, indent=4))

    if not isinstance(plan, dict) or "target_file" not in plan:

        print()
        print("=" * 60)
        print("ERREUR PLANNER")
        print("=" * 60)
        print(plan)

        return

    target_file = plan["target_file"]
    expected_output = plan.get("expected_output", "")

    print()
    print("FICHIER CIBLE :", target_file)

    print()
    print("RESULTAT ATTENDU :", expected_output)

    # ========================================================
    # TENTATIVES
    # ========================================================

    max_attempts = 3

    developer_result = None
    tester_result = None

    for attempt in range(1, max_attempts + 1):

        print()
        print("=" * 60)
        print(f"TENTATIVE {attempt} / {max_attempts}")
        print("=" * 60)

        # ====================================================
        # DEVELOPER
        # ====================================================

        print()
        print("[2/3] DEVELOPER")
        print("-" * 60)

        developer_task = f"""
OBJECTIF :

{objective}

PLAN :

{json.dumps(plan, ensure_ascii=False, indent=4)}

FICHIER CIBLE OBLIGATOIRE :

{target_file}

RESULTAT ATTENDU :

{expected_output}

TON ROLE :

Tu es le Developer.

Tu dois :

1. Lire le plan.
2. Créer ou modifier uniquement :
   {target_file}
3. Écrire le code nécessaire.
4. Exécuter le programme si nécessaire.
5. Corriger les erreurs techniques.
6. Lorsque l'implémentation est terminée, arrêter ton travail.

IMPORTANT :

Tu ne dois PAS décider si le projet est PASS ou FAIL.

Le Tester est responsable de la validation finale.

Tu dois terminer par un JSON :

{{
    "status": "DONE",
    "file": "{target_file}",
    "message": "Implémentation terminée."
}}
"""

        if tester_result:

            developer_task += f"""

============================================================
RETOUR DU TESTER
============================================================

Le Tester a trouvé le problème suivant :

{json.dumps(tester_result, ensure_ascii=False, indent=4)}

Corrige uniquement ce problème dans :

{target_file}
"""

        developer_result = developer.run(
            developer_task,
            max_steps=6
        )

        print()
        print("DEVELOPER RESULT :")
        print(json.dumps(
            developer_result,
            ensure_ascii=False,
            indent=4
        ))

        # ====================================================
        # TESTER
        # ====================================================

        print()
        print("[3/3] TESTER")
        print("-" * 60)

        tester_task = f"""
OBJECTIF UTILISATEUR :

{objective}

FICHIER À TESTER :

{target_file}

RESULTAT ATTENDU :

{expected_output}

TON ROLE :

Tu es le Tester.

Tu dois uniquement vérifier le travail du Developer.

Tu ne dois :

- modifier aucun fichier ;
- créer aucun fichier ;
- corriger aucun code.

PROCÉDURE :

1. Utilise read_file sur exactement :

{target_file}

2. Analyse le code.

3. Utilise run_python sur exactement :

{target_file}

4. Observe la sortie réelle.

5. Compare le comportement réel avec l'objectif.

IMPORTANT :

Une exécution réussie de Python ne signifie PAS automatiquement PASS.

Tu dois vérifier que le comportement correspond réellement à
l'objectif utilisateur.

SI LE TEST EST RÉUSSI :

Retourne UNIQUEMENT :

{{
    "status": "PASS",
    "file": "{target_file}",
    "result": "résultat réel",
    "message": "Le programme respecte l'objectif."
}}

SI LE TEST ÉCHOUE :

Retourne UNIQUEMENT :

{{
    "status": "FAIL",
    "file": "{target_file}",
    "error": "description précise du problème",
    "message": "Correction nécessaire."
}}
"""

        tester_result = tester.run(
            tester_task,
            max_steps=5
        )

        print()
        print("TEST RESULT :")
        print(json.dumps(
            tester_result,
            ensure_ascii=False,
            indent=4
        ))

        # ====================================================
        # VALIDATION
        # ====================================================

        if not isinstance(tester_result, dict):

            print()
            print("⚠️ Le Tester n'a pas retourné un objet JSON.")

            continue

        if tester_result.get("status") == "PASS":

            print()
            print("=" * 60)
            print("                 TEST RÉUSSI")
            print("=" * 60)

            print()
            print("Fichier :", tester_result.get("file"))
            print("Résultat :", tester_result.get("result"))
            print("Message :", tester_result.get("message"))

            break

        # ====================================================
        # FAIL
        # ====================================================

        print()
        print("=" * 60)
        print("                 TEST ÉCHOUÉ")
        print("=" * 60)

        print()
        print("Erreur :", tester_result.get("error"))
        print("Message :", tester_result.get("message"))

        if attempt < max_attempts:

            print()
            print("→ Retour vers le Developer pour correction.")

        else:

            print()
            print("⚠️ Nombre maximum de tentatives atteint.")

    # ========================================================
    # CONTEXTE
    # ========================================================

    print()
    print("=" * 60)
    print("                 CONTEXT PARTAGÉ")
    print("=" * 60)

    print()
    print("OBJECTIVE :")
    print(objective)

    print()
    print("PLAN :")
    print(json.dumps(
        plan,
        ensure_ascii=False,
        indent=4
    ))

    print()
    print("TARGET FILE :")
    print(target_file)

    print()
    print("EXPECTED OUTPUT :")
    print(expected_output)

    print()
    print("DEVELOPER RESULT :")
    print(json.dumps(
        developer_result,
        ensure_ascii=False,
        indent=4
    ))

    print()
    print("TEST RESULT :")
    print(json.dumps(
        tester_result,
        ensure_ascii=False,
        indent=4
    ))

    print()
    print("ATTEMPT :", attempt)

    print()
    print("=" * 60)
    print("                 FINISHED")
    print("=" * 60)


if __name__ == "__main__":
    main()