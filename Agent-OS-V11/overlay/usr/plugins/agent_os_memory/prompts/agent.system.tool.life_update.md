### life_update

Modifie une entrée personnelle déjà enregistrée.

Arguments JSON :

- `record_id` si connu ; sinon `query` avec le titre ou la description ;
- `action` : `update|complete|reschedule|cancel|archive` ;
- `changes` : champs corrigés (`title`, dates ISO, `status`, `priority`,
  `task_bucket`, etc.) ;
- `reason` : formulation source ou raison courte de la correction.

Utilise `complete` lorsqu'une tâche est explicitement marquée comme terminée.
Une occurrence de réalisation est conservée. Si le résultat indique
`ambiguous`, montre les candidats et demande lequel Romain vise ; ne choisis
jamais silencieusement.

Le report automatique quotidien est réservé aux tâches datées non réalisées.
Un rendez-vous ou un événement ne doit être déplacé que si Romain le demande
explicitement.
