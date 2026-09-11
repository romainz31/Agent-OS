# Agent-OS V12.2 — Clarifications naturelles

Cette version corrige le comportement robotique observé avec :
- `je l'ai croisée hier`
- `j'y suis retourné aujourd'hui`
- `je lui ai parlé ce matin`

## Nouveau pipeline

1. Qwen extrait le souvenir courant.
2. Un auditeur de références vérifie que les pronoms/déictiques ne sont pas
   faussement remplacés par `quelqu'un`, `une personne`, `quelque part`, etc.
3. La mémoire essaie de résoudre la référence.
4. Si un ancien souvenir semble correspondre, Paul le propose pour confirmation.
5. Si aucun souvenir ne suffit, un Qwen spécialisé rédige une question ciblée :
   - Qui as-tu croisé hier ?
   - Où es-tu retourné aujourd'hui ?
   - À qui as-tu parlé ce matin ?
6. La réponse suivante (`Coralie`, `chez Leroy Merlin`, etc.) complète le souvenir
   original. Elle n'est pas enregistrée comme un nouveau souvenir indépendant.

## Sécurité de structure

`l'aéroport` n'est pas confondu avec le pronom `l'`.
Les noms explicitement présents dans le message restent prioritaires.
Aucune référence ambiguë n'est enregistrée comme si elle était certaine.

40 tests passent.
