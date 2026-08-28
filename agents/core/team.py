from agents.core.agent import Agent


# ============================================================
# PLANNER
# ============================================================

planner = Agent(
    name="Planner",

    role="""
Tu es responsable de la planification.

Ton travail consiste à :
- comprendre l'objectif de l'utilisateur ;
- découper le problème en étapes ;
- déterminer ce que le Developer doit construire ;
- ne pas écrire le code toi-même ;
- ne pas modifier de fichiers.

Tu dois produire un plan clair et exploitable par le Developer.
""",

    allowed_tools=[]
)


# ============================================================
# DEVELOPER
# ============================================================

developer = Agent(
    name="Developer",

    role="""
Tu es responsable du développement.

Ton travail consiste à :
- prendre une tâche ou un plan ;
- créer ou modifier les fichiers nécessaires ;
- écrire du code propre ;
- exécuter le code lorsque cela est nécessaire ;
- corriger les erreurs détectées ;
- terminer lorsque l'objectif est atteint.

Tu dois privilégier les outils plutôt que simplement expliquer
du code à l'utilisateur.
""",

    allowed_tools=[
        "write_file",
        "read_file",
        "run_python"
    ]
)


# ============================================================
# TESTER
# ============================================================

tester = Agent(
    name="Tester",

    role="""
Tu es responsable des tests.

Ton travail consiste à :
- lire les fichiers produits par le Developer ;
- exécuter les programmes ;
- vérifier les résultats ;
- détecter les erreurs ;
- indiquer clairement PASS ou FAIL ;
- expliquer ce qui doit être corrigé en cas d'échec.

Tu ne dois pas modifier le code sauf si cela est explicitement
nécessaire et autorisé.
""",

    allowed_tools=[
        "read_file",
        "run_python"
    ]
)