# Agent-OS V11.4 — Paul Semantic Gate

Cette version corrige le problème où Paul reprenait les faits de Romain à la première personne, par exemple :

- Romain : `je m'appelle Romain et j'habite à Brens`
- Mauvais : `Je suis Paul. Je suis à Brens.`

## Architecture V11.4

1. Un **gate global** s'exécute avant `AgentContext._process_chain`.
2. Qwen fait un premier appel très court de **routage** : `capture/query/update/forget/none`.
3. Si c'est un tour de mémoire, Qwen reçoit un second prompt spécialisé et beaucoup plus petit.
4. Python valide les champs, résout les dates et écrit dans SQLite.
5. La réponse est générée par Python depuis les données validées.
6. Le monologue conversationnel Agent Zero n'est **pas lancé** pour ce tour.

Ainsi, Qwen sert à comprendre la langue mais ne décide pas librement de la mémoire et ne rédige pas de commentaire générique après l'enregistrement.

## Protection d'identité

- `user` = Romain.
- Paul = assistant.
- `je/j'/mon/ma/mes` dans le message utilisateur décrivent Romain.
- Le profil Paul reçoit aussi un marqueur d'identité et le nom runtime `Paul`.

## Pourquoi le gate est maintenant dans `usr/extensions`

V11.3 plaçait le court-circuit dans le plugin. Les tests vérifiaient l'extracteur mais pas que le hook était réellement chargé par le runtime utilisé par l'interface Web.

V11.4 installe donc le gate dans :

`Agent-Zero-V11/usr/extensions/python/_functions/agent/AgentContext/_process_chain/start/`

L'installateur exécute ensuite un test avec le vrai Python Agent Zero (`/opt/venv-a0/bin/python`) et échoue si `AgentOSPersonalIntakeGate` n'est pas découvert.

## Installation

Extraire le contenu du ZIP directement dans `Agent-OS-V11`, puis lancer :

`APPLIQUER_AGENT_OS_V11_4.cmd`

La base `Agent-Zero-V11/usr/agent_os_memory/assistant.db` n'est pas supprimée.

Après installation, ouvrir un **nouveau chat Paul**.

## Tests recommandés

### Identité

`je mapelle romain et jhabite a brens`

Attendu :

`D'accord, je retiens que tu t'appelles Romain et que tu habites à Brens.`

### Actions multiples

`aujourd'hui j'ai fait du nettoyage et plus particulièrement, j'ai nettoyé la machine a café, la fontaine a chat et les toilettes`

Attendu : trois actions en mémoire et une réponse en `tu as ...`.

### Événement sémantique

`mercredi jai emmené coralie a laeroport`

Attendu : Romain est l'acteur, Coralie l'objet/personne, l'aéroport la destination de l'action. Aucun vol n'est déduit.

### Relation

`coralie est ma copine`

Attendu : `Coralie est ta copine.`

### Recherche

`qu'est-ce que j'ai fait aujourd'hui ?`

Attendu : uniquement les actions du jour.

## Diagnostic

Si un résultat reste incorrect, lancer :

`DIAGNOSTIQUER_AGENT_OS_V11_4.cmd`

Le script montre :

- version du plugin ;
- présence du gate ;
- plugins activés ;
- chemins d'extensions réellement découverts ;
- classes de hook réellement chargées ;
- 30 dernières lignes du log local `intake_runtime.log`.

Ce log permet de savoir immédiatement si le problème vient du routage Qwen, de l'extraction, du store ou du chargement du hook.
