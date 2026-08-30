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

        # ----------------------------------------------------
        # MÉMOIRE INDIVIDUELLE
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # MÉMOIRE PARTAGÉE
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # MÉMOIRE DE CONNAISSANCES
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # CONTEXTE DIRECT
        # ----------------------------------------------------

        if extra_context:

            context_sections += [

                "",

                "RÉSULTATS DIRECTS DES AUTRES AGENTS :",

                extra_context

            ]


        # ----------------------------------------------------
        # TÂCHE
        # ----------------------------------------------------

        task_with_context = f"""

{chr(10).join(context_sections)}

============================================================

NOUVEAU MESSAGE DE L'UTILISATEUR :

{message}

"""


        # ----------------------------------------------------
        # EXÉCUTION
        # ----------------------------------------------------

        result = self.run(
            task_with_context,
            max_steps=max_steps
        )


        response_text = (
            self.stringify_result(
                result
            )
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


        # ----------------------------------------------------
        # MÉMOIRE DE CONNAISSANCES
        #
        # Seul le Researcher peut créer des connaissances.
        # ----------------------------------------------------

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
    # RUN
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
ROLE
============================================================

{self.role}

============================================================
OUTILS AUTORISÉS
============================================================

{self.allowed_tools}

============================================================
RÈGLES
============================================================

1. Utilise uniquement les outils autorisés.

2. Respecte strictement ton rôle.

3. Ne fais jamais le travail d'un autre agent.

4. Si un outil échoue, analyse l'erreur.

5. Après une erreur, tu peux réessayer.

6. Ne répète jamais exactement la même action
   si son résultat n'a pas changé.

7. Une exécution Python réussie ne signifie PAS
   automatiquement que la tâche est terminée.

8. Lorsque ton travail est terminé,
   retourne uniquement un JSON final.

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


            # ------------------------------------------------
            # RÉPONSE FINALE
            # ------------------------------------------------

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


            # ------------------------------------------------
            # OUTIL
            # ------------------------------------------------

            tool = decision.get(
                "tool"
            )


            arguments = decision.get(
                "arguments",
                {}
            )


            # ------------------------------------------------
            # VÉRIFICATION AUTORISATION
            # ------------------------------------------------

            if tool not in self.allowed_tools:

                error = (
                    f"Outil non autorisé : {tool}"
                )


                print()

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


            # ------------------------------------------------
            # ACTION
            # ------------------------------------------------

            action = {

                "tool":
                    tool,

                "arguments":
                    arguments

            }


            previous_tool_entries = [

                item

                for item in history

                if "tool" in item

            ]


            previous_actions = [

                {

                    "tool":
                        item.get("tool"),

                    "arguments":
                        item.get("arguments")

                }

                for item in previous_tool_entries

            ]


            if action in previous_actions:

                last_result = next(

                    (

                        item.get(
                            "result"
                        )

                        for item in reversed(
                            previous_tool_entries
                        )

                        if item.get(
                            "tool"
                        ) == tool

                        and item.get(
                            "arguments"
                        ) == arguments

                    ),

                    None

                )


                repeat_count = sum(

                    1

                    for item in history

                    if item.get(
                        "type"
                    ) == "repeated_action"

                    and item.get(
                        "action"
                    ) == action

                )


                if repeat_count >= 1:

                    success = (

                        isinstance(
                            last_result,
                            dict
                        )

                        and last_result.get(
                            "success",
                            True
                        ) is not False

                        and not last_result.get(
                            "error"
                        )

                    ) or (

                        isinstance(
                            last_result,
                            str
                        )

                        and "erreur"
                        not in last_result.lower()

                        and "error"
                        not in last_result.lower()

                    )


                    return {

                        "status":
                            "DONE"
                            if success
                            else "FAIL",

                        "message":
                            (
                                "Travail arrêté automatiquement "
                                "après détection d'une boucle."
                            ),

                        "last_action":
                            action,

                        "last_result":
                            last_result

                    }


                history.append({

                    "type":
                        "repeated_action",

                    "action":
                        action,

                    "previous_result":
                        last_result,

                    "instruction":
                        (
                            "Cette action a déjà été exécutée. "
                            "Ne la répète pas. "
                            "Choisis une action différente "
                            "ou termine la tâche."
                        )

                })

                continue


            # ------------------------------------------------
            # EXÉCUTION
            # ------------------------------------------------

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


        # ----------------------------------------------------
        # LIMITE
        # ----------------------------------------------------

        return {

            "status":
                "FAIL",

            "message":
                (
                    f"La tâche n'a pas pu être terminée "
                    f"dans la limite de {max_steps} étapes."
                )

        }
