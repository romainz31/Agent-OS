from flask import Flask, render_template, request, jsonify

from agents.core.team import planner, developer, tester
from agents.core.memory_store import load_agent_memory, load_shared_memory


app = Flask(__name__)


# ============================================================
# AGENTS DISPONIBLES DANS L'INTERFACE
# ============================================================

AGENTS = {
    "planner": planner,
    "developer": developer,
    "tester": tester
}


# ============================================================
# PAGE PRINCIPALE
# ============================================================

@app.route("/")
def index():

    return render_template(
        "index.html",
        agents=list(AGENTS.keys())
    )


# ============================================================
# API : HISTORIQUE (mémoire individuelle + partagée)
# ============================================================

@app.route("/api/history")
def api_history():

    agent_key = request.args.get("agent", "")

    agent = AGENTS.get(agent_key)

    if agent is None:
        return jsonify({"error": f"Agent inconnu : {agent_key}"}), 400

    return jsonify({
        "individual": load_agent_memory(agent.name),
        "shared": load_shared_memory()
    })


# ============================================================
# API : ENVOYER UN MESSAGE À UN AGENT
# ============================================================

@app.route("/api/chat", methods=["POST"])
def api_chat():

    data = request.get_json(force=True, silent=True) or {}

    agent_key = data.get("agent", "")
    message = (data.get("message") or "").strip()
    shared = bool(data.get("shared", False))

    agent = AGENTS.get(agent_key)

    if agent is None:
        return jsonify({"error": f"Agent inconnu : {agent_key}"}), 400

    if not message:
        return jsonify({"error": "Message vide."}), 400

    result = agent.chat(message, shared=shared)

    response_text = agent.stringify_result(result)

    return jsonify({
        "response": response_text,
        "individual": load_agent_memory(agent.name),
        "shared": load_shared_memory()
    })


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    app.run(debug=True, port=5000)