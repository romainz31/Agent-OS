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

    def __init__(
        self,
        name,
        role,
        allowed_tools=None
    ):

        self.name = name
        self.role = role
        self.allowed_tools = allowed_tools or []

    # ========================================================
    # CHAT
    # ========================================================

    def chat(
        self,
        message,
        shared=False,
        max_steps=8,
        extra_context=""
    ):

        individual_history = load_agent_memory(
            self.name
        )

        context_sections = [

            "HISTORIQUE DE CONVERSATION AVEC CET AGENT :",

            format_history(
                individual_history
            )

        ]

        # ----------------------------------------------------
        # MÉMOIRE PARTAGÉE
        # ----------------------------------------------------

        if shared:

            shared_history = load_shared_memory()

            context_sections += [

                "",

                "MÉMOIRE PARTAGÉE DU PROJET :",

                format_history(
                    shared_history
                )

            ]

        # ----------------------------------------------------
        # CONTEXTE TRANSMIS PAR L'ORCHESTRATEUR
        # ----------------------------------------------------

        if extra_context:

            context_sections += [

                "",

                "CONTEXTE TRANSMIS PAR L'ORCHESTRATEUR :",

                extra_context

            ]

        task_with_context = f"""

{chr(10).join(context_sections)}

============================================================

NOUVELLE DEMANDE :

{message}
"""

        result = self.run(
            task_with_context,
            max_steps=max_steps
        )

        response_text = self.stringify_result(
            result
        )

        # ----------------------------------------------------
        # MÉMOIRE INDIVIDUELLE
        # ----------------------------------------------------

        append_agent_memory(
            self.name,
            "user",
            message
        )

        append_agent_memory(
            self.name,
            "agent",
            response_text
        )

        # ----------------------------------------------------
        # MÉMOIRE PARTAGÉE
        # ----------------------------------------------------

        if shared:

            append_shared_memory(
                self.name,
                "user",
                message
            )

            append_shared_memory(
                self.name,
                "agent",
                response_text
            )

        return result

    # ========================================================
    # FORMATAGE
    # ========================================================

    @staticmethod
    def stringify_result(result):

        if isinstance(
            result,
            dict
        ):

            message = result.get(
                "message"
            )

            status = result.get(
                "status"
            )

            if message and status:

                return (
                    f"[{status}] "
                    f"{message}"
                )

            if message:

                return message

            try:

                import json

                return json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2
                )

            except Exception:

                return str(result)

        return str(result)

    # ========================================================
    # EXECUTION AGENT
    # ========================================================

    def run(
        self,
        task,
        max_steps=8
    ):

        history = []

        system_prompt = f"""

Tu es l'agent {self.name} de Agent-OS.

============================================================
TON RÔLE
============================================================

{self.role}

============================================================
OUTILS AUTORISÉS
============================================================

{self.allowed_tools}

============================================================
RÈGLES GÉNÉRALES
============================================================

1. Respecte strictement ton rôle.

2. Utilise uniquement les outils autorisés.

3. Ne répète jamais inutilement une action.

4. Analyse toujours le résultat d'un outil avant
   de décider de l'action suivante.

5. Si une action réussit, considère son résultat
   comme acquis.

6. Si une action échoue, corrige la cause avant
   de réessayer.

7. Ne répète jamais exactement la même action
   après un échec sans modifier quelque chose.

8. Les fichiers du projet destinés aux utilisateurs
   doivent être placés dans :

   applications/

9. Les données doivent être placées dans :

   data/

10. NE JAMAIS créer un fichier utilisateur à la racine
    du projet.

11. Lorsqu'un fichier est créé dans applications/,
    utilise toujours un chemin comme :

    applications/mon_fichier.py

12. Avant d'utiliser run_python, vérifie que le programme
    peut réellement s'exécuter automatiquement.

13. NE CRÉE PAS de programme nécessitant une saisie
    utilisateur interactive avec input() si tu comptes
    utiliser run_python pour le tester.

14. Évite les boucles infinies comme :

    while True:

    lorsqu'elles nécessitent une interaction utilisateur.

15. Pour tester un programme interactif, crée plutôt
    des fonctions testables automatiquement.

16. Si le programme fonctionne et que les tests sont
    réussis, arrête ton travail.

17. Ne relance pas un test déjà réussi sans raison.

18. Lorsque ton travail est terminé, retourne un JSON final.

============================================================
FORMAT DES OUTILS
============================================================

Pour utiliser un outil :

{{
    "tool": "nom_outil",
    "arguments": {{
        "argument": "valeur"
    }}
}}

Pour terminer :

{{
    "status": "DONE",
    "message": "description du travail effectué"
}}

============================================================
"""

        # ====================================================
        # BOUCLE DE TRAVAIL
        # ====================================================

        for step in range(
            1,
            max_steps + 1
        ):

            print()
            print(
                "=" * 60
            )

            print(
                f"ÉTAPE {step}/{max_steps}"
            )

            print(
                "=" * 60
            )

            prompt = f"""

{system_prompt}

============================================================
TÂCHE
============================================================

{task}

============================================================
HISTORIQUE DES ACTIONS
============================================================

{history}

============================================================

Décide maintenant de la prochaine action.

Retourne UNIQUEMENT du JSON.
"""

            response = ask_llm(
                prompt
            )

            print()
            print(
                "RÉPONSE DU LLM :"
            )

            print(
                response
            )

            decision = analyze_response(
                response
            )

            # =================================================
            # RÉPONSE INVALIDE
            # =================================================

            if not isinstance(
                decision,
                dict
            ):

                history.append({

                    "type":
                        "llm_error",

                    "response":
                        response

                })

                continue

            # =================================================
            # RÉPONSE FINALE
            # =================================================

            if "tool" not in decision:

                print()
                print(
                    "=" * 60
                )

                print(
                    "RÉPONSE FINALE"
                )

                print(
                    "=" * 60
                )

                print(
                    decision
                )

                return decision

            # =================================================
            # OUTIL
            # =================================================

            tool = decision.get(
                "tool"
            )

            arguments = decision.get(
                "arguments",
                {}
            )

            # =================================================
            # OUTIL AUTORISÉ
            # =================================================

            if tool not in self.allowed_tools:

                error = (
                    f"Outil non autorisé : {tool}"
                )

                print(
                    "ERREUR :",
                    error
                )

                history.append({

                    "tool":
                        tool,

                    "arguments":
                        arguments,

                    "result": {

                        "success":
                            False,

                        "error":
                            error

                    }

                })

                continue

            # =================================================
            # NORMALISATION DES CHEMINS
            # =================================================

            arguments = self.normalize_arguments(
                tool,
                arguments
            )

            action = {

                "tool":
                    tool,

                "arguments":
                    arguments

            }

            # =================================================
            # DÉTECTION ACTION IDENTIQUE
            # =================================================

            previous_actions = [

                {

                    "tool":
                        item.get(
                            "tool"
                        ),

                    "arguments":
                        item.get(
                            "arguments"
                        )

                }

                for item in history

                if "tool" in item

            ]

            if action in previous_actions:

                previous_result = None

                for item in reversed(
                    history
                ):

                    if (
                        item.get(
                            "tool"
                        )
                        ==
                        tool

                        and

                        item.get(
                            "arguments"
                        )
                        ==
                        arguments
                    ):

                        previous_result = item.get(
                            "result"
                        )

                        break

                # ------------------------------------------------
                # Si l'action avait réussi
                # ------------------------------------------------

                if self._result_successful(
                    previous_result
                ):

                    print()
                    print(
                        "⚠️ Action déjà exécutée avec succès."
                    )

                    return {

                        "status":
                            "DONE",

                        "message":
                            (
                                "Travail terminé. "
                                "L'action demandée avait "
                                "déjà été exécutée avec succès."
                            )

                    }

                # ------------------------------------------------
                # Action ayant échoué
                # ------------------------------------------------

                print()
                print(
                    "⚠️ Action répétée après échec."
                )

                history.append({

                    "type":
                        "repeated_action",

                    "action":
                        action,

                    "previous_result":
                        previous_result,

                    "instruction":
                        (
                            "Ne répète pas cette action. "
                            "Corrige le problème ou "
                            "choisis une autre approche."
                        )

                })

                continue

            # =================================================
            # EXÉCUTION
            # =================================================

            print()
            print(
                f"[AGENT] → Outil : {tool}"
            )

            result = execute({

                "tool":
                    tool,

                "arguments":
                    arguments

            })

            print()
            print(
                "RÉSULTAT OUTIL :"
            )

            print(
                result
            )

            history.append({

                "tool":
                    tool,

                "arguments":
                    arguments,

                "result":
                    result

            })

        # =====================================================
        # LIMITE
        # =====================================================

        return {

            "status":
                "FAIL",

            "message":
                (
                    f"Nombre maximum de {max_steps} "
                    "étapes atteint."
                )

        }

    # ========================================================
    # NORMALISATION DES ARGUMENTS
    # ========================================================

    @staticmethod
    def normalize_arguments(
        tool,
        arguments
    ):

        if not isinstance(
            arguments,
            dict
        ):

            return {}

        arguments = dict(
            arguments
        )

        # ----------------------------------------------------
        # Tous les fichiers utilisateur doivent être
        # dans applications/
        # ----------------------------------------------------

        if tool in (
            "write_file",
            "read_file",
            "run_python"
        ):

            file_path = arguments.get(
                "file_path"
            )

            if isinstance(
                file_path,
                str
            ):

                file_path = file_path.replace(
                    "\\",
                    "/"
                )

                # ---------------------------------------------
                # Fichier racine
                # ---------------------------------------------

                if (
                    "/" not in file_path
                    and
                    not file_path.startswith(
                        "applications/"
                    )
                    and
                    not file_path.startswith(
                        "data/"
                    )
                ):

                    file_path = (
                        "applications/"
                        + file_path
                    )

                arguments[
                    "file_path"
                ] = file_path

        return arguments

    # ========================================================
    # SUCCÈS OUTIL
    # ========================================================

    @staticmethod
    def _result_successful(
        result
    ):

        if result is None:

            return False

        if isinstance(
            result,
            dict
        ):

            if result.get(
                "success"
            ) is False:

                return False

            if result.get(
                "error"
            ):

                return False

            return True

        if isinstance(
            result,
            str
        ):

            text = result.lower()

            if (
                "erreur" in text
                or
                "error" in text
                or
                "failed" in text
                or
                "timeout" in text
                or
                "délai maximum" in text
            ):

                return False

            return True

        return False