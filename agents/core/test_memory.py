from agents.core.memory import load_memory, save_memory


memory = load_memory()

print("Mémoire actuelle :")
print(memory)


memory["preferences"]["temperature"] = 21


save_memory(memory)

print("Nouvelle mémoire enregistrée")