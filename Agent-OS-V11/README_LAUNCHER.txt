Agent-OS V11.0.1 - Lanceur Windows

NOUVEAU FICHIER
---------------
DEMARRER_AGENT_OS.cmd

BUT
---
Un double-clic suffit pour ouvrir Agent-OS V11 dans le navigateur.

Le lanceur :
1. verifie que Docker est disponible ;
2. demarre Docker Desktop si necessaire ;
3. attend que le moteur Docker soit pret ;
4. verifie que le conteneur "agent-os-v11" existe ;
5. demarre le conteneur s'il est arrete ;
6. verifie la presence du plugin V11 "agent_os_memory" ;
7. attend l'interface Web ;
8. ouvre http://localhost:5080 dans le navigateur.

INSTALLATION
------------
Copie DEMARRER_AGENT_OS.cmd dans :
C:\Users\romai\Desktop\Formation Agent IA\Agent-OS\Agent-OS-V11\

Tu peux ensuite creer un raccourci Windows vers ce fichier et placer le
raccourci ou tu veux.

IMPORTANT
---------
Ce lanceur ne supprime ni ne recree le conteneur Docker.
Il ne touche pas a la base assistant.db ni aux donnees de /a0/usr.

ARRET MANUEL ACTUEL
-------------------
docker stop agent-os-v11
