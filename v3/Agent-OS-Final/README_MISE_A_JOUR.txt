MISE À JOUR TELEGRAM — MENU + /HELP

Fichiers :
- telegram_client.py
- test_telegram_commands.py

Cette mise à jour :
- met /help à jour ;
- synchronise automatiquement le menu Telegram via setMyCommands au démarrage ;
- ajoute des raccourcis /manager, /decisions, /conversation, /research, etc. ;
- ajoute les commandes avec paramètres /priority, /deadline, /pause, /resume, /cancel, /retry ;
- conserve les boutons Autoriser / Refuser pour les approbations.

INSTALLATION
1. Remplacer telegram_client.py à la racine du projet.
2. Copier test_telegram_commands.py à la racine.
3. Lancer :
   python .\test_telegram_commands.py
4. Redémarrer :
   python -u .\telegram_client.py

Au démarrage, le terminal doit afficher :
Commandes Telegram : menu de commandes synchronisé

Dans Telegram, ferme/réouvre éventuellement le menu "/" si l'ancien menu reste affiché quelques secondes.
