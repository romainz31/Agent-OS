AGENT-OS V5.5 — ARTIFACTS ET BUILD RÉEL
=======================================

Cette mise à jour se pose PAR-DESSUS V5.4.1.

OBJECTIF
--------

Permettre à Paul de recevoir une demande orientée résultat, par exemple :

  crée un .exe qui ouvre une boite de dialogue avec ecris "coucou coralie"

sans obliger l'utilisateur à fournir lui-même un chemin de fichier complet.

NOUVEAUTÉS V5.5
---------------

1. Création d'artefacts .exe
   Le Developer reconnaît maintenant les demandes de création d'exécutables
   Windows et ne traite plus un .exe comme un simple fichier texte.

2. Nom automatique
   Si aucun nom complet n'est fourni, Agent-OS choisit un nom raisonnable.
   Exemple :

   "coucou coralie" -> workspace/dist/coucou_coralie.exe

3. Source intermédiaire réel
   Le Developer crée un source Python réel dans :

   workspace/applications/

4. Build PyInstaller réel
   Le source est transformé en véritable exécutable Windows via PyInstaller.
   Aucun shell arbitraire n'est ouvert au Developer.

5. Permissions dédiées
   Deux permissions étroites sont ajoutées :

   - build_artifact
   - run_artifact_test

   Les protections existantes restent en place :

   - shell_command reste BLOCKED
   - install_software reste BLOCKED

6. Cas boîte de dialogue déterministe
   Pour une demande simple de boîte de dialogue avec un texte explicite,
   Agent-OS génère directement un petit programme tkinter fiable sans demander
   au LLM d'inventer la structure du code.

7. Self-test intégré
   Les exécutables produits contiennent un mode :

   --self-test

   Ce mode n'ouvre pas la fenêtre et permet au Tester de vérifier le binaire.

8. Tester binaire
   Le Tester ne tente plus de lire un .exe comme du texte.
   Il vérifie :

   - présence réelle du fichier ;
   - signature MZ ;
   - signature PE ;
   - taille et SHA-256 ;
   - exécution réelle du --self-test.

9. Planner déterministe
   Une demande simple de création de .exe produit directement :

   Developer -> Tester

   sans appel LLM inutile pour le planning.

10. Nettoyage Git
    Les sorties temporaires et exécutables générés sont ignorés :

    workspace/.agentos_build/
    workspace/dist/

DÉPENDANCE AJOUTÉE
------------------

PyInstaller >= 6.15.0

Cette branche supporte Python 3.14.

INSTALLATION
------------

Depuis v3\Agent-OS-Final :

python -m pip install -r requirements.txt

TEST V5.5
---------

python .\test_v55.py

Le test vérifie notamment :

- la nouvelle permission de build ;
- le maintien du blocage du shell ;
- le plan Developer -> Tester ;
- l'inférence de dist/coucou_coralie.exe ;
- le source tkinter déterministe ;
- la validation syntaxique ;
- le rejet d'un faux .exe texte ;
- sur Windows avec PyInstaller : build réel, signatures MZ/PE et self-test réel.

TEST RÉEL CONSEILLÉ
-------------------

Redémarre Agent-OS puis demande à Paul :

  crée un .exe qui ouvre une boite de dialogue avec ecris "coucou coralie"

Résultat attendu :

1. Paul crée une mission avec Developer puis Tester.
2. Aucune erreur explicit_path_missing.
3. Le Developer crée un source sous workspace/applications/.
4. PyInstaller crée workspace/dist/coucou_coralie.exe.
5. Le Tester confirme un vrai binaire PE et exécute --self-test.
6. En lançant manuellement l'exécutable, une boîte affiche "coucou coralie".

IMPORTANT
---------

V5.5 n'autorise pas le Developer à lancer des commandes shell arbitraires.
Le builder PyInstaller est codé explicitement et ne prend pas une commande libre
produite par le LLM.

LIMITES V5.5
------------

- Le builder .exe fonctionne sur Windows ; PyInstaller n'est pas un
  cross-compilateur.
- Cette première version construit les exécutables depuis Python.
- Les futurs artefacts (zip, PDF, installateur MSI, image Docker, etc.) pourront
  être ajoutés avec le même modèle : builder dédié + permissions dédiées + tests.
