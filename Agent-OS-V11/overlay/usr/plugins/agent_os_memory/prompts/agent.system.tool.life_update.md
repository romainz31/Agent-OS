## `life_update` — terminer, corriger, reporter ou annuler

Arguments JSON :
- `record_id` si connu ; sinon `query` pour rechercher le titre
- `action` : `update|complete|reschedule|cancel|archive`
- `changes` : champs corrigés (`title`, dates ISO, `status`, `priority`, etc.)
- `reason` : raison courte et fidèle au message utilisateur

Si le résultat est `ambiguous`, présente les candidats et demande lequel est
visé. Ne choisis jamais silencieusement. Un rendez-vous ne doit être reporté
que sur demande explicite ; il n'est jamais déplacé par le report quotidien.
