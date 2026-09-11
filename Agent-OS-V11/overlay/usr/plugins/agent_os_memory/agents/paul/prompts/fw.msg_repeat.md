Tu viens d'envoyer exactement le même message une seconde fois. Ne le répète
pas.

Produis maintenant un seul objet JSON valide avec `tool_name` et `tool_args` :

- si un outil `life_*` a déjà réussi, appelle `response` avec une réponse
  naturelle en français ;
- si une recherche n'a rien trouvé, appelle `response` et dis-le simplement ;
- si une opération différente reste réellement nécessaire, appelle cet autre
  outil avec des arguments différents ;
- si rien d'autre n'est possible, appelle `response` et explique le blocage.

N'ajoute aucun texte hors de l'objet JSON.
