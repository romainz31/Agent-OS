from agents.brain.llm import ask_llm
from agents.brain.decision import analyze_response
from agents.tools.registry import TOOLS


def run_agent(objective):
    print("VERSION NOUVELLE AGENT")

    print("Objectif :", objective)

    completed = False

    while not completed:

        response = ask_llm(objective)

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

            completed = True


        elif decision["action"] == "answer":

            print("\nRéponse finale :", decision["content"])

            completed = True