from agents.core.team import developer, tester
from agents.brain.llm import ask_llm
from agents.brain.decision import analyze_response
from agents.executor.executor import execute


# ============================================================
# CONFIGURATION
# ============================================================

file_path = "applications/agent_created.py"

expected = "42"


# ============================================================
# 1. DEVELOPER — PREMIÈRE VERSION
# ============================================================

developer_task = """
Crée le fichier :

applications/agent_created.py

Il doit contenir une fonction :

multiply(a, b)

Cette fonction doit multiplier deux nombres.

Pour cette première version, fais volontairement une erreur :
utilise + au lieu de *.

Ajoute également :

print(multiply(6, 7))

Utilise obligatoirement l'outil write_file.
"""

print("\n========== DEVELOPER ==========")

response = ask_llm(developer_task, mode="chat")

print(response)

decision = analyze_response(response)

print("\nDÉCISION :")
print(decision)

if decision["action"] == "tool":

    result = execute(decision)

    print("\nRÉSULTAT DEVELOPER :")
    print(result)


# ============================================================
# 2. BOUCLE TEST / CORRECTION
# ============================================================

for attempt in range(3):

    print("\n")
    print("=" * 60)
    print(f"TENTATIVE {attempt + 1}")
    print("=" * 60)


    # ========================================================
    # TESTER — EXÉCUTION
    # ========================================================

    tester_task = f"""
Tu es l'agent Tester.

Tu dois tester le fichier :

{file_path}

Le programme doit effectuer le test :

multiply(6, 7)

Le résultat attendu est :

42

Utilise obligatoirement l'outil run_python pour exécuter :

{file_path}
"""

    print("\n========== TESTER ==========")

    response = ask_llm(tester_task, mode="chat")

    print(response)

    decision = analyze_response(response)

    print("\nDÉCISION :")
    print(decision)

    if decision["action"] != "tool":

        print("\n❌ Le Tester n'a pas demandé l'outil run_python.")
        break

    result = execute(decision)

    print("\nRÉSULTAT OUTIL :")
    print(result)


    # ========================================================
    # VÉRIFICATION DÉTERMINISTE
    # ========================================================

    output = result.get("output", "").strip()

    print("\n========== VÉRIFICATION ==========")

    print("Résultat obtenu :", output)
    print("Résultat attendu :", expected)


    if output == expected:

        print("\n✅ TEST PASS")

        print("\nLe programme est correct.")
        break


    # ========================================================
    # TEST ÉCHOUÉ
    # ========================================================

    print("\n❌ TEST FAIL")


    # ========================================================
    # RAPPORT DU TESTER
    # ========================================================

    report_task = f"""
Tu es l'agent Tester.

La mission est de vérifier cette fonction :

multiply(a, b)

Le test demandé est :

multiply(6, 7)

Le résultat attendu est :

42

Le système a exécuté le programme et a obtenu :

{output}

Le système a déjà déterminé que le test est :

FAIL

Rédige maintenant un rapport court destiné au Developer.

Le rapport doit expliquer :
- le résultat obtenu ;
- le résultat attendu ;
- la cause probable de l'erreur ;
- ce que le Developer doit corriger.

Ne demande aucun nouvel outil.
Ne réponds pas avec un appel à l'outil addition.
Ne réponds pas avec un appel à run_python.

Réponds simplement avec le rapport du test.
"""

    print("\n========== RAPPORT TESTER ==========")

    report = ask_llm(report_task, mode="chat")

    print(report)


    # ========================================================
    # DEVELOPER — CORRECTION
    # ========================================================

    correction_task = f"""
Tu es l'agent Developer.

Tu dois corriger le fichier :

{file_path}


MISSION ORIGINALE :

Créer une fonction Python :

multiply(a, b)

Cette fonction doit multiplier deux nombres.

Le test obligatoire est :

multiply(6, 7)

Le résultat attendu est :

42


RÉSULTAT DU TEST :

Le programme a actuellement produit :

{output}

Le résultat attendu est :

{expected}


RAPPORT DU TESTER :

{report}


INSTRUCTIONS :

1. Corrige le problème identifié par le Tester.

2. La fonction doit réellement effectuer une multiplication.

Elle doit utiliser :

return a * b

3. CONSERVE obligatoirement le test :

print(multiply(6, 7))

4. Ne supprime pas le test.

5. Réécris le fichier COMPLET.

6. Utilise obligatoirement l'outil write_file.

7. Le fichier doit être directement exécutable par Python.

Le contenu final doit au minimum être :

def multiply(a, b):
    return a * b

print(multiply(6, 7))
"""

    print("\n========== DEVELOPER CORRECTION ==========")

    response = ask_llm(correction_task, mode="chat")

    print(response)

    decision = analyze_response(response)

    print("\nDÉCISION CORRECTION :")
    print(decision)

    if decision["action"] != "tool":

        print("\n❌ Le Developer n'a pas demandé write_file.")
        break

    result = execute(decision)

    print("\nRÉSULTAT CORRECTION :")
    print(result)


else:

    print("\n⚠️ Nombre maximum de tentatives atteint.")