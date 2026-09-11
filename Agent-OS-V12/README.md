# Agent-OS V12 — Paul et la mémoire sémantique locale

V12 repart d'Agent Zero pour le runtime d'agents, les outils, les projets, la
mémoire vectorielle générale et Telegram. La mémoire personnelle de Paul est un
plugin séparé et structuré : `agent_os_memory`.

## Principe

Le pipeline V12 fait interpréter les messages par Qwen local via Ollama, puis
valide et enregistre les projections dans SQLite. Le texte utilisateur complet
est conservé : Paul peut mémoriser les identités, goûts, relations, lieux,
actions, occurrences, tâches, rendez-vous et événements, puis répondre à des
questions naturelles en recherchant les preuves locales.

- Agent Zero reste le moteur d'agents.
- La mémoire vectorielle Agent Zero conserve les connaissances générales,
  solutions et conventions de projet.
- `agent_os_memory` est la source de vérité pour la vie personnelle : tâches,
  rendez-vous, événements, actions accomplies, ressentis, relations,
  préférences et faits personnels.
- Une information personnelle est recherchée localement avant toute recherche
  Web. Une donnée absente doit provoquer une question, jamais une invention.

## Installation Windows

Depuis PowerShell, sans activer de virtualenv :

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALLER_V12.ps1
```

Par défaut, Agent Zero est installé à côté de ce dossier dans
`Agent-Zero-V12`. L'installateur n'efface ni `usr`, ni une base existante.

Pour seulement mettre à jour le plugin dans une installation existante :

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALLER_V12.ps1 `
  -InstallPath "C:\chemin\vers\Agent-Zero-V12" -SkipClone
```

## Migration V10

La migration est volontairement explicite : Paul ne lit pas un dossier
personnel sans que son chemin soit fourni.

```powershell
python .\migration\migrate_v10.py `
  --agenda "C:\chemin\Agent-OS-V10\data\agenda.db" `
  --memory "C:\chemin\Agent-OS-V10\data\memory.json" `
  --target "C:\chemin\Agent-Zero-V12\usr\agent_os_memory\assistant.db"
```

La commande est idempotente : relancer la même migration ne duplique pas les
éléments déjà importés.

## Tests hors ligne

```powershell
python -m unittest discover -s tests -v
```

Les tests n'appellent ni modèle IA, ni Web. Ils valident la source unique, les
corrections, les relances contextuelles et les règles de report.
