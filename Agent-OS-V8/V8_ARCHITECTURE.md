# Agent-OS V8 — Option C

## Principe

Agent-OS reste la couche produit et personnelle. Les frameworks externes sont des moteurs remplaçables.

```text
                 PAUL / AGENT-OS
                       |
       identité + mémoire + agenda + conversation
       Mission Control + M-xxx + Web/CLI/Telegram
                       |
              Integration Registry
          _____________|______________
         |             |              |
    Agent Zero      LangGraph        MAF
    exécution       workflow         parallèle
    sandbox         checkpoint       fan-out/in
    plugins/MCP
         |
    OpenHands (optionnel pour code/sandbox)
```

## Décisions V8.0

| Fonction | Propriétaire V8 | Pourquoi |
|---|---|---|
| Identité Paul | Agent-OS | doit rester stable quel que soit le worker |
| Mémoire personnelle | Agent-OS/SQLite | une seule source de vérité utilisateur |
| Agenda/contexte conversation | Agent-OS/SQLite | nécessaire aux références comme « et le 12/10 ? » |
| Missions M-xxx | Agent-OS | contrat utilisateur stable |
| Mission Control | Agent-OS | pause/reprise/annulation indépendantes du moteur |
| Workflow/checkpoint | LangGraph si installé | ne pas recoder un moteur de graphe/persistance |
| Exécution outillée/sandbox | Agent Zero si configuré | réutiliser une brique mature |
| Parallélisme multi-agent | Microsoft Agent Framework | réutiliser ConcurrentBuilder |
| Coding agent | OpenHands | pont préparé, auto-délégation désactivée en V8.0 |
| LLM de secours | Ollama direct | V8 doit fonctionner sans frameworks externes |

## Règle pour les prochaines versions

Avant une grosse fonctionnalité :
1. comparer Agent Zero / LangGraph / Microsoft Agent Framework / OpenHands ;
2. réutiliser la meilleure brique quand son interface est stable ;
3. écrire nous-mêmes uniquement la couche spécifique à Agent-OS.

## Limite volontaire de V8.0

Le pont OpenHands ne déclenche pas encore de conversation de coding automatiquement. C'est volontaire : on valide d'abord le nouveau noyau, la mémoire vide, les missions et les intégrations LangGraph/Agent Zero/MAF. Une fois la base stable, OpenHands pourra devenir un worker `coding` derrière le même contrat de mission.
