class AgentContext:

    def __init__(self, objective):

        self.objective = objective

        self.plan = None
        self.target_file = None
        self.expected_output = None

        self.developer_result = None
        self.test_result = None

        self.attempt = 0

    def set_plan(self, plan):
        self.plan = plan

    def set_target_file(self, target_file):
        self.target_file = target_file

    def set_expected_output(self, expected_output):
        self.expected_output = expected_output

    def set_developer_result(self, result):
        self.developer_result = result

    def set_test_result(self, result):
        self.test_result = result

    def next_attempt(self):
        self.attempt += 1

    def to_dict(self):

        return {
            "objective": self.objective,
            "plan": self.plan,
            "target_file": self.target_file,
            "expected_output": self.expected_output,
            "developer_result": self.developer_result,
            "test_result": self.test_result,
            "attempt": self.attempt
        }

    def display(self):

        print()
        print("=" * 60)
        print("                 CONTEXT PARTAGÉ")
        print("=" * 60)
        print()

        for key, value in self.to_dict().items():

            print(f"{key} : {value}")