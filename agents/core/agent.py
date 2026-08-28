from agents.brain.llm import ask_llm


class Agent:

    def __init__(self, name, role):
        self.name = name
        self.role = role

    def run(self, task):

        prompt = f"""
Tu es l'agent {self.name}.

Ton rôle :
{self.role}

Tâche :
{task}

Réponds en respectant strictement ton rôle.
"""

        response = ask_llm(prompt)

        return response