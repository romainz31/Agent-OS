AGENT-OS — V4.8 FINALE
======================

Cette archive termine la V4.8 et conserve toutes les corrections mémoire V4.7.

NOUVEAUTÉS / CORRECTIONS
------------------------
1. Manager autonome
   - supervision périodique des missions ;
   - récupération d'une tâche orpheline ;
   - retry automatique contrôlé ;
   - diagnostic AI Worker avant changement de stratégie ;
   - escalade humaine lorsque le budget autonome est épuisé ;
   - aucune approbation sensible accordée automatiquement ;
   - priorités et deadlines persistantes ;
   - journal persistant des décisions.

2. manager status corrigé
   - lit les missions directement au moment de la commande ;
   - distingue les missions actives des missions récemment terminées ;
   - affiche la dernière mission récente lorsqu'elle vient juste de finir ;
   - affiche récupérations, escalades et nombre de décisions ;
   - deadlines affichées avec temps restant.

3. Heure locale
   - manager_decisions.json continue d'être enregistré en UTC ;
   - l'affichage de Paul est converti dans le fuseau local de la machine.

4. Vrai suivi de conversation persistant
   - nouveau fichier data/conversations.json ;
   - fil actif persistant après redémarrage ;
   - reprise initiale depuis l'ancienne session V4.7 ;
   - sujet courant + résumé déterministe + derniers échanges ;
   - le fil est fourni au LLM séparément de la mémoire personnelle ;
   - archivage automatique après longue inactivité ;
   - commande "nouvelle conversation" pour repartir avec un fil vierge ;
   - commandes "conversation status" et "conversation history".

5. Oubli cohérent
   - un oubli explicite purge aussi les valeurs correspondantes du fil de
     conversation et de ses anciens sujets/résumés ;
   - une donnée oubliée ne doit donc plus pouvoir réapparaître via le contexte
     conversationnel.

FICHIERS À REMPLACER / AJOUTER
------------------------------
api_server.py
agentos/memory.py
agentos/router.py
agentos/personal_manager.py
agentos/autonomy.py
agentos/autonomous_runtime.py
agentos/conversation.py   <-- nouveau

test_update.py
test_v48.py

INSTALLATION
------------
1. Arrêter api_server.py.
2. Copier les fichiers de l'archive en conservant l'arborescence.
3. Ne pas supprimer le dossier data : les mémoires et missions existantes sont
   conservées.
4. Lancer :

   python .\test_update.py
   python .\test_v48.py

5. Puis :

   python -u .\api_server.py

TESTS RÉELS CONSEILLÉS
----------------------
manager status
manager decisions
conversation status

Puis parler normalement à Paul sur un sujet :
"On continue sur le suivi de conversation d'Agent-OS."
"Du coup, qu'est-ce qu'il nous reste à faire dessus ?"

Redémarrer api_server.py puis demander :
"On en était où sur ce sujet ?"

Paul doit utiliser le fil précédent sans confondre celui-ci avec les souvenirs
personnels ou les anciennes missions.

Pour repartir volontairement de zéro sur le contexte de discussion :

nouvelle conversation

Cela archive le fil précédent mais ne supprime PAS les souvenirs personnels.

API
---
/api/autonomy
/api/autonomy/decisions
/api/autonomy/check
/api/conversation
/api/conversation/history


FINITION CONTEXTE CONVERSATIONNEL
--------------------------------
- Les états temporaires (fatigue, repos, stress, motivation, humeur) ne changent plus le sujet du fil.
- Ils sont exclus du résumé et du contexte quand la question actuelle porte sur un autre sujet.
- « On en était où ? » est désormais déterministe et reprend le dernier sujet substantiel.
- Un ancien conseil de repos ne doit plus être recyclé après changement d'état.
- Le contexte émotionnel reste accessible lorsque l'utilisateur pose explicitement une question sur son état.


FINITION V4.8 — ANTI-BOUCLE BIEN-ÊTRE
=====================================
- Les anciennes clôtures génériques de Paul ne sont plus réinjectées dans le contexte.
- Pour une question non émotionnelle, les références spontanées au repos, à l'énergie, au confort ou au bien-être sont filtrées avant affichage.
- Les messages qui parlent réellement de fatigue/repos peuvent toujours recevoir une réponse adaptée.
- test_v48.py contient désormais 47 contrôles, dont une reproduction du scénario Lady Di / repos.
