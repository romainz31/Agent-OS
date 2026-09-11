# Agent-OS V11.6 — Correctif extracteur Qwen

## Cause trouvee dans le diagnostic V11.5

Le gate et le routeur fonctionnaient. Le routeur renvoyait bien `capture`.
Le probleme etait l'extracteur : Qwen recopiait litteralement les choix du schema, par exemple `action|task|appointment...`, au lieu de choisir une valeur concrete.

V11.6 change le contrat envoye a Qwen :

- plus aucun faux enum concatene dans les exemples JSON ;
- exemples complets et concrets pour identite, domicile, nettoyage multiple, aeroport et relation ;
- reparation Python d'un `kind` mal forme quand les autres champs prouvent deja le type ;
- une relance automatique de Qwen si la premiere extraction recopie le schema ou regroupe plusieurs actions ;
- diagnostic enrichi avec `_extractor_diagnostic` ;
- scripts CMD sans BOM ;
- diagnostic Python execute avec `-w /a0`, donc plus de faux `ModuleNotFoundError`;
- lecture du log en UTF-8.

## Installation

1. Extraire le CONTENU du ZIP dans le dossier `Agent-OS-V11`.
2. Accepter les remplacements.
3. Lancer `APPLIQUER_AGENT_OS_V11_6.cmd`.
4. Ouvrir un nouveau chat Paul.

## Tests a faire

`je mapelle romain et jhabite a brens`

Attendu : Paul confirme que **tu** t'appelles Romain et que **tu** habites a Brens.

Puis :

`aujourd'hui j'ai fait du nettoyage et plus particulierement, j'ai nettoye la machine a cafe, la fontaine a chat et les toilettes`

Attendu : trois actions distinctes dans la memoire et une confirmation en `tu as nettoye...`.

## Diagnostic

Si le resultat n'est pas bon, lancer `DIAGNOSTIQUER_AGENT_OS_V11_6.cmd`.
Le log montrera desormais le premier probleme detecte, le nombre de tentatives et le resultat de la relance.
