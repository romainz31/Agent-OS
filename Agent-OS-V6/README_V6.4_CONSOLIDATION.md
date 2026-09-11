# Agent-OS V6.4 — Consolidation runtime

Cette livraison est volontairement limitée aux fichiers modifiés/ajoutés.

## Objectif

Réduire le couplage de `agentos/runtime.py` sans casser son interface publique.

Avant :
- récupération ;
- génération des payloads ;
- statut ;
- vue agents ;
- commandes ;
- missions ;
- tâches ;
- validations ;
- mémoire ;

étaient réunis dans `runtime.py`.

Après :
- `runtime.py` = façade publique ;
- `runtime_recovery.py` = reprise après interruption ;
- `runtime_views.py` = sérialisation, statut et vue agents.

## Fichiers

À copier dans ton dossier `Agent-OS-V6` :

- `agentos/runtime.py` (remplace l'existant)
- `agentos/runtime_recovery.py` (nouveau)
- `agentos/runtime_views.py` (nouveau)
- `tests/test_v64_consolidation.py` (nouveau)

## Test

Depuis le dossier Agent-OS-V6 :

```powershell
python -m tests.test_v64_consolidation
python -m tests.run_all
```

Puis démarrage habituel :

```powershell
python api_server.py
```

## Pourquoi cette étape

La consolidation est faite progressivement pour éviter une régression massive.
`memory.py`, `manager.py` et les autres gros modules ne sont pas encore découpés
dans cette livraison. La prochaine consolidation pourra s'attaquer à la mémoire
en conservant une façade `Memory` compatible avec le code existant.

Cette version prépare également l'arrivée d'un module distinct de checkpoints
et d'un graphe de mission sans charger davantage `runtime.py`.
