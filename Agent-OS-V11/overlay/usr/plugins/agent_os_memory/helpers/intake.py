from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from .normalization import clean, normalize
from .temporal import day_expression_to_iso_bounds, ensure_reference, resolve_temporal_expression


KINDS = {"task", "appointment", "event", "action", "mood", "note", "fact", "preference", "relation"}
FACT_KINDS = {"fact", "preference", "relation"}
STATUSES = {"pending", "scheduled", "done", "logged", "cancelled", "archived"}
VALID_MODES = {"none", "capture", "query", "update", "forget"}
VALID_AGGREGATES = {"list", "count"}


ROUTER_SYSTEM = r"""
Tu es le ROUTEUR sémantique de la mémoire personnelle de Paul.
Tu ne réponds jamais à Romain.

RÈGLE ABSOLUE
- Analyse d'abord et uniquement MESSAGE_UTILISATEUR.
- N'utilise jamais une ancienne question, un ancien filtre ou la mémoire connue pour
  changer le sens d'une phrase autonome actuelle.
- PENDING_CLARIFICATION sert uniquement à savoir si un message très court répond
  directement à une vraie question de clarification précédente.

IDENTITÉS
- Romain = utilisateur.
- Paul = assistant.
- Dans MESSAGE_UTILISATEUR, « je », « j' », « mon », « ma », « mes » parlent de Romain.

Choisis UNE route : capture, query, update, forget, none.
- capture : Romain affirme/donne N'IMPORTE QUELLE information autobiographique ou personnelle :
  fait, relation, préférence, humeur, action accomplie, observation, chose vue/entendue, tâche,
  rendez-vous, événement, détail de sa journée, personne rencontrée, lieu visité, etc.
  Exemples à capturer : « j'ai vu un canard aujourd'hui », « il y avait un chat dans mon jardin »,
  « samedi je dois aller chercher Coralie à l'aéroport ».
- query : Romain pose une question sur sa mémoire personnelle.
- update : Romain demande explicitement de corriger, terminer, annuler ou reporter un élément mémorisé.
- forget : Romain demande explicitement d'oublier/supprimer un souvenir.
- none : conversation générale, explication, code, recherche, etc.

`query_follow_up=true` UNIQUEMENT si la question actuelle est elliptique et ne peut
pas être comprise seule sans reprendre la requête précédente, par exemple « et mardi ? ».
Une question autonome comme « qui travaille demain matin ? » ou
« qu'est-ce que j'ai fait mardi ? » a query_follow_up=false.

`uses_pending=true` UNIQUEMENT si MESSAGE_UTILISATEUR répond directement à
PENDING_CLARIFICATION. Une nouvelle phrase complète a uses_pending=false.

SORTIE JSON SEULEMENT :
{"route":"capture","uses_pending":false,"query_follow_up":false,"clarification":null}

EXEMPLES
- « Coralie est ma copine »
  => {"route":"capture","uses_pending":false,"query_follow_up":false,"clarification":null}
- « ma copine travaille demain matin »
  => {"route":"capture","uses_pending":false,"query_follow_up":false,"clarification":null}
- « mardi j'ai lavé ma voiture »
  => {"route":"capture","uses_pending":false,"query_follow_up":false,"clarification":null}
- « qui travaille demain matin ? »
  => {"route":"query","uses_pending":false,"query_follow_up":false,"clarification":null}
- « qu'est-ce que j'ai fait mardi ? »
  => {"route":"query","uses_pending":false,"query_follow_up":false,"clarification":null}
- « et mardi ? »
  => {"route":"query","uses_pending":false,"query_follow_up":true,"clarification":null}
- clarification « Tu parles de qui ? » puis « Coralie »
  => {"route":"none","uses_pending":true,"query_follow_up":false,"clarification":null}
- « explique-moi Frigate »
  => {"route":"none","uses_pending":false,"query_follow_up":false,"clarification":null}
""".strip()


CAPTURE_SYSTEM = r"""
Tu es l'EXTRACTEUR SÉMANTIQUE du message courant pour la mémoire personnelle de Paul.
Tu ne réponds jamais à l'utilisateur. Tu analyses MESSAGE_UTILISATEUR pour lui-même.

RÈGLE ABSOLUE DE PORTÉE
- Tu n'as PAS accès à la mémoire générale ni à l'historique conversationnel ici.
- N'extrais QUE les informations explicitement présentes dans MESSAGE_UTILISATEUR.
- Si une personne est désignée par une relation (« ma copine ») ou un pronom (« elle », « l' »)
  et que son identité n'est pas explicitement donnée dans le message, NE L'INVENTE PAS.
  Marque le champ comme non résolu via `unresolved`.
- Le contexte sera traité plus tard par un résolveur séparé.

IDENTITÉS
- `user` = Romain.
- Paul = assistant.
- « je », « j' », « mon », « ma », « mes » dans le message = Romain.

TYPES `kind`
- fact : identité/caractéristique stable de Romain ou d'une personne
- relation : relation entre une personne et Romain
- preference : préférence
- mood : humeur/ressenti
- action : action déjà accomplie
- task : chose que Romain doit/veut faire
- appointment : rendez-vous
- event : événement prévu/constaté qui n'est pas une tâche de Romain
- note : information personnelle ne rentrant pas mieux ailleurs

RÈGLES SÉMANTIQUES
- OBJECTIF DE MÉMOIRE : ne perds aucun détail autobiographique explicite. Tout ce que Romain
  raconte sur sa vie, sa journée, ce qu'il a vu/fait/prévu/ressenti doit produire au moins un item.
- Si aucune catégorie spécialisée ne convient, utilise `note` plutôt que de jeter l'information.
- Une observation personnelle (« j'ai vu un canard aujourd'hui ») est une `action` de perception :
  actor=user, verb=voir, object=canard, date explicite si présente.
- Sépare les idées distinctes en plusieurs items, même dans une seule phrase.
- Une liste de plusieurs objets d'une même action produit un item par objet.
- Pour chaque item, identifie si possible : actor, verb, object, destination, personnes,
  lieux, relation, date naturelle et statut.
- Une action passée : kind=action, status=done.
- Une tâche future de Romain : kind=task, status=pending.
- Si une personne ou un lieu est NOMMÉ explicitement dans le message (`Coralie`, `Toulouse`,
  `l'aéroport`), utilise directement ce nom dans actor/object/destination et dans `entities`.
  Ne marque JAMAIS un nom explicite comme `unresolved`.
- Un fait futur concernant quelqu'un d'autre (« ma copine travaille demain matin »)
  est généralement un event, pas une task de Romain.
- Une date naturelle reste textuelle dans time_expression. Python la résout ensuite.
- Ne déduis jamais un vol, une résidence, une intention, une localisation actuelle ou une cause absente.
- `details` peut contenir les détails explicites qui ne rentrent pas dans actor/verb/object/destination.
- `keywords` contient quelques concepts canoniques utiles à la recherche future, sans invention.
- Le texte source complet est conservé séparément par Python : ne le résume pas au point de perdre une information.

CHAMPS NON RÉSOLUS
Si un champ essentiel dépend du contexte, laisse ce champ vide et ajoute `unresolved`.
IMPORTANT : un pronom ou déictique n'est JAMAIS une valeur résolue.
- `l'`, `le`, `la`, `lui`, `elle`, `eux`, `leur` peuvent désigner une personne/objet précédent.
- `y`, `là`, `là-bas`, `cet endroit` peuvent désigner un lieu précédent.
- N'écris JAMAIS `quelqu'un`, `une personne`, `quelque part`, `un endroit` dans actor/object/destination
  pour masquer une référence inconnue. Le champ doit rester vide et être marqué unresolved.

Exemples de structure :
"unresolved":[{"field":"actor","mention":"ma copine","reason":"relation_to_user"}]
"unresolved":[{"field":"object","mention":"l'","reason":"pronoun_person"}]
"unresolved":[{"field":"object","mention":"lui","reason":"pronoun_person"}]
"unresolved":[{"field":"destination","mention":"y","reason":"deictic_place"}]

Ne demande PAS encore à l'utilisateur : le système cherchera d'abord dans sa mémoire.

FORMAT
{"clarification":null,"items":[...]}

EXEMPLES
Message : Coralie est ma copine
=> {"clarification":null,"items":[{"kind":"relation","title":"Coralie est la copine de Romain","subject":"Coralie","predicate":"relation_to_user","value":"copine","inferred":false,"entities":[{"type":"person","name":"Coralie","role":"related"}]}]}

Message : mon deuxième prénom est Michel
=> {"clarification":null,"items":[{"kind":"fact","title":"ton deuxième prénom est Michel","subject":"user","predicate":"middle_name","value":"Michel","inferred":false}]}

Message : mardi j'ai lavé ma voiture
=> {"clarification":null,"items":[{"kind":"action","title":"lavé ma voiture","status":"done","time_expression":"mardi","actor":"user","verb":"laver","object":"ma voiture","inferred":false,"entities":[{"type":"object","name":"ma voiture","role":"object"}]}]}

Message : ma copine travaille demain matin
=> {"clarification":null,"items":[{"kind":"event","title":"ma copine travaille demain matin","status":"scheduled","time_expression":"demain matin","actor":"","verb":"travailler","object":"","inferred":false,"unresolved":[{"field":"actor","mention":"ma copine","reason":"relation_to_user","relation":"copine"}]}]}

Message : samedi je dois aller chercher Coralie à l'aéroport
=> {"clarification":null,"items":[{"kind":"task","title":"aller chercher Coralie à l'aéroport","status":"pending","time_expression":"samedi","actor":"user","verb":"aller chercher","object":"Coralie","destination":"aéroport","inferred":false,"keywords":["chercher","Coralie","aéroport"],"entities":[{"type":"person","name":"Coralie","role":"object"},{"type":"place","name":"aéroport","role":"destination"}]}]}

Message : j'ai vu un canard aujourd'hui
=> {"clarification":null,"items":[{"kind":"action","title":"vu un canard","status":"done","time_expression":"aujourd'hui","actor":"user","verb":"voir","object":"canard","inferred":false,"keywords":["voir","canard"],"entities":[{"type":"object","name":"canard","role":"object"}]}]}

Message : il y avait un canard dans mon jardin ce matin
=> {"clarification":null,"items":[{"kind":"event","title":"un canard était dans mon jardin","status":"logged","time_expression":"ce matin","actor":"canard","verb":"être","destination":"mon jardin","inferred":false,"keywords":["canard","jardin"],"entities":[{"type":"object","name":"canard","role":"actor"},{"type":"place","name":"mon jardin","role":"location"}]}]}

Message : je l'ai emmenée à l'aéroport mercredi
=> {"clarification":null,"items":[{"kind":"action","title":"emmené quelqu'un à l'aéroport","status":"done","time_expression":"mercredi","actor":"user","verb":"emmener","object":"","destination":"aéroport","inferred":false,"entities":[{"type":"place","name":"aéroport","role":"destination"}],"unresolved":[{"field":"object","mention":"l'","reason":"pronoun"}]}]}

Message : aujourd'hui j'ai nettoyé la machine à café, la fontaine à chat et les toilettes
=> {"clarification":null,"items":[{"kind":"action","title":"nettoyé la machine à café","status":"done","time_expression":"aujourd'hui","actor":"user","verb":"nettoyer","object":"machine à café","inferred":false},{"kind":"action","title":"nettoyé la fontaine à chat","status":"done","time_expression":"aujourd'hui","actor":"user","verb":"nettoyer","object":"fontaine à chat","inferred":false},{"kind":"action","title":"nettoyé les toilettes","status":"done","time_expression":"aujourd'hui","actor":"user","verb":"nettoyer","object":"toilettes","inferred":false}]}

Message : je l'ai croisée hier
=> {"clarification":null,"items":[{"kind":"action","title":"croisé une personne","status":"done","time_expression":"hier","actor":"user","verb":"croiser","object":"","inferred":false,"unresolved":[{"field":"object","mention":"l'","reason":"pronoun_person"}]}]}

Message : j'y suis retourné aujourd'hui
=> {"clarification":null,"items":[{"kind":"action","title":"retourné dans un lieu","status":"done","time_expression":"aujourd'hui","actor":"user","verb":"retourner","destination":"","inferred":false,"unresolved":[{"field":"destination","mention":"y","reason":"deictic_place"}]}]}

Message : je lui ai parlé ce matin
=> {"clarification":null,"items":[{"kind":"action","title":"parlé à une personne","status":"done","time_expression":"ce matin","actor":"user","verb":"parler","object":"","inferred":false,"unresolved":[{"field":"object","mention":"lui","reason":"pronoun_person"}]}]}

INTERDIT
- Ajouter des faits venant d'un autre message.
- Répéter d'anciens faits d'identité.
- Transformer une déclaration en question.
- Inventer une identité pour « ma copine », « elle », « l' », etc.
""".strip()


QUERY_SYSTEM = r"""
Tu es l'EXTRACTEUR de REQUÊTE MÉMOIRE du message courant.
Tu ne réponds jamais à Romain et tu n'utilises aucun ancien filtre.
Analyse uniquement MESSAGE_UTILISATEUR.

Ton rôle n'est PAS de faire une recherche textuelle littérale. Tu traduis la question
en intention sémantique afin que Paul puisse retrouver un souvenir même si les mots changent.

`follow_up` vaut true uniquement pour une vraie ellipse comme « et mardi ? ».
Une question autonome a toujours follow_up=false.

`semantic` décrit ce que Romain cherche :
- actor : qui agit, `user` pour Romain
- verb : action canonique à rechercher (`laver`, `voir`, `aller chercher`, `travailler`...)
- object : objet/personne concerné
- destination : lieu/destination si utile
- concepts : autres concepts importants
- question_type : list, when, who, what, count
- order : all, latest, earliest
- limit : nombre maximal souhaité (1 pour « la dernière fois »)

Le champ `text` est seulement un indice secondaire. Ne mets pas des mots comme
« dernière fois », « quand », « est-ce que » dans `text`.

FORMAT JSON :
{"clarification":null,"query":{"text":"","kinds":[],"statuses":[],"date_expression":"","start_expression":"","end_expression":"","subject":"","predicate":"","entity":"","entity_type":"","aggregate":"list","follow_up":false,"semantic":{"actor":"","verb":"","object":"","destination":"","concepts":[],"question_type":"list","order":"all","limit":20}}}

EXEMPLES
- « comment s'appelle ma copine ? »
  => {"clarification":null,"query":{"text":"copine","kinds":["relation"],"statuses":[],"date_expression":"","start_expression":"","end_expression":"","subject":"","predicate":"relation_to_user","entity":"","entity_type":"person","aggregate":"list","follow_up":false,"semantic":{"actor":"","verb":"","object":"","destination":"","concepts":["copine"],"question_type":"who","order":"all","limit":20}}}
- « qui travaille demain matin ? »
  => {"clarification":null,"query":{"text":"","kinds":["event"],"statuses":[],"date_expression":"demain matin","start_expression":"","end_expression":"","subject":"","predicate":"","entity":"","entity_type":"","aggregate":"list","follow_up":false,"semantic":{"actor":"","verb":"travailler","object":"","destination":"","concepts":[],"question_type":"who","order":"all","limit":20}}}
- « qu'est-ce que j'ai fait mardi ? »
  => {"clarification":null,"query":{"text":"","kinds":["action"],"statuses":[],"date_expression":"mardi","start_expression":"","end_expression":"","subject":"","predicate":"","entity":"","entity_type":"","aggregate":"list","follow_up":false,"semantic":{"actor":"user","verb":"","object":"","destination":"","concepts":[],"question_type":"what","order":"all","limit":20}}}
- « quand est-ce que j'ai lavé la voiture la dernière fois ? »
  => {"clarification":null,"query":{"text":"","kinds":["action"],"statuses":[],"date_expression":"","start_expression":"","end_expression":"","subject":"","predicate":"","entity":"","entity_type":"","aggregate":"list","follow_up":false,"semantic":{"actor":"user","verb":"laver","object":"voiture","destination":"","concepts":["voiture"],"question_type":"when","order":"latest","limit":1}}}
- « quand ai-je vu un canard pour la dernière fois ? »
  => {"clarification":null,"query":{"text":"","kinds":["action","event","note"],"statuses":[],"date_expression":"","start_expression":"","end_expression":"","subject":"","predicate":"","entity":"","entity_type":"","aggregate":"list","follow_up":false,"semantic":{"actor":"user","verb":"voir","object":"canard","destination":"","concepts":["canard"],"question_type":"when","order":"latest","limit":1}}}
- « combien de fois ai-je vu un canard ces six derniers mois ? »
  => {"clarification":null,"query":{"text":"","kinds":["action","event","note"],"statuses":[],"date_expression":"ces six derniers mois","start_expression":"","end_expression":"","subject":"","predicate":"","entity":"","entity_type":"","aggregate":"count","follow_up":false,"semantic":{"actor":"user","verb":"voir","object":"canard","destination":"","concepts":["canard"],"question_type":"count","order":"all","limit":100}}}
- « et mercredi ? »
  => {"clarification":null,"query":{"text":"","kinds":[],"statuses":[],"date_expression":"mercredi","start_expression":"","end_expression":"","subject":"","predicate":"","entity":"","entity_type":"","aggregate":"list","follow_up":true,"semantic":{"actor":"","verb":"","object":"","destination":"","concepts":[],"question_type":"list","order":"all","limit":20}}}
""".strip()

QUERY_MATCHER_SYSTEM = r"""
Tu es le MATCHER SÉMANTIQUE de la mémoire de Paul.
Tu ne réponds jamais à Romain.

On te donne une INTENTION_RECHERCHE déjà extraite et une liste de SOUVENIRS_CANDIDATS.
Sélectionne UNIQUEMENT les ids dont le sens correspond réellement à la recherche.
Tu peux reconnaître des variantes grammaticales et synonymes simples :
- laver / lavé
- voir / vu
- chercher / aller chercher
- voiture / ma voiture / ta voiture
Mais n'invente aucune correspondance absente.

Un souvenir candidat contient son texte source original et, quand disponible, les rôles
sémantiques actor/verb/object/destination extraits lors de l'enregistrement. Utilise-les en priorité.

SORTIE JSON SEULEMENT :
{"record_ids":["L-..."],"reason":"correspondance sémantique"}
Si aucun souvenir ne correspond :
{"record_ids":[],"reason":"aucune correspondance"}
""".strip()


RESOLVER_SYSTEM = r"""
Tu es le RÉSOLVEUR DE RÉFÉRENCES de Paul.
Tu n'interprètes PAS à nouveau le message entier et tu ne crées AUCUN nouvel item.

On te fournit :
- MESSAGE_UTILISATEUR
- PLAN_COURANT déjà extrait sans contexte
- MEMOIRE_UTILE
- éventuellement CONTEXTE_RECENT

Ton unique rôle est de remplir les champs listés dans `unresolved`.
Tu ne dois jamais modifier un champ déjà explicite dans PLAN_COURANT.
Tu ne dois jamais ajouter d'ancien fait, d'ancien événement ou d'ancienne préférence.

Pour chaque résolution certaine, retourne un patch :
{"patches":[{"item_index":0,"fields":{"actor":"Coralie"},"entities":[{"type":"person","name":"Coralie","role":"actor"}],"resolution":{"source":"known_memory","confidence":0.95}}],"clarification":null}

Si le contexte ne permet pas une résolution sûre, ne devine pas :
{"patches":[],"clarification":{"needed":true,"question":"Tu parles de qui ?"}}
""".strip()


AMBIGUITY_MATCHER_SYSTEM = r"""
Tu es le CHERCHEUR DE SOUVENIRS CANDIDATS de Paul.
Tu ne réponds jamais directement à Romain.

Le résolveur normal n'a pas réussi à remplir un ou plusieurs champs `unresolved`.
Tu reçois :
- MESSAGE_UTILISATEUR actuel ;
- PLAN_COURANT avec les champs non résolus ;
- SOUVENIRS_CANDIDATS contenant notamment `source_text`, c'est-à-dire les phrases
  complètes réellement dites par Romain.

Ton rôle :
1. chercher si un ancien souvenir permet de proposer une valeur plausible pour
   un champ non résolu ;
2. t'appuyer d'abord sur les phrases sources complètes, puis sur actor/verb/object,
   entities et dates ;
3. NE JAMAIS modifier un champ déjà explicite ;
4. NE JAMAIS affirmer qu'un candidat est certain : il sera proposé à Romain pour confirmation.

Retourne au maximum 3 propositions classées de la plus plausible à la moins plausible.
Chaque proposition doit viser un champ réellement `unresolved`.

SORTIE JSON :
{"candidates":[
  {
    "item_index":0,
    "field":"object",
    "value":"Coralie",
    "record_id":"L-...",
    "confidence":0.88,
    "reason":"le souvenir source mentionne Coralie dans un contexte compatible"
  }
]}

Si aucun ancien souvenir n'aide :
{"candidates":[]}
""".strip()


AMBIGUITY_CONFIRMATION_SYSTEM = r"""
Tu interprètes UNIQUEMENT la réponse de Romain à une proposition de clarification mémoire.

On te donne :
- QUESTION_POSÉE ;
- CANDIDATS_PROPOSÉS ;
- RÉPONSE_UTILISATEUR.

Retourne UNE action :
- accept : Romain confirme le candidat proposé ;
- select : Romain choisit explicitement un candidat parmi plusieurs ;
- provide_value : Romain donne directement la vraie valeur (ex. « non, c'était Léa ») ;
- reject : Romain refuse sans donner la bonne valeur ;
- new_topic : Romain ne répond pas à la clarification et lance clairement un nouveau sujet.

SORTIE JSON :
{"action":"accept","candidate_index":0,"value":""}
{"action":"select","candidate_index":1,"value":""}
{"action":"provide_value","candidate_index":-1,"value":"Léa"}
{"action":"reject","candidate_index":-1,"value":""}
{"action":"new_topic","candidate_index":-1,"value":""}

N'invente jamais la valeur.
""".strip()


REFERENCE_AUDITOR_SYSTEM = r"""
Tu es l'AUDITEUR DE RÉFÉRENCES du message courant.
Tu ne réponds pas à Romain et tu ne consultes aucune mémoire.

On te donne MESSAGE_UTILISATEUR et PLAN_COURANT déjà extrait.
Ton unique rôle est de détecter si le plan a FAUSSEMENT considéré comme résolu un pronom,
un déictique ou une référence vague.

Exemples :
- « je l'ai croisée hier » ne peut PAS avoir object=`quelqu'un` comme résolution.
  Le bon résultat garde object vide et ajoute unresolved sur `l'`.
- « j'y suis retourné aujourd'hui » garde destination vide et unresolved sur `y`.
- « je lui ai parlé ce matin » garde object vide et unresolved sur `lui`.
- « Coralie, je lui ai parlé ce matin » peut être résolu en Coralie car le nom est dans le même message.
- « je suis retourné à Toulouse » est déjà explicite : ne crée aucun unresolved.

Tu ne modifies jamais kind, verb, date ou les champs déjà explicitement nommés dans le message.
Retourne le plan corrigé complet sous :
{"items":[...]}
""".strip()


CLARIFICATION_RECOVERY_SYSTEM = r"""
Tu es le RÉCUPÉRATEUR SÉMANTIQUE de Paul.
L'extracteur principal a produit une structure techniquement invalide, mais le message est personnel.

Ne demande jamais à l'utilisateur de reformuler une phrase compréhensible.
Reconstruis uniquement ce qui est clair dans MESSAGE_UTILISATEUR et marque ce qui manque en `unresolved`.

Exemples :
- « j'y suis retourné aujourd'hui »
  => action, actor=user, verb=retourner, time_expression=aujourd'hui,
     destination vide, unresolved destination=`y`.
- « je lui ai parlé ce matin »
  => action, actor=user, verb=parler, time_expression=ce matin,
     object vide, unresolved object=`lui`.
- « je l'ai croisée hier »
  => action, actor=user, verb=croiser, time_expression=hier,
     object vide, unresolved object=`l'`.

N'invente jamais `quelqu'un`, `une personne`, `quelque part` comme valeur résolue.
Si une partie manque, garde le reste du souvenir.

SORTIE JSON :
{"clarification":null,"items":[...]}
""".strip()


TARGETED_CLARIFICATION_SYSTEM = r"""
Tu rédiges UNE question courte et naturelle en français pour lever exactement la référence
encore non résolue dans un souvenir de Romain.

Tu reçois MESSAGE_UTILISATEUR et PLAN_COURANT.
Préserve ce qui est déjà compris (action, date, lieu explicite) et demande seulement l'information manquante.

Exemples :
- `je l'ai croisée hier`, object manquant -> « Qui as-tu croisé hier ? »
- `j'y suis retourné aujourd'hui`, destination manquante -> « Où es-tu retourné aujourd'hui ? »
- `je lui ai parlé ce matin`, object manquant -> « À qui as-tu parlé ce matin ? »

Ne dis jamais :
- « Tu peux préciser la référence ? »
- « Reformule »
- « Je n'ai pas compris »

SORTIE JSON :
{"question":"..."}
""".strip()


UPDATE_SYSTEM = r"""
Tu extrais une demande EXPLICITE de modification d'un souvenir personnel à partir du seul MESSAGE_UTILISATEUR.
Actions autorisées : complete, cancel, archive, reschedule, update.
Ne réponds pas à l'utilisateur et n'invente pas de cible.
Réponds avec UN SEUL objet JSON.
Exemple :
{"clarification":null,"update":{"record_id":"","query":"dentiste","action":"reschedule","time_expression":"mardi","changes":{},"explicit_request":true}}
""".strip()


FORGET_SYSTEM = r"""
Tu extrais une demande EXPLICITE d'oubli à partir du seul MESSAGE_UTILISATEUR.
Ne réponds pas à l'utilisateur et n'invente pas de cible.
Réponds avec UN SEUL objet JSON.
Exemple :
{"clarification":null,"forget":{"query":"Coralie est ma copine","record_ids":[],"explicit_request":true}}
""".strip()


ROUTE_SYSTEMS = {
    "capture": CAPTURE_SYSTEM,
    "query": QUERY_SYSTEM,
    "update": UPDATE_SYSTEM,
    "forget": FORGET_SYSTEM,
}


@dataclass
class IntakeOutcome:
    status: str
    prompt_context: str
    raw_plan: dict[str, Any]
    saved: list[dict[str, Any]]
    query_result: dict[str, Any] | None = None
    clarification_question: str = ""
    operation_result: dict[str, Any] | None = None


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _metadata_confidence(value: Any, fallback: float = 0.95) -> float:
    """Confidence is metadata, never the decision gate.

    Small local models often copy `0.0` from an example schema even when every
    extracted field is correct. Treat missing/zero as unspecified and fall back
    to a conservative structural score. Ambiguity is decided from required
    fields and `clarification`, not from this number.
    """
    parsed = _clamp(value, -1.0)
    if parsed <= 0.01:
        return _clamp(fallback, 0.95)
    return parsed


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    # Fast path.
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception:
        pass

    # Markdown fence or extra chatter recovery.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.I | re.S)
    if fenced:
        try:
            value = json.loads(fenced.group(1))
            return value if isinstance(value, dict) else None
        except Exception:
            pass

    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(raw[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(raw[start:index + 1])
                    return value if isinstance(value, dict) else None
                except Exception:
                    return None
    return None




def _ensure_intake_state_table(store: Any) -> None:
    with store.connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS semantic_intake_state(
                context_id TEXT PRIMARY KEY,
                pending_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )"""
        )


def _get_intake_state(store: Any, context_id: str) -> dict[str, Any] | None:
    if not context_id:
        return None
    _ensure_intake_state_table(store)
    with store.connect() as db:
        row = db.execute(
            "SELECT pending_json FROM semantic_intake_state WHERE context_id=?",
            (context_id,),
        ).fetchone()
    if not row:
        return None
    try:
        value = json.loads(row["pending_json"] or "{}")
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _set_intake_state(store: Any, context_id: str, value: dict[str, Any]) -> None:
    if not context_id:
        return
    _ensure_intake_state_table(store)
    with store.connect() as db:
        db.execute(
            """INSERT INTO semantic_intake_state(context_id,pending_json,updated_at)
               VALUES(?,?,?)
               ON CONFLICT(context_id) DO UPDATE SET
                 pending_json=excluded.pending_json, updated_at=excluded.updated_at""",
            (context_id, json.dumps(value, ensure_ascii=False, default=str), store.now().isoformat()),
        )


def _clear_intake_state(store: Any, context_id: str) -> None:
    if not context_id:
        return
    _ensure_intake_state_table(store)
    with store.connect() as db:
        db.execute("DELETE FROM semantic_intake_state WHERE context_id=?", (context_id,))


def _known_context(store: Any, limit: int = 24) -> str:
    try:
        payload = store.query(limit=limit)
    except Exception:
        return "(aucune mémoire personnelle disponible)"

    lines: list[str] = []
    for fact in payload.get("facts", [])[:limit]:
        lines.append(
            f"FAIT: {fact.get('subject')} | {fact.get('predicate')} | {fact.get('value')}"
        )
    for record in payload.get("records", [])[: max(0, limit - len(lines))]:
        entities = ", ".join(
            f"{item.get('canonical_name')}[{item.get('role')}]"
            for item in record.get("entities", [])
        )
        line = f"EVENEMENT: {record.get('kind')} | {record.get('title')}"
        if entities:
            line += f" | {entities}"
        lines.append(line)
    return "\n".join(lines) if lines else "(aucun fait personnel connu)"


def _known_context_for_plan(store: Any, plan: dict[str, Any], limit: int = 24) -> str:
    """Charge d'abord le contexte réellement utile aux références non résolues.

    Exemple : pour `ma copine`, on demande prioritairement les relations
    `relation_to_user` plutôt que les 24 derniers souvenirs sans rapport.
    """
    targeted: list[str] = []
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    relations = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for entry in item.get("unresolved", []) if isinstance(item.get("unresolved"), list) else []:
            if not isinstance(entry, dict):
                continue
            if normalize(entry.get("reason", "")) == "relation to user":
                relation = normalize(entry.get("relation", ""))
                if relation:
                    relations.add(relation)
    if relations:
        try:
            payload = store.query(kinds=["relation"], predicate="relation_to_user", limit=50)
            for fact in payload.get("facts", []):
                value = normalize(fact.get("value", ""))
                if value in relations:
                    targeted.append(
                        f"FAIT: {fact.get('subject')} | {fact.get('predicate')} | {fact.get('value')}"
                    )
        except Exception:
            pass
    if targeted:
        return "\n".join(targeted[:limit])
    return _known_context(store, limit)


def _question(plan: dict[str, Any], fallback: str) -> str:
    clarification = plan.get("clarification")
    if isinstance(clarification, dict):
        value = clean(clarification.get("question", ""))
        if value:
            return value
    return fallback


def _safe_entities(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        name = clean(item.get("name", ""))
        if not name:
            continue
        entity_type = normalize(item.get("type", "person")) or "person"
        if entity_type not in {"person", "place", "project", "organization", "object"}:
            entity_type = "object"
        role = normalize(item.get("role", "related")) or "related"
        result.append({"type": entity_type, "name": name, "role": role})
    return result


def _time_payload(
    item: dict[str, Any],
    *,
    source_text: str,
    reference: datetime,
    timezone: str,
) -> tuple[dict[str, Any], str]:
    kind = normalize(item.get("kind", ""))
    expression = clean(item.get("time_expression", ""))
    payload: dict[str, Any] = {"time_expression": expression}
    if kind in FACT_KINDS or kind in {"note"}:
        return payload, ""

    prefer = "past" if kind in {"action", "mood"} else "future"
    resolved = None
    if expression:
        resolved = resolve_temporal_expression(
            expression,
            reference=reference,
            timezone=timezone,
            prefer=prefer,
            clock_source=source_text,
        )

    if kind == "action":
        resolved = resolved or reference
        payload.update(
            completed_at=resolved.isoformat(),
            date_precision="exact" if resolved.hour != 12 or resolved.minute else "day",
        )
    elif kind == "mood":
        # Mood stays logged; keep its day when explicitly dated.
        if resolved:
            payload.update(start_at=resolved.isoformat(), date_precision="day")
    elif kind == "task":
        if resolved:
            payload.update(due_at=resolved.isoformat(), date_precision="day")
    elif kind in {"appointment", "event"}:
        if not resolved:
            status = normalize(item.get("status", ""))
            # Un événement constaté sans date explicite est rattaché au moment où
            # Romain le raconte. Un rendez-vous / événement futur reste daté explicitement.
            if kind == "event" and status in {"logged", "done", ""}:
                resolved = reference
            else:
                return payload, "Quelle date dois-je retenir pour ce rendez-vous ou cet événement ?"
        payload.update(
            start_at=resolved.isoformat(),
            date_precision="exact" if resolved.hour != 12 or resolved.minute else "day",
        )
    return payload, ""


def _capture_item_payload(
    item: dict[str, Any],
    *,
    source_text: str,
    reference: datetime,
    timezone: str,
    threshold: float,
) -> tuple[dict[str, Any] | None, str]:
    kind = normalize(item.get("kind", ""))
    if kind not in KINDS:
        return None, "Je n'ai pas compris quel type d'information tu veux que je retienne."

    # V11.6: a model-generated confidence score is metadata only.
    # Required semantic fields below decide whether the item is safe to store.
    confidence = _metadata_confidence(item.get("confidence"), fallback=0.95)

    title = clean(item.get("title", ""))
    subject = clean(item.get("subject", ""))
    predicate = clean(item.get("predicate", ""))
    value = clean(item.get("value", ""))

    if kind in FACT_KINDS:
        if not subject:
            subject = "user"
        if kind == "relation" and not predicate:
            predicate = "relation_to_user"
        if not predicate or not value:
            return None, "Quelle information précise dois-je retenir ?"
        title = title or f"{subject} {predicate} {value}"
    elif not title:
        return None, "Qu'est-ce que tu veux que je retienne exactement ?"

    temporal, temporal_question = _time_payload(
        item,
        source_text=source_text,
        reference=reference,
        timezone=timezone,
    )
    if temporal_question:
        return None, temporal_question

    status = normalize(item.get("status", ""))
    if status and status not in STATUSES:
        status = ""

    semantic = {
        key: clean(item.get(key, ""))
        for key in ("actor", "verb", "object", "destination")
        if clean(item.get(key, ""))
    }
    if isinstance(item.get("details"), dict):
        semantic["details"] = {clean(k): clean(v) if not isinstance(v, (dict, list)) else v for k, v in item["details"].items()}
    if isinstance(item.get("keywords"), list):
        semantic["keywords"] = [clean(value) for value in item["keywords"] if clean(value)]
    semantic["extraction_confidence"] = confidence
    semantic["extractor"] = "utility_model"

    payload: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "source_text": clean(source_text),
        "confidence": confidence,
        "inferred": bool(item.get("inferred", False)),
        "entities": _safe_entities(item.get("entities")),
        "metadata": {"semantic_intake": semantic},
        **temporal,
    }
    if status:
        payload["status"] = status
    if kind in FACT_KINDS:
        payload.update(subject=subject, predicate=predicate, value=value)
    return payload, ""


def _compact_result(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    result: dict[str, Any] = {
        "found": payload.get("found", 0),
        "count": payload.get("count"),
        "records": [],
        "facts": [],
    }
    for item in payload.get("records", [])[:20]:
        result["records"].append(
            {
                "kind": item.get("kind"),
                "title": item.get("title"),
                "status": item.get("status"),
                "start_at": item.get("start_at"),
                "due_at": item.get("due_at"),
                "completed_at": item.get("completed_at"),
                "entities": [
                    {
                        "name": ent.get("canonical_name"),
                        "type": ent.get("entity_type"),
                        "role": ent.get("role"),
                    }
                    for ent in item.get("entities", [])
                ],
            }
        )
    for fact in payload.get("facts", [])[:20]:
        result["facts"].append(
            {
                "kind": fact.get("fact_kind"),
                "subject": fact.get("subject"),
                "predicate": fact.get("predicate"),
                "value": fact.get("value"),
            }
        )
    if result.get("count") is None:
        result.pop("count", None)
    return result


def _query_semantic_spec(plan: dict[str, Any]) -> dict[str, Any]:
    query = plan.get("query") if isinstance(plan.get("query"), dict) else {}
    semantic = query.get("semantic") if isinstance(query.get("semantic"), dict) else {}
    if not semantic:
        return {}
    return {
        "actor": clean(semantic.get("actor", "")),
        "verb": clean(semantic.get("verb", "")),
        "object": clean(semantic.get("object", "")),
        "destination": clean(semantic.get("destination", "")),
        "concepts": [clean(x) for x in semantic.get("concepts", []) if clean(x)] if isinstance(semantic.get("concepts"), list) else [],
        "question_type": normalize(semantic.get("question_type", "list")) or "list",
        "order": normalize(semantic.get("order", "all")) or "all",
        "limit": max(1, min(100, int(semantic.get("limit", 20) or 20))),
    }


def _semantic_query_needed(plan: dict[str, Any]) -> bool:
    spec = _query_semantic_spec(plan)
    if not spec:
        return False
    return bool(spec.get("verb") or spec.get("object") or spec.get("destination") or spec.get("concepts"))


def _memory_moment(record: dict[str, Any]) -> str:
    return clean(record.get("completed_at") or record.get("start_at") or record.get("due_at") or record.get("created_at") or "")


def _candidate_memory_payload(records: list[dict[str, Any]], limit: int = 100) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for record in records[:limit]:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        semantic = metadata.get("semantic_intake") if isinstance(metadata.get("semantic_intake"), dict) else {}
        candidates.append({
            "id": record.get("id"),
            "kind": record.get("kind"),
            "title": record.get("title"),
            "source_text": record.get("source_text"),
            "status": record.get("status"),
            "occurrences": record.get("occurrences", 1),
            "completed_at": record.get("completed_at"),
            "start_at": record.get("start_at"),
            "due_at": record.get("due_at"),
            "semantic": semantic,
            "entities": [
                {"name": e.get("canonical_name"), "type": e.get("entity_type"), "role": e.get("role")}
                for e in (record.get("entities") or []) if isinstance(e, dict)
            ],
        })
    return candidates


def _query_match_prompt(plan: dict[str, Any], records: list[dict[str, Any]]) -> str:
    return (
        "INTENTION_RECHERCHE:\n"
        + json.dumps(_query_semantic_spec(plan), ensure_ascii=False, default=str)
        + "\n\nSOUVENIRS_CANDIDATS:\n"
        + json.dumps(_candidate_memory_payload(records), ensure_ascii=False, default=str)
    )


def _apply_semantic_matches(
    result: dict[str, Any], plan: dict[str, Any], match: dict[str, Any] | None
) -> dict[str, Any]:
    output = dict(result or {})
    records = list(output.get("records") or [])
    if isinstance(match, dict):
        ids = [clean(x) for x in match.get("record_ids", []) if clean(x)] if isinstance(match.get("record_ids"), list) else []
        if ids:
            wanted = set(ids)
            records = [record for record in records if clean(record.get("id")) in wanted]
        else:
            records = []

    spec = _query_semantic_spec(plan)
    order = spec.get("order", "all")
    reverse = order != "earliest"
    if order in {"latest", "earliest"}:
        records.sort(key=_memory_moment, reverse=reverse)
    limit = int(spec.get("limit", 20) or 20)
    records = records[:limit]
    output["records"] = records
    output["found"] = len(records) + len(output.get("facts") or [])
    query = plan.get("query") if isinstance(plan.get("query"), dict) else {}
    if normalize(query.get("aggregate", "list")) == "count":
        output["count"] = sum(max(1, int(record.get("occurrences", 1) or 1)) for record in records) + len(output.get("facts") or [])
    output["semantic_match"] = {
        "used": True,
        "order": order,
        "limit": limit,
        "selected_ids": [record.get("id") for record in records],
    }
    return output


def _query_payload(
    plan: dict[str, Any],
    *,
    reference: datetime,
    timezone: str,
    context_id: str,
) -> tuple[dict[str, Any], str]:
    query = plan.get("query") if isinstance(plan.get("query"), dict) else {}
    aggregate = normalize(query.get("aggregate", "list")) or "list"
    if aggregate not in VALID_AGGREGATES:
        aggregate = "list"

    semantic = query.get("semantic") if isinstance(query.get("semantic"), dict) else {}
    semantic_search = bool(semantic and (clean(semantic.get("verb", "")) or clean(semantic.get("object", "")) or clean(semantic.get("destination", "")) or semantic.get("concepts")))
    payload: dict[str, Any] = {
        # En recherche sémantique, on récupère large puis Qwen matche les souvenirs.
        # Le filtre texte littéral du store serait trop fragile (lavé/laver, vu/voir...).
        "text": "" if semantic_search else clean(query.get("text", "")),
        "kinds": [normalize(item) for item in query.get("kinds", []) if normalize(item)],
        "statuses": [normalize(item) for item in query.get("statuses", []) if normalize(item)],
        "subject": clean(query.get("subject", "")),
        "predicate": clean(query.get("predicate", "")),
        "entity": clean(query.get("entity", "")),
        "entity_type": normalize(query.get("entity_type", "")),
        "aggregate": aggregate,
        "follow_up": bool(query.get("follow_up", False)),
        "context_id": context_id,
    }

    date_expression = clean(query.get("date_expression", ""))
    start_expression = clean(query.get("start_expression", ""))
    end_expression = clean(query.get("end_expression", ""))
    if date_expression:
        start, end = day_expression_to_iso_bounds(
            date_expression, reference=reference, timezone=timezone, prefer="past"
        )
        if start is None:
            return payload, f"Je n'arrive pas à déterminer la période « {date_expression} ». Tu peux préciser ?"
        payload.update(start=start, end=end)
    else:
        if start_expression:
            start, _ = day_expression_to_iso_bounds(
                start_expression, reference=reference, timezone=timezone, prefer="past"
            )
            if start is None:
                return payload, f"Je n'arrive pas à déterminer le début « {start_expression} ». Tu peux préciser ?"
            payload["start"] = start
        if end_expression:
            _, end = day_expression_to_iso_bounds(
                end_expression, reference=reference, timezone=timezone, prefer="past"
            )
            if end is None:
                return payload, f"Je n'arrive pas à déterminer la fin « {end_expression} ». Tu peux préciser ?"
            payload["end"] = end
    return payload, ""


def _forget_guard(source_text: str) -> bool:
    text = normalize(source_text)
    markers = (
        "oublie", "oublier", "supprime", "supprimer", "efface", "effacer",
        "ne retiens plus", "retire de ta memoire", "enleve de ta memoire",
    )
    return any(marker in text for marker in markers)


def _render_prompt_context(
    *,
    status: str,
    saved: list[dict[str, Any]],
    query_result: dict[str, Any] | None,
    clarification: str,
    operation_result: dict[str, Any] | None = None,
) -> str:
    data = {
        "status": status,
        "saved": [
            {
                "operation": item.get("operation"),
                "kind": (item.get("record") or {}).get("kind"),
                "title": (item.get("record") or {}).get("title"),
                "completed_at": (item.get("record") or {}).get("completed_at"),
                "due_at": (item.get("record") or {}).get("due_at"),
                "start_at": (item.get("record") or {}).get("start_at"),
                "fact": {
                    "subject": (item.get("fact") or {}).get("subject"),
                    "predicate": (item.get("fact") or {}).get("predicate"),
                    "value": (item.get("fact") or {}).get("value"),
                } if item.get("fact") else None,
            }
            for item in saved
        ],
        "query_result": _compact_result(query_result),
        "operation_result": operation_result,
        "clarification_question": clarification,
    }
    rules = [
        "AGENT-OS INTAKE RESULT — source structurée prioritaire pour ce tour.",
        json.dumps(data, ensure_ascii=False, default=str),
        "Règles de réponse :",
        "- Ne te présente pas à nouveau et ne répète pas une formule d'accueil.",
        "- N'invente ni promenade, ni activité, ni détail absent.",
        "- Si status=clarification_required, pose uniquement la question de clarification, naturellement et brièvement.",
        "- Si status=captured, la mémoire est déjà écrite : n'appelle PAS life_capture une seconde fois.",
        "- Si status=query_ready, réponds à partir de query_result et n'appelle PAS life_query une seconde fois.",
        "- Si status=updated ou forgotten, l'opération est déjà faite : confirme simplement.",
        "- Si status=none ou extractor_unavailable, poursuis la conversation normale.",
    ]
    return "\n".join(rules)




def _join_french(items: list[str]) -> str:
    values = [clean(item) for item in items if clean(item)]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} et {values[1]}"
    return ", ".join(values[:-1]) + f" et {values[-1]}"


def _time_prefix(expression: str) -> str:
    value = clean(expression)
    if not value:
        return ""
    normalized = normalize(value)
    if normalized in {"aujourd hui", "hier", "demain"}:
        return value
    if normalized.startswith(("ce ", "cet ", "cette ", "ces ")):
        return value
    return value


def _fact_clause(saved_item: dict[str, Any]) -> str:
    record = saved_item.get("record") or {}
    fact = saved_item.get("fact") or {}
    subject = clean(fact.get("subject", ""))
    predicate = normalize(fact.get("predicate", ""))
    value = clean(fact.get("value", ""))
    title = clean(record.get("title", ""))

    if predicate == "relation to user" and subject and value:
        feminine = {"copine", "compagne", "femme", "mere", "mère", "soeur", "sœur", "fille"}
        article = "ta" if normalize(value) in {normalize(x) for x in feminine} else "ton"
        return f"{subject} est {article} {value}"
    if predicate == "name" and normalize(subject) == "user" and value:
        return f"tu t'appelles {value}"
    if predicate == "home location" and normalize(subject) == "user" and value:
        return f"tu habites à {value}"
    if predicate == "middle name" and normalize(subject) == "user" and value:
        return f"ton deuxième prénom est {value}"
    if predicate == "workplace" and normalize(subject) == "user" and value:
        return f"tu travailles à {value}"
    if title:
        return title
    if subject and value:
        return f"{subject} : {value}"
    return ""


def _user_to_assistant_perspective(text: str) -> str:
    """Adapte les possessifs de Romain uniquement au moment de la réponse.

    La mémoire conserve le texte utilisateur original. Exemple :
    ``lavé ma voiture`` reste stocké tel quel, mais Paul dit
    ``tu as lavé ta voiture``.
    """
    value = clean(text)
    if not value:
        return value
    for pattern, replacement in (
        (r"\bmes\b", "tes"),
        (r"\bmon\b", "ton"),
        (r"\bma\b", "ta"),
    ):
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value


def _capture_direct_reply(saved: list[dict[str, Any]]) -> str:
    records = [item.get("record") or {} for item in saved if isinstance(item, dict)]
    if not records:
        return "D'accord, c'est retenu."

    # Tous les faits/relation/préférences : confirmation en deuxième personne.
    # C'est une barrière d'identité : Paul ne reformule jamais un fait de Romain
    # avec « je ».
    if records and all(record.get("kind") in FACT_KINDS for record in records):
        clauses = [_fact_clause(item) for item in saved]
        clauses = [item for item in clauses if item]
        if not clauses:
            return "D'accord, c'est retenu."
        if len(clauses) == 1:
            return f"D'accord, je retiens que {clauses[0]}."
        return "D'accord, je retiens que " + " et que ".join(clauses) + "."

    actions = [record for record in records if record.get("kind") == "action"]
    if actions and len(actions) == len(records):
        titles = [_user_to_assistant_perspective(record.get("title", "")) for record in actions]
        expressions = [clean(record.get("time_expression", "")) for record in actions]
        expression = expressions[0] if expressions and all(x == expressions[0] for x in expressions) else ""

        split = [title.split(" ", 1) for title in titles if title]
        if len(split) == len(titles) and split and all(parts[0] == split[0][0] and len(parts) == 2 for parts in split):
            verb = split[0][0]
            objects = [parts[1] for parts in split]
            body = f"tu as {verb} {_join_french(objects)}"
        else:
            body = "tu as " + _join_french(titles)

        when = _time_prefix(expression)
        if when:
            if normalize(when) == "aujourd hui":
                return f"D'accord, je retiens qu'aujourd'hui {body}."
            return f"D'accord, je retiens que {body} {when}."
        return f"D'accord, je retiens que {body}."

    titles = [_user_to_assistant_perspective(record.get("title", "")) for record in records]
    return f"D'accord, je retiens : {_join_french(titles)}."


MONTHS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _format_memory_date(record: dict[str, Any]) -> str:
    raw = _memory_moment(record)
    if not raw:
        return "une date inconnue"
    try:
        dt = datetime.fromisoformat(raw)
        return f"le {dt.day} {MONTHS_FR[dt.month]} {dt.year}"
    except Exception:
        return raw[:10] or "une date inconnue"


def _query_semantic_reply(outcome: IntakeOutcome) -> str | None:
    result = outcome.query_result or {}
    records = list(result.get("records") or [])
    query = outcome.raw_plan.get("query") if isinstance(outcome.raw_plan.get("query"), dict) else {}
    semantic = query.get("semantic") if isinstance(query.get("semantic"), dict) else {}
    if not semantic:
        return None
    question_type = normalize(semantic.get("question_type", "list")) or "list"
    order = normalize(semantic.get("order", "all")) or "all"
    if question_type == "when" and order in {"latest", "earliest"}:
        if not records:
            return "Je n'ai pas retrouvé de souvenir correspondant dans ma mémoire personnelle."
        record = records[0]
        title = _user_to_assistant_perspective(record.get("title", ""))
        if order == "latest":
            return f"La dernière fois enregistrée, c'était {_format_memory_date(record)} : tu as {title}." if record.get("kind") == "action" else f"La dernière occurrence enregistrée date du {_format_memory_date(record).removeprefix('le ')} : {title}."
        return f"La première fois que j'ai en mémoire, c'était {_format_memory_date(record)} : {title}."
    return None


def _query_direct_reply(outcome: IntakeOutcome) -> str:
    result = outcome.query_result or {}
    records = list(result.get("records") or [])
    facts = list(result.get("facts") or [])
    plan_query = outcome.raw_plan.get("query") if isinstance(outcome.raw_plan.get("query"), dict) else {}
    aggregate = normalize(plan_query.get("aggregate", "list")) or "list"
    date_expression = clean(plan_query.get("date_expression", ""))

    if aggregate == "count":
        count = int(result.get("count", result.get("found", 0)) or 0)
        if date_expression:
            return f"J'en trouve {count} pour {date_expression}."
        return f"J'en trouve {count}."

    semantic_reply = _query_semantic_reply(outcome)
    if semantic_reply:
        return semantic_reply

    if not records and not facts:
        if date_expression:
            return f"Je n'ai rien enregistré pour {date_expression}."
        return "Je n'ai pas cette information dans ma mémoire personnelle."

    # Actions : priorité à une réponse conversationnelle et factuelle.
    if records and all(item.get("kind") == "action" for item in records):
        titles = [_user_to_assistant_perspective(item.get("title", "")) for item in records]
        split = [title.split(" ", 1) for title in titles if title]
        if len(split) == len(titles) and split and all(parts[0] == split[0][0] and len(parts) == 2 for parts in split):
            verb = split[0][0]
            body = f"tu as {verb} {_join_french([parts[1] for parts in split])}"
        else:
            body = "tu as " + _join_french(titles)
        if date_expression:
            if normalize(date_expression) == "aujourd hui":
                return f"Aujourd'hui, {body}."
            return f"{date_expression[:1].upper() + date_expression[1:]}, {body}."
        return f"J'ai en mémoire que {body}."

    if facts and not records:
        if len(facts) == 1:
            fact = facts[0]
            subject = clean(fact.get("subject", ""))
            predicate = normalize(fact.get("predicate", ""))
            value = clean(fact.get("value", ""))
            if predicate == "relation to user" and subject and value:
                feminine = {"copine", "compagne", "femme", "mere", "mère", "soeur", "sœur", "fille"}
                article = "ta" if normalize(value) in {normalize(x) for x in feminine} else "ton"
                return f"{subject} est {article} {value}."
            if predicate == "middle name" and normalize(subject) == "user" and value:
                return f"Ton deuxième prénom est {value}."
            if predicate == "name" and normalize(subject) == "user" and value:
                return f"Tu t'appelles {value}."
            if predicate == "home location" and normalize(subject) == "user" and value:
                return f"Tu habites à {value}."
            return f"J'ai en mémoire : {subject} — {fact.get('predicate')} — {value}."

    labels = [clean(item.get("title", "")) for item in records]
    labels += [f"{clean(item.get('subject', ''))}: {clean(item.get('value', ''))}" for item in facts]
    return "J'ai en mémoire : " + _join_french(labels) + "."


def render_direct_reply(outcome: IntakeOutcome) -> str | None:
    """Réponse contrôlée pour les tours déjà entièrement traités par l'intake.

    Le LLM principal n'a plus à reformuler ces résultats : cela élimine les
    commentaires génériques/hallucinés tout en gardant Qwen pour la compréhension.
    """
    if outcome.status == "clarification_required":
        return clean(outcome.clarification_question) or "Tu peux préciser ?"
    if outcome.status == "captured":
        return _capture_direct_reply(outcome.saved)
    if outcome.status == "query_ready":
        return _query_direct_reply(outcome)
    if outcome.status == "updated":
        operation = (outcome.operation_result or {}).get("operation")
        if operation == "not_found":
            return "Je n'ai pas trouvé l'élément à modifier."
        return "D'accord, c'est mis à jour."
    if outcome.status == "forgotten":
        count = int((outcome.operation_result or {}).get("count", 0) or 0)
        if count == 0:
            return "Je n'ai pas trouvé ce souvenir dans la mémoire personnelle."
        return "D'accord, je ne le retiendrai plus dans la mémoire personnelle."
    return None


async def _call_json_model(
    caller: Callable[..., Awaitable[str]],
    *,
    system: str,
    prompt: str,
) -> tuple[dict[str, Any] | None, str]:
    try:
        raw = await caller(system=system, message=prompt)
    except Exception as exc:
        return None, f"MODEL_ERROR: {exc}"
    return _extract_json_object(raw), str(raw or "")




def _looks_like_choice_placeholder(value: Any) -> bool:
    """Detect schema examples accidentally copied by a small local model."""
    raw = clean(value)
    if not raw:
        return False
    if "|" in raw:
        return True
    normalized = normalize(raw)
    return normalized in {
        "user ou nom explicite",
        "none complete still ambiguous abandon",
        "person place project organization object",
        "actor object destination location related",
        "done pending scheduled logged",
        "complete cancel archive reschedule update",
        "list count",
    }


def _repair_obvious_capture_structure(plan: dict[str, Any]) -> dict[str, Any]:
    """Repair only conclusions already present in Qwen's structured fields.

    This never parses the user's sentence with regexes. It only fixes a malformed
    enum when the rest of the model output already proves the category.
    """
    result = dict(plan)
    items = result.get("items") if isinstance(result.get("items"), list) else []
    repaired: list[dict[str, Any]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        kind = normalize(item.get("kind", ""))
        status = normalize(item.get("status", ""))
        subject = clean(item.get("subject", ""))
        predicate = normalize(item.get("predicate", ""))
        value = clean(item.get("value", ""))
        actor = clean(item.get("actor", ""))
        verb = clean(item.get("verb", ""))
        obj = clean(item.get("object", ""))
        title = clean(item.get("title", ""))

        if kind not in KINDS:
            if subject and predicate and value:
                kind = "relation" if predicate == "relation to user" else "fact"
                item["kind"] = kind
            elif status == "done" and (actor or verb or obj or title):
                kind = "action"
                item["kind"] = kind
            elif status == "pending" and (actor or verb or obj or title):
                kind = "task"
                item["kind"] = kind

        if _looks_like_choice_placeholder(item.get("status", "")):
            item.pop("status", None)
        if _looks_like_choice_placeholder(item.get("actor", "")):
            item.pop("actor", None)
        if _looks_like_choice_placeholder(item.get("pending_resolution", "")):
            item.pop("pending_resolution", None)

        repaired.append(item)

    result["items"] = repaired
    if _looks_like_choice_placeholder(result.get("pending_resolution", "")):
        result.pop("pending_resolution", None)
    return result


def _capture_plan_problem(plan: dict[str, Any]) -> str:
    clarification = plan.get("clarification")
    if isinstance(clarification, dict) and bool(clarification.get("needed")):
        return ""

    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    if not items:
        return "aucun item concret n'a été extrait"

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            return f"item {index} n'est pas un objet JSON"
        kind = normalize(item.get("kind", ""))
        if kind not in KINDS:
            return f"item {index}: kind invalide ou placeholder ({clean(item.get('kind', ''))})"
        if _looks_like_choice_placeholder(item.get("status", "")):
            return f"item {index}: status recopié depuis le schéma"
        if _looks_like_choice_placeholder(item.get("actor", "")):
            return f"item {index}: actor recopié depuis le schéma"

        if kind in FACT_KINDS:
            if not clean(item.get("predicate", "")) or not clean(item.get("value", "")):
                return f"item {index}: fait sans predicate/value concret"
        elif not clean(item.get("title", "")):
            return f"item {index}: title manquant"

    action_items = [item for item in items if isinstance(item, dict) and normalize(item.get("kind", "")) == "action"]
    if len(action_items) == 1:
        entities = action_items[0].get("entities") if isinstance(action_items[0].get("entities"), list) else []
        object_entities = [
            ent for ent in entities
            if isinstance(ent, dict)
            and normalize(ent.get("role", "")) == "object"
            and clean(ent.get("name", ""))
        ]
        if len(object_entities) >= 2:
            return "plusieurs objets d'action ont été regroupés dans un seul item"
    return ""


def _plan_problem(route: str, plan: dict[str, Any]) -> str:
    if route == "capture":
        return _capture_plan_problem(plan)
    if route == "query":
        query = plan.get("query") if isinstance(plan.get("query"), dict) else None
        if query is None:
            return "objet query manquant"
        aggregate = normalize(query.get("aggregate", "list")) or "list"
        if aggregate not in VALID_AGGREGATES or _looks_like_choice_placeholder(query.get("aggregate", "")):
            return "aggregate invalide ou placeholder"
        for kind in query.get("kinds", []) if isinstance(query.get("kinds"), list) else []:
            if normalize(kind) not in KINDS:
                return f"kind de requête invalide ({clean(kind)})"
        return ""
    if route == "update":
        update = plan.get("update") if isinstance(plan.get("update"), dict) else None
        if update is None:
            return "objet update manquant"
        action = normalize(update.get("action", ""))
        if action not in {"complete", "cancel", "archive", "reschedule", "update"}:
            return "action de mise à jour invalide ou placeholder"
        return ""
    if route == "forget":
        forget = plan.get("forget") if isinstance(plan.get("forget"), dict) else None
        if forget is None:
            return "objet forget manquant"
        if not clean(forget.get("query", "")) and not (forget.get("record_ids") or []):
            return "cible d'oubli manquante"
        return ""
    return ""


def _retry_prompt(prompt: str, *, route: str, problem: str, previous_raw: str) -> str:
    return (
        prompt
        + "\n\nCORRECTION_OBLIGATOIRE:\n"
        + f"La sortie précédente pour la route {route} est invalide : {problem}.\n"
        + "Tu as probablement recopié un exemple de schéma au lieu de choisir des valeurs concrètes.\n"
        + "Repars du MESSAGE_UTILISATEUR original. Ne recopie aucune liste de choix dans un champ.\n"
        + "Pour une liste d'actions, renvoie un item distinct par objet.\n"
        + "Si le message est clair, extrais-le : ne demande pas une clarification artificielle.\n"
        + "SORTIE_PRECEDENTE_INVALIDE:\n"
        + str(previous_raw or "")[:1800]
    )


def _current_turn_prompt(
    *,
    source_text: str,
    reference: datetime,
    timezone: str,
    pending: dict[str, Any] | None = None,
) -> str:
    """Prompt d'interprétation isolé du tour courant.

    Aucune mémoire connue ni historique conversationnel n'entre dans le routeur
    ou l'extracteur primaire. C'est la barrière principale contre la contamination
    d'un nouveau message par un ancien fait ou une ancienne requête.
    """
    return (
        f"REFERENCE_LOCALE: {reference.isoformat()} ({timezone})\n"
        f"MESSAGE_UTILISATEUR: {source_text}\n\n"
        f"PENDING_CLARIFICATION:\n{json.dumps(pending or {}, ensure_ascii=False, default=str)}\n"
    )


def _resolution_prompt(
    *,
    source_text: str,
    plan: dict[str, Any],
    reference: datetime,
    timezone: str,
    history: str,
    known: str,
    pending: dict[str, Any] | None,
    history_limit: int,
) -> str:
    return (
        f"REFERENCE_LOCALE: {reference.isoformat()} ({timezone})\n"
        f"MESSAGE_UTILISATEUR: {source_text}\n\n"
        "PLAN_COURANT:\n"
        + json.dumps(plan, ensure_ascii=False, default=str)
        + "\n\nMEMOIRE_UTILE:\n"
        + str(known or "(aucune)")
        + "\n\nCONTEXTE_RECENT:\n"
        + str(history or "")[-history_limit:]
        + "\n\nPENDING_CLARIFICATION:\n"
        + json.dumps(pending or {}, ensure_ascii=False, default=str)
        + "\n"
    )


def _unresolved_fields(item: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    value = item.get("unresolved")
    if not isinstance(value, list):
        return result
    for entry in value:
        if not isinstance(entry, dict):
            continue
        field = clean(entry.get("field", ""))
        if field and not clean(item.get(field, "")):
            result.add(field)
    return result


def _repair_explicit_entity_resolution(plan: dict[str, Any]) -> dict[str, Any]:
    """Répare un `unresolved` redondant à partir de la sortie structurée de Qwen.

    On ne reparcourt pas la phrase utilisateur avec des regex. Si Qwen a déjà créé
    une entité explicite avec le bon rôle (ex. Coralie[object]), Python peut remplir
    le champ correspondant sans second appel ni clarification.
    """
    result = dict(plan)
    items = [dict(item) if isinstance(item, dict) else item for item in (result.get("items") or [])]
    role_to_field = {"actor": "actor", "object": "object", "destination": "destination", "location": "destination"}
    for item in items:
        if not isinstance(item, dict):
            continue
        unresolved = item.get("unresolved") if isinstance(item.get("unresolved"), list) else []
        if not unresolved:
            continue
        entities = item.get("entities") if isinstance(item.get("entities"), list) else []
        by_role: dict[str, list[str]] = {}
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            role = normalize(entity.get("role", ""))
            name = clean(entity.get("name", ""))
            if role and name:
                by_role.setdefault(role, []).append(name)
        kept = []
        for entry in unresolved:
            if not isinstance(entry, dict):
                continue
            field = clean(entry.get("field", ""))
            if not field:
                continue
            if clean(item.get(field, "")):
                continue
            candidates = by_role.get(field, [])
            if not candidates and field == "destination":
                candidates = by_role.get("location", [])
            if len(candidates) == 1:
                item[field] = candidates[0]
                continue
            reason = normalize(entry.get("reason", ""))
            mention = clean(entry.get("mention", ""))
            if mention and reason in {"named entity", "explicit name", "explicit", "person name", "place name"}:
                item[field] = mention
                current_entities = item.get("entities") if isinstance(item.get("entities"), list) else []
                entity_type = "place" if field == "destination" else ("person" if reason in {"named entity", "person name", "explicit name"} else "object")
                candidate_entity = {"type": entity_type, "name": mention, "role": field}
                if candidate_entity not in current_entities:
                    current_entities.append(candidate_entity)
                item["entities"] = current_entities
                continue
            kept.append(entry)
        if kept:
            item["unresolved"] = kept
        else:
            item.pop("unresolved", None)
    result["items"] = items
    return result


def _plan_needs_resolution(plan: dict[str, Any]) -> bool:
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    return any(isinstance(item, dict) and _unresolved_fields(item) for item in items)


def _apply_resolution_patches(
    plan: dict[str, Any], resolution: dict[str, Any]
) -> dict[str, Any]:
    """Applique uniquement des patches sur des champs explicitement non résolus.

    Le résolveur n'a jamais le droit d'ajouter un nouvel item ou d'écraser une
    information explicite extraite du message courant.
    """
    result = dict(plan)
    items = [dict(item) if isinstance(item, dict) else item for item in (result.get("items") or [])]
    patches = resolution.get("patches") if isinstance(resolution.get("patches"), list) else []
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        try:
            index = int(patch.get("item_index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(items) or not isinstance(items[index], dict):
            continue
        item = items[index]
        allowed = _unresolved_fields(item)
        if not allowed:
            continue
        fields = patch.get("fields") if isinstance(patch.get("fields"), dict) else {}
        unresolved_entries = item.get("unresolved") if isinstance(item.get("unresolved"), list) else []
        mentions_by_field = {
            clean(entry.get("field", "")): clean(entry.get("mention", ""))
            for entry in unresolved_entries if isinstance(entry, dict)
        }
        resolved_now: set[str] = set()
        for field, value in fields.items():
            field = clean(field)
            if field not in allowed:
                continue
            value = clean(value)
            if not value:
                continue
            item[field] = value
            mention = mentions_by_field.get(field, "")
            title = clean(item.get("title", ""))
            if mention and title and re.search(re.escape(mention), title, flags=re.I):
                item["title"] = re.sub(re.escape(mention), value, title, count=1, flags=re.I)
            resolved_now.add(field)

        entities = patch.get("entities") if isinstance(patch.get("entities"), list) else []
        if entities:
            current = item.get("entities") if isinstance(item.get("entities"), list) else []
            current = [entry for entry in current if isinstance(entry, dict)]
            for entity in entities:
                if not isinstance(entity, dict) or not clean(entity.get("name", "")):
                    continue
                if entity not in current:
                    current.append(entity)
            item["entities"] = current

        unresolved = item.get("unresolved") if isinstance(item.get("unresolved"), list) else []
        item["unresolved"] = [
            entry for entry in unresolved
            if not (isinstance(entry, dict) and clean(entry.get("field", "")) in resolved_now)
        ]
        if not item["unresolved"]:
            item.pop("unresolved", None)
        if resolved_now:
            item["resolution"] = patch.get("resolution") or {"source": "context"}
        items[index] = item

    result["items"] = items
    remaining = any(isinstance(item, dict) and _unresolved_fields(item) for item in items)
    clarification = resolution.get("clarification") if isinstance(resolution.get("clarification"), dict) else None
    if remaining:
        if clarification:
            result["clarification"] = clarification
        elif not isinstance(result.get("clarification"), dict):
            result["clarification"] = {"needed": True, "question": "Tu peux préciser la référence ?"}
    else:
        result["clarification"] = None
    return result



def _all_memory_candidates(store: Any, limit: int = 100) -> list[dict[str, Any]]:
    """Retourne des souvenirs avec leur phrase source complète pour lever une ambiguïté."""
    try:
        payload = store.query(limit=limit)
    except Exception:
        return []

    records = list(payload.get("records") or [])
    result: list[dict[str, Any]] = []
    for record in records[:limit]:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        semantic = metadata.get("semantic_intake") if isinstance(metadata.get("semantic_intake"), dict) else {}
        result.append({
            "id": clean(record.get("id", "")),
            "kind": clean(record.get("kind", "")),
            "title": clean(record.get("title", "")),
            "source_text": clean(record.get("source_text", "")),
            "status": clean(record.get("status", "")),
            "completed_at": record.get("completed_at"),
            "start_at": record.get("start_at"),
            "due_at": record.get("due_at"),
            "semantic": semantic,
            "entities": [
                {
                    "name": clean(entity.get("canonical_name", "")),
                    "type": clean(entity.get("entity_type", "")),
                    "role": clean(entity.get("role", "")),
                }
                for entity in (record.get("entities") or [])
                if isinstance(entity, dict)
            ],
        })
    return result


def _ambiguity_match_prompt(
    source_text: str,
    plan: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    return (
        "MESSAGE_UTILISATEUR:\n" + clean(source_text)
        + "\n\nPLAN_COURANT:\n"
        + json.dumps(plan, ensure_ascii=False, default=str)
        + "\n\nSOUVENIRS_CANDIDATS:\n"
        + json.dumps(candidates, ensure_ascii=False, default=str)
    )


def _normalize_ambiguity_candidates(
    match: dict[str, Any] | None,
    memories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(match, dict):
        return []
    known = {clean(item.get("id", "")): item for item in memories if clean(item.get("id", ""))}
    output: list[dict[str, Any]] = []
    for raw in match.get("candidates", []) if isinstance(match.get("candidates"), list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            item_index = int(raw.get("item_index", -1))
        except (TypeError, ValueError):
            continue
        field = clean(raw.get("field", ""))
        value = clean(raw.get("value", ""))
        record_id = clean(raw.get("record_id", ""))
        try:
            confidence = float(raw.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        memory = known.get(record_id)
        if item_index < 0 or not field or not value or memory is None:
            continue
        output.append({
            "item_index": item_index,
            "field": field,
            "value": value,
            "record_id": record_id,
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": clean(raw.get("reason", "")),
            "source_text": clean(memory.get("source_text", "")),
            "title": clean(memory.get("title", "")),
        })
    output.sort(key=lambda item: item["confidence"], reverse=True)
    return output[:3]


def _candidate_question(candidates: list[dict[str, Any]], fallback: str) -> str:
    if not candidates:
        return fallback
    if len(candidates) == 1:
        candidate = candidates[0]
        source = candidate.get("source_text") or candidate.get("title")
        if source:
            return (
                f"Tu parles de {candidate['value']} ? "
                f"Je retrouve ce souvenir : « {source} »."
            )
        return f"Tu parles de {candidate['value']} ?"

    parts = []
    for index, candidate in enumerate(candidates[:3], start=1):
        source = candidate.get("source_text") or candidate.get("title")
        if source:
            parts.append(f"{index}) {candidate['value']} — « {source} »")
        else:
            parts.append(f"{index}) {candidate['value']}")
    return "J'ai trouvé plusieurs souvenirs possibles : " + " ; ".join(parts) + ". Lequel correspond ?"


def _apply_confirmed_candidate(plan: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    patch = {
        "item_index": candidate.get("item_index", 0),
        "fields": {clean(candidate.get("field", "")): clean(candidate.get("value", ""))},
        "entities": [],
        "resolution": {
            "source": "user_confirmed_memory_candidate",
            "record_id": clean(candidate.get("record_id", "")),
            "confidence": 1.0,
        },
    }
    field = clean(candidate.get("field", ""))
    value = clean(candidate.get("value", ""))
    if field in {"actor", "object"} and value:
        patch["entities"] = [{"type": "person", "name": value, "role": field}]
    elif field == "destination" and value:
        patch["entities"] = [{"type": "place", "name": value, "role": "destination"}]
    return _apply_resolution_patches(plan, {"patches": [patch], "clarification": None})


def _confirmation_prompt(pending: dict[str, Any], answer: str) -> str:
    return (
        "QUESTION_POSÉE:\n" + clean(pending.get("question", ""))
        + "\n\nCANDIDATS_PROPOSÉS:\n"
        + json.dumps(pending.get("candidates") or [], ensure_ascii=False, default=str)
        + "\n\nRÉPONSE_UTILISATEUR:\n" + clean(answer)
    )


def _persist_capture_plan(
    *,
    store: Any,
    plan: dict[str, Any],
    source_text: str,
    context_id: str,
    config: dict[str, Any],
    reference: datetime,
    timezone: str,
    confidence: float = 0.95,
) -> IntakeOutcome:
    """Persiste un plan de capture déjà compris/résolu, sans repasser par Qwen."""
    saved: list[dict[str, Any]] = []
    questions: list[str] = []
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if _clamp(item.get("confidence"), 0.0) <= 0.01:
            item["confidence"] = confidence
        payload, question = _capture_item_payload(
            item,
            source_text=source_text,
            reference=reference,
            timezone=timezone,
            threshold=_clamp(config.get("semantic_intake_confidence", 0.85), 0.85),
        )
        if question:
            questions.append(question)
            continue
        if payload is None:
            continue
        if payload.get("inferred") and not bool(config.get("allow_inferred_facts", False)):
            questions.append("Cette information semble déduite plutôt qu'explicite. Tu peux me la confirmer ?")
            continue
        try:
            saved.append(store.capture(context_id=context_id, **payload))
        except ValueError as exc:
            questions.append(str(exc))

    if questions:
        question = clean(questions[0])
        if context_id:
            _set_intake_state(
                store,
                context_id,
                {
                    "type": "clarification",
                    "original_message": source_text,
                    "question": question,
                    "partial_plan": plan,
                },
            )
        context = _render_prompt_context(
            status="clarification_required", saved=saved, query_result=None, clarification=question
        )
        return IntakeOutcome("clarification_required", context, plan, saved, clarification_question=question)

    if context_id:
        _clear_intake_state(store, context_id)
    context = _render_prompt_context(status="captured", saved=saved, query_result=None, clarification="")
    return IntakeOutcome("captured", context, plan, saved)



def _first_unresolved_target(plan: dict[str, Any]) -> tuple[int, str] | None:
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        fields = sorted(_unresolved_fields(item))
        if fields:
            return index, fields[0]
    return None


async def _search_ambiguity_candidates(
    *,
    caller: Callable[..., Awaitable[str]],
    store: Any,
    source_text: str,
    plan: dict[str, Any],
    limit: int = 100,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Cherche dans les phrases sources complètes sans résoudre silencieusement."""
    if not _plan_needs_resolution(plan):
        return plan, {"used": False, "candidate_count": 0, "proposals": []}

    memories = _all_memory_candidates(store, limit=limit)
    if not memories:
        return plan, {"used": True, "candidate_count": 0, "proposals": []}

    raw_match, raw = await _call_json_model(
        caller,
        system=AMBIGUITY_MATCHER_SYSTEM,
        prompt=_ambiguity_match_prompt(source_text, plan, memories),
    )
    proposals = _normalize_ambiguity_candidates(raw_match, memories)
    # Comme Romain devra confirmer, on peut garder un seuil modéré.
    proposals = [item for item in proposals if float(item.get("confidence", 0.0) or 0.0) >= 0.55][:3]

    output = dict(plan)
    if proposals:
        fallback = _question(output, "Tu peux préciser la référence ?")
        output["clarification"] = {
            "needed": True,
            "question": _candidate_question(proposals, fallback),
        }
        output["_ambiguity_candidates"] = proposals

    return output, {
        "used": True,
        "candidate_count": len(memories),
        "proposals": proposals,
        "raw": str(raw or "")[:1500],
    }



_GENERIC_REFERENCE_VALUES = {
    "quelqu un", "quelqu une", "une personne", "la personne", "personne",
    "quelque part", "un endroit", "cet endroit", "un lieu",
    "lui", "elle", "elles", "eux", "leur", "y", "la bas",
}


def _is_generic_reference_value(value: Any) -> bool:
    return normalize(clean(value)) in _GENERIC_REFERENCE_VALUES


def _reference_audit_needed(source_text: str, plan: dict[str, Any]) -> bool:
    """Détecte les tours où un pronom/déictique peut avoir été faussement 'résolu'."""
    raw = clean(source_text).casefold()
    normalized = normalize(source_text)
    markers = (
        "j'y", " j’y", " lui ", " elle ", " elles ", " eux ",
        " leur ", " là-bas", " la-bas", " cet endroit", " cette personne",
    )
    if any(marker in f" {raw} " for marker in markers):
        return True
    # `l'` n'est pronominal que dans une construction comme `je l'ai`,
    # `je l'emmène`, etc. Il ne faut surtout pas confondre avec `l'aéroport`.
    if re.search(r"\b(?:je|j|tu|il|elle|on|nous|vous|ils|elles)\s+l\s+\w+", normalized):
        return True
    if re.search(r"\bj\s+y\b|\b(?:lui|elle|elles|eux|leur)\b", normalized):
        return True
    for item in plan.get("items", []) if isinstance(plan.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        for field in ("actor", "object", "destination"):
            if _is_generic_reference_value(item.get(field, "")):
                return True
    return False


def _apply_reference_audit(plan: dict[str, Any], audit: dict[str, Any] | None) -> dict[str, Any]:
    """N'autorise l'auditeur qu'à corriger les champs de référence, jamais le sens du souvenir."""
    if not isinstance(audit, dict) or not isinstance(audit.get("items"), list):
        return plan

    result = dict(plan)
    original_items = result.get("items") if isinstance(result.get("items"), list) else []
    audited_items = audit.get("items")
    merged: list[Any] = []

    for index, original in enumerate(original_items):
        if not isinstance(original, dict):
            merged.append(original)
            continue
        item = dict(original)
        audited = audited_items[index] if index < len(audited_items) and isinstance(audited_items[index], dict) else {}

        for field in ("actor", "object", "destination"):
            old_value = clean(item.get(field, ""))
            new_value = clean(audited.get(field, ""))
            # Un champ explicite et concret ne peut pas être écrasé par l'auditeur.
            if old_value and not _is_generic_reference_value(old_value):
                continue
            if new_value and not _is_generic_reference_value(new_value):
                item[field] = new_value
            elif field in audited and (not new_value or _is_generic_reference_value(new_value)):
                item[field] = ""

        if isinstance(audited.get("unresolved"), list):
            cleaned = []
            for entry in audited["unresolved"]:
                if not isinstance(entry, dict):
                    continue
                field = clean(entry.get("field", ""))
                mention = clean(entry.get("mention", ""))
                reason = clean(entry.get("reason", ""))
                if field in {"actor", "object", "destination"} and mention:
                    cleaned.append({"field": field, "mention": mention, "reason": reason or "context_reference"})
            if cleaned:
                item["unresolved"] = cleaned
            else:
                item.pop("unresolved", None)

        # Si l'auditeur résout explicitement une référence avec un nom déjà présent
        # dans le même message, on peut reprendre ses entités.
        if isinstance(audited.get("entities"), list):
            current = item.get("entities") if isinstance(item.get("entities"), list) else []
            for entity in audited["entities"]:
                if isinstance(entity, dict) and clean(entity.get("name", "")) and entity not in current:
                    current.append(entity)
            if current:
                item["entities"] = current

        merged.append(item)

    result["items"] = merged
    return result


def _targeted_question_prompt(source_text: str, plan: dict[str, Any]) -> str:
    return (
        "MESSAGE_UTILISATEUR:\n" + clean(source_text)
        + "\n\nPLAN_COURANT:\n"
        + json.dumps(plan, ensure_ascii=False, default=str)
    )


def _fallback_targeted_question(plan: dict[str, Any]) -> str:
    target = _first_unresolved_target(plan)
    if not target:
        return "Quel détail manque pour que je puisse retenir ce souvenir correctement ?"
    item_index, field = target
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    item = items[item_index] if 0 <= item_index < len(items) and isinstance(items[item_index], dict) else {}
    if field == "destination":
        return "De quel endroit parles-tu ?"
    if field in {"actor", "object"}:
        return "De qui parles-tu ?"
    return "Quel détail manque ?"


async def _ensure_targeted_clarification(
    *,
    caller: Callable[..., Awaitable[str]],
    source_text: str,
    plan: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if not _plan_needs_resolution(plan):
        return plan, ""
    reply, raw = await _call_json_model(
        caller,
        system=TARGETED_CLARIFICATION_SYSTEM,
        prompt=_targeted_question_prompt(source_text, plan),
    )
    question = clean((reply or {}).get("question", "")) if isinstance(reply, dict) else ""
    if not question:
        question = _fallback_targeted_question(plan)
    output = dict(plan)
    output["clarification"] = {"needed": True, "question": question}
    return output, str(raw or "")[:1200]


async def _complete_capture_references(
    *,
    caller: Callable[..., Awaitable[str]],
    store: Any,
    plan: dict[str, Any],
    source_text: str,
    reference: datetime,
    timezone: str,
    history: str,
    pending: dict[str, Any] | None,
    uses_pending: bool,
    history_limit: int,
    known_limit: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Pipeline V12.2 : auditer -> résoudre -> chercher souvenir -> question ciblée."""
    output = _repair_obvious_capture_structure(dict(plan))
    output = _repair_explicit_entity_resolution(output)

    audit_raw = ""
    audit_used = _reference_audit_needed(source_text, output)
    if audit_used:
        audit, audit_raw = await _call_json_model(
            caller,
            system=REFERENCE_AUDITOR_SYSTEM,
            prompt=(
                "MESSAGE_UTILISATEUR:\n" + clean(source_text)
                + "\n\nPLAN_COURANT:\n"
                + json.dumps(output, ensure_ascii=False, default=str)
            ),
        )
        output = _apply_reference_audit(output, audit)
        output = _repair_explicit_entity_resolution(output)

    resolution_raw = ""
    if _plan_needs_resolution(output):
        known = _known_context_for_plan(store, output, known_limit)
        resolver_prompt = _resolution_prompt(
            source_text=source_text,
            plan=output,
            reference=reference,
            timezone=timezone,
            history=history,
            known=known,
            pending=pending if uses_pending else None,
            history_limit=history_limit,
        )
        resolution, resolution_raw = await _call_json_model(
            caller, system=RESOLVER_SYSTEM, prompt=resolver_prompt
        )
        if isinstance(resolution, dict):
            output = _apply_resolution_patches(output, resolution)

    ambiguity_diag = {"used": False, "candidate_count": 0, "proposals": []}
    targeted_raw = ""
    if _plan_needs_resolution(output):
        output, ambiguity_diag = await _search_ambiguity_candidates(
            caller=caller,
            store=store,
            source_text=source_text,
            plan=output,
            limit=int(config.get("semantic_ambiguity_candidate_limit", 100) or 100),
        )
        proposals = output.get("_ambiguity_candidates") if isinstance(output.get("_ambiguity_candidates"), list) else []
        if _plan_needs_resolution(output) and not proposals:
            output, targeted_raw = await _ensure_targeted_clarification(
                caller=caller,
                source_text=source_text,
                plan=output,
            )

    output["_resolution_diagnostic"] = {
        "used": bool(resolution_raw),
        "raw": str(resolution_raw or "")[:1200],
        "remaining": [
            sorted(_unresolved_fields(item))
            for item in (output.get("items") or [])
            if isinstance(item, dict) and _unresolved_fields(item)
        ],
    }
    output["_reference_audit"] = {
        "used": audit_used,
        "raw": str(audit_raw or "")[:1200],
    }
    output["_ambiguity_diagnostic"] = ambiguity_diag
    if targeted_raw:
        output["_targeted_clarification_raw"] = targeted_raw
    return output


def _fallback_note_plan(source_text: str) -> dict[str, Any]:
    return {
        "clarification": None,
        "items": [{
            "kind": "note",
            "title": clean(source_text),
            "status": "logged",
            "inferred": False,
            "details": {"semantic_fallback": True},
            "keywords": [],
        }],
        "_semantic_fallback": True,
    }


async def semantic_intake(
    *,
    agent: Any,
    store: Any,
    message: str,
    context_id: str,
    config: dict[str, Any],
    history: str = "",
    model_call: Callable[..., Awaitable[str]] | None = None,
) -> IntakeOutcome:
    """Route puis extrait un tour de mémoire personnelle.

    V11.6 sépare volontairement le routage et l'extraction. Un petit modèle local
    n'a plus à décider du type de tour ET remplir simultanément un énorme schéma.
    Une fois qu'un tour est routé vers la mémoire, il ne doit plus retomber dans
    le LLM conversationnel en cas d'extraction incomplète : on clarifie.
    """
    source_text = clean(message)
    timezone = str(config.get("timezone") or "Europe/Paris")
    threshold = _clamp(config.get("semantic_intake_confidence", 0.85), 0.85)
    router_threshold = _clamp(config.get("semantic_router_confidence", 0.78), 0.78)
    reference = ensure_reference(store.now(), timezone)

    if not source_text:
        context = _render_prompt_context(
            status="none", saved=[], query_result=None, clarification=""
        )
        return IntakeOutcome("none", context, {}, [])

    pending = _get_intake_state(store, context_id) if context_id else None
    history_limit = max(
        500,
        min(12000, int(config.get("semantic_intake_history_chars", 2400) or 2400)),
    )
    known_limit = max(
        5,
        min(50, int(config.get("semantic_intake_known_items", 24) or 24)),
    )
    # V11.8 : le routeur et l'extracteur primaire ne voient QUE le tour courant.
    # La mémoire/historique ne seront chargés qu'en phase de résolution ciblée.
    prompt = _current_turn_prompt(
        source_text=source_text,
        reference=reference,
        timezone=timezone,
        pending=pending,
    )

    caller = model_call or getattr(agent, "call_utility_model", None)
    if not callable(caller):
        context = _render_prompt_context(
            status="extractor_unavailable", saved=[], query_result=None, clarification=""
        )
        return IntakeOutcome("extractor_unavailable", context, {}, [])

    # V12.1 : si Paul avait proposé un souvenir candidat pour lever une ambiguïté,
    # on interprète d'abord la réponse de Romain. Le plan original est conservé :
    # on ne réinterprète pas toute la phrase et on n'applique jamais un candidat
    # sans confirmation.
    if isinstance(pending, dict) and pending.get("type") in {"memory_candidate_confirmation", "reference_clarification"}:
        confirmation, confirmation_raw = await _call_json_model(
            caller,
            system=AMBIGUITY_CONFIRMATION_SYSTEM,
            prompt=_confirmation_prompt(pending, source_text),
        )
        action = normalize((confirmation or {}).get("action", "")) if isinstance(confirmation, dict) else ""
        candidates = pending.get("candidates") if isinstance(pending.get("candidates"), list) else []
        partial_plan = pending.get("partial_plan") if isinstance(pending.get("partial_plan"), dict) else {}
        original_message = clean(pending.get("original_message", "")) or source_text

        if action in {"accept", "select", "provide value"}:
            selected = None
            if action in {"accept", "select"} and candidates:
                try:
                    candidate_index = int((confirmation or {}).get("candidate_index", 0))
                except (TypeError, ValueError):
                    candidate_index = 0
                if len(candidates) > 1 and action == "accept" and candidate_index == 0 and not clean((confirmation or {}).get("value", "")):
                    question = "Lequel de ces souvenirs correspond ?"
                    pending["question"] = question
                    _set_intake_state(store, context_id, pending)
                    context = _render_prompt_context(
                        status="clarification_required", saved=[], query_result=None, clarification=question
                    )
                    return IntakeOutcome("clarification_required", context, partial_plan, [], clarification_question=question)
                if 0 <= candidate_index < len(candidates):
                    selected = dict(candidates[candidate_index])

            if action == "provide value":
                target = _first_unresolved_target(partial_plan)
                value = clean((confirmation or {}).get("value", ""))
                if target and value:
                    selected = {
                        "item_index": target[0],
                        "field": target[1],
                        "value": value,
                        "record_id": "",
                        "confidence": 1.0,
                    }

            if selected:
                resumed_plan = _apply_confirmed_candidate(partial_plan, selected)
                if not _plan_needs_resolution(resumed_plan):
                    resumed_plan["mode"] = "capture"
                    resumed_plan["_ambiguity_confirmation"] = {
                        "action": action,
                        "raw": str(confirmation_raw or "")[:1000],
                        "candidate": selected,
                    }
                    return _persist_capture_plan(
                        store=store,
                        plan=resumed_plan,
                        source_text=original_message,
                        context_id=context_id,
                        config=config,
                        reference=reference,
                        timezone=timezone,
                    )

                question = _question(resumed_plan, "Il reste une référence ambiguë. Tu peux préciser ?")
                _set_intake_state(
                    store,
                    context_id,
                    {
                        "type": "clarification",
                        "original_message": original_message,
                        "question": question,
                        "partial_plan": resumed_plan,
                    },
                )
                context = _render_prompt_context(
                    status="clarification_required", saved=[], query_result=None, clarification=question
                )
                return IntakeOutcome("clarification_required", context, resumed_plan, [], clarification_question=question)

        if action == "reject":
            question = "D'accord. De qui ou de quoi parlais-tu exactement ?"
            pending["question"] = question
            pending["candidates"] = []
            _set_intake_state(store, context_id, pending)
            context = _render_prompt_context(
                status="clarification_required", saved=[], query_result=None, clarification=question
            )
            return IntakeOutcome("clarification_required", context, partial_plan, [], clarification_question=question)

        if action == "new topic":
            _clear_intake_state(store, context_id)
            pending = None
            prompt = _current_turn_prompt(
                source_text=source_text,
                reference=reference,
                timezone=timezone,
                pending=None,
            )
        elif action not in {"accept", "select", "provide value", "reject"}:
            question = clean(pending.get("question", "")) or "Tu peux préciser ?"
            context = _render_prompt_context(
                status="clarification_required", saved=[], query_result=None, clarification=question
            )
            return IntakeOutcome("clarification_required", context, partial_plan, [], clarification_question=question)

    # 1) ROUTAGE COURT -----------------------------------------------------
    router, router_raw = await _call_json_model(
        caller, system=ROUTER_SYSTEM, prompt=prompt
    )
    if not isinstance(router, dict):
        question = (
            "Je n'ai pas réussi à déterminer proprement si ce message doit aller "
            "dans ta mémoire. Tu peux le reformuler en une phrase simple ?"
        )
        if context_id:
            _set_intake_state(
                store,
                context_id,
                {
                    "original_message": source_text,
                    "question": question,
                    "router_raw": router_raw[:1000],
                },
            )
        context = _render_prompt_context(
            status="clarification_required",
            saved=[],
            query_result=None,
            clarification=question,
        )
        return IntakeOutcome(
            "clarification_required", context, {"mode": "router_error", "raw": router_raw[:1000]}, [], clarification_question=question
        )

    route = normalize(router.get("route") or router.get("mode") or "none") or "none"
    if route not in VALID_MODES:
        route = "none"
    route_confidence = _metadata_confidence(router.get("confidence"), 0.95 if route != "none" else 0.80)
    route_clarification = (
        router.get("clarification")
        if isinstance(router.get("clarification"), dict)
        else {}
    )

    # Si une clarification est en attente, une réponse courte (« Coralie ») peut
    # être impossible à classer seule. On reprend alors le mode partiel précédent.
    pending_plan = (
        pending.get("partial_plan")
        if isinstance(pending, dict) and isinstance(pending.get("partial_plan"), dict)
        else {}
    )
    pending_mode = normalize(pending_plan.get("mode", "")) if pending_plan else ""
    uses_pending = bool(router.get("uses_pending", False))
    router_query_follow_up = bool(router.get("query_follow_up", False))
    if pending and uses_pending and pending_mode in VALID_MODES - {"none"}:
        # Le routeur sémantique confirme que le message courant répond réellement
        # à la clarification précédente (ex. « Coralie » après « Tu parles de qui ? »).
        route = pending_mode
        route_confidence = max(route_confidence, router_threshold)
    elif pending:
        # Une nouvelle phrase complète gagne TOUJOURS sur une ancienne clarification.
        # Le pending est retiré AVANT l'extracteur : il ne peut plus détourner Qwen.
        if context_id:
            _clear_intake_state(store, context_id)
        pending = None
        prompt = _current_turn_prompt(
            source_text=source_text,
            reference=reference,
            timezone=timezone,
            pending=None,
        )

    if bool(route_clarification.get("needed")):
        question = clean(route_clarification.get("question", "")) or "Tu peux préciser ?"
        if context_id:
            _set_intake_state(
                store,
                context_id,
                {
                    "original_message": (pending or {}).get("original_message") or source_text,
                    "question": question,
                    "partial_plan": {"mode": route},
                },
            )
        context = _render_prompt_context(
            status="clarification_required", saved=[], query_result=None, clarification=question
        )
        return IntakeOutcome(
            "clarification_required", context, {"mode": route, "router": router}, [], clarification_question=question
        )

    if route == "none":
        if context_id and pending:
            # Un nouveau sujet normal abandonne une ancienne clarification.
            _clear_intake_state(store, context_id)
        context = _render_prompt_context(
            status="none", saved=[], query_result=None, clarification=""
        )
        return IntakeOutcome("none", context, {"mode": "none", "router": router}, [])

    # 2) EXTRACTION SPÉCIFIQUE AU TYPE DE TOUR -----------------------------
    extractor_system = ROUTE_SYSTEMS.get(route)
    if not extractor_system:
        context = _render_prompt_context(
            status="none", saved=[], query_result=None, clarification=""
        )
        return IntakeOutcome("none", context, {"mode": "none"}, [])

    plan, extractor_raw = await _call_json_model(
        caller, system=extractor_system, prompt=prompt
    )
    if not isinstance(plan, dict):
        question = "J'ai compris que c'est une information personnelle, mais pas assez précisément pour l'enregistrer sans erreur. Tu peux la reformuler ?"
        if context_id:
            _set_intake_state(
                store,
                context_id,
                {
                    "original_message": (pending or {}).get("original_message") or source_text,
                    "question": question,
                    "partial_plan": {"mode": route},
                    "extractor_raw": extractor_raw[:1000],
                },
            )
        context = _render_prompt_context(
            status="clarification_required", saved=[], query_result=None, clarification=question
        )
        return IntakeOutcome(
            "clarification_required", context, {"mode": route, "raw": extractor_raw[:1000], "router": router}, [], clarification_question=question
        )

    plan = dict(plan)
    if route == "capture":
        plan = await _complete_capture_references(
            caller=caller,
            store=store,
            plan=plan,
            source_text=source_text,
            reference=reference,
            timezone=timezone,
            history=history,
            pending=pending,
            uses_pending=uses_pending,
            history_limit=history_limit,
            known_limit=known_limit,
            config=config,
        )

    # Une requête autonome ne peut jamais hériter du filtre précédent, même si
    # l'extracteur se trompe sur follow_up. Il faut l'accord du routeur ET de
    # l'extracteur pour activer la fusion dans le store.
    if route == "query" and isinstance(plan.get("query"), dict):
        plan["query"] = dict(plan["query"])
        plan["query"]["follow_up"] = bool(
            router_query_follow_up and plan["query"].get("follow_up", False)
        )

    first_problem = _plan_problem(route, plan)
    retry_raw = ""
    retry_used = False
    clarification_before_retry = (
        plan.get("clarification")
        if isinstance(plan.get("clarification"), dict)
        else {}
    )
    if (
        first_problem
        and not bool(clarification_before_retry.get("needed"))
        and bool(config.get("semantic_intake_retry_invalid_output", True))
    ):
        retry_used = True
        retry_plan, retry_raw = await _call_json_model(
            caller,
            system=extractor_system,
            prompt=_retry_prompt(
                prompt, route=route, problem=first_problem, previous_raw=extractor_raw
            ),
        )
        if isinstance(retry_plan, dict):
            plan = dict(retry_plan)
            if route == "capture":
                plan = await _complete_capture_references(
                    caller=caller,
                    store=store,
                    plan=plan,
                    source_text=source_text,
                    reference=reference,
                    timezone=timezone,
                    history=history,
                    pending=pending,
                    uses_pending=uses_pending,
                    history_limit=history_limit,
                    known_limit=known_limit,
                    config=config,
                )
            if route == "query" and isinstance(plan.get("query"), dict):
                plan["query"] = dict(plan["query"])
                plan["query"]["follow_up"] = bool(
                    router_query_follow_up and plan["query"].get("follow_up", False)
                )

    remaining_problem = _plan_problem(route, plan)
    plan["mode"] = route
    plan["router"] = router
    plan["_pipeline_diagnostic"] = {
        "version": "12.2",
        "primary_scope": "current_turn_only",
        "query_follow_up_allowed": bool(router_query_follow_up),
        "resolver_used": bool((plan.get("_resolution_diagnostic") or {}).get("used", False)),
    }
    plan["_extractor_diagnostic"] = {
        "attempts": 2 if retry_used else 1,
        "first_problem": first_problem,
        "remaining_problem": remaining_problem,
        "first_raw": str(extractor_raw or "")[:1200],
        "retry_raw": str(retry_raw or "")[:1200] if retry_used else "",
    }
    confidence = _metadata_confidence(plan.get("confidence"), route_confidence)
    clarification = (
        plan.get("clarification")
        if isinstance(plan.get("clarification"), dict)
        else {}
    )

    if plan.get("pending_resolution") == "abandon" and context_id:
        _clear_intake_state(store, context_id)
        pending = None

    # V11.7 : une sortie techniquement invalide de Qwen n'est PAS une ambiguïté
    # utilisateur. Elle ne doit jamais créer un pending qui pollue les messages
    # suivants. On demande éventuellement une reformulation, mais sans état latent.
    if remaining_problem and not bool(clarification.get("needed")):
        if route == "capture":
            # V12.2 : une phrase compréhensible avec une référence ambiguë ne doit
            # JAMAIS tomber sur « reformule ». Un Qwen spécialisé récupère le sens
            # certain (verbe/date/etc.) et marque uniquement la référence manquante.
            recovery_prompt = (
                prompt
                + "\n\nPROBLEME_STRUCTUREL:\n" + clean(remaining_problem)
                + "\n\nSORTIE_PRECEDENTE:\n" + str(retry_raw or extractor_raw or "")[:1800]
            )
            recovered, recovery_raw = await _call_json_model(
                caller,
                system=CLARIFICATION_RECOVERY_SYSTEM,
                prompt=recovery_prompt,
            )
            if isinstance(recovered, dict):
                recovered = await _complete_capture_references(
                    caller=caller,
                    store=store,
                    plan=recovered,
                    source_text=source_text,
                    reference=reference,
                    timezone=timezone,
                    history=history,
                    pending=pending,
                    uses_pending=uses_pending,
                    history_limit=history_limit,
                    known_limit=known_limit,
                    config=config,
                )
                recovered["mode"] = route
                recovered["router"] = router
                recovered["_recovery_diagnostic"] = {
                    "used": True,
                    "raw": str(recovery_raw or "")[:1500],
                    "original_problem": remaining_problem,
                }
                recovered_problem = _plan_problem(route, recovered)
                recovered_clarification = (
                    recovered.get("clarification")
                    if isinstance(recovered.get("clarification"), dict)
                    else {}
                )
                if not recovered_problem or bool(recovered_clarification.get("needed")):
                    plan = recovered
                    remaining_problem = recovered_problem
                    clarification = recovered_clarification

            # Si Qwen n'a vraiment pas réussi à structurer une information personnelle,
            # on conserve le texte brut plutôt que de répondre comme un parseur.
            if remaining_problem and not bool(clarification.get("needed")):
                plan = _fallback_note_plan(source_text)
                plan["mode"] = route
                plan["router"] = router
                plan["_pipeline_diagnostic"] = {
                    "version": "12.2",
                    "primary_scope": "current_turn_only",
                    "semantic_fallback": True,
                }
                remaining_problem = ""
                clarification = {}
        else:
            if context_id:
                _clear_intake_state(store, context_id)
            question = "Tu peux préciser ce que tu cherches dans ta mémoire ?"
            context = _render_prompt_context(
                status="clarification_required", saved=[], query_result=None, clarification=question
            )
            return IntakeOutcome(
                "clarification_required", context, plan, [], clarification_question=question
            )

    # A clear structural extraction is not rejected because Qwen emitted an
    # arbitrary low score. Only an explicit ambiguity reaches this branch.
    if bool(clarification.get("needed")):
        question = _question(plan, "Tu peux préciser ce que tu veux que je retienne ?")
        if context_id:
            proposals = plan.get("_ambiguity_candidates") if isinstance(plan.get("_ambiguity_candidates"), list) else []
            _set_intake_state(
                store,
                context_id,
                {
                    "type": (
                        "memory_candidate_confirmation"
                        if proposals
                        else ("reference_clarification" if _plan_needs_resolution(plan) else "clarification")
                    ),
                    "original_message": (pending or {}).get("original_message") or source_text,
                    "question": question,
                    "partial_plan": plan,
                    "candidates": proposals,
                },
            )
        context = _render_prompt_context(
            status="clarification_required", saved=[], query_result=None, clarification=question
        )
        return IntakeOutcome(
            "clarification_required", context, plan, [], clarification_question=question
        )

    mode = route

    if mode == "capture":
        saved: list[dict[str, Any]] = []
        questions: list[str] = []
        items = plan.get("items") if isinstance(plan.get("items"), list) else []
        if not items:
            questions.append("Qu'est-ce que tu veux que je retienne exactement ?")
        for item in items:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            if _clamp(item.get("confidence"), 0.0) <= 0.01:
                item["confidence"] = confidence
            payload, question = _capture_item_payload(
                item,
                source_text=(pending or {}).get("original_message") or source_text,
                reference=reference,
                timezone=timezone,
                threshold=threshold,
            )
            if question:
                questions.append(question)
                continue
            if payload is None:
                continue
            if payload.get("inferred") and not bool(config.get("allow_inferred_facts", False)):
                questions.append(
                    "Cette information semble déduite plutôt qu'explicite. Tu peux me la confirmer ?"
                )
                continue
            try:
                saved.append(store.capture(context_id=context_id, **payload))
            except ValueError as exc:
                questions.append(str(exc))

        if questions:
            question = clean(questions[0])
            if context_id:
                _set_intake_state(
                    store,
                    context_id,
                    {
                        "original_message": (pending or {}).get("original_message") or source_text,
                        "question": question,
                        "partial_plan": plan,
                        "saved_count": len(saved),
                    },
                )
            context = _render_prompt_context(
                status="clarification_required", saved=saved, query_result=None, clarification=question
            )
            return IntakeOutcome(
                "clarification_required", context, plan, saved, clarification_question=question
            )

        if context_id:
            _clear_intake_state(store, context_id)
        context = _render_prompt_context(
            status="captured", saved=saved, query_result=None, clarification=""
        )
        return IntakeOutcome("captured", context, plan, saved)

    if mode == "query":
        query_payload, question = _query_payload(
            plan, reference=reference, timezone=timezone, context_id=context_id
        )
        if question:
            if context_id:
                _set_intake_state(
                    store,
                    context_id,
                    {"original_message": source_text, "question": question, "partial_plan": plan},
                )
            context = _render_prompt_context(
                status="clarification_required", saved=[], query_result=None, clarification=question
            )
            return IntakeOutcome(
                "clarification_required", context, plan, [], clarification_question=question
            )
        # Recherche en deux étages : le store fournit des candidats, Qwen décide
        # lesquels correspondent sémantiquement. Cela évite de dépendre des mots exacts.
        semantic_used = _semantic_query_needed(plan)
        if semantic_used:
            broad_payload = dict(query_payload)
            broad_payload["text"] = ""
            broad_payload["aggregate"] = "list"
            broad_payload["limit"] = 100
            result = store.query(**broad_payload)
            candidates = list(result.get("records") or [])
            match = None
            match_raw = ""
            if candidates:
                match, match_raw = await _call_json_model(
                    caller, system=QUERY_MATCHER_SYSTEM, prompt=_query_match_prompt(plan, candidates)
                )
            result = _apply_semantic_matches(result, plan, match if isinstance(match, dict) else {"record_ids": []})
            plan["_query_match_diagnostic"] = {
                "used": True,
                "candidate_count": len(candidates),
                "raw": str(match_raw or "")[:1500],
                "selected_ids": (result.get("semantic_match") or {}).get("selected_ids", []),
            }
        else:
            result = store.query(**query_payload)
            plan["_query_match_diagnostic"] = {"used": False}
        if context_id:
            _clear_intake_state(store, context_id)
        context = _render_prompt_context(
            status="query_ready", saved=[], query_result=result, clarification=""
        )
        return IntakeOutcome("query_ready", context, plan, [], query_result=result)

    if mode == "forget":
        spec = plan.get("forget") if isinstance(plan.get("forget"), dict) else {}
        if not bool(spec.get("explicit_request")) or not _forget_guard(source_text):
            question = "Tu veux bien que j'oublie réellement cette information de ma mémoire ?"
            context = _render_prompt_context(
                status="clarification_required", saved=[], query_result=None, clarification=question
            )
            return IntakeOutcome(
                "clarification_required", context, plan, [], clarification_question=question
            )
        result = store.forget(
            record_ids=spec.get("record_ids") if isinstance(spec.get("record_ids"), list) else None,
            query=clean(spec.get("query", "")),
            context_id=context_id,
        )
        if result.get("requires_user_choice"):
            question = "J'ai plusieurs souvenirs qui correspondent. Lequel veux-tu oublier ?"
            context = _render_prompt_context(
                status="clarification_required",
                saved=[],
                query_result=None,
                clarification=question,
                operation_result=result,
            )
            return IntakeOutcome(
                "clarification_required", context, plan, [], clarification_question=question
            )
        context = _render_prompt_context(
            status="forgotten", saved=[], query_result=None, clarification="", operation_result=result
        )
        return IntakeOutcome("forgotten", context, plan, [], operation_result=result)

    # UPDATE
    spec = plan.get("update") if isinstance(plan.get("update"), dict) else {}
    if not bool(spec.get("explicit_request")):
        question = "Tu veux bien modifier cet élément de ta mémoire ?"
        context = _render_prompt_context(
            status="clarification_required", saved=[], query_result=None, clarification=question
        )
        return IntakeOutcome(
            "clarification_required", context, plan, [], clarification_question=question
        )

    action = normalize(spec.get("action", "update")) or "update"
    changes = dict(spec.get("changes") or {}) if isinstance(spec.get("changes"), dict) else {}
    if action == "reschedule":
        expression = clean(spec.get("time_expression", ""))
        resolved = (
            resolve_temporal_expression(
                expression,
                reference=reference,
                timezone=timezone,
                prefer="future",
                clock_source=source_text,
            )
            if expression
            else None
        )
        if resolved is None:
            question = "À quelle nouvelle date veux-tu le reporter ?"
            context = _render_prompt_context(
                status="clarification_required", saved=[], query_result=None, clarification=question
            )
            return IntakeOutcome(
                "clarification_required", context, plan, [], clarification_question=question
            )
        changes.update(
            start_at=resolved.isoformat(),
            due_at=resolved.isoformat(),
            time_expression=expression,
        )

    result = store.update(
        record_id=clean(spec.get("record_id", "")),
        query=clean(spec.get("query", "")),
        context_id=context_id,
        action=action,
        changes=changes,
        reason="Demande explicite interprétée par l'intake sémantique V11.6",
    )
    if result.get("requires_user_choice"):
        question = "J'ai plusieurs éléments qui correspondent. Lequel veux-tu modifier ?"
        context = _render_prompt_context(
            status="clarification_required",
            saved=[],
            query_result=None,
            clarification=question,
            operation_result=result,
        )
        return IntakeOutcome(
            "clarification_required", context, plan, [], clarification_question=question
        )
    context = _render_prompt_context(
        status="updated", saved=[], query_result=None, clarification="", operation_result=result
    )
    return IntakeOutcome("updated", context, plan, [], operation_result=result)

