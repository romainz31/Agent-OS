MISE À JOUR AGENT-OS — FINITION MÉMOIRE RELATIONNELLE / PAUL
=============================================================

FICHIERS DU PACK
----------------
api_server.py
agentos/memory.py
agentos/router.py
agentos/personal_manager.py
test_update.py
README_MISE_A_JOUR.txt

IMPORTANT
---------
- les noms de fichiers restent simples ;
- ne supprime PAS data/memory.json ;
- la migration et la maintenance se font automatiquement au démarrage ;
- les anciennes missions réellement enregistrées restent dans l'historique
  opérationnel : la mise à jour ne réécrit pas l'histoire d'Agent-OS.

CORRECTIONS PRINCIPALES
-----------------------
1. Doublons relationnels
   Les anciennes préférences génériques qui décrivent en réalité une règle de
   communication sont reclassées puis fusionnées.

   Exemple :
   - COMMUNICATION : "Préfère des réponses directes..."
   - ancien doublon PRÉFÉRENCES : "je préfère qu'on aille droit au but..."

   Après maintenance : une seule mémoire canonique dans COMMUNICATION.

2. Occurrences / renforcements
   - deux formulations différentes du même fait renforcent la mémoire ;
   - un double envoi identique quasi instantané ne gonfle pas le compteur ;
   - une fusion/migration utilise le maximum des occurrences, jamais leur
     somme ;
   - un redémarrage ne renforce aucune mémoire.

3. Corrections naturelles
   Exemples reconnus :
   - Finalement mon poisson préféré est le tétra amande.
   - Corrige : ma copine s'appelle Coralie.

   Une nouvelle valeur remplace l'ancienne et l'ancienne passe dans
   l'historique relationnel comme superseded.

4. Oubli ciblé
   Exemples :
   - Oublie mon poisson préféré.
   - Peux-tu oublier mon poisson préféré ?
   - memory forget mon poisson préféré

   L'oubli ne supprime pas les centres d'intérêt voisins et les anciennes
   valeurs oubliées ne restent pas lisibles dans l'historique relationnel.

5. État émotionnel
   L'état du moment expire désormais rapidement :
   - humeur : 4 h ;
   - motivation : 4 h ;
   - énergie : 3 h ;
   - stress : 3 h ;
   - frustration : 3 h.

   Une observation plus ancienne reste disponible dans l'historique mais ne
   doit plus influencer la conversation actuelle.

6. Routage
   Les phrases personnelles/corrections ne créent plus de mission par erreur.

   Conversation / mémoire :
   - D'habitude je teste le code le soir.
   - Je préfère que tu me donnes le fichier complet...
   - Corrige : ma copine s'appelle Coralie.

   Vraies missions :
   - Teste workspace/test_a.py
   - Peux-tu modifier workspace/app.py ?
   - Recherche des informations sur Zigbee2MQTT

NOUVELLES COMMANDES MÉMOIRE
---------------------------
memory relations
memory history
memory stats
memory cleanup
memory forget <ce qu'il faut oublier>
memory correct <nouvelle information>

Exemples :
memory cleanup
memory forget ma copine
memory correct Ma copine s'appelle Coralie.

INSTALLATION
------------
Depuis la racine v3/agent-os-final, copie/remplace les fichiers du ZIP en
respectant l'arborescence.

NE PAS SUPPRIMER data/memory.json.

TEST AUTOMATIQUE
----------------
Arrête de préférence les clients qui écrivent dans Agent-OS pendant le test.
Le test lui-même utilise un dossier temporaire et ne modifie pas la vraie
mémoire.

Depuis v3/agent-os-final :

python -m py_compile .\agentos\memory.py
python -m py_compile .\agentos\router.py
python -m py_compile .\agentos\personal_manager.py
python -m py_compile .\api_server.py
python .\test_update.py

Résultat attendu à la fin :

TOUS LES TESTS LOCAUX SONT PASSÉS.

TEST RÉEL CONSEILLÉ
-------------------
1. memory debug
2. memory cleanup
3. memory debug
4. Corrige : ma copine s'appelle Coralie.
5. memory relations
6. Aujourd'hui je suis motivé.
7. emotion

Pour tester la péremption émotionnelle, inutile d'attendre pendant notre
session : le test_update.py la simule automatiquement avec une observation de
5 heures.


CORRECTIFS D'INTÉGRATION AJOUTÉS
--------------------------------
- Un oubli de relation purge maintenant aussi les anciennes valeurs de la conversation récente.
- Les questions précises comme « Comment s'appelle ma copine ? » lisent uniquement la mémoire relationnelle structurée.
- Les questions « mes habitudes », « mes préférences de communication », « mes centres d'intérêt », etc. sont isolées par catégorie.
- Une donnée oubliée ne peut donc plus être ressuscitée par le LLM depuis la conversation récente.
