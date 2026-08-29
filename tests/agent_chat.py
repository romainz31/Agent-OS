from agents.core.team import planner, developer, tester


# ============================================================
# AGENTS DISPONIBLES
# ============================================================

AGENTS = {
    "1": planner,
    "2": developer,
    "3": tester,
}


# ============================================================
# AFFICHAGE
# ============================================================

def show_menu():

    print()
    print("=" * 40)
    print("           AGENT-OS")
    print("=" * 40)
    print()
    print("1. Planner")
    print("2. Developer")
    print("3. Tester")
    print("4. Quitter")
    print()


# ============================================================
# CHAT
# ============================================================

def chat_with_agent(agent):

    print()
    print("=" * 40)
    print(f"       AGENT : {agent.name.upper()}")
    print("=" * 40)

    print()
    print("Écris une tâche.")
    print("Tape 'back' pour revenir au menu.")
    print()

    while True:

        task = input(f"{agent.name} > ")

        if task.lower() == "back":
            break

        if not task.strip():
            continue

        print()
        print(f"[{agent.name}] travaille...")
        print()

        response = agent.run(task)

        print(response)
        print()


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():

    while True:

        show_menu()

        choice = input("Choix > ")

        if choice == "4":
            print()
            print("Arrêt de Agent-OS.")
            break

        if choice not in AGENTS:
            print()
            print("Choix invalide.")
            continue

        agent = AGENTS[choice]

        chat_with_agent(agent)


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":
    main()