from flask import (
    Flask,
    render_template,
    request,
    jsonify
)

from agents.core.team import (
    planner,
    developer,
    tester,
    researcher
)

from agents.core.memory_store import (
    load_agent_memory,
    save_agent_memory,
    load_shared_memory,
    save_shared_memory
)

from agents.core.chat_store import (
    create_chat,
    load_chat,
    list_chats,
    add_message,
    delete_chat
)


app = Flask(__name__)


# ============================================================
# AGENTS
# ============================================================

AGENTS = {

    "planner":
        planner,

    "developer":
        developer,

    "tester":
        tester,

    "researcher":
        researcher

}


# ============================================================
# PAGE PRINCIPALE
# ============================================================

@app.route("/")
def index():

    return render_template(
        "index.html",
        agents=list(
            AGENTS.keys()
        )
    )


# ============================================================
# LISTE DES CHATS
# ============================================================

@app.route("/api/chats")
def api_chats():

    chats = list_chats()

    result = []

    for chat in chats:

        result.append({

            "id":
                chat["id"],

            "title":
                chat.get(
                    "title",
                    "Nouveau chat"
                ),

            "agents":
                chat.get(
                    "agents",
                    []
                ),

            "shared":
                chat.get(
                    "shared",
                    False
                ),

            "updated_at":
                chat.get(
                    "updated_at",
                    ""
                )

        })

    return jsonify({

        "chats":
            result

    })


# ============================================================
# CRÉER CHAT
# ============================================================

@app.route(
    "/api/chats",
    methods=["POST"]
)
def api_create_chat():

    data = (
        request.get_json(
            force=True,
            silent=True
        )
        or {}
    )

    agents = data.get(
        "agents",
        []
    )

    if not isinstance(
        agents,
        list
    ):

        return jsonify({

            "error":
                "La liste des agents est invalide."

        }), 400

    if not agents:

        return jsonify({

            "error":
                "Sélectionne au moins un agent."

        }), 400

    for agent in agents:

        if agent not in AGENTS:

            return jsonify({

                "error":
                    f"Agent inconnu : {agent}"

            }), 400

    # Une mémoire partagée est utilisée lorsque
    # plusieurs agents participent au même chat.
    shared = len(
        agents
    ) > 1

    chat = create_chat(

        agents=
            agents,

        shared=
            shared

    )

    return jsonify({

        "chat":
            chat

    })


# ============================================================
# CHARGER CHAT
# ============================================================

@app.route(
    "/api/chats/<chat_id>"
)
def api_get_chat(
    chat_id
):

    chat = load_chat(
        chat_id
    )

    if chat is None:

        return jsonify({

            "error":
                "Chat introuvable."

        }), 404

    return jsonify({

        "chat":
            chat

    })


# ============================================================
# SUPPRIMER CHAT
# ============================================================

@app.route(
    "/api/chats/<chat_id>",
    methods=["DELETE"]
)
def api_delete_chat(
    chat_id
):

    deleted = delete_chat(
        chat_id
    )

    if not deleted:

        return jsonify({

            "error":
                "Chat introuvable."

        }), 404

    return jsonify({

        "success":
            True

    })


# ============================================================
# HISTORIQUE
# ============================================================

@app.route(
    "/api/history"
)
def api_history():

    chat_id = request.args.get(
        "chat_id",
        ""
    )

    if chat_id:

        chat = load_chat(
            chat_id
        )

        if chat is None:

            return jsonify({

                "error":
                    "Chat introuvable."

            }), 404

        return jsonify({

            "messages":
                chat.get(
                    "messages",
                    []
                ),

            "agents":
                chat.get(
                    "agents",
                    []
                ),

            "shared":
                chat.get(
                    "shared",
                    False
                )

        })

    return jsonify({

        "messages":
            []

    })


# ============================================================
# ENVOYER MESSAGE
# ============================================================

@app.route(
    "/api/chat",
    methods=["POST"]
)
def api_chat():

    data = (
        request.get_json(
            force=True,
            silent=True
        )
        or {}
    )

    chat_id = data.get(
        "chat_id",
        ""
    )

    message = (
        data.get(
            "message"
        )
        or ""
    ).strip()

    if not chat_id:

        return jsonify({

            "error":
                "Aucun chat sélectionné."

        }), 400

    if not message:

        return jsonify({

            "error":
                "Message vide."

        }), 400

    chat = load_chat(
        chat_id
    )

    if chat is None:

        return jsonify({

            "error":
                "Chat introuvable."

        }), 404

    selected_agents = chat.get(
        "agents",
        []
    )

    if not selected_agents:

        return jsonify({

            "error":
                "Aucun agent dans ce chat."

        }), 400

    shared = bool(
        chat.get(
            "shared",
            False
        )
    )

    # ========================================================
    # MESSAGE UTILISATEUR
    # ========================================================

    add_message(

        chat_id,

        "user",

        message

    )

    # ========================================================
    # CONTEXTE DE TRAVAIL
    # ========================================================

    previous_outputs = []

    responses = []

    # ========================================================
    # CHAÎNE D'AGENTS
    # ========================================================

    for agent_index, agent_key in enumerate(
        selected_agents
    ):

        agent = AGENTS.get(
            agent_key
        )

        if agent is None:

            continue

        # ----------------------------------------------------
        # CONTEXTE TRANSMIS AUX AGENTS SUIVANTS
        # ----------------------------------------------------

        direct_context = ""

        if previous_outputs:

            direct_context = (
                "\n\n".join(
                    previous_outputs
                )
            )

        # ----------------------------------------------------
        # MESSAGE DE TRAVAIL
        # ----------------------------------------------------

        if agent_index == 0:

            agent_message = message

        else:

            agent_message = f"""
Travaille sur la demande originale de l'utilisateur.

DEMANDE ORIGINALE :
{message}

Tu es l'agent {agent.name} dans une chaîne
multi-agents.

Les agents précédents ont déjà travaillé sur
cette demande.

Utilise leurs résultats ci-dessous comme base
de travail.

Ne recommence pas inutilement leur travail.

Concentre-toi UNIQUEMENT sur ton rôle.

RÉSULTATS DES AGENTS PRÉCÉDENTS :
"""

        # ----------------------------------------------------
        # APPEL AGENT
        # ----------------------------------------------------

        result = agent.chat(

            agent_message,

            shared=
                shared,

            extra_context=
                direct_context

        )

        response_text = (
            agent.stringify_result(
                result
            )
        )

        # ----------------------------------------------------
        # SAUVEGARDE CHAT
        # ----------------------------------------------------

        add_message(

            chat_id,

            "agent",

            response_text,

            agent=
                agent_key

        )

        # ----------------------------------------------------
        # CONSERVATION POUR AGENT SUIVANT
        # ----------------------------------------------------

        previous_outputs.append(

            f"""
============================================================
AGENT : {agent.name}
============================================================

{response_text}
"""

        )

        responses.append({

            "agent":
                agent_key,

            "name":
                agent.name,

            "response":
                response_text,

            "success":
                True

        })

    # ========================================================
    # CHAT FINAL
    # ========================================================

    chat = load_chat(
        chat_id
    )

    return jsonify({

        "chat":
            chat,

        "responses":
            responses

    })


# ============================================================
# RESET MÉMOIRE
# ============================================================

@app.route(
    "/api/reset-memory",
    methods=["POST"]
)
def api_reset_memory():

    data = (
        request.get_json(
            force=True,
            silent=True
        )
        or {}
    )

    memory_type = data.get(
        "type",
        ""
    )

    # --------------------------------------------------------
    # PLANNER
    # --------------------------------------------------------

    if memory_type == "planner":

        save_agent_memory(
            planner.name,
            []
        )

        return jsonify({

            "success":
                True,

            "message":
                "Mémoire du Planner réinitialisée."

        })

    # --------------------------------------------------------
    # DEVELOPER
    # --------------------------------------------------------

    if memory_type == "developer":

        save_agent_memory(
            developer.name,
            []
        )

        return jsonify({

            "success":
                True,

            "message":
                "Mémoire du Developer réinitialisée."

        })

    # --------------------------------------------------------
    # TESTER
    # --------------------------------------------------------

    if memory_type == "tester":

        save_agent_memory(
            tester.name,
            []
        )

        return jsonify({

            "success":
                True,

            "message":
                "Mémoire du Tester réinitialisée."

        })

    # --------------------------------------------------------
    # RESEARCHER
    # --------------------------------------------------------

    if memory_type == "researcher":

        save_agent_memory(
            researcher.name,
            []
        )

        return jsonify({

            "success":
                True,

            "message":
                "Mémoire du Researcher réinitialisée."

        })

    # --------------------------------------------------------
    # MÉMOIRE PARTAGÉE
    # --------------------------------------------------------

    if memory_type == "shared":

        save_shared_memory([])

        return jsonify({

            "success":
                True,

            "message":
                "Mémoire partagée réinitialisée."

        })

    return jsonify({

        "error":
            "Type de mémoire inconnu."

    }), 400


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        port=5000
    )