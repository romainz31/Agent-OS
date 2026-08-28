from agents.executor.executor import execute


decision = {
    "tool": "write_file",
    "arguments": {
        "path": "data/test_agent.txt",
        "content": "Bonjour, ceci a été écrit par un agent IA."
    }
}


result = execute(decision)


print("RESULTAT :", result)