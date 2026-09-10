# Agent-OS V10.2.0 — Timeline personnelle

V10.2 remplace le couple séparé **Agenda + Journal** par une **Timeline personnelle centrale**.

La table SQLite `agenda_items` devient la source commune pour les tâches, rendez-vous,
événements, actions accomplies et ressentis. Les types restent distincts, mais Paul ne
doit plus chercher l'information dans deux systèmes concurrents.

## Exemples

```text
Toi : aujourdhui jai nettoyé la fontaine a chats, les toilettes, la machine a café
Paul : D'accord, pour aujourd'hui : tu as nettoyé la fontaine a chats, tu as nettoyé
les toilettes et tu as nettoyé la machine a café.

Toi : j'ai fait quoi comme taches aujourdhui?
Paul : Aujourd'hui, tu as fait 3 choses :
- nettoyé la fontaine a chats
- nettoyé les toilettes
- nettoyé la machine a café
```

```text
Toi : lundi je dois nettoyer la piscine
Toi : rdv chez le dentiste lundi à 15h
Toi : timeline lundi

Paul : Timeline pour le 14/09/2026 :
Rendez-vous :
- 15:00 — le dentiste
À faire :
- nettoyer la piscine
```

## Mise à jour depuis V10.1

Arrêter Agent-OS, sauvegarder `data/agenda.db`, puis extraire le ZIP dans le dossier
V10.1 et accepter le remplacement. Aucun dossier `data/` ou `workspace/` n'est fourni.

Au premier démarrage, les anciennes entrées `life_events` sont copiées dans la Timeline
une seule fois. L'ancienne table n'est pas supprimée.

## Compatibilité

`/api/life`, `life_journal.py`, les commandes `Journal : ...` et
`manager.life_journal` sont conservés comme compatibilité. Le nouveau code utilise
`PersonalTimeline` et `/api/timeline`.
