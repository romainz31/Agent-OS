# Agent-OS V8.0 — Hybrid Integration Kernel

V8 repart d'une mémoire vide et garde Agent-OS comme couche personnelle : identité de Paul, mémoire relationnelle, agenda, missions M-xxx, Mission Control, Web/CLI/Telegram.

Les briques externes sont utilisées comme moteurs spécialisés :

- **Agent Zero** : exécution outillée, sandbox, plugins, MCP/A2A via son API externe.
- **LangGraph** : workflows et checkpoints persistants.
- **Microsoft Agent Framework (MAF)** : orchestration multi-agent concurrente ; les plans multi-étapes peuvent être exécutés en fan-out/fan-in lorsque MAF est disponible.
- **OpenHands** : exécuteur code/sandbox optionnel, préparé comme intégration externe.

La V8 fonctionne sans Agent Zero/OpenHands. Les intégrations sont détectées au démarrage et exposées dans `/api/integrations`.

## 1. Installation Windows

```powershell
cd "C:\chemin\vers\Agent-OS-V8"
py -3.14 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Installation rapide (évite les problèmes d'activation PowerShell) :

```powershell
.\install_v8.ps1 -Integrations
```

Ou manuellement, pour activer LangGraph + MAF :

```powershell
pip install -r requirements-integrations.txt
```

Tu peux copier `.env.example` en `.env` pour garder les réglages entre deux lancements.

## 2. Ollama

Par défaut :

- URL : `http://127.0.0.1:11434`
- modèle : `qwen2.5:7b`

Tu peux modifier avec :

```powershell
$env:OLLAMA_MODEL="qwen2.5:7b"
```

## 3. Lancer Agent-OS

Terminal 1 :

```powershell
python -u .\api_server.py
```

Interface : http://127.0.0.1:8765

Terminal 2 facultatif :

```powershell
python -u .\run.py
```

## 4. Tester la V8

```powershell
python -m tests.test_v8
```

La base livrée est volontairement vide : aucun souvenir personnel, aucune mission, aucun agenda.

## 5. Commandes naturelles utiles

- `comment je m'appelle ?`
- `je m'appelle Romain`
- `qu'est-ce que tu sais de moi ?`
- `samedi je dois aller chercher quelqu'un à l'aéroport`
- `qu'ai-je prévu samedi ?`
- `et le 12/10/2026 ?`
- `mission: analyse ce dossier et propose une solution`
- `missions`
- `pause M-001`
- `reprends M-001`
- `annule M-001`
- `status`

## 6. Agent Zero

Lance Agent Zero séparément, puis configure :

```powershell
$env:AGENT_ZERO_URL="http://127.0.0.1:50001"
$env:AGENT_ZERO_API_KEY="..."
```

V8 utilise l'endpoint externe `/api_message` avec `X-API-KEY`. Le `context_id` renvoyé est conservé par mission afin de garder la continuité côté Agent Zero.

## 7. OpenHands

OpenHands reste désactivé par défaut dans V8.0. Configure son Agent Server :

```powershell
$env:OPENHANDS_URL="http://127.0.0.1:8000"
$env:OPENHANDS_API_KEY="..."
```

V8.0 vérifie sa disponibilité mais ne lui confie pas automatiquement les missions : on activera le routage code après nos premiers tests de stabilité.

## 8. Philosophie V8

Avant toute grosse fonctionnalité :

1. regarder Agent Zero / LangGraph / Microsoft Agent Framework / OpenHands ;
2. réutiliser la brique si elle est adaptée ;
3. ne coder dans Agent-OS que ce qui constitue sa valeur propre : Paul, contexte personnel, mémoire, arbitrage, Mission Control et expérience utilisateur.
