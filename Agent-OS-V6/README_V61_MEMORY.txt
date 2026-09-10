AGENT-OS V6.1 — UNDERSTANDING + MEMORY

But de cette mise à jour
========================
Cette étape corrige le problème où Paul pouvait détecter une émotion puis
ignorer le reste du message.

Exemple cible :
"il est tard je suis fatigué je ne veux pas travailler il faut que tu me divertisse"

Après V6.1 :
- la fatigue est retenue comme état temporaire ;
- "je ne veux pas travailler" est compris comme contrainte du moment ;
- "divertis-moi" reste le but principal ;
- aucune mission n'est créée juste pour divertir ;
- Paul répond à la demande au lieu de seulement dire que ton énergie est basse.

La mémoire sait aussi recevoir des événements banals sans marqueur temporel :
- "j'ai vu un canard"
- "j'ai fait la vaisselle"
- "j'ai mangé une pizza"

Installation
============
1. Décompresse le contenu du ZIP dans le dossier Agent-OS-V6.
2. Ouvre PowerShell dans Agent-OS-V6.
3. Lance :

   python .\APPLY_V61_MEMORY.py

Le script :
- vérifie qu'il trouve bien ta V6 actuelle ;
- prépare toutes les modifications avant d'écrire ;
- modifie agentos/manager.py et agentos/memory.py ;
- ajoute agentos/understanding.py ;
- compile les 3 fichiers pour vérifier la syntaxe.

Il ne crée pas de .bak ni de fichier temporaire.

Ce qui change
=============
- nouveau UnderstandingEngine sémantique basé sur ton Ollama actuel ;
- plusieurs intentions peuvent coexister dans un seul message ;
- le Router regex reste présent comme fallback si Ollama ou le JSON échoue ;
- les émotions ne court-circuitent plus une autre demande ;
- mémoire épisodique portée de 200 à 5000 événements ;
- mémoire durable portée de 250 à 2000 faits ;
- mémoire relationnelle portée de 120 à 500 éléments par catégorie ;
- événements quotidiens transmis à la mémoire même sans "aujourd'hui/hier".

Tests à faire après redémarrage
===============================
1.
il est tard je suis fatigué je ne veux pas travailler il faut que tu me divertisse

Attendu :
Paul doit te divertir / répondre à la demande.
Il peut tenir compte de ta fatigue, mais ne doit pas répondre seulement
"je retiens que ton énergie est basse".

2.
j'ai vu un canard

Puis :
tu te souviens du canard ?

Attendu :
le souvenir du canard doit pouvoir ressortir.

3.
j'ai fait la vaisselle

Puis un peu plus tard :
qu'est-ce que je t'ai raconté aujourd'hui ?

4.
on pourrait peut-être refaire mon dashboard Home Assistant

Attendu :
discussion, PAS création automatique d'une mission.

5.
refais mon dashboard Home Assistant

Attendu :
demande de travail ; création d'une mission.

Important
=========
Cette V6.1 garde memory.json et toutes les données existantes.
Elle ne remet pas la mémoire à zéro.

Le stockage reste encore en JSON. Avec 5000 épisodes cela convient pour
continuer le développement, mais une prochaine étape devra passer le journal
épisodique vers un stockage plus adapté (SQLite + recherche sémantique) afin
de conserver beaucoup plus d'historique sans injecter toute la mémoire au LLM.
