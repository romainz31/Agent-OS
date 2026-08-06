from agents.tools.registry import TOOLS
from agents.core.router import choose_tool


def run_agent(objective):

    print("Objectif reçu :", objective)

    tool_name = choose_tool(objective)

    if tool_name:
        tool = TOOLS[tool_name]

        result = tool(5, 3)

        print("Résultat :", result)

    else:
        print("Aucun outil trouvé")


if __name__ == "__main__":
    run_agent("Calculer une opération")