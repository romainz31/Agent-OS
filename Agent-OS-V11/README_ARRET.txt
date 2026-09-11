Agent-OS V11.0.2 - Lanceur d'arret Windows

NOUVEAU FICHIER
---------------
ARRETER_AGENT_OS.cmd

BUT
---
Un double-clic suffit pour arreter Agent-OS puis fermer Docker Desktop.

Le lanceur :
1. verifie Docker ;
2. verifie si le conteneur "agent-os-v11" existe ;
3. arrete proprement le conteneur avec un delai pouvant aller jusqu'a 30 secondes ;
4. ferme Docker Desktop avec la commande officielle "docker desktop stop" ;
5. utilise DockerCli.exe -Shutdown uniquement en solution de compatibilite si necessaire.

IMPORTANT
---------
Le conteneur n'est PAS supprime.
La base assistant.db et le dossier /a0/usr restent conserves.
Le prochain lancement avec DEMARRER_AGENT_OS.cmd reutilisera la meme instance.

INSTALLATION
------------
Copie ARRETER_AGENT_OS.cmd dans :
C:\Users\romai\Desktop\Formation Agent IA\Agent-OS\Agent-OS-V11\

Tu peux ensuite creer un raccourci Windows vers ce fichier et le placer ou tu veux.
