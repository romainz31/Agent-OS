from agents.tools.registry import TOOLS


def execute(decision):

    tool_name = decision["tool"]

    if tool_name not in TOOLS:
        return f"Outil inconnu : {tool_name}"

    tool = TOOLS[tool_name]

    arguments = decision.get("arguments", {})

    try:
        result = tool(**arguments)

        return result

    except Exception as e:
        return f"Erreur lors de l'exécution de {tool_name} : {e}"