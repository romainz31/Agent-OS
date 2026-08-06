from agents.tools.registry import TOOLS


def execute(decision):

    tool_name = decision["tool"]

    tool = TOOLS[tool_name]

    arguments = decision["arguments"]

    result = tool(
        arguments["a"],
        arguments["b"]
    )

    return result