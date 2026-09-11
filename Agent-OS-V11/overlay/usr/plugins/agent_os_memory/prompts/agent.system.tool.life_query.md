### life_query

Interroge la mémoire personnelle structurée avant toute recherche Web ou toute
réponse fondée sur un souvenir vague.

Arguments JSON :

- `text` : sujet ou action recherchée ;
- `kinds` : types parmi ceux de `life_capture` ;
- `statuses` : par exemple `pending` ou `done` ;
- `start`, `end` : bornes ISO inclusives ;
- `task_bucket` : `daily` ou `backlog` ;
- `subject`, `predicate` : filtres de faits et préférences ;
- `entity`, `entity_type` : personne, lieu, animal ou projet ;
- `current_facts_only` : `true` par défaut ;
- `aggregate` : `list` ou `count` ;
- `include_details` : `true` pour retrouver les messages sources et détails ;
- `follow_up=true` quand la question complète la précédente, par exemple
  « et le 12/09/2026 ? » ;
- `limit` : de 1 à 100.

Cas importants :

- « Combien de fois ai-je nettoyé la cuisine ce mois-ci ? » : utilise
  `kinds=["action"]`, la période du mois, `aggregate=count`. Lis le champ
  `count` ou `activity_count`, qui additionne les occurrences réelles, et non
  seulement `records`.
- « Qu'ai-je fait cette semaine ? » : utilise `kinds=["action"]` et la
  période demandée ; les `activities` contiennent chaque détail source.
- « Quelles sont mes tâches générales ? » : utilise
  `kinds=["task"]`, `statuses=["pending"]`, `task_bucket="backlog"`.
- « Qu'ai-je prévu pour demain ? » : utilise `kinds=["task"]`, la date de
  demain, puis distingue les tâches `daily` du backlog général.

Le résultat est local. Si `found=0`, dis simplement que tu ne possèdes pas
encore cette information et pose une question utile ; ne lance pas le Web pour
inventer une réponse personnelle.

Réponds ensuite naturellement en français, sans réciter les tables, JSON ou
identifiants.
