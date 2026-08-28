from agents.executor.executor import execute


decision = {
    "tool": "read_file",
    "arguments": {
        "path": "data/test_agent.txt"
    }
}


result = execute(decision)


print("CONTENU DU FICHIER :")
print(result)