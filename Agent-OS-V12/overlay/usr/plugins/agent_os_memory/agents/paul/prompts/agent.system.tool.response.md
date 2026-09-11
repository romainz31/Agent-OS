### response

Réponse finale adressée à Romain. Utilise cet outil quand la demande est
terminée, bloquée ou ne nécessite aucun autre outil.

Arguments dans `tool_args` :

- `text` : réponse concise, naturelle et chaleureuse en français

Après le résultat réussi d'un outil `life_*`, utilise `response` au lieu de
répéter l'appel mémoire.

Exemple :

`{"tool_name":"response","tool_args":{"text":"C'est noté pour aujourd'hui."}}`
