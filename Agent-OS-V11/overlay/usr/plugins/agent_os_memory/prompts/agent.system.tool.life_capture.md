### life_capture

Enregistre une déclaration personnelle de Romain dans la mémoire structurée
de Paul. Appelle cet outil dès qu'un message contient une information claire
sur sa vie, même s'il ne demande pas explicitement de la retenir.

Arguments JSON :

- `kind` obligatoire : `task|appointment|event|action|mood|note|fact|preference|relation` ;
- `title` obligatoire : titre court et fidèle, sans supprimer les détails importants ;
- `source_text` : message utilisateur complet à l'origine de l'information ;
- `metadata` : objet contenant les détails complémentaires (personnes, lieux,
  objets, pièce, quantité, raison, contrainte, contexte) ;
- `start_at`, `end_at`, `due_at`, `completed_at` : dates ISO, jamais une date
  inventée ;
- `date_precision` : `exact|day|week|month|unknown` ;
- `time_expression` : expression originale comme `demain` ou `le 12/12/2026` ;
- `status` : `pending|scheduled|done|logged|cancelled|archived` ;
- `task_bucket` : `daily` pour une tâche datée, `backlog` pour une tâche sans
  date ;
- `entities` : liste de `{type,name,role}` pour les personnes, lieux, animaux
  ou projets ;
- `confidence` entre 0 et 1 ; `inferred=true` uniquement pour une déduction
  prudente ;
- pour `fact|preference|relation` : `subject`, `predicate`, `value`.

Règles de compréhension :

1. Une phrase personnelle claire est enregistrée sans demander « que dois-je
   retenir ? ».
2. Si plusieurs informations sont présentes, fais un appel par information,
   en conservant `source_text` et les mêmes détails pertinents.
3. « Je dois / il faut / à faire » devient `task` avec `status=pending` quand
   il s'agit d'une action concrète à exécuter. Un déplacement, une sortie ou un
   voyage daté comme « je dois aller à la mer le 12/12/2026 » devient plutôt un
   `event`.
4. « J'ai fait / j'ai nettoyé / c'est fait » devient `action`. Une action peut
   fermer automatiquement la tâche correspondante et crée une occurrence
   consultable séparément.
5. « J'aime le bleu » devient une `preference`, par exemple
   `predicate=couleur préférée`, `value=bleu`, `subject=user`.
6. « Je vais à la mer le 12/12/2026 » devient un `event` daté avec
   `start_at=2026-12-12T00:00:00` et `date_precision=day`.
7. Convertis `aujourd'hui`, `demain`, les jours de la semaine et les dates
   françaises en ISO en utilisant la date courante fournie par le système.
8. Ne mémorise jamais une réponse de Paul avec `source_role=assistant`.
9. N'utilise pas la mémoire vectorielle générale pour remplacer cet outil.
