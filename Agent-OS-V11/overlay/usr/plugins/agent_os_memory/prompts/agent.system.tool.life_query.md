## `life_query` — rappel personnel, agenda et journal

Pour toute question personnelle sur ce que l'utilisateur a prévu, fait,
ressenti, préféré ou dit à propos d'une personne, interroge cet outil AVANT le
Web et avant la mémoire vectorielle générale.

Arguments JSON :
- `text` : sujet recherché
- `kinds` : liste parmi les types de `life_capture`
- `statuses` : filtre d'état
- `start`, `end` : bornes ISO inclusives
- `subject`, `predicate` : filtres de faits
- `entity`, `entity_type` : personne, lieu ou projet relié ; permet de répondre
  précisément à « avec qui ? » et « où ? »
- `current_facts_only` : vrai par défaut
- `aggregate` : `list` ou `count`
- `follow_up=true` quand la demande complète la question précédente, par
  exemple « et le 12/09/2026 ? » ; les nouveaux filtres remplacent les anciens
- `limit` : 1 à 100

Si `found=0`, dis simplement que tu n'as pas cette information et pose une
question utile. `web_needed=false` signifie qu'une recherche Web ne doit pas
être lancée pour combler ce vide personnel.

Réponds ensuite naturellement. Ne récite pas les noms de tables, les JSON ou
les identifiants sauf si l'utilisateur demande un diagnostic.
