# Agent-OS V7.0.1 — base modulaire

Cette V7 repart de la version réellement présente sur `main` au commit
`2895c967` (V6.6.3.4), avec une mémoire et un workspace vides au premier
démarrage. Elle conserve le Manager Paul, Web/CLI/Telegram, les missions
persistantes M-xxx, le travail en arrière-plan, les priorités, dépendances,
sous-missions, approbations, reprises, documents, agenda, mémoire relationnelle,
Researcher, Developer, Tester, spécialistes, apprentissage et collaboration.

## Première intégration Agent Zero

La V7 adapte trois briques matures d'Agent Zero sans importer sa lourde pile :

- un bus d'extensions ordonné avec hooks avant/après tâche ou outil ;
- un contrat d'outil normalisé (`ToolSpec`, `ToolResponse`, catalogue, schéma) ;
- une politique d'actions propre à chaque profil d'agent.

Le moteur de missions publie maintenant `task.submitted`,
`task.before_execute`, `task.after_execute` et `task.execution_error`. Une
extension en erreur est isolée et diagnostiquée sans faire tomber la mission.
Les premiers outils migrés sont `workspace_tree` et `read_workspace_file`.

Agent Zero est sous licence MIT. Voir `THIRD_PARTY_NOTICES.md` et
`licenses/AGENT_ZERO_MIT.txt`.

## Installation Windows / PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python api_server.py
```

Si PowerShell bloque `Activate.ps1`, l'activation n'est pas obligatoire :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe api_server.py
```

Ollama doit être lancé et contenir par défaut `qwen2.5:7b`. L'interface est
disponible sur http://127.0.0.1:8765.

Pour Telegram, dans un second terminal :

```powershell
.\.venv\Scripts\Activate.ps1
$env:TELEGRAM_BOT_TOKEN = "ton_token"
$env:TELEGRAM_ALLOWED_CHAT_ID = "ton_chat_id"
python telegram_client.py
```

La CLI se lance avec `python run.py`. Ne lance qu'un seul `api_server.py` pour
un même dossier de données.

## Données neuves

Les dossiers `data/` et `workspace/` ne sont pas livrés. Agent-OS les crée au
premier démarrage. La V7 ne recopie donc aucune mémoire, conversation, mission,
tâche, compétence, personne, agenda ou fichier produit par la V6.

Pour choisir des emplacements distincts :

```powershell
$env:AGENTOS_DATA_DIR = "C:\\AgentOS\\v7-data"
$env:AGENTOS_WORKSPACE_DIR = "C:\\AgentOS\\v7-workspace"
```

## Vérification

```powershell
python -m tests.run_all
python -m tests.test_v7
```

## Correctif V7.0.1 — identité et mémoire personnelle

- « je m'appelle… » et « j'habite… » alimentent directement le profil durable ;
- « comment je m'appelle ? » et « où j'habite ? » répondent depuis SQLite ;
- une demande comme « dis-moi ce que tu possèdes en mémoire » produit un
  inventaire déterministe, sans profil inventé par le LLM ;
- ces messages ne peuvent lancer ni mission Researcher ni recherche Web ;
- les fautes observées `mapelle` et `memmoire` sont tolérées.

Diagnostics V7 :

- http://127.0.0.1:8765/api/modules
- http://127.0.0.1:8765/api/tools?profile=developer

## Suite prévue

La migration reste progressive : les outils de création/modification, les
prompts modulaires et l'isolation complète par projet seront branchés sur les
contrats V7 au fil des versions, avec tests de non-régression à chaque étape.
