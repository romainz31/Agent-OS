## `life_capture` — mémoire personnelle structurée

Utilise cet outil quand l'utilisateur déclare quelque chose à retenir sur sa
vie : tâche, rendez-vous, événement, action accomplie, humeur, fait,
préférence ou relation.

Arguments JSON :
- `kind` obligatoire : `task|appointment|event|action|mood|note|fact|preference|relation`
- `title` obligatoire : formulation courte fidèle à l'utilisateur
- dates ISO facultatives : `start_at`, `end_at`, `due_at`, `completed_at`
- `status` : `pending|scheduled|done|logged|cancelled|archived`
- `date_precision` : `exact|day|week|month|unknown`
- `time_expression` : expression originale, par exemple `samedi`
- `source_text` : message utilisateur exact
- `confidence` de 0 à 1 ; `inferred=true` uniquement pour une déduction prudente
- `entities`: liste de `{type,name,role}` pour personnes, lieux ou projets
- pour `fact|preference|relation` : `subject`, `predicate`, `value`

Règles :
- n'enregistre jamais ta propre réponse comme souvenir utilisateur ;
- convertis les dates relatives en ISO avec la date locale courante, tout en
  conservant l'expression originale ;
- une action terminée peut automatiquement fermer une tâche existante ;
- ne crée pas un rendez-vous sans date : demande la date à l'utilisateur ;
- n'utilise pas la mémoire vectorielle générale pour remplacer cet outil.
- V12 ajoute semantic_state (planned, in_progress, completed, cancelled ou
  unknown), action_verb, object_text, location_text et occurrences.
- entity_attributes conserve les détails d'une personne, d'un lieu ou d'un
  objet sous la forme entity, attribute, value et type.
- conserve toujours le source_text complet : les projections ne remplacent
  jamais les mots de Romain.
