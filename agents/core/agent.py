from agents.brain.llm import ask_llm
from agents.brain.decision import analyze_response
from agents.executor.executor import execute


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

            result = execute(decision)

            print("\nRésultat outil :", result)
            history.append(
    {
        "tool": decision["tool"],
        "result": result
    }
)

        elif decision["action"] == "answer":

            print("\nRéponse finale :", decision["content"])

            completed = True