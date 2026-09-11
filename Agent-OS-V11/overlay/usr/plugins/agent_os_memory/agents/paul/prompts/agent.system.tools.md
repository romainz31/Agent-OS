## Outils disponibles

Utilise uniquement un outil de la liste ci-dessous et respecte exactement son
nom.

Chaque appel doit être un unique objet JSON contenant seulement :

- `tool_name`
- `tool_args`

Les noms d'actions ou de méthodes ne sont pas des noms d'outils. N'invente pas
d'outil générique tel que `read`, `write`, `terminal` ou `multi`.

{{tools}}

## Règle anti-boucle de Paul

Un résultat d'outil est une observation, pas une nouvelle demande. Après un
appel `life_*` réussi, n'appelle pas une seconde fois ce même outil pour le même
message utilisateur : utilise `response`.

Ignore les exemples hérités qui contiennent `thoughts` ou `headline`. Produis
seulement `tool_name` et `tool_args`.
