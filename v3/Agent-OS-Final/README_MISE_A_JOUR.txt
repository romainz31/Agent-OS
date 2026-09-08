AGENT-OS V5.4.1 — APPRENTISSAGE AUTONOME
=========================================

Cette mise à jour se pose PAR-DESSUS V5.3.
Remplace les fichiers du ZIP en conservant leur arborescence.

NOUVEAUTÉS V5.4.1
---------------

1. Préparation avant worker
   Le moteur peut maintenant différer une tâche AVANT de la passer RUNNING.
   Le worker ne consomme donc aucun slot pendant sa formation.

2. Détection automatique prudente de skills
   Exemples détectés sans "skill require" manuel :
   - .yaml / .yml -> yaml
   - .py -> python
   - Home Assistant -> home_assistant
   - MQTT -> mqtt
   - Frigate -> frigate
   - Docker, FastAPI, Telegram, Ollama, GitHub, ZHA, etc.
   Les skills déjà connus du registre sont aussi détectés lorsqu'ils sont
   explicitement cités dans la demande.

3. Apprentissage Researcher autonome
   Si un skill requis :
   - n'existe pas ;
   - a une confiance effective < 0.50 ;
   - est périmé / non documenté ;
   alors une tâche "Apprentissage autonome — <skill>" est créée pour Researcher.

4. Dépendance réelle
   La tâche métier dépend de la tâche Researcher. Elle reprend automatiquement
   seulement lorsque l'apprentissage a été validé.

5. Validation documentaire + pertinence
   Un apprentissage n'est accepté que si les sources parlent réellement du
   skill ciblé ET si elles fournissent :
   - au moins une source A/B pertinente ; OU
   - au moins deux sources C pertinentes provenant de domaines indépendants.
   Pour les noms ambigus comme Frigate, un contexte technique (NVR, caméra,
   MQTT, Docker, Home Assistant, docs.frigate.video...) est aussi exigé.
   Une source fiable mais hors sujet ne compte jamais.

6. Niveau de confiance prudent
   Le Researcher ne s'auto-proclame jamais expert. Un apprentissage Web crée en
   général un skill basique ou intermédiaire, avec une confiance calculée depuis
   la qualité et le nombre de sources.

7. Pas de régression du savoir manuel
   Si un skill existant a déjà un meilleur niveau ou une meilleure confiance,
   un apprentissage automatique ne les baisse pas.

8. Transfert inter-workers
   Un skill frais et fiable déjà appris pour Developer peut être attribué à
   Tester sans nouvelle recherche Web quand Tester en a besoin.

9. Mutualisation
   Deux tâches de la MÊME mission qui ont simultanément besoin du même skill
   partagent la même tâche Researcher.

10. Requête Web ciblée
   Les tâches d'apprentissage n'envoient plus toute la grosse consigne métier
   au moteur de recherche. Une requête courte et technique est générée, et les
   moteurs Web généraux sont essayés avant Wikipedia.

11. Rejet des synthèses non concluantes
   Si le Researcher écrit lui-même « aucune source pertinente », « aucune
   information pertinente », « sources insuffisantes », etc., le skill n'est
   jamais promu même si plusieurs URL ont été trouvées.

12. Migration corrective
   Au démarrage, les anciens skills appris automatiquement avec une synthèse
   non concluante ou uniquement des sources hors sujet sont mis en quarantaine :
   niveau novice, confiance <= 0.20, validation retirée. La prochaine mission
   déclenche donc un nouvel apprentissage.

13. Persistance
   - data/skills.json : connaissances techniques
   - data/learning.json : historique d'apprentissage
   - data/learning_state.json : activation/désactivation

COMMANDES
---------

learning status
learning history
learning on
learning off

Telegram :
/learning
/learninghistory
/learning_on
/learning_off

API :
GET /api/learning
GET /api/learning/history

TESTS
-----

PowerShell :

python .\test_v50.py
python .\test_v51.py
python .\test_v52.py
python .\test_v53.py
python .\test_v54.py
python .\test_telegram_commands.py

Résultats attendus :
- V5.0 : 37 contrôles
- V5.1 : 47 contrôles
- V5.2 : 52 contrôles
- V5.3 : 47 contrôles
- V5.4.1 : 77 contrôles
- Telegram : tous les contrôles passent

Puis :

python -u .\api_server.py
python -u .\telegram_client.py

TEST RÉEL CONSEILLÉ
-------------------

Après redémarrage, vérifie d'abord l'ancien skill Frigate :

skill frigate

Le mauvais apprentissage montré avant ce correctif doit être mis en
quarantaine (niveau novice / confiance basse, validation retirée).

Relance ensuite une mission Frigate :

Crée workspace/frigate_test_2.yaml avec un exemple de configuration Frigate
pour Home Assistant avec MQTT.

Pendant le travail :

learning status
workload status

Puis :

learning history
skill frigate

Cette fois, Frigate ne doit redevenir basique/intermédiaire QUE si les sources
retenues parlent réellement de Frigate technique. Une recherche hors sujet doit
échouer et empêcher le Developer de reprendre.

LIMITES VOLONTAIRES V5.4.1
------------------------

- La détection automatique reste conservatrice : elle ne demande pas au LLM du
  scheduler d'inventer librement des noms de compétences.
- Pour une technologie inconnue de la table de détection et absente du registre,
  "skill require M-XXX nom_du_skill" reste disponible.
- Le Researcher apprend depuis les résultats Web sourcés qu'il possède déjà ;
  une future version pourra extraire le contenu complet des pages officielles.
- V5.4.1 traite l'apprentissage AVANT le travail. La collaboration inter-agents
  en plein milieu d'une tâche (Developer -> Researcher -> Developer) sera la
  prochaine brique de la roadmap.
