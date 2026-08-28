import json

from agents.brain.llm import ask_llm
from agents.executor.executor import execute


class Agent:

    def __init__(self, name, role, allowed_tools=None):
        self.name = name
        self.role = role
        self.allowed_tools = allowed_tools or []

    def run(self, task):

        prompt = f"""
Tu es l'agent {self.name}.

Ton rôle :
{self.role}

Tâche :
{task}

Outils autorisés :
{self.allowed_tools}

RÈGLES STRICTES :

1. Travaille étape par étape.
2. N'utilise que les outils autorisés.
3. Ne répète jamais exactement la même action.
4. Après chaque outil, analyse son résultat.
5. Si une action réussit et que la tâche est terminée, arrête-toi.
6. Si une erreur apparaît, corrige-la puis reteste.
7. Pour utiliser un outil, réponds UNIQUEMENT avec un JSON valide.
8. Quand la tâche est terminée, réponds normalement.
9. Ne réécris jamais un fichier identique sans raison.
10. Ne lance pas plusieurs fois inutilement le même programme.

IMPORTANT :

Si tu crées un fichier Python avec write_file, le contenu doit être
du vrai code Python.

Dans le JSON, utilise \\n pour représenter les retours à la ligne.

Exemple :

{{
    "tool": "write_file",
    "arguments": {{
        "file_path": "applications/test.py",
        "content": "def multiply(a, b):\\n    return a * b\\n\\nprint(multiply(6, 7))"
    }}
}}
"""

        max_steps = 8

        executed_actions = []

        for step in range(max_steps):

            print()
            print("=" * 60)
            print(f"ÉTAPE {step + 1}/{max_steps}")
            print("=" * 60)

            response = ask_llm(prompt, mode="chat")

            print()
            print("RÉPONSE DU LLM :")
            print(response)

            # ==================================================
            # RÉPONSE NORMALE DU LLM
            # ==================================================

            try:
                decision = json.loads(response)

            except json.JSONDecodeError:

                print()
                print("============================================================")
                print("RÉPONSE FINALE")
                print("============================================================")
                print(response)

                return response

            # ==================================================
            # PAS D'OUTIL
            # ==================================================

            if "tool" not in decision:

                print()
                print("============================================================")
                print("RÉPONSE FINALE")
                print("============================================================")
                print(response)

                return response

            tool_name = decision["tool"]
            arguments = decision.get("arguments", {})

            print()
            print("[AGENT] → Outil :", tool_name)

            # ==================================================
            # SÉCURITÉ : OUTIL AUTORISÉ ?
            # ==================================================

            if tool_name not in self.allowed_tools:

                result = (
                    f"ERREUR : l'agent {self.name} "
                    f"n'est pas autorisé à utiliser l'outil "
                    f"{tool_name}."
                )

                print()
                print("RÉSULTAT OUTIL :")
                print(result)

                prompt = f"""
La tentative précédente a échoué.

Erreur :
{result}

Tâche :
{task}

Outils autorisés :
{self.allowed_tools}

Choisis maintenant une action différente et autorisée.

Si la tâche est terminée, réponds normalement.
"""

                continue

            # ==================================================
            # IDENTIFICATION DE L'ACTION
            # ==================================================

            action_key = (
                tool_name,
                json.dumps(
                    arguments,
                    sort_keys=True,
                    ensure_ascii=False
                )
            )

            # ==================================================
            # DÉTECTION DES RÉPÉTITIONS
            # ==================================================

            if action_key in executed_actions:

                print()
                print("⚠️ ACTION DÉJÀ EXÉCUTÉE")
                print("Outil :", tool_name)
                print("Arguments :", arguments)
                print("→ Exécution ignorée.")

                # Si le LLM insiste malgré tout,
                # on lui donne une dernière instruction claire.

                prompt = f"""
Tu répètes exactement la même action.

Action déjà exécutée :
{json.dumps(decision, ensure_ascii=False)}

Tu dois maintenant faire l'une des deux choses suivantes :

1. utiliser un AUTRE outil autorisé pour poursuivre ;
2. terminer la tâche avec une réponse normale.

NE répète PAS cette action.

Tâche :
{task}

Outils autorisés :
{self.allowed_tools}
"""

                continue

            executed_actions.append(action_key)

            # ==================================================
            # EXÉCUTION
            # ==================================================

            try:

                result = execute(decision)

            except Exception as e:

                result = {
                    "success": False,
                    "output": "",
                    "error": str(e)
                }

            print()
            print("RÉSULTAT OUTIL :")
            print(result)

            # ==================================================
            # RÈGLE IMPORTANTE :
            #
            # run_python réussi = programme exécuté correctement
            # ==================================================

            if tool_name == "run_python":

                if isinstance(result, dict):

                    success = result.get("success", False)

                    if success:

                        output = result.get("output", "").strip()

                        print()
                        print("=" * 60)
                        print("✅ TÂCHE TERMINÉE")
                        print("=" * 60)

                        if output:

                            print(
                                f"Le programme a été exécuté "
                                f"avec succès.\nRésultat : {output}"
                            )

                        else:

                            print(
                                "Le programme a été exécuté "
                                "avec succès."
                            )

                        return (
                            "Tâche terminée avec succès. "
                            f"Résultat : {output}"
                            if output
                            else
                            "Tâche terminée avec succès."
                        )

            # ==================================================
            # PRÉPARATION DU PROCHAIN TOUR
            # ==================================================

            prompt = f"""
Tu es l'agent {self.name}.

Ton rôle :
{self.role}

Tâche initiale :
{task}

Outils autorisés :
{self.allowed_tools}

Tu viens d'utiliser cet outil :

{json.dumps(decision, ensure_ascii=False, indent=4)}

Résultat :

{result}

Analyse maintenant le résultat.

RÈGLES :

- Si une erreur est présente, corrige-la.
- Si le fichier doit être modifié, utilise write_file.
- Si le programme doit être testé, utilise run_python.
- Ne répète jamais exactement la même action.
- Ne réécris pas un fichier identique sans raison.
- Si la tâche est terminée, réponds normalement.
- Si tu utilises un outil, réponds UNIQUEMENT avec un JSON valide.
"""

        # ======================================================
        # LIMITE
        # ======================================================

        print()
        print("⚠️ Nombre maximum d'étapes atteint.")
        print(
            f"La tâche n'a pas pu être terminée "
            f"dans la limite de {max_steps} étapes."
        )

        return (
            f"La tâche n'a pas pu être terminée "
            f"dans la limite de {max_steps} étapes."
        )