CORRECTIF PAUL — AGENT-OS V11.1

Cause corrigée
---------------
Le profil Paul avait seulement un agent.yaml avec un champ "context".
Dans Agent Zero, ce champ sert principalement au contexte de délégation et ne remplace pas
le prompt principal du chat. Paul pouvait donc être sélectionné dans l'interface tout en
continuant à se comporter comme Agent Zero.

Ce correctif ajoute :
1. overlay/usr/plugins/agent_os_memory/agents/paul/prompts/agent.system.main.specifics.md
   -> vraie identité et règles de mémoire de Paul.
2. overlay/usr/plugins/agent_os_memory/agents/paul/prompts/fw.initial_message.md
   -> remplace le message initial "I'm Agent Zero" par un accueil de Paul.
3. APPLIQUER_CORRECTIF_PAUL.cmd
   -> recopie le plugin avec INSTALLER_V11.ps1 et redémarre le conteneur si Docker tourne.

Installation
------------
1. Extraire le contenu de ce ZIP DANS le dossier Agent-OS-V11 existant.
2. Accepter le remplacement/ajout des fichiers.
3. Double-cliquer sur APPLIQUER_CORRECTIF_PAUL.cmd.
4. Ouvrir Agent Zero.
5. Créer un NOUVEAU chat et vérifier que le profil Paul est sélectionné.

Test conseillé
--------------
Message 1 :
je m'appelle Romain et j'habite à Brens dans le Tarn en France

Message 2 :
hier j'ai nettoyé la machine à café, la fontaine à chat et les toilettes

Puis :
qu'est-ce que j'ai fait hier ?

Résultat attendu
----------------
Paul doit :
- se présenter comme Paul, pas Agent Zero ;
- mémoriser séparément le nom et le lieu ;
- mémoriser séparément les 3 actions ;
- pouvoir les retrouver avec life_query.
