from agents.brain.llm import ask_llm
from agents.brain.decision import analyze_response
from agents.tools.registry import TOOLS


def run_agent(objective):
    print("Objectif :", objective)

    completed = False
    history = []

    while not completed:

        response = ask_llm(
    objective + "\nHistorique :\n" + str(history)
)

        print("\nLLM :")
        print(response)

        decision = analyze_response(response)

        print("\nDécision :")
        print(decision)


        if decision["action"] == "tool":

            tool_name = decision["tool"]

            tool = TOOLS[tool_name]

            arguments = decision["arguments"]

            result = tool(
                arguments["a"],
                arguments["b"]
            )

            print("\nRésultat outil :", result)
            history.append(
    {
        "tool": tool_name,
        "result": result
    }
)

            


        elif decision["action"] == "answer":

            print("\nRéponse finale :", decision["content"])

            completed = True