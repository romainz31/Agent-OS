from helpers.extension import Extension


class PaulIdentity(Extension):
    def execute(self, **kwargs):
        if self.agent and self.agent.number == 0:
            self.agent.agent_name = "Paul"
            self.agent.set_data("agent_os_identity", {"assistant": "Paul", "user": "Romain"})
