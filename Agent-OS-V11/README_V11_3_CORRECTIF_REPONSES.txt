AGENT-OS V11.3 — CORRECTIF RÉPONSES / MÉMOIRE DE PAUL
=====================================================

PROBLÈME OBSERVÉ EN V11.2
-------------------------
L'intake Qwen comprenait souvent correctement l'information et l'écrivait dans
SQLite, mais la réponse finale repassait ensuite dans le modèle conversationnel.
Le modèle ajoutait alors des phrases génériques ou absurdes :

  "C'est bien, merci."
  "C'est une activité très utile..."
  "...pour assurer la sécurité des personnes."

Il pouvait également reprendre l'événement précédent au lieu de répondre au
message courant, par exemple après "Coralie est ma copine".

CORRECTION V11.3
----------------
Le pipeline devient :

  message de Romain
       -> Qwen : compréhension / extraction sémantique
       -> Python : validation + dates + cohérence
       -> SQLite : écriture / recherche
       -> réponse contrôlée de Paul

Pour un tour de mémoire déjà compris, le modèle conversationnel principal n'est
PLUS appelé une seconde fois. Cela empêche les commentaires inventés.

Qwen reste utilisé là où il est utile : comprendre le langage naturel.
Python reste responsable de ce qui est réellement accepté et mémorisé.

EXEMPLES ATTENDUS
-----------------
Romain :
  aujourd'hui j'ai nettoyé la machine à café, la fontaine à chat et les toilettes

Paul :
  D'accord, je retiens qu'aujourd'hui tu as nettoyé la machine à café,
  la fontaine à chat et les toilettes.

Romain :
  mercredi jai emmené coralie a laeroport

Paul :
  D'accord, je retiens que tu as emmené Coralie à l'aéroport mercredi.

Romain :
  coralie est ma copine

Paul :
  D'accord, je retiens que Coralie est ta copine.

Romain :
  qu'est-ce que j'ai fait aujourd'hui ?

Paul :
  Aujourd'hui, tu as nettoyé la machine à café, la fontaine à chat et les toilettes.

Romain :
  qu'est-ce que j'ai fait mercredi ?

Paul :
  Mercredi, tu as emmené Coralie à l'aéroport.

AUTRES CORRECTIONS
------------------
- Le MESSAGE COURANT est désormais prioritaire dans l'extracteur.
  L'historique ne sert qu'à résoudre les pronoms/références implicites.
- "Coralie est ma copine" ne doit plus être remplacé par l'événement précédent.
- Si Qwen donne une confiance globale mais oublie la confiance de l'élément,
  l'élément hérite de la confiance globale au lieu d'être rejeté par erreur.
- Les réponses de mémoire sont produites à partir des données réellement
  enregistrées/retrouvées, pas à partir d'une reformulation libre du LLM.
- Les phrases génériques "c'est bien, merci", "activité utile", "sécurité", etc.
  sont explicitement interdites dans le fallback conversationnel de Paul.
- L'ancienne extension V11.2 message_loop_start est neutralisée pour éviter un
  second passage de l'intake.
- Aucune suppression ni remise à zéro de assistant.db.

INSTALLATION
------------
1. Extrais LE CONTENU du ZIP dans ton dossier Agent-OS-V11 existant.
2. Accepte le remplacement des fichiers.
3. Double-clique APPLIQUER_AGENT_OS_V11_3.cmd.
4. Le script réutilise INSTALLER_V11.ps1 et redémarre agent-os-v11 si Docker
   est actif.
5. Ouvre un NOUVEAU chat avec Paul.

Il n'est pas nécessaire de désinstaller le plugin ni d'effacer sa mémoire.

TEST TECHNIQUE
--------------
TESTER_AGENT_OS_V11_3.cmd lance 11 tests unitaires.
