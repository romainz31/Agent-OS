AGENT-OS V11.2 — PAUL / INTAKE SÉMANTIQUE
==========================================

BUT
---
Cette version ne laisse plus le modèle principal décider seul s'il doit mémoriser.
Avant la réponse de Paul, un intake sémantique analyse le message avec le modèle
Utility d'Agent Zero. Si Utility n'est pas configuré, il retombe automatiquement
sur le modèle de chat actif (donc ton Qwen local si c'est celui que tu utilises).

PIPELINE
--------
Message naturel
  -> Qwen : extraction sémantique JSON
  -> Python : validation / dates / ambiguïtés
  -> agent_os_memory : SQLite
  -> Paul : réponse naturelle

Qwen comprend le sens ; Python garantit ce qui est réellement enregistré.

EXEMPLES TRAITÉS
----------------
1) "aujourd'hui j'ai nettoyé la machine à café, la fontaine à chat et les toilettes"
   -> 3 actions distinctes.

2) "mercredi jai emmené coralie a laeroport"
   -> acteur=user/Romain
   -> action=emmener
   -> personne objet=Coralie
   -> destination de l'action=aéroport
   -> mercredi résolu par Python vers la bonne date passée
   -> ne déduit PAS vol, domicile ou localisation actuelle de Coralie.

3) "coralie est ma copine"
   -> relation structurée : Coralie / relation_to_user / copine.

4) "je l'ai emmenée mercredi" sans contexte suffisant
   -> aucune écriture hasardeuse
   -> Paul demande qui est "elle"
   -> la clarification est conservée dans SQLite pour le message suivant.

5) "qu'est-ce que j'ai fait hier ?"
   -> l'intake interroge directement la mémoire structurée et fournit le résultat à Paul.

6) "combien de fois j'ai nettoyé le filtre ces trois derniers mois ?"
   -> la période naturelle est résolue par Python, pas calculée au hasard par Qwen.

AUTRES CORRECTIONS
------------------
- Paul ne doit plus se représenter à chaque réponse.
- Suppression des suggestions hors sujet du style "promenade dans le parc".
- Schémas JSON complets ajoutés aux outils life_* pour le tool calling Agent Zero.
- Protection anti-double-écriture si Paul appelle quand même life_capture après l'intake.
- Les faits déduits sont refusés par défaut : si l'information manque, Paul demande.
- L'intake ne s'active que pour le profil Paul, agent principal A0.
- Les autres profils Agent Zero ne sont pas modifiés.

INSTALLATION
------------
1. Arrête si possible le conteneur Agent-OS pendant la copie.
2. Extrais LE CONTENU du ZIP dans ton dossier existant :
   Agent-OS-V11
   en acceptant le remplacement des fichiers.
3. Double-clique : APPLIQUER_AGENT_OS_V11_2.cmd
4. Le script réutilise INSTALLER_V11.ps1 avec -SkipClone et redémarre
   automatiquement le conteneur agent-os-v11 s'il existe.
5. Dans le navigateur, crée un NOUVEAU chat avec le profil Paul.

Aucune désinstallation du plugin n'est nécessaire.
Ce correctif inclut aussi le correctif de profil Paul V11.1 : tu peux l'appliquer
directement même si V11.1 n'a pas été installé séparément.
La base usr/agent_os_memory/assistant.db n'est pas écrasée.

TEST MANUEL CONSEILLÉ
---------------------
Envoie exactement, un message à la fois :

  aujourd'hui j'ai fait du nettoyage et plus particulièrement, j'ai nettoyé la machine a café, la fontaine a chat et les toilettes

  mercredi jai emmené coralie a laeroport

  coralie est ma copine

  qu'est-ce que j'ai fait aujourd'hui ?

  qu'est-ce que j'ai fait mercredi ?

Paul doit confirmer sans refaire sa présentation et sans inventer d'activité.

TEST TECHNIQUE OPTIONNEL
------------------------
Double-clique TESTER_AGENT_OS_V11_2.cmd.
Il teste le parseur temporel et le pipeline sémantique sans toucher à ta base réelle.
