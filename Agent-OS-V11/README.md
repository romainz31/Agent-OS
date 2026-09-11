# Agent-OS V11.1 — Paul sur Agent Zero

V11 repart d'Agent Zero pour le runtime d'agents, les outils, les projets, la
mémoire vectorielle générale et Telegram. La mémoire personnelle de Paul est un
plugin séparé et structuré : `agent_os_memory`.

## Principe

- Agent Zero reste le moteur d'agents.
- La mémoire vectorielle Agent Zero conserve les connaissances générales,
  solutions et conventions de projet.
- `agent_os_memory` est la source de vérité pour la vie personnelle : tâches,
  rendez-vous, événements, actions accomplies, ressentis, relations,
  préférences et faits personnels. Chaque déclaration utilisateur conserve son
  texte source et ses détails ; le stockage ne compresse plus les occurrences
  en une seule ligne.
- Une information personnelle est recherchée localement avant toute recherche
  Web. Une donnée absente doit provoquer une question, jamais une invention.

## Règle de planification

Une tâche datée apparaît dans la liste du jour concerné. Si elle n'est pas
terminée après son échéance, le passage quotidien la déplace dans le backlog
général en conservant sa date d'origine et son historique. Les rendez-vous et
événements ne sont jamais déplacés automatiquement.

Les actions réalisées sont enregistrées comme des occurrences indépendantes.
Paul peut donc répondre à « combien de fois ai-je nettoyé la cuisine ce mois-ci
? » sans confondre le nombre de lignes de mémoire avec le nombre d'actions.

## Installation Windows

Depuis PowerShell, sans activer de virtualenv :

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALLER_V11.ps1
```

Par défaut, Agent Zero est installé à côté de ce dossier dans
`Agent-Zero-V11`. L'installateur n'efface ni `usr`, ni une base existante.

Pour seulement mettre à jour le plugin dans une installation existante :

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALLER_V11.ps1 `
  -InstallPath "C:\chemin\vers\Agent-Zero-V11" -SkipClone
```

## Migration V10

La migration est volontairement explicite : Paul ne lit pas un dossier
personnel sans que son chemin soit fourni.

```powershell
python .\migration\migrate_v10.py `
  --agenda "C:\chemin\Agent-OS-V10\data\agenda.db" `
  --memory "C:\chemin\Agent-OS-V10\data\memory.json" `
  --target "C:\chemin\Agent-Zero-V11\usr\agent_os_memory\assistant.db"
```

La commande est idempotente : relancer la même migration ne duplique pas les
éléments déjà importés.

## Tests hors ligne

```powershell
python -m unittest discover -s tests -v
```

Les tests n'appellent ni modèle IA, ni Web. Ils valident la source unique, les
corrections, les relances contextuelles et les règles de report.
