from agents.core.orchestrator import Orchestrator


def main():

    orchestrator = Orchestrator()

    objective = """
Créer une fonction Python multiply qui multiplie 6 par 7
et affiche le résultat.
"""

    result = orchestrator.run(objective)

    print()
    print("=" * 60)
    print("RESULTAT FINAL")
    print("=" * 60)
    print(result)


if __name__ == "__main__":
    main()