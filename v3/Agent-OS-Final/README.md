# Agent-OS Final — version de référence

Projet séparé du dépôt d'apprentissage actuel. Il sert de cible technique propre à tester sans écraser le V2 en cours.

## Inclus

- Manager conversationnel
- routage déterministe
- titres/descriptions basés sur la demande courante (corrige le bug de vieux titre)
- tâches persistantes JSON
- workers parallèles
- Researcher DDGS
- Developer avec vrais fichiers
- pré-validation Python **avant** approbation
- Permission Engine hors LLM
- `oui` / `non` pour les modifications existantes
- contrôle SHA-256 avant écriture approuvée (évite une modification devenue obsolète)
- écriture atomique
- Tester avec `py_compile` réel
- runtime limité à `workspace/tests/` et `workspace/applications/`
- mémoire simple séparant session et éléments durables explicites
- aucun shell arbitraire donné aux agents

## Installation PowerShell

```powershell
cd Agent-OS-Final
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Ollama doit être lancé. Modèle par défaut : `qwen2.5:7b`.

## Commandes

```text
status
tasks
approvals
memory
oui
non
quit
```

## Tests rapides

```text
Teste workspace/applications/hello.py et vérifie les erreurs Python.
```

```text
Modifie workspace/applications/hello.py pour afficher Bonjour Romain.
```

Pour une modification existante, le Developer génère une proposition, Python la compile d'abord si c'est un `.py`, puis seulement si elle est valide la tâche passe en `waiting_approval`.

```text
oui
```

L'écriture finale vérifie aussi que le fichier n'a pas changé entre la proposition et ton approbation.

## Architecture

```text
Utilisateur
   |
Manager
   +-- conversation + mémoire
   |
   +-- Router
       |
       +-- Researcher
       +-- Developer -> pré-validation -> approbation -> écriture
       +-- Tester -> preuves réelles
       +-- AI Worker
```

## Ce qui reste volontairement pour la suite

- Discord / Telegram
- scheduler et deadlines réelles
- missions multi-étapes avancées
- sandbox Docker forte pour le code
- Home Assistant
- mémoire vectorielle / connaissances
- notifications push
- outils spécialisés supplémentaires

Cette version est une **bêta technique de référence**, pas encore une version production exposée à Internet.
