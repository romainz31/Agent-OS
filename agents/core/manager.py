import json

from agents.brain.llm import ask_manager
from agents.core.team import planner, developer, tester


class Manager:

    def __init__(self):

        self.agents = {
            "planner": planner,
            "developer": developer,
            "tester": tester
        }

    def choose_agent(self, task):

        response = ask_manager(task)

        print("\n[MANAGER LLM]")
        print(response)

        try:
            decision = json.loads(response)

        except json.JSONDecodeError:
            print("[MANAGER] Réponse JSON invalide.")
            return None, None

        agent_name = decision.get("agent")
        agent_task = decision.get("task")

        if agent_name not in self.agents:
            print("[MANAGER] Agent inconnu :", agent_name)
            return None, None

        return agent_name, agent_task


    def run(self, task):

        agent_name, agent_task = self.choose_agent(task)

        if agent_name is None:
            return "Le Manager n'a pas réussi à choisir un agent."

        agent = self.agents[agent_name]

        print(f"\n[MANAGER] → {agent.name}")
        print(f"[TÂCHE] → {agent_task}")

        return agent.run(agent_task)