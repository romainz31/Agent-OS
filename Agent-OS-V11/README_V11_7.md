# Agent-OS V11.7 — Correctif clarification / changement de sujet

Corrige le bug observé après :
1. `mon deuxième prénom est Michel`
2. Paul demande une reformulation
3. `Coralie est ma copine`
4. Paul continue à demander le deuxième prénom en boucle.

## Cause
Une erreur technique de l'extracteur était enregistrée comme une vraie clarification utilisateur.
Le `pending` contaminait alors les messages suivants.

## Correctif
- une sortie Qwen techniquement invalide ne crée plus de pending ;
- le routeur retourne `uses_pending` pour distinguer une vraie réponse à une clarification d'un nouveau message ;
- une nouvelle phrase complète efface l'ancienne clarification avant l'extraction ;
- une vraie réponse courte à une ambiguïté peut toujours compléter le souvenir précédent ;
- ajout du fait `middle_name` et des réponses naturelles associées.

## Tests
21 tests sémantiques passent, notamment :
- deuxième prénom ;
- erreur technique sans pollution du tour suivant ;
- nouvelle phrase complète qui remplace une clarification en attente ;
- vraie clarification `je l'ai emmenée` → `Coralie` qui continue de fonctionner.
