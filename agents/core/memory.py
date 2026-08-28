import json


MEMORY_FILE = "data/memory.json"


def load_memory():

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_memory(memory):

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=4, ensure_ascii=False)


def add_memory(agent, task, result):

    memory = load_memory()

    entry = {
        "agent": agent,
        "task": task,
        "result": result
    }

    memory.append(entry)

    save_memory(memory)