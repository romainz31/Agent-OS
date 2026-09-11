# Agent-OS V12.1 — Mémoire épisodique + clarification intelligente

V12.1 reprend toute la V12 et ajoute une étape de récupération de contexte quand une
référence reste ambiguë.

## Principe

1. Qwen analyse d'abord le message courant sans contamination par l'historique.
2. Le résolveur ciblé tente de résoudre les références avec les faits connus.
3. Si une référence reste inconnue, Paul recherche jusqu'à 100 souvenirs candidats.
4. Le matcher Qwen reçoit notamment `source_text`, la phrase complète réellement dite
   par Romain lors de l'enregistrement du souvenir.
5. Paul ne choisit jamais silencieusement :
   - un candidat plausible -> il le propose ;
   - plusieurs candidats -> il les liste ;
   - aucun candidat -> il pose une question ouverte.
6. La réponse de Romain est interprétée par un Qwen dédié :
   accept / select / provide_value / reject / new_topic.
7. Le souvenir n'est complété et enregistré qu'après confirmation.

Exemple :
`je l'ai croisée hier`
-> Paul retrouve `mercredi j'ai déposé Coralie à l'aéroport`
-> `Tu parles de Coralie ? Je retrouve ce souvenir : « ... »`
-> `oui`
-> le souvenir courant est enregistré avec `object=Coralie`.

Une nouvelle phrase complète reste prioritaire et ne peut pas être absorbée par une
ancienne clarification.
