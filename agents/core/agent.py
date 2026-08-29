from agents.brain.llm import ask_llm
from agents.brain.decision import analyze_response
from agents.executor.executor import execute
from agents.core.memory_store import (
    load_agent_memory,
    append_agent_memory,
    load_shared_memory,
    append_shared_memory,
    format_history
)


class Agent:

    def __init__(self, name, role, allowed_tools=None):
        self.name = name
        self.role = role
        self.allowed_tools = allowed_tools or []

    # ========================================================
    # CHAT : point d'entrée conversationnel (mémoire incluse)
    # ========================================================
    #
    # Contrairement à run(), qui exécute une tâche ponctuelle
    # sans se souvenir de rien d'un appel à l'autre, chat() est
    # destiné à l'interface : il conserve une mémoire propre à
    # l'agent, et peut aussi lire/écrire dans une mémoire
    # partagée entre agents pour les projets de groupe.

    def chat(self, message, shared=False, max_steps=8):

        individual_history = load_agent_memory(self.name)

        context_sections = [
            "HISTORIQUE DE CONVERSATION AVEC CET AGENT "
            "(du plus ancien au plus récent) :",
            format_history(individual_history)
        ]

        if shared:

            shared_history = load_shared_memory()

            context_sections += [
                "",
                "MÉMOIRE PARTAGÉE DU PROJET DE GROUPE "
                "(échanges d'autres agents et de l'utilisateur) :",
                format_history(shared_history)
            ]

        task_with_context = f"""
{chr(10).join(context_sections)}

============================================================

NOUVEAU MESSAGE DE L'UTILISATEUR :

{message}
"""

        result = self.run(task_with_context, max_steps=max_steps)

        response_text = self.stringify_result(result)

        append_agent_memory(self.name, "user", message)
        append_agent_memory(self.name, "agent", response_text)

        if shared:

            append_shared_memory(self.name, "user", message)
            append_shared_memory(self.name, "agent", response_text)

        return result

    @staticmethod
    def stringify_result(result):
        """
        Convertit le résultat renvoyé par run() (dict ou str)
        en texte lisible, pour l'affichage dans le chat et le
        stockage en mémoire.
        """

        if isinstance(result, dict):

            message = result.get("message")
            status = result.get("status")

            if message and status:
                return f"[{status}] {message}"

            if message:
                return message

            return str(result)

        return str(result)

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

            previous_tool_entries = [
                item for item in history if "tool" in item
            ]

            previous_actions = [
                {
                    "tool": item.get("tool"),
                    "arguments": item.get("arguments")
                }
                for item in previous_tool_entries
            ]

            if action in previous_actions:

                # Résultat obtenu la ou les fois précédentes où
                # cette action identique a été exécutée.
                last_result = next(
                    (
                        item.get("result")
                        for item in reversed(previous_tool_entries)
                        if item.get("tool") == tool
                        and item.get("arguments") == arguments
                    ),
                    None
                )

                # Nombre de fois où cette action a déjà été
                # bloquée pour répétition (pas exécutée, juste
                # proposée à nouveau).
                repeat_count = sum(
                    1
                    for item in history
                    if item.get("type") == "repeated_action"
                    and item.get("action") == action
                )

                if repeat_count >= 1:

                    # ------------------------------------------
                    # DISJONCTEUR
                    #
                    # Le LLM a déjà été prévenu une fois et
                    # persiste à proposer exactement la même
                    # action. Un modèle local de petite taille
                    # peut rester bloqué indéfiniment dans ce
                    # cas : on arrête nous-mêmes la boucle plutôt
                    # que de consommer les étapes restantes pour
                    # rien.
                    # ------------------------------------------

                    print()
                    print("⛔ Boucle détectée : action identique proposée")
                    print("   plusieurs fois malgré l'avertissement.")
                    print("   Arrêt automatique de l'agent.")

                    success = (
                        isinstance(last_result, dict)
                        and last_result.get("success", True) is not False
                        and not last_result.get("error")
                    ) or (
                        isinstance(last_result, str)
                        and "erreur" not in last_result.lower()
                        and "error" not in last_result.lower()
                    )

                    return {
                        "status": "DONE" if success else "FAIL",
                        "message": (
                            "Travail arrêté automatiquement après "
                            "détection d'une boucle (action répétée "
                            "sans progrès)."
                        ),
                        "last_action": action,
                        "last_result": last_result
                    }

                print()
                print("⚠️ Action répétée inutilement.")
                print("Le LLM doit choisir une autre action.")

                history.append({
                    "type": "repeated_action",
                    "action": action,
                    "previous_result": last_result,
                    "instruction": (
                        "Cette action a déjà été exécutée avec le "
                        "résultat indiqué ci-dessus. Ne la répète "
                        "surtout pas. Si ce résultat est un succès, "
                        "termine maintenant en renvoyant le JSON "
                        "final. Sinon, choisis un outil ou des "
                        "arguments réellement différents."
                    )
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