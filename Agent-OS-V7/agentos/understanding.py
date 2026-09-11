from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from agentos.llm import LLM


ALLOWED_PRIMARY_INTENTS = {
    "conversation",
    "question",
    "work",
    "learning",
    "memory_query",
    "memory_control",
    "operational",
    "agenda",
}

ALLOWED_CONVERSATION_GOALS = {
    "casual_chat",
    "entertainment",
    "advice",
    "explanation",
    "brainstorming",
    "emotional_support",
    "none",
}

ALLOWED_WORKERS = {
    "ai_worker",
    "researcher",
    "developer",
    "tester",
}

ALLOWED_MEMORY_KINDS = {
    "episode",
    "fact",
    "preference",
    "habit",
    "relation",
    "profile",
}

# PERSONAL PROFILE EXTRACTION V6.5
ALLOWED_DURABLE_CATEGORIES = {
    "profile",
    "relation",
    "interest",
    "project",
    "goal",
    "skill",
    "preference",
    "habit",
}

ALLOWED_TONES = {
    "calm",
    "neutral",
    "dynamic",
}

ALLOWED_VERBOSITY = {
    "short",
    "normal",
    "detailed",
}


ALLOWED_AGENDA_ACTIONS = {
    "add",
    "query",
    "complete",
    "reschedule",
    "none",
}

ALLOWED_AGENDA_VIEWS = {
    "todo",
    "appointment",
    "event",
    "program",
    "none",
}

ALLOWED_AGENDA_FIELDS = {
    "what",
    "where",
    "when",
    "who",
    "none",
}

ALLOWED_AGENDA_PRIORITIES = {
    "high",
    "normal",
    "low",
    "none",
}


@dataclass(frozen=True)
class MemoryItem:
    kind: str
    content: str
    confidence: float = 0.8


@dataclass(frozen=True)
class DurableProfileItem:
    category: str
    subject: str
    value: str = ""
    confidence: float = 0.8
    importance: float = 0.6
    explicit: bool = True


@dataclass
class Understanding:
    primary_intent: str = "conversation"
    conversation_goal: str = "casual_chat"
    confidence: float = 0.0

    topic: str = ""
    continues_previous_topic: bool | None = None

    work_requested: bool = False
    work_explicit: bool = False
    work_objective: str = ""
    worker: str | None = None
    work_confidence: float = 0.0

    learning_requested: bool = False
    learning_subject: str = ""
    learning_confidence: float = 0.0


    agenda_requested: bool = False
    agenda_action: str = "none"
    agenda_view: str = "none"
    agenda_target: str = ""
    agenda_time: str = ""
    agenda_subject: str = ""
    agenda_field: str = "none"
    agenda_priority: str = "none"
    agenda_confidence: float = 0.0

    # V6.5 : concepts durables extraits du message utilisateur.
    durable_items: list[DurableProfileItem] = field(default_factory=list)

    memory_items: list[MemoryItem] = field(default_factory=list)
    user_state: dict[str, Any] = field(default_factory=dict)
    response_style: dict[str, Any] = field(default_factory=dict)

    pure_state_update: bool = False
    reason: str = ""
    source: str = "fallback"

    @property
    def routing_confident(self) -> bool:
        if self.source == "llm":
            return self.confidence >= 0.58
        if self.source == "deterministic":
            return self.confidence >= 0.80
        return False


class UnderstandingEngine:
    """Agent-OS V6.2.1 — compréhension naturelle, mémoire et continuité.

    V6.2.1 conserve V6.2 et ajoute :
    - reconnaissance explicite des questions portant sur la mémoire personnelle ;
    - capture de secours des événements personnels préfixés par une date relative ;
    - consolidation de l'épisode même si le petit LLM oublie de l'extraire.

    V6.2 ajoute à V6.1 :
    - détection explicite des demandes d'apprentissage ;
    - sujet courant + continuité ou changement de sujet ;
    - indications de style de réponse sans transformer l'émotion en sujet ;
    - préférences de communication mémorisables ;
    - fallback déterministe fort pour les demandes évidentes.
    """

    SYSTEM_PROMPT = r"""
Tu es le moteur de compréhension interne d'Agent-OS V6.2.1.
Tu ne réponds jamais à l'utilisateur et tu n'exécutes aucune tâche.
Tu analyses uniquement le message utilisateur et tu renvoies UN objet JSON,
sans markdown, sans commentaire et sans texte avant ou après.

Un même message peut contenir plusieurs dimensions en parallèle : intention,
sujet, état personnel, préférence de communication, souvenir et travail.

RÈGLE 1 — BUT PRINCIPAL
Un état personnel ou émotionnel ne remplace jamais la demande principale.
Exemple :
"il est tard je suis fatigué je ne veux pas travailler il faut que tu me divertisse"
= conversation, entertainment, énergie basse, wants_to_work=false, aucune mission.

RÈGLE 2 — TRAVAIL
Crée une demande de travail uniquement lorsque l'utilisateur délègue réellement
quelque chose à accomplir : recherche substantielle, développement, test,
production, analyse structurée ou apprentissage d'une compétence.
Les demandes conversationnelles restent une conversation : raconter, divertir,
discuter, expliquer, conseiller, donner des idées ou brainstormer.

Distingue :
- "on pourrait refaire mon dashboard" = discussion, pas une mission ;
- "comment tu referais mon dashboard ?" = question/discussion ;
- "refais mon dashboard Home Assistant" = travail/developer ;
- "cherche les meilleures solutions de mémoire IA" = travail/researcher ;
- "raconte-moi une histoire" = conversation/entertainment.

RÈGLE 3 — APPRENTISSAGE
Une formulation naturelle qui demande à Agent-OS d'acquérir une compétence est
une vraie demande de travail, même formulée comme "tu peux ... ?".
Exemples :
- "apprends YAML" = learning.requested=true ;
- "forme-toi sur Frigate" = learning.requested=true ;
- "tu peux apprendre des compétences pour développer du YAML ?"
  = learning.requested=true, subject="YAML" ;
- "est-ce que YAML est difficile à apprendre ?"
  = simple question, learning.requested=false.
Pour un apprentissage, worker="researcher" et work.requested=true.
L'objectif doit être actionnable et conserver TOUT le sujet demandé.
Ne réduis jamais "apprendre comment créer des fils de discussion sur Telegram"
à "apprendre", "Telegram", "connaissance" ou "acquérir la connaissance".
Le verbe apprendre décrit l'action ; les mots qui suivent décrivent l'objet réel
de l'apprentissage et doivent rester présents dans learning.subject/goal.

RÈGLE 4 — SUJET / CONTINUITÉ
Identifie le sujet du MESSAGE ACTUEL en quelques mots.
Compare-le au sujet précédent fourni dans le prompt.
- Si le message change clairement de sujet, continues_previous_topic=false.
- Si c'est une relance, un pronom, "et ça ?", "comme on disait", etc., true.
- Si aucun sujet précédent n'existe, null.
Exemple : après YAML, "j'ai vu un canard bleu hier" = sujet "canard bleu",
continues_previous_topic=false. Le YAML ne doit pas contaminer la réponse.

RÈGLE 5 — MÉMOIRE PERSONNELLE
Extrais uniquement ce que l'utilisateur affirme réellement sur lui, sa vie ou
ses préférences. Les événements banals sont valides :
"j'ai vu un canard", "j'ai fait la vaisselle", "j'ai mangé une pizza".
Ne mémorise pas comme souvenir une question, un ordre à l'agent, une hypothèse,
un exemple fictif ou une tâche Agent-OS.
Les émotions temporaires vont dans user_state, pas dans memory_items.

RÈGLE 5B — QUESTION SUR LA MÉMOIRE PERSONNELLE
Une question qui demande ce que l'utilisateur t'a déjà raconté, ce qu'il a fait,
où il a emmené quelqu'un, avec qui il était, ou jusqu'à quand un événement
personnel dure est une memory_query, PAS une recherche Web.
Exemples :
- "où est-ce que j'ai emmené Coralie hier ?" = memory_query ;
- "jusqu'à quand Coralie est-elle en voyage ?" si Coralie est une personne de
  la vie de l'utilisateur déjà présente dans le contexte = memory_query ;
- "tu te souviens du canard ?" = memory_query ;
- "qu'est-ce que je t'ai dit sur mon aquarium ?" = memory_query.
Pour memory_query : work.requested=false. Le Manager doit interroger sa mémoire
personnelle et ne jamais chercher une personne privée sur Internet par défaut.


RÈGLE 5C — AGENDA PERSONNEL / TODO / RENDEZ-VOUS
Reconnais sémantiquement ce qui concerne le planning personnel de l'utilisateur,
même si sa phrase ne correspond à aucun mot-clé exact.

L'agenda contient trois choses différentes :
- todo = tâche personnelle à accomplir ;
- appointment = rendez-vous ;
- event = événement personnel notable planifié ;
- program = vue combinée de tout ce qui est prévu.

Exemples :
- "samedi je dois aller chercher Coralie à l'aéroport"
  => agenda.requested=true, action="add", view="todo", target="samedi",
     subject="aller chercher Coralie à l'aéroport" ;
- "je dois faire quoi samedi ?"
  => agenda.requested=true, action="query", view="todo", target="samedi",
     field="what" ;
- "quelles sont mes tâches samedi ?"
  => agenda query/todo/samedi ;
- "où je dois aller samedi ?"
  => agenda query/program/samedi, field="where" ;
- "à quelle heure est mon rendez-vous demain ?"
  => agenda query/appointment/demain, field="when" ;
- "les événements prévus pour samedi ?" APRÈS une discussion sur son agenda
  => agenda query/event/samedi ;
- "mon programme samedi ?"
  => agenda query/program/samedi ;
- "j'ai fini la manucure"
  => agenda complete/todo, subject="manucure".

Utilise le message précédent et le sujet précédent pour comprendre les relances.
Si l'utilisateur vient de parler de son agenda, une phrase courte comme
"et samedi ?" ou "les événements prévus samedi ?" continue naturellement ce
contexte sauf indication contraire.

IMPORTANT : ne confonds pas agenda personnel et recherche publique.
- "je dois faire quoi samedi ?" = consulter SES tâches, pas proposer des sorties ;
- "quels événements sont prévus samedi à Toulouse ?" = question externe/publique,
  agenda.requested=false ;
- "que faire à Paris samedi ?" = recommandations externes,
  agenda.requested=false.

Pour une entrée d'agenda, ne crée pas une mission Agent-OS.
work.requested=false.
Une TODO ou un rendez-vous n'est pas un souvenir épisodique déjà vécu : ne le
mets pas dans memory_items. L'agenda possède son propre stockage.
Dans agenda.target, conserve une expression temporelle normalisée mais naturelle
("aujourd'hui", "demain", "samedi", "dans 3 jours", "20 septembre").
Corrige une petite faute évidente si nécessaire, par exemple "samdi" => "samedi".
agenda.subject contient seulement le sujet utile, sans recopier toute la phrase.

PRIORITÉ DES TODO :
- high si l'utilisateur exprime sémantiquement urgence, gravité, importance,
  caractère critique, essentiel, prioritaire, impératif, pressé ou équivalent ;
- low s'il exprime le contraire : peu important, pas urgent, secondaire,
  peut attendre, faible priorité, quand il aura le temps, ou équivalent ;
- normal seulement si une priorité normale est explicitement demandée ;
- none si aucune priorité n'est exprimée. Une nouvelle TODO none sera stockée
  comme priorité normale par l'agenda.
- "reporte X à demain" est action="reschedule", jamais action="add".
Exemples :
"demain je dois appeler le garage, c'est vital" => priority="high" ;
"je dois ranger le garage, ça peut attendre" => priority="low".

RÈGLE 5D — PROFIL DURABLE V6.5
En plus des souvenirs épisodiques, extrais les informations RELATIVEMENT
DURABLES sur l'utilisateur dans durable_items.

Catégories :
- profile : identité, lieu de vie, métier, logement ou autre fait stable ;
- relation : personne importante et nature du lien ;
- interest : centre d'intérêt ou passion explicitement affirmé ;
- project : projet personnel/professionnel actif ;
- goal : objectif à moyen/long terme ;
- skill : compétence ou savoir-faire de l'utilisateur ;
- preference : préférence durable, y compris communication/outils ;
- habit : habitude ou routine répétée.

Exemples :
- "je vis à Brens" => profile, subject="lieu de vie", value="Brens" ;
- "Coralie est ma copine" => relation, subject="Coralie", value="partenaire" ;
- "j'adore la domotique" => interest, subject="domotique", value="aime" ;
- "je développe Agent-OS" => project, subject="Agent-OS", value="projet actif" ;
- "mon objectif est d'avoir 2200 euros de revenus passifs" => goal ;
- "je maîtrise le froid et la climatisation" => skill ;
- "je préfère recevoir les fichiers complets" => preference.

IMPORTANT :
- durable_items contient uniquement ce que l'utilisateur affirme réellement ;
- une TODO, un rendez-vous, une humeur temporaire ou un événement ponctuel ne
  devient pas un trait durable ;
- une simple question sur un sujet ne prouve pas que c'est un centre d'intérêt ;
- explicit=true quand l'utilisateur l'affirme. N'invente jamais un intérêt
  déduit de la fréquence : cette inférence sera faite séparément par V6.5 ;
- importance mesure seulement à quel point l'information semble centrale dans
  CE message (0.5 normal, 0.8 très important, 1.0 explicitement principal) ;
- confidence mesure la confiance d'extraction, pas l'importance.

Les instructions durables sur la façon de répondre sont des préférences :
- "sois moins enjoué avec moi" -> preference ;
- "réponds-moi directement" -> preference ;
- "arrête de me demander si ça va quand je dis que je suis fatigué" -> preference ;
- "le soir sois plus calme et plus court" -> preference.
Conserve une formulation proche de celle de l'utilisateur.

RÈGLE 6 — STYLE
response_style ne commande que la FORME, jamais le sujet de la réponse.
Une fatigue récente peut rendre la réponse plus calme/courte, mais ne doit pas
faire parler spontanément de fatigue, de sommeil ou de bien-être.
mention_state=true uniquement si le message courant demande explicitement de
parler de cet état ou si une réponse directe à cet état est le but principal.
Par défaut, évite l'enthousiasme forcé.

worker :
- developer = écrire/modifier/réparer du code ou des fichiers ;
- tester = tester/compiler/vérifier techniquement ;
- researcher = recherche documentaire ou apprentissage ;
- ai_worker = analyse, planification, rédaction ou travail intellectuel ;
- null = pas de mission.

Format exact :
{
  "primary_intent": "conversation|question|work|learning|memory_query|memory_control|operational",
  "conversation_goal": "casual_chat|entertainment|advice|explanation|brainstorming|emotional_support|none",
  "confidence": 0.0,
  "topic": "sujet actuel court",
  "continues_previous_topic": true,
  "work": {
    "requested": false,
    "explicit": false,
    "objective": "",
    "worker": null,
    "confidence": 0.0
  },
  "learning": {
    "requested": false,
    "subject": "",
    "goal": "",
    "confidence": 0.0
  },
  "agenda": {
    "requested": false,
    "action": "add|query|complete|reschedule|none",
    "view": "todo|appointment|event|program|none",
    "target": "",
    "time": "",
    "subject": "",
    "field": "what|where|when|who|none",
    "priority": "high|normal|low|none",
    "confidence": 0.0
  },
  "memory_items": [
    {
      "type": "episode|fact|preference|habit|relation|profile",
      "content": "...",
      "confidence": 0.0
    }
  ],
  "durable_items": [
    {
      "category": "profile|relation|interest|project|goal|skill|preference|habit",
      "subject": "concept court et stable",
      "value": "valeur ou description courte",
      "confidence": 0.0,
      "importance": 0.0,
      "explicit": true
    }
  ],
  "user_state": {
    "energy": "low|normal|high|unknown",
    "motivation": "low|normal|high|unknown",
    "stress": "low|moderate|high|unknown",
    "mood": "positive|neutral|negative|unknown",
    "wants_to_work": true
  },
  "response_style": {
    "tone": "calm|neutral|dynamic",
    "verbosity": "short|normal|detailed",
    "mention_state": false
  },
  "pure_state_update": false,
  "reason": "courte justification interne"
}

continues_previous_topic utilise true, false ou null.
wants_to_work utilise true, false ou null.
pure_state_update=true seulement si le message est essentiellement une mise à
jour d'état personnel appelant au plus un accusé de réception. Dès qu'il y a
une autre demande, mets false.
""".strip()

    TECH_SUBJECTS = (
        ("yaml", "YAML"),
        ("home assistant", "Home Assistant"),
        ("home-assistant", "Home Assistant"),
        ("frigate", "Frigate"),
        ("python", "Python"),
        ("docker", "Docker"),
        ("mqtt", "MQTT"),
        ("zha", "ZHA"),
        ("fastapi", "FastAPI"),
        ("telegram", "Telegram"),
        ("ollama", "Ollama"),
        ("github", "GitHub"),
        ("powershell", "PowerShell"),
        ("sql", "SQL"),
        ("javascript", "JavaScript"),
        ("typescript", "TypeScript"),
    )

    LEARNING_PATTERNS = (
        r"\bapprends\b",
        r"\bapprendre\b",
        r"\bapprennes\b",
        r"\bforme[- ]toi\b",
        r"\bte former\b",
        r"\btu peux apprendre\b",
        r"\bpeux[- ]tu apprendre\b",
        r"\bj[' ]?aimerais que tu apprennes\b",
        r"\bje veux que tu apprennes\b",
    )

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.last_topic = ""
        self.last_message = ""

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, number))

    @staticmethod
    def _clean(text: Any) -> str:
        return " ".join(str(text or "").strip().split())

    @staticmethod
    def _ascii(text: Any) -> str:
        normalized = unicodedata.normalize(
            "NFKD",
            str(text or "").lower(),
        )
        return "".join(
            char
            for char in normalized
            if not unicodedata.combining(char)
        )

    @classmethod
    def _json_object(cls, raw: str) -> dict[str, Any] | None:
        text = str(raw or "").strip()
        if not text:
            return None

        text = re.sub(
            r"^\s*```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\s*```\s*$",
            "",
            text,
        ).strip()

        start = text.find("{")
        if start < 0:
            return None

        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

        return value if isinstance(value, dict) else None

    @classmethod
    def _normalize_memory_items(cls, raw_items: Any) -> list[MemoryItem]:
        if not isinstance(raw_items, list):
            return []

        result: list[MemoryItem] = []
        seen: set[tuple[str, str]] = set()

        for raw in raw_items[:12]:
            if not isinstance(raw, dict):
                continue

            kind = cls._clean(raw.get("type", raw.get("kind", ""))).lower()
            content = cls._clean(raw.get("content", ""))
            confidence = cls._clamp(raw.get("confidence", 0.8))

            if kind not in ALLOWED_MEMORY_KINDS or not content or confidence < 0.45:
                continue

            key = (kind, cls._ascii(content).rstrip(" .!?,;:"))
            if key in seen:
                continue
            seen.add(key)

            result.append(
                MemoryItem(
                    kind=kind,
                    content=content,
                    confidence=confidence,
                )
            )

        return result

    @classmethod
    def _normalize_durable_items(
        cls,
        raw_items: Any,
    ) -> list[DurableProfileItem]:
        if not isinstance(raw_items, list):
            return []

        result: list[DurableProfileItem] = []
        seen: set[tuple[str, str]] = set()
        for raw in raw_items[:12]:
            if not isinstance(raw, dict):
                continue
            category = cls._clean(raw.get("category", "")).lower()
            subject = cls._clean(raw.get("subject", ""))[:180]
            value = cls._clean(raw.get("value", ""))[:400]
            confidence = cls._clamp(raw.get("confidence", 0.8))
            importance = cls._clamp(raw.get("importance", 0.6))
            explicit = raw.get("explicit", True)
            explicit = explicit if isinstance(explicit, bool) else True

            if (
                category not in ALLOWED_DURABLE_CATEGORIES
                or not subject
                or confidence < 0.45
            ):
                continue

            key = (category, cls._ascii(subject).rstrip(" .!?,;:"))
            if key in seen:
                continue
            seen.add(key)
            result.append(
                DurableProfileItem(
                    category=category,
                    subject=subject,
                    value=value,
                    confidence=confidence,
                    importance=importance,
                    explicit=explicit,
                )
            )
        return result

    @classmethod
    def _normalize_response_style(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}

        result: dict[str, Any] = {}
        tone = cls._clean(raw.get("tone", "")).lower()
        verbosity = cls._clean(raw.get("verbosity", "")).lower()
        mention_state = raw.get("mention_state", None)

        if tone in ALLOWED_TONES:
            result["tone"] = tone
        if verbosity in ALLOWED_VERBOSITY:
            result["verbosity"] = verbosity
        if isinstance(mention_state, bool):
            result["mention_state"] = mention_state

        return result

    @classmethod
    def _from_payload(cls, payload: dict[str, Any]) -> Understanding:
        primary = cls._clean(payload.get("primary_intent", "conversation")).lower()
        if primary not in ALLOWED_PRIMARY_INTENTS:
            primary = "conversation"

        goal = cls._clean(payload.get("conversation_goal", "casual_chat")).lower()
        if goal not in ALLOWED_CONVERSATION_GOALS:
            goal = "casual_chat"

        topic = cls._clean(payload.get("topic", ""))[:120]
        continuity_raw = payload.get("continues_previous_topic", None)
        continuity = continuity_raw if isinstance(continuity_raw, bool) else None

        work = payload.get("work", {})
        if not isinstance(work, dict):
            work = {}

        requested = bool(work.get("requested", False))
        explicit = bool(work.get("explicit", False))
        objective = cls._clean(work.get("objective", ""))
        worker_raw = cls._clean(work.get("worker", "")).lower()
        worker = worker_raw if worker_raw in ALLOWED_WORKERS else None
        work_confidence = cls._clamp(work.get("confidence", 0.0))

        learning = payload.get("learning", {})
        if not isinstance(learning, dict):
            learning = {}

        learning_requested = bool(learning.get("requested", False))
        learning_subject = cls._clean(learning.get("subject", ""))[:160]
        learning_goal = cls._clean(learning.get("goal", ""))
        learning_confidence = cls._clamp(learning.get("confidence", 0.0))


        agenda = payload.get("agenda", {})
        if not isinstance(agenda, dict):
            agenda = {}

        agenda_requested = bool(agenda.get("requested", False))
        agenda_action = cls._clean(agenda.get("action", "none")).lower()
        agenda_view = cls._clean(agenda.get("view", "none")).lower()
        agenda_target = cls._clean(agenda.get("target", ""))[:120]
        agenda_time = cls._clean(agenda.get("time", ""))[:40]
        agenda_subject = cls._clean(agenda.get("subject", ""))[:240]
        agenda_field = cls._clean(agenda.get("field", "none")).lower()
        agenda_priority = cls._clean(agenda.get("priority", "none")).lower()
        agenda_confidence = cls._clamp(agenda.get("confidence", 0.0))

        if agenda_action not in ALLOWED_AGENDA_ACTIONS:
            agenda_action = "none"
        if agenda_view not in ALLOWED_AGENDA_VIEWS:
            agenda_view = "none"
        if agenda_field not in ALLOWED_AGENDA_FIELDS:
            agenda_field = "none"
        if agenda_priority not in ALLOWED_AGENDA_PRIORITIES:
            agenda_priority = "none"

        if agenda_confidence < 0.50:
            agenda_requested = False
            agenda_action = "none"
            agenda_view = "none"
            agenda_field = "none"
            agenda_priority = "none"

        if learning_requested:
            requested = True
            explicit = True
            worker = "researcher"
            work_confidence = max(work_confidence, learning_confidence)
            primary = "learning"
            if learning_goal:
                objective = learning_goal
            elif learning_subject:
                objective = (
                    "Apprendre et consolider la compétence technique "
                    f"{learning_subject} à partir de sources fiables, puis la "
                    "rendre réutilisable par les workers d'Agent-OS."
                )

        # SEMANTIC AGENDA V6.4.2 — l'agenda est une intention personnelle
        # distincte du travail Agent-OS et de la recherche Web.
        if agenda_requested:
            requested = False
            explicit = False
            objective = ""
            worker = None
            primary = "agenda"

        confidence = cls._clamp(payload.get("confidence", work_confidence))
        if agenda_requested:
            confidence = max(confidence, agenda_confidence)
        if learning_requested:
            confidence = max(confidence, learning_confidence)

        if requested and worker is None:
            worker = "ai_worker"

        if not requested:
            worker = None
            objective = ""
            explicit = False

        user_state = payload.get("user_state", {})
        if not isinstance(user_state, dict):
            user_state = {}

        cleaned_state: dict[str, Any] = {}
        allowed_states = {
            "energy": {"low", "normal", "high", "unknown"},
            "motivation": {"low", "normal", "high", "unknown"},
            "stress": {"low", "moderate", "high", "unknown"},
            "mood": {"positive", "neutral", "negative", "unknown"},
        }

        for key, allowed in allowed_states.items():
            value = cls._clean(user_state.get(key, "unknown")).lower()
            if value in allowed and value != "unknown":
                cleaned_state[key] = value

        wants_to_work = user_state.get("wants_to_work", None)
        if isinstance(wants_to_work, bool):
            cleaned_state["wants_to_work"] = wants_to_work

        response_style = cls._normalize_response_style(
            payload.get("response_style", {})
        )

        pure_state_update = bool(payload.get("pure_state_update", False))
        if requested or agenda_requested or goal in {
            "entertainment",
            "advice",
            "explanation",
            "brainstorming",
        }:
            pure_state_update = False

        return Understanding(
            primary_intent=primary,
            conversation_goal=goal,
            confidence=confidence,
            topic=topic,
            continues_previous_topic=continuity,
            work_requested=requested,
            work_explicit=explicit,
            work_objective=objective,
            worker=worker,
            work_confidence=work_confidence,
            learning_requested=learning_requested,
            learning_subject=learning_subject,
            learning_confidence=learning_confidence,
            agenda_requested=agenda_requested,
            agenda_action=agenda_action,
            agenda_view=agenda_view,
            agenda_target=agenda_target,
            agenda_time=agenda_time,
            agenda_subject=agenda_subject,
            agenda_field=agenda_field,
            agenda_priority=agenda_priority,
            agenda_confidence=agenda_confidence,
            durable_items=cls._normalize_durable_items(payload.get("durable_items", [])),
            memory_items=cls._normalize_memory_items(payload.get("memory_items", [])),
            user_state=cleaned_state,
            response_style=response_style,
            pure_state_update=pure_state_update,
            reason=cls._clean(payload.get("reason", "")),
            source="llm",
        )


    # =========================================================
    # LEARNING OBJECTIVE PRESERVATION V6.6.0.2
    # =========================================================

    @classmethod
    def _learning_request_body(
        cls,
        message: str,
    ) -> str:
        """Conserve le contenu réel demandé après le verbe d'apprentissage.

        Le LLM décide SI c'est une demande d'apprentissage.
        Le texte utilisateur décide CE QU'Agent-OS doit apprendre.
        """
        clean = cls._clean(message)
        if not clean:
            return ""

        value = clean

        patterns = (
            r"^\s*je\s+voudrais\s+apprendre\s+",
            r"^\s*j[' ]?aimerais\s+apprendre\s+",
            r"^\s*je\s+veux\s+apprendre\s+",
            r"^\s*je\s+souhaite\s+apprendre\s+",
            r"^\s*je\s+voudrais\s+que\s+tu\s+apprennes\s+",
            r"^\s*j[' ]?aimerais\s+que\s+tu\s+apprennes\s+",
            r"^\s*je\s+veux\s+que\s+tu\s+apprennes\s+",
            r"^\s*tu\s+peux\s+apprendre\s+",
            r"^\s*peux[- ]?tu\s+apprendre\s+",
            r"^\s*apprends\s+",
            r"^\s*apprendre\s+",
            r"^\s*forme[- ]?toi\s+(?:sur\s+)?",
            r"^\s*te\s+former\s+(?:sur\s+)?",
        )

        for pattern in patterns:
            stripped = re.sub(
                pattern,
                "",
                value,
                count=1,
                flags=re.IGNORECASE,
            ).strip(" .!?;:")
            if stripped != value.strip(" .!?;:"):
                value = stripped
                break

        value = cls._clean(value).strip(" .!?;:")

        # Évite les résultats vides ou génériques du type « apprendre ».
        generic = {
            "",
            "apprendre",
            "connaissance",
            "la connaissance",
            "des connaissances",
            "acquerir la connaissance",
            "acquérir la connaissance",
            "une competence",
            "une compétence",
        }
        if cls._ascii(value) in {
            cls._ascii(item)
            for item in generic
        }:
            return ""

        return value[:500]

    @classmethod
    def _canonical_learning_objective(
        cls,
        message: str,
        *,
        fallback_subject: str = "",
    ) -> tuple[str, str]:
        body = cls._learning_request_body(message)

        if body:
            # Le sujet est le contenu complet de la demande, pas seulement
            # la technologie détectée.
            subject = body
            objective = (
                "Apprendre et maîtriser : "
                + body
                + ". Rechercher des sources techniques fiables, "
                  "comprendre les concepts, API, contraintes et exemples de code, "
                  "puis conserver une synthèse exploitable par Agent-OS."
            )
            return subject, objective

        subject = cls._clean(fallback_subject) or "compétence demandée"
        objective = (
            "Apprendre et consolider la compétence "
            + subject
            + " à partir de sources fiables, puis la rendre "
              "réutilisable par les workers d'Agent-OS."
        )
        return subject, objective

    @staticmethod
    def _learning_goal_is_generic(value: str) -> bool:
        clean = " ".join(str(value or "").strip().lower().split())
        generic = (
            "",
            "apprendre",
            "acquérir la connaissance",
            "acquerir la connaissance",
            "acquérir des connaissances",
            "acquerir des connaissances",
            "faire des recherches",
            "effectuer la recherche",
            "acquérir la compétence",
            "acquerir la competence",
        )
        if clean in generic:
            return True
        return len(clean) < 12


    @classmethod
    def _extract_learning_subject(cls, normalized: str) -> str:
        found: list[str] = []
        for marker, label in cls.TECH_SUBJECTS:
            if marker in normalized and label not in found:
                found.append(label)

        if found:
            if "YAML" in found and "Home Assistant" in found:
                return "YAML pour Home Assistant"
            return " / ".join(found[:3])

        match = re.search(
            r"(?:apprends|apprendre|apprennes|forme[- ]toi(?:\s+sur)?|te former(?:\s+sur)?)\s+(.{2,100}?)(?:[?.!]|$)",
            normalized,
            flags=re.IGNORECASE,
        )
        if match:
            return cls._clean(match.group(1))[:100]

        return ""

    @classmethod
    def _looks_like_learning_request(cls, normalized: str) -> bool:
        if not any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in cls.LEARNING_PATTERNS):
            return False

        # "est-ce que X est difficile à apprendre" parle de l'apprentissage
        # sans demander à Paul de se former.
        if re.search(
            r"\b(?:est ce que|est-ce que).{0,80}\b(?:difficile|facile|long|temps).{0,50}\bapprendre\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            return False

        return True

    @classmethod
    def _v701_personal_identity_message(cls, message: str) -> bool:
        n = cls._ascii(cls._clean(message))
        n = re.sub(r"[^a-z0-9]+", " ", n)
        n = " ".join(n.split())
        return bool(re.search(
            r"\b(?:je m appelle|mon prenom est|mon nom est|j habite|je vis|je reside|"
            r"comment je m appelle|comment je mappelle|comment je mapelle|"
            r"quel est mon nom|quel est mon prenom|"
            r"ou j habite|ou est ce que j habite|que sais tu (?:de|sur) moi|"
            r"dis moi ce que tu sais de moi|ce que tu (?:possede|possedes|as) en mem+oire)\b",
            n,
        ))

    @classmethod
    def _fallback(cls, message: str, reason: str = "fallback déterministe") -> Understanding:
        clean = cls._clean(message)
        normalized = cls._ascii(clean)

        if cls._looks_like_learning_request(normalized):
            subject = cls._extract_learning_subject(normalized) or "compétence demandée"
            return Understanding(
                primary_intent="learning",
                conversation_goal="none",
                confidence=0.90,
                topic=f"apprentissage {subject}",
                continues_previous_topic=None,
                work_requested=True,
                work_explicit=True,
                work_objective=(
                    "Apprendre et consolider la compétence technique "
                    f"{subject} à partir de sources fiables, puis la rendre "
                    "réutilisable par les workers d'Agent-OS."
                ),
                worker="researcher",
                work_confidence=0.90,
                learning_requested=True,
                learning_subject=subject,
                learning_confidence=0.90,
                memory_items=[],
                user_state={},
                response_style={"tone": "neutral", "verbosity": "short", "mention_state": False},
                pure_state_update=False,
                reason=reason + " | demande d'apprentissage explicite",
                source="deterministic",
            )

        entertainment_markers = (
            "divertis-moi",
            "divertis moi",
            "divertisse-moi",
            "divertisse moi",
            "me divertisse",
            "me divertir",
            "divertir",
            "amuse-moi",
            "amuse moi",
            "raconte-moi une histoire",
            "raconte moi une histoire",
            "raconte-moi une blague",
            "raconte moi une blague",
            "fais-moi rire",
            "fais moi rire",
            "on joue",
            "un jeu",
        )
        asks_entertainment = any(marker in normalized for marker in entertainment_markers)

        state: dict[str, Any] = {}
        if re.search(r"\b(fatigue|fatiguee|creve|crevee|epuise|epuisee|claque|claquee|ko|hs)\b", normalized):
            state["energy"] = "low"
        if re.search(r"\b(pas envie de travailler|pas envie de bosser|je ne veux pas travailler|je veux pas travailler)\b", normalized):
            state["motivation"] = "low"
            state["wants_to_work"] = False
        if re.search(r"\b(stresse|stressee|anxieux|anxieuse|sous pression)\b", normalized):
            state["stress"] = "high"

        memory_items: list[MemoryItem] = []

        looks_question = (
            clean.endswith("?")
            or normalized.startswith(
                (
                    "qui ", "que ", "quoi ", "quand ", "comment ",
                    "pourquoi ", "combien ", "est-ce ", "est ce ",
                    "peux-tu ", "peux tu ",
                )
            )
        )

        addressed_to_agent = any(
            marker in normalized
            for marker in (
                "que tu ", "tu peux ", "peux-tu ", "peux tu ",
                "il faut que tu ", "je veux que tu ",
                "j'aimerais que tu ", "j aimerais que tu ",
            )
        )

        communication_preference = (
            not looks_question
            and any(
                marker in normalized
                for marker in (
                    "sois moins enjou", "sois plus calme", "sois plus direct",
                    "reponds-moi", "repond moi", "parle-moi", "parle moi",
                    "evite de me demander", "arrete de me demander",
                    "quand il est tard", "le soir sois", "la nuit sois",
                )
            )
        )
        if communication_preference:
            memory_items.append(
                MemoryItem(kind="preference", content=clean, confidence=0.82)
            )

        event_start = re.match(
            r"^(?:(?:hier|avant[ -]?hier|aujourd[' ]?hui|ce matin|cet apres[ -]?midi|ce soir|cette nuit)\s+)?"
            r"(?:j[' ]?ai\s+|je viens de\s+|je suis alle\s+|je suis allee\s+)",
            normalized,
        )
        if event_start and not looks_question and not addressed_to_agent:
            memory_items.append(
                MemoryItem(kind="episode", content=clean, confidence=0.68)
            )

        goal = "entertainment" if asks_entertainment else "casual_chat"
        pure_state_update = bool(state) and not (
            asks_entertainment or looks_question or addressed_to_agent
        )

        confidence = 0.84 if asks_entertainment else 0.35
        source = "deterministic" if asks_entertainment else "fallback"

        style = {
            "tone": "calm" if state.get("energy") == "low" else "neutral",
            "verbosity": "short" if state.get("energy") == "low" else "normal",
            "mention_state": bool(pure_state_update),
        }

        return Understanding(
            primary_intent="question" if looks_question and not asks_entertainment else "conversation",
            conversation_goal=goal,
            confidence=confidence,
            topic="",
            continues_previous_topic=None,
            work_requested=False,
            work_explicit=False,
            work_objective="",
            worker=None,
            work_confidence=0.0,
            memory_items=memory_items,
            user_state=state,
            response_style=style,
            pure_state_update=pure_state_update,
            reason=reason,
            source=source,
        )

    def analyze(self, message: str) -> Understanding:
        clean = self._clean(message)
        if not clean:
            return self._fallback(clean, reason="message vide")

        previous_topic = self.last_topic or "(aucun)"
        previous_message = self.last_message or "(aucun)"

        prompt = (
            "Analyse ce message utilisateur selon le schéma imposé.\n\n"
            "SUJET PRÉCÉDENT :\n"
            + previous_topic
            + "\n\nMESSAGE PRÉCÉDENT :\n"
            + previous_message[-500:]
            + "\n\nMESSAGE UTILISATEUR ACTUEL :\n"
            + clean
        )

        try:
            raw = self.llm.chat(prompt, system=self.SYSTEM_PROMPT)
        except Exception as exc:
            result = self._fallback(
                clean,
                reason=f"LLM indisponible : {type(exc).__name__}",
            )
            self._remember_turn(clean, result)
            return result

        payload = self._json_object(raw)
        if payload is None:
            result = self._fallback(clean, reason="JSON de compréhension invalide")
            self._remember_turn(clean, result)
            return result

        result = self._from_payload(payload)

        # V7.0.1 — une identité ou une question sur la mémoire ne peut jamais
        # devenir une mission, même si le petit modèle remplit mal son JSON.
        normalized = self._ascii(clean)
        if self._v701_personal_identity_message(clean):
            result.primary_intent = (
                "memory_query" if (clean.endswith("?") or "sais" in normalized or "memoire" in normalized)
                else "conversation"
            )
            result.work_requested = False
            result.work_explicit = False
            result.work_objective = ""
            result.worker = None
            result.work_confidence = 0.0
            result.learning_requested = False
            result.learning_subject = ""
            result.learning_confidence = 0.0
            result.confidence = max(result.confidence, 0.99)
            result.reason = "garde V7.0.1 : identité/mémoire personnelle"

        # Une mission d'apprentissage exige désormais une formulation
        # déterministe explicite. Un booléen halluciné par le LLM ne suffit pas.
        elif self._looks_like_learning_request(normalized):
            subject, objective = self._canonical_learning_objective(
                clean,
                fallback_subject=result.learning_subject,
            )

            result.primary_intent = "learning"
            result.learning_requested = True
            result.learning_subject = subject
            result.learning_confidence = max(
                result.learning_confidence,
                0.92,
            )
            result.work_requested = True
            result.work_explicit = True
            result.work_objective = objective
            result.worker = "researcher"
            result.work_confidence = max(
                result.work_confidence,
                0.92,
            )
            result.confidence = max(
                result.confidence,
                0.92,
            )
            result.reason = (
                str(result.reason or "").strip()
                + " | objectif d'apprentissage préservé depuis le message utilisateur"
            ).strip(" |")

        if result.work_requested and result.work_confidence < 0.58:
            result.work_requested = False
            result.work_explicit = False
            result.work_objective = ""
            result.worker = None
            result.learning_requested = False
            result.learning_subject = ""
            result.reason = (
                result.reason + " | demande de travail trop incertaine"
            ).strip(" |")

        # Filet de sécurité : si le LLM a raté une demande naturelle d'apprendre,
        # le détecteur déterministe reprend la main.
        normalized = self._ascii(clean)
        if not result.work_requested and self._looks_like_learning_request(normalized):
            fallback = self._fallback(
                clean,
                reason="rattrapage déterministe apprentissage",
            )
            if fallback.learning_requested:
                result = fallback

        # Une préférence de communication explicite doit rester mémorisable,
        # même si le LLM l'a classée comme simple conversation.
        fallback_memory = self._fallback(clean)
        if not any(item.kind == "preference" for item in result.memory_items):
            for item in fallback_memory.memory_items:
                if item.kind == "preference":
                    result.memory_items.append(item)

        # V6.2.1 : un événement personnel évident ne doit pas disparaître
        # simplement parce que le petit LLM a oublié de le mettre dans
        # memory_items. Le texte utilisateur brut reste la source de vérité.
        existing_episode_keys = {
            self._ascii(item.content).rstrip(" .!?,;:")
            for item in result.memory_items
            if item.kind == "episode"
        }
        for item in fallback_memory.memory_items:
            if item.kind != "episode":
                continue
            key = self._ascii(item.content).rstrip(" .!?,;:")
            if key not in existing_episode_keys:
                result.memory_items.append(item)
                existing_episode_keys.add(key)

        self._remember_turn(clean, result)
        return result

    def _remember_turn(self, message: str, result: Understanding) -> None:
        self.last_message = self._clean(message)
        if result.topic:
            self.last_topic = result.topic
