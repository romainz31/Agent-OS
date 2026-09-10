## `life_rollover` — report quotidien des tâches

Utilise `life_rollover` au début d'une journée ou quand l'utilisateur demande
de reporter les tâches non faites. `target_date` est une date ISO facultative.

Seules les tâches `pending`, en retard et explicitement datées sont déplacées.
Les tâches sans date, rendez-vous et événements ne bougent jamais.
