### life_rollover

Exécute le passage d'une journée à l'autre pour les tâches personnelles.

Une tâche `pending` explicitement datée et en retard est retirée de la liste du
jour et conservée dans le backlog général. Sa date prévue, la date de report,
le nombre de reports et l'historique sont conservés.

Ne déplace jamais automatiquement un rendez-vous, un événement, une tâche sans
date ou une tâche déjà terminée. `target_date` est une date ISO facultative ;
sans argument, utilise la date locale courante.
