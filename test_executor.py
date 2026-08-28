from agents.executor.executor import execute


decision = {
    "tool": "addition",
    "arguments": {
        "a": 8,
        "b": 8
    }
}


result = execute(decision)


print("RESULTAT :", result)