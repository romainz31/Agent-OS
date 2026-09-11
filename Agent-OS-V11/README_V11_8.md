# Agent-OS V11.8 — Pipeline sémantique Qwen isolé

V11.7 mélangeait le message courant, l'historique récent et la mémoire connue dans le même prompt.
Cela permettait à Qwen de réextraire d'anciens faits ou de réutiliser un ancien filtre.

V11.8 sépare strictement :
1. routeur Qwen sur le seul message courant ;
2. extracteur Qwen sur le seul message courant ;
3. validation Python ;
4. résolveur Qwen uniquement si un champ est explicitement `unresolved` ;
5. résolution temporelle Python ;
6. écriture/requête SQLite.

Une ancienne requête n'est fusionnée que si routeur ET extracteur identifient une vraie ellipse comme `et mardi ?`.

26 tests passent, dont les cas :
- `Coralie est ma copine` sans contamination Romain/Brens/Michel ;
- `ma copine travaille demain matin` avec résolution `ma copine -> Coralie` au second passage ;
- `qui travaille demain matin ?` sans héritage d'un ancien filtre ;
- `mardi j'ai lavé ma voiture` traité comme action ;
- `qu'est-ce que j'ai fait mardi ?` traité comme requête autonome.
