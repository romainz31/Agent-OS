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

from agents.core.knowledge_store import (
    search_knowledge,
    format_knowledge,
    add_knowledge
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

        self.allowed_tools = (
            allowed_tools or []
        )


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

        individual_history = (
            load_agent_memory(
                self.name
            )
        )

        context_sections = [

            "HISTORIQUE DE CONVERSATION AVEC CET AGENT "
            "(du plus ancien au plus récent) :",

            format_history(
                individual_history
            )

        ]

        if shared:

            shared_history = (
                load_shared_memory()
            )

            context_sections += [

                "",

                "MÉMOIRE PARTAGÉE DU PROJET "
                "(échanges des agents et de l'utilisateur) :",

                format_history(
                    shared_history
                )

            ]

        relevant_knowledge = (
            search_knowledge(
                message,
                max_results=5
            )
        )

        context_sections += [

            "",

            "BASE DE CONNAISSANCES "
            "(informations déjà recherchées sur le Web) :",

            format_knowledge(
                relevant_knowledge
            )

        ]

        if extra_context:

            context_sections += [

                "",

                "RÉSULTATS DIRECTS DES AUTRES AGENTS :",

                extra_context

            ]

        task_with_context = f"""

{chr(10).join(context_sections)}

============================================================

NOUVEAU MESSAGE DE L'UTILISATEUR :

{message}

"""

        result = self.run(
            task_with_context,
            max_steps=max_steps
        )

        response_text = (
            self.stringify_result(
                result
            )
        )

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

        if self.name == "Researcher":

            self._save_research_knowledge(
                result
            )

        return result


    # ========================================================
    # SAUVEGARDE RESEARCH
    # ========================================================

    def _save_research_knowledge(
        self,
        result
    ):

        if not isinstance(
            result,
            dict
        ):

            return

        knowledge = result.get(
            "knowledge"
        )

        if not isinstance(
            knowledge,
            dict
        ):

            return

        title = knowledge.get(
            "title",
            ""
        )

        source = knowledge.get(
            "source",
            ""
        )

        summary = knowledge.get(
            "summary",
            ""
        )

        facts = knowledge.get(
            "facts",
            []
        )

        topics = knowledge.get(
            "topics",
            []
        )

        if not title:

            return

        add_knowledge(

            title=title,

            source=source,

            summary=summary,

            facts=facts,

            topics=topics

        )


    # ========================================================
    # STRINGIFY
    # ========================================================

    @staticmethod
    def stringify_result(
        result
    ):

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
                    f"[{status}] {message}"
                )

            if message:

                return message

            return str(
                result
            )

        return str(
            result
        )


    # ========================================================
    # VALIDATION DU VERDICT
    # ========================================================

    def _validate_final_decision(
        self,
        decision,
        history
    ):

        if not isinstance(
            decision,
            dict
        ):

            return {

                "valid":
                    False,

                "reason":
                    "La réponse finale n'est pas un dictionnaire JSON."

            }


        status = decision.get(
            "status"
        )


        # ====================================================
        # PASS / FAIL RÉSERVÉS AU TESTER
        # ====================================================

        if status in [
            "PASS",
            "FAIL"
        ]:

            if self.name != "Tester":

                return {

                    "valid":
                        False,

                    "reason":
                        (
                            f"L'agent {self.name} n'a pas le droit "
                            f"de produire un verdict {status}. "
                            f"Seul le Tester peut produire PASS ou FAIL."
                        )

                }


        # ====================================================
        # PREUVES OBLIGATOIRES POUR PASS
        # ====================================================

        if (
            self.name == "Tester"
            and status == "PASS"
        ):

            tools_used = [

                item.get(
                    "tool"
                )

                for item in history

                if item.get(
                    "tool"
                )

            ]


            if "read_file" not in tools_used:

                return {

                    "valid":
                        False,

                    "reason":
                        (
                            "PASS refusé : le Tester n'a pas utilisé "
                            "read_file pour inspecter le fichier réel."
                        )

                }


            if "run_python" not in tools_used:

                return {

                    "valid":
                        False,

                    "reason":
                        (
                            "PASS refusé : le Tester n'a pas exécuté "
                            "le programme avec run_python."
                        )

                }


            execution_results = [

                item.get(
                    "result"
                )

                for item in history

                if (
                    item.get("tool")
                    == "run_python"
                )

            ]


            successful_execution = False


            for result in execution_results:

                if not isinstance(
                    result,
                    dict
                ):

                    continue

                if result.get(
                    "success"
                ) is True:

                    successful_execution = True

                    break


            if not successful_execution:

                return {

                    "valid":
                        False,

                    "reason":
                        (
                            "PASS refusé : aucune exécution réussie "
                            "du programme n'a été observée par le Tester."
                        )

                }


        return {

            "valid":
                True,

            "reason":
                ""

        }


    # ========================================================
    # AGENTS SANS OUTILS
    # ========================================================

    def _run_without_tools(
        self,
        task
    ):

        prompt = f"""

Tu es l'agent {self.name} de Agent-OS.

============================================================
ROLE
============================================================

{self.role}

============================================================
IMPORTANT
============================================================

Tu ne disposes d'AUCUN outil.

Tu dois uniquement analyser la tâche et produire
immédiatement ton résultat final.

Ne propose aucune utilisation d'outil.

Ne simule aucune action technique.

Ne retourne aucun texte hors du JSON final.

============================================================
TÂCHE
============================================================

{task}

============================================================
RÉPONSE
============================================================

Retourne directement le JSON final correspondant à ton rôle.

"""

        print()

        print(
            "=" * 60
        )

        print(
            "EXÉCUTION DIRECTE — AGENT SANS OUTILS"
        )

        print(
            "=" * 60
        )

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

        if not isinstance(
            decision,
            dict
        ):

            return {

                "status":
                    "FAIL",

                "message":
                    (
                        f"L'agent {self.name} "
                        "n'a pas retourné un JSON valide."
                    ),

                "raw_response":
                    response

            }

        return decision


    # ========================================================
    # RUN
    # ========================================================

    def run(
        self,
        task,
        max_steps=8
    ):

        # ----------------------------------------------------
        # OPTIMISATION IMPORTANTE
        # ----------------------------------------------------
        # Un agent sans outils n'a aucune raison de fonctionner
        # dans une boucle d'actions.
        #
        # Exemple :
        # Planner -> aucun outil -> réponse directe.
        # ----------------------------------------------------

        if not self.allowed_tools:

            return self._run_without_tools(
                task
            )


        history = []


        system_prompt = f"""

Tu es l'agent {self.name} de Agent-OS.

============================================================
ROLE
============================================================

{self.role}

============================================================
OUTILS AGENT-OS AUTORISÉS
============================================================

{self.allowed_tools}

IMPORTANT :

La liste ci-dessus contient la liste COMPLÈTE des outils
que tu peux réellement appeler.

Tu ne peux appeler AUCUN autre outil.

Un nom de commande, de fonction, de programme, de module,
d'API ou d'exemple découvert dans une page Web n'est PAS
automatiquement un outil Agent-OS.

Seuls les outils présents dans "OUTILS AGENT-OS AUTORISÉS"
peuvent être utilisés dans un JSON avec le champ "tool".

============================================================
RÈGLES GÉNÉRALES
============================================================

1. Utilise uniquement les outils autorisés.

2. Respecte strictement ton rôle.

3. Ne fais jamais le travail d'un autre agent.

4. Si un outil échoue, analyse réellement son résultat.

5. Après une erreur, choisis une stratégie adaptée.

6. Ne répète jamais exactement la même action
   si son résultat précédent était suffisant.

7. Une exécution réussie signifie uniquement que Python
   s'est terminé sans erreur système.

8. Une exécution réussie ne prouve pas à elle seule
   que l'objectif est respecté.

9. Analyse toujours réellement le contenu de output.

10. N'invente jamais de résultat d'outil.

11. Lorsque les preuves disponibles permettent de conclure,
    termine immédiatement.

12. Ne crée jamais de fichier supplémentaire sans nécessité.

============================================================
RÈGLE DE SÉPARATION DES RÔLES
============================================================

Le Developer peut effectuer des tests techniques.

Cependant :

- le Developer ne produit jamais PASS ;
- le Developer ne produit jamais FAIL comme verdict ;
- le Developer indique uniquement que son implémentation
  est terminée ;
- le Tester est le seul agent autorisé à produire PASS ou FAIL.

Le Tester doit produire ses propres preuves.

============================================================
RÈGLE SPÉCIALE TESTER
============================================================

Si tu es le Tester :

1. identifie le fichier réel ;
2. utilise read_file ;
3. analyse le code réel ;
4. utilise run_python lorsque possible ;
5. utilise input_data lorsqu'un input() est nécessaire ;
6. analyse réellement output et error ;
7. compare les résultats avec l'objectif ;
8. seulement après cela, produis PASS ou FAIL.

Tu ne dois jamais inventer un résultat.

============================================================
FORMAT OUTIL
============================================================

Si tu dois utiliser un outil :

Retourne UNIQUEMENT :

{{
    "tool": "nom_outil",
    "arguments": {{
        "argument": "valeur"
    }}
}}

============================================================
FORMAT FINAL
============================================================

Lorsque ton rôle est terminé :

Retourne UNIQUEMENT un JSON final.

Aucun texte en dehors du JSON.

"""


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

TÂCHE :

{task}

============================================================

HISTORIQUE DES ACTIONS :

{history}

============================================================

DÉCISION :

Choisis UNE seule action :

1. utiliser un outil autorisé ;
2. terminer immédiatement avec le JSON final.

Si les informations nécessaires sont déjà disponibles,
termine.

Ne répète pas une action déjà exécutée avec succès
sans raison précise.

Si une action précédente a échoué, analyse son erreur
avant de décider de la suite.

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

                validation = (
                    self._validate_final_decision(
                        decision,
                        history
                    )
                )


                if not validation.get(
                    "valid"
                ):

                    error = validation.get(
                        "reason"
                    )

                    print()

                    print(
                        "[AGENT] Verdict final refusé."
                    )

                    print(
                        "[AGENT]",
                        error
                    )

                    history.append({

                        "type":
                            "invalid_final_decision",

                        "decision":
                            decision,

                        "reason":
                            error

                    })

                    continue


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


            if tool not in self.allowed_tools:

                error = (
                    f"Outil non autorisé : {tool}. "
                    f"Outils disponibles : {self.allowed_tools}."
                )

                print()

                print(
                    "ERREUR :",
                    error
                )

                history.append({

                    "type":
                        "unauthorized_tool",

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


            action = {

                "tool":
                    tool,

                "arguments":
                    arguments

            }


            # =================================================
            # DÉTECTION DE RÉPÉTITION
            # =================================================

            previous_success = None


            for item in reversed(
                history
            ):

                if (
                    item.get("tool") == tool
                    and item.get("arguments") == arguments
                ):

                    result = item.get(
                        "result"
                    )

                    if (
                        isinstance(
                            result,
                            dict
                        )
                        and result.get(
                            "success"
                        ) is True
                    ):

                        previous_success = result

                    break


            if previous_success is not None:

                print()

                print(
                    "[AGENT] Action déjà exécutée avec succès."
                )

                print(
                    "[AGENT] Le résultat existant est réutilisé."
                )

                history.append({

                    "type":
                        "repeated_success",

                    "action":
                        action,

                    "previous_result":
                        previous_success,

                    "instruction":
                        (
                            "Cette action a déjà réussi. "
                            "Utilise le résultat existant et "
                            "termine si ton rôle est terminé."
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


            if isinstance(
                result,
                dict
            ):

                if result.get(
                    "success"
                ) is True:

                    print(
                        "[AGENT] Outil exécuté avec succès."
                    )

                else:

                    print(
                        "[AGENT] L'outil a retourné une erreur."
                    )


            history.append({

                "tool":
                    tool,

                "arguments":
                    arguments,

                "result":
                    result

            })


        # ====================================================
        # LIMITE
        # ====================================================

        return {

            "status":
                "FAIL",

            "message":
                (
                    f"La tâche n'a pas pu être terminée "
                    f"dans la limite de {max_steps} étapes."
                ),

            "history":
                history

        }