# Agent-OS V11.5 — correctif validation sémantique

V11.5 corrige le faux rejet observé en V11.4 : Qwen pouvait extraire correctement
un souvenir tout en recopiant `confidence: 0.0` depuis le schéma. Python demandait
alors une précision malgré des champs complets.

## Règle V11.5

- Qwen comprend/extrait.
- Python valide les champs requis et les dates.
- Un score de confiance généré par le modèle est uniquement une métadonnée.
- Une extraction complète n'est jamais rejetée uniquement à cause d'un score bas.
- Une vraie ambiguïté doit être signalée par `clarification.needed=true` ou par un
  champ essentiel manquant.
- Le Semantic Gate reste placé avant `AgentContext._process_chain`, donc un tour de
  mémoire traité ne passe pas dans le Paul conversationnel.

## Installation

Extraire le contenu dans `Agent-OS-V11`, accepter les remplacements puis lancer :

`APPLIQUER_AGENT_OS_V11_5.cmd`

Ouvrir ensuite un nouveau chat Paul et tester :

1. `je mapelle romain et jhabite a brens`
2. `aujourd'hui j'ai fait du nettoyage et plus particulièrement, j'ai nettoyé la machine a café, la fontaine a chat et les toilettes`
3. `mercredi jai emmené coralie a laeroport`
4. `coralie est ma copine`

Le fichier `DIAGNOSTIQUER_AGENT_OS_V11_5.cmd` affiche les dernières décisions de
l'intake si une phrase reste mal comprise.
