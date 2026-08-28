from agents.core.manager import Manager


manager = Manager()


tasks = [
    "Analyse l'architecture de notre application.",
    "Développe une fonction Python pour additionner deux nombres.",
    "Teste notre fonction et cherche les erreurs."
]


for task in tasks:

    print("\n==============================")
    print("MISSION :", task)

    result = manager.run(task)

    print("\nRÉPONSE :")
    print(result)