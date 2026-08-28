from agents.executor.executor import execute


decision = {
    "tool": "run_python",
    "arguments": {
        "path": "applications/test_execution.py"
    }
}


result = execute(decision)


print("RESULTAT :")
print(result)