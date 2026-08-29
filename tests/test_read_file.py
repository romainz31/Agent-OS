from agents.executor.executor import execute


decision = {
    "tool": "read_file",
    "arguments": {
        "file_path": "data/test_agent.txt"
    }
}


result = execute(decision)


print("CONTENU DU FICHIER :")
print(result)