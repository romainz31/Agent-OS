from agents.brain.llm import ask_llm
from agents.brain.decision import analyze_response
from agents.executor.executor import execute


class Agent:

    def __init__(self, name, role, allowed_tools=None):
        self.name = name
        self.role = role
        self.allowed_tools = allowed_tools or []

    def run(self, task, max_steps=8):

        history = []

        system_prompt = f"""
Tu es l'agent {self.name}.

ROLE :
{self.role}

OUTILS AUTORISÉS :
{self.allowed_tools}

RÈGLES :

1. Utilise uniquement les outils autorisés.
2. Respecte strictement ton rôle.
3. Ne fais jamais le travail d'un autre agent.
4. Si un outil échoue, analyse l'erreur.
5. Après une erreur, tu peux réessayer.
6. Ne répète jamais exactement la même action si son résultat n'a pas changé.
7. Une exécution Python réussie ne signifie PAS automatiquement que la tâche est terminée.
8. Lorsque ton travail est terminé, retourne uniquement un JSON final.
"""

        for step in range(1, max_steps + 1):

            print()
            print("=" * 60)
            print(f"ÉTAPE {step}/{max_steps}")
            print("=" * 60)

            prompt = f"""
{system_prompt}

TÂCHE :

{task}

HISTORIQUE DES ACTIONS :

{history}

============================================================

Décide maintenant de l'action suivante.

SI TU DOIS UTILISER UN OUTIL :

Retourne UNIQUEMENT :

{{
    "tool": "nom_outil",
    "arguments": {{
        "argument": "valeur"
    }}
}}

SI TON TRAVAIL EST TERMINÉ :

Retourne UNIQUEMENT un JSON final adapté à ton rôle.

NE RETOURNE PAS DE TEXTE EN DEHORS DU JSON.
"""

            response = ask_llm(prompt)

            print()
            print("RÉPONSE DU LLM :")
            print(response)

            decision = analyze_response(response)

            # --------------------------------------------------
            # Réponse invalide
            # --------------------------------------------------

            if not isinstance(decision, dict):

                print()
                print("⚠️ Réponse JSON invalide.")

                history.append({
                    "type": "llm_error",
                    "response": response
                })

                continue

            # --------------------------------------------------
            # RÉPONSE FINALE
            # --------------------------------------------------

            if "tool" not in decision:

                print()
                print("=" * 60)
                print("RÉPONSE FINALE")
                print("=" * 60)
                print(decision)

                return decision

            # --------------------------------------------------
            # ACTION OUTIL
            # --------------------------------------------------

            tool = decision.get("tool")
            arguments = decision.get("arguments", {})

            # --------------------------------------------------
            # Vérification outil autorisé
            # --------------------------------------------------

            if tool not in self.allowed_tools:

                error = f"Outil non autorisé : {tool}"

                print()
                print("ERREUR :", error)

                history.append({
                    "tool": tool,
                    "arguments": arguments,
                    "result": {
                        "success": False,
                        "error": error
                    }
                })

                continue

            # --------------------------------------------------
            # Détection des actions identiques
            # --------------------------------------------------

            action = {
                "tool": tool,
                "arguments": arguments
            }

            previous_actions = [
                {
                    "tool": item.get("tool"),
                    "arguments": item.get("arguments")
                }
                for item in history
                if "tool" in item
            ]

            if action in previous_actions:

                print()
                print("⚠️ Action répétée inutilement.")
                print("Le LLM doit choisir une autre action.")

                history.append({
                    "type": "repeated_action",
                    "action": action
                })

                continue

            # --------------------------------------------------
            # EXÉCUTION
            # --------------------------------------------------

            print()
            print(f"[AGENT] → Outil : {tool}")

            result = execute({
                "tool": tool,
                "arguments": arguments
            })

            print()
            print("RÉSULTAT OUTIL :")
            print(result)

            # --------------------------------------------------
            # HISTORIQUE
            # --------------------------------------------------

            history.append({
                "tool": tool,
                "arguments": arguments,
                "result": result
            })

        # ------------------------------------------------------
        # LIMITE
        # ------------------------------------------------------

        print()
        print("⚠️ Nombre maximum d'étapes atteint.")

        return {
            "status": "FAIL",
            "message": (
                f"La tâche n'a pas pu être terminée "
                f"dans la limite de {max_steps} étapes."
            )
        }