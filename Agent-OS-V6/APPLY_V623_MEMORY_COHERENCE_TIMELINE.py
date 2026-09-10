from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: motif attendu 1 fois, trouvé {count} fois. "
            "Aucun fichier n'a été modifié."
        )
    return text.replace(old, new, 1)


def find_root(script_dir: Path) -> Path:
    candidates = [
        script_dir,
        Path.cwd(),
        script_dir.parent,
        Path.cwd() / "Agent-OS-V6",
        script_dir.parent / "Agent-OS-V6",
    ]

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if (
            (candidate / "agentos" / "personal_manager.py").is_file()
            and (candidate / "agentos" / "memory.py").is_file()
            and (candidate / "agentos" / "conversation.py").is_file()
        ):
            return candidate

    raise RuntimeError(
        "Impossible de trouver Agent-OS-V6. Place ce script dans Agent-OS-V6 "
        "ou lance-le depuis ce dossier."
    )


MEMORY_TEMPORAL_HELPERS = r'''
    # =========================================================
    # EVENT TIMELINE V6.2.3
    # =========================================================

    @classmethod
    def _event_date_from_text(
        cls,
        text: str,
        *,
        reference_at: Any = None,
    ) -> str | None:
        """Résout une date d'événement quand le texte la rend explicite.

        La résolution se fait relativement au moment où le souvenir a été
        raconté. C'est essentiel pour les anciens épisodes : un ancien "hier"
        ne doit pas être recalculé par rapport à la date du prochain redémarrage.
        """
        normalized = cls._ascii(cls._clean_text(text))
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        normalized = " ".join(normalized.split())
        if not normalized:
            return None

        reference = cls._parse_time(reference_at) if reference_at else None
        if reference is None:
            reference = datetime.now().astimezone()
        else:
            try:
                reference = reference.astimezone()
            except Exception:
                pass

        base = reference.replace(
            hour=12,
            minute=0,
            second=0,
            microsecond=0,
        )

        # Expressions les plus précises d'abord.
        if re.search(r"\bavant hier\b", normalized):
            return (base - timedelta(days=2)).date().isoformat()

        if re.search(r"(?<!avant )\bhier\b", normalized):
            return (base - timedelta(days=1)).date().isoformat()

        if any(
            marker in normalized
            for marker in (
                "aujourd hui",
                "ce matin",
                "cet apres midi",
                "ce soir",
                "cette nuit",
            )
        ):
            return base.date().isoformat()

        if re.search(r"\bdemain\b", normalized):
            return (base + timedelta(days=1)).date().isoformat()

        number_words = {
            "un": 1,
            "une": 1,
            "deux": 2,
            "trois": 3,
            "quatre": 4,
            "cinq": 5,
            "six": 6,
            "sept": 7,
            "huit": 8,
            "neuf": 9,
            "dix": 10,
            "onze": 11,
            "douze": 12,
            "treize": 13,
            "quatorze": 14,
            "quinze": 15,
        }
        ago = re.search(
            r"\bil y a\s+(\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze)\s+jours?\b",
            normalized,
        )
        if ago:
            raw = ago.group(1)
            days = int(raw) if raw.isdigit() else number_words.get(raw)
            if days is not None:
                return (base - timedelta(days=days)).date().isoformat()

        weekdays = {
            "lundi": 0,
            "mardi": 1,
            "mercredi": 2,
            "jeudi": 3,
            "vendredi": 4,
            "samedi": 5,
            "dimanche": 6,
        }
        weekday_match = re.search(
            r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+dernier(?:e)?\b",
            normalized,
        )
        if weekday_match:
            target_weekday = weekdays[weekday_match.group(1)]
            delta = (base.weekday() - target_weekday) % 7
            if delta == 0:
                delta = 7
            return (base - timedelta(days=delta)).date().isoformat()

        return None

    def _attach_event_date(
        self,
        text: str,
    ) -> None:
        event_date = self._event_date_from_text(
            text,
            reference_at=self._now(),
        )
        if not event_date:
            return

        wanted = self._key(text)
        for item in reversed(self.data.get("episodic", [])[-60:]):
            if not isinstance(item, dict):
                continue
            if self._key(item.get("content", "")) != wanted:
                continue
            if item.get("event_date") != event_date:
                item["event_date"] = event_date
                self._save()
            return

    def _resolved_event_date(
        self,
        item: dict[str, Any],
    ) -> str | None:
        current = self._clean_text(
            item.get("event_date", "")
        )
        if current:
            return current

        content = self._clean_text(
            item.get("content", "")
        )
        if not content:
            return None

        resolved = self._event_date_from_text(
            content,
            reference_at=item.get("created_at"),
        )
        if resolved:
            item["event_date"] = resolved
            self._save()
        return resolved

    def latest_episodic_match(
        self,
        query: str,
    ) -> dict[str, Any] | None:
        """Retourne le dernier événement vécu correspondant à la requête.

        On compare la date de l'événement, pas la date à laquelle le souvenir
        a été raconté. Les anciens épisodes sans ``event_date`` sont résolus à
        la volée à partir de leur texte et de leur ``created_at``.
        """
        ignored = {
            "quand", "derniere", "dernier", "fois", "pour", "la", "le",
            "les", "est", "ce", "que", "jai", "j", "ai", "je", "tu",
            "me", "moi", "souviens", "rappelle", "date", "moment",
        }
        query_tokens = {
            token
            for token in self._expanded_tokens(query)
            if token not in ignored
        }
        if not query_tokens:
            query_tokens = self._expanded_tokens(query)
        if not query_tokens:
            return None

        candidates: list[tuple[int, int, float, int, dict[str, Any]]] = []

        for index, item in enumerate(self.data.get("episodic", [])):
            if not isinstance(item, dict):
                continue
            content = self._clean_text(item.get("content", ""))
            if not content:
                continue

            content_tokens = self._expanded_tokens(content)
            overlap = len(query_tokens & content_tokens)
            if overlap <= 0:
                continue

            event_date = self._resolved_event_date(item)
            event_rank = 0
            has_event_date = 0
            if event_date:
                try:
                    event_rank = int(event_date.replace("-", ""))
                    has_event_date = 1
                except ValueError:
                    event_rank = 0

            created = self._parse_time(item.get("created_at", ""))
            created_rank = created.timestamp() if created is not None else 0.0

            candidates.append(
                (
                    overlap,
                    has_event_date,
                    float(event_rank),
                    index,
                    {
                        **dict(item),
                        "event_date": event_date,
                        "created_rank": created_rank,
                    },
                )
            )

        if not candidates:
            return None

        # D'abord la meilleure correspondance sémantique. Parmi les souvenirs
        # aussi pertinents, le plus récent dans la chronologie vécue gagne.
        best_overlap = max(row[0] for row in candidates)
        relevant = [row for row in candidates if row[0] == best_overlap]
        relevant.sort(
            key=lambda row: (
                row[1],
                row[2],
                row[4].get("created_rank", 0.0),
                row[3],
            ),
            reverse=True,
        )
        result = dict(relevant[0][4])
        result.pop("created_rank", None)
        return result

'''


PERSONAL_V623_HELPERS = r'''
    # =========================================================
    # MEMORY COHERENCE / CHAT FRENCH V6.2.3
    # =========================================================

    @classmethod
    def _v623_chat_normalize(
        cls,
        message: str,
    ) -> str:
        """Normalise quelques formes naturelles/SMS sans corriger le message."""
        value = cls._normalize(message)
        replacements = (
            (r"\bjai\b", "j ai"),
            (r"\bjavais\b", "j avais"),
            (r"\bjetais\b", "j etais"),
            (r"\bjsuis\b", "je suis"),
            (r"\bjusqua\b", "jusqu a"),
            (r"\bcest\b", "c est"),
            (r"\bquest ce\b", "qu est ce"),
        )
        for pattern, replacement in replacements:
            value = re.sub(pattern, replacement, value)
        return " ".join(value.split())

    @classmethod
    def _v623_personal_statement(
        cls,
        message: str,
    ) -> bool:
        """Détecte une déclaration sur la vie de l'utilisateur.

        Une déclaration personnelle n'a aucune raison de déclencher une
        recherche Web automatique : le Web ne peut pas savoir ce que vient de
        vivre l'utilisateur.
        """
        if cls._v621_question_like(message):
            return False
        if cls._v621_explicit_web_request(message):
            return False

        normalized = cls._v623_chat_normalize(message)
        if not normalized:
            return False

        first_person = bool(
            re.search(
                r"\b(?:j ai|j avais|j etais|je suis|je vais|je viens|je pars|"
                r"je rentre|je retourne|je fais|je travaille|on a|nous avons)\b",
                normalized,
            )
        )
        relation = any(
            marker in normalized
            for marker in (
                "ma copine", "mon copain", "ma compagne", "mon compagnon",
                "ma femme", "mon mari", "ma mere", "mon pere", "ma soeur",
                "mon frere", "mon ami", "mon amie", "mes parents",
            )
        )
        temporal = bool(
            re.search(
                r"\b(?:aujourd hui|hier|avant hier|demain|ce matin|ce soir|"
                r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
                r"semaine derniere|mois dernier|il y a)\b",
                normalized,
            )
        )

        return first_person or (relation and temporal)

    def _v623_personal_statement_has_explicit_anchor(
        self,
        message: str,
    ) -> bool:
        normalized = self._v623_chat_normalize(message)
        relation = any(
            marker in normalized
            for marker in (
                "ma copine", "mon copain", "ma compagne", "mon compagnon",
                "ma femme", "mon mari", "ma mere", "mon pere", "ma soeur",
                "mon frere", "mon ami", "mon amie", "mes parents",
            )
        )
        if relation:
            return True

        for name in self._v621_known_person_names():
            if name and re.search(
                rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])",
                normalized,
            ):
                return True
        return False

    def _v623_timeline_context(
        self,
        message: str,
    ) -> str:
        normalized = self._v623_chat_normalize(message)
        asks_latest = any(
            marker in normalized
            for marker in (
                "derniere fois",
                "dernier fois",
                "la derniere fois",
                "pour la derniere fois",
            )
        )
        if not asks_latest:
            return "(aucune comparaison chronologique demandée)"

        try:
            item = self.memory.latest_episodic_match(message)
        except Exception:
            item = None

        if not isinstance(item, dict):
            return (
                "Aucun événement personnel correspondant n'a été retrouvé. "
                "Ne cherche pas sur le Web : demande à l'utilisateur si besoin."
            )

        content = str(item.get("content", "") or "").strip()
        event_date = str(item.get("event_date", "") or "").strip()
        return (
            "DERNIER ÉVÉNEMENT PERSONNEL CORRESPONDANT\n"
            f"- date de l'événement : {event_date or '(date exacte inconnue)'}\n"
            f"- souvenir utilisateur : {content}\n"
            "Cette date décrit quand l'événement s'est produit, pas quand il a "
            "été raconté. Utilise ce bloc comme source prioritaire."
        )

'''


def patch_memory(text: str) -> str:
    if "# EVENT TIMELINE V6.2.3" in text:
        raise RuntimeError("memory.py semble déjà contenir V6.2.3.")
    if "def maybe_remember_with_understanding(" not in text:
        raise RuntimeError(
            "memory.py ne correspond pas à V6.1+. Applique d'abord les versions précédentes."
        )

    text = replace_once(
        text,
        "from datetime import datetime, timezone\n",
        "from datetime import datetime, timedelta, timezone\n",
        "memory.py / import timedelta",
    )

    old_temporal = '''    @classmethod
    def _has_temporal_marker(cls, text: str) -> bool:
        """Détecte les marqueurs temporels comme des mots/expressions entiers.

        Évite notamment le faux positif historique : ``hier`` dans ``fichier``.
        """
        normalized = cls._ascii(cls._clean_text(text))
        for marker in cls.TEMPORAL_MARKERS:
            wanted = cls._ascii(marker)
            pattern = r"(?<![a-z0-9_])" + re.escape(wanted) + r"(?![a-z0-9_])"
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return True
        return False

'''
    new_temporal = '''    @classmethod
    def _has_temporal_marker(cls, text: str) -> bool:
        """Détecte les marqueurs temporels comme des mots/expressions entiers."""
        normalized = cls._ascii(cls._clean_text(text))
        for marker in cls.TEMPORAL_MARKERS:
            wanted = cls._ascii(marker)
            pattern = r"(?<![a-z0-9_])" + re.escape(wanted) + r"(?![a-z0-9_])"
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return True

        # V6.2.3 : couvre les formulations naturelles absentes de la liste
        # historique : "dimanche dernier", "mardi", "il y a 3 jours", etc.
        natural = re.sub(r"[^a-z0-9]+", " ", normalized)
        natural = " ".join(natural.split())
        if re.search(
            r"\\b(?:aujourd\\s+hui|avant\\s+hier|ce\\s+matin|ce\\s+soir|cette\\s+nuit|la\\s+semaine\\s+derniere|le\\s+mois\\s+dernier|ce\\s+week(?:end|-end)|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\\s+dernier(?:e)?)?\\b",
            natural,
        ):
            return True
        if re.search(
            r"\\bil y a\\s+(?:\\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze)\\s+(?:jour|jours|semaine|semaines|mois|an|ans)\\b",
            natural,
        ):
            return True
        return False

'''
    text = replace_once(
        text,
        old_temporal,
        new_temporal + MEMORY_TEMPORAL_HELPERS,
        "memory.py / chronologie des événements",
    )

    old_remember_episode = '''        self._remember_timeline(
            "episodic",
            text,
            kind=kind,
            source=source,
            confidence=confidence,
            limit=self.EPISODIC_LIMIT,
        )

    def remember_operational(
'''
    new_remember_episode = '''        self._remember_timeline(
            "episodic",
            text,
            kind=kind,
            source=source,
            confidence=confidence,
            limit=self.EPISODIC_LIMIT,
        )
        # V6.2.3 : mémorise aussi quand l'événement s'est réellement produit.
        self._attach_event_date(text)

    def remember_operational(
'''
    text = replace_once(
        text,
        old_remember_episode,
        new_remember_episode,
        "memory.py / event_date lors de l'enregistrement",
    )

    return text


def patch_personal_manager(text: str) -> str:
    if "# MEMORY COHERENCE / CHAT FRENCH V6.2.3" in text:
        raise RuntimeError("personal_manager.py semble déjà contenir V6.2.3.")
    if "# PERSONAL MEMORY REASONING V6.2.2" not in text:
        raise RuntimeError(
            "personal_manager.py ne correspond pas à V6.2.2. Applique d'abord V6.2.2."
        )

    # 1) Ajoute les helpers avant la recherche factuelle.
    research_marker = '''    # =========================================================
    # FACTUAL RESEARCH V4.9
    # =========================================================
'''
    text = replace_once(
        text,
        research_marker,
        PERSONAL_V623_HELPERS + research_marker,
        "personal_manager.py / helpers V6.2.3",
    )

    # 2) Les formes 'jai/javais/jsuis' doivent être reconnues comme les formes
    # apostrophées dans le détecteur mémoire privé V6.2.1.
    old_normalize = '''        if self._v621_explicit_web_request(message):
            return False

        normalized = self._normalize(message)

        explicit_recall = any(
'''
    new_normalize = '''        if self._v621_explicit_web_request(message):
            return False

        # V6.2.3 : l'utilisateur écrit souvent naturellement sans apostrophe
        # (jai, javais, jsuis, jusqua). On normalise seulement pour l'intention.
        normalized = self._v623_chat_normalize(message)

        explicit_recall = any(
'''
    text = replace_once(
        text,
        old_normalize,
        new_normalize,
        "personal_manager.py / français conversationnel",
    )

    # 3) Aucune déclaration personnelle ne doit déclencher le Researcher.
    old_research_guard = '''        if self._v621_is_personal_memory_query(
            message
        ):
            return None

        gateway = getattr(
'''
    new_research_guard = '''        if (
            self._v621_is_personal_memory_query(message)
            or self._v623_personal_statement(message)
        ):
            # V6.2.3 : le Web ne peut pas confirmer la vie privée de
            # l'utilisateur. Les affirmations personnelles vont au Manager/
            # mémoire ; les questions personnelles vont au rappel mémoire.
            return None

        gateway = getattr(
'''
    text = replace_once(
        text,
        old_research_guard,
        new_research_guard,
        "personal_manager.py / zéro Web sur déclarations personnelles",
    )

    # 4) Isole un nouveau souvenir des anciennes réponses de Paul. Une relance
    # pronominale sans nom explicite garde toutefois le contexte utilisateur.
    old_thread = '''    def _v62_thread_context(
        self,
        message: str,
    ) -> str:
        # V6.2.2 — en mode rappel personnel, seules les paroles de l'utilisateur
        # servent de contexte factuel. Les réponses passées de Paul sont exclues.
        if (
            hasattr(self, "_v621_is_personal_memory_query")
            and self._v621_is_personal_memory_query(message)
        ):
            return self._v622_recent_user_context(
                message,
                limit=10,
            )

        understanding = getattr(
'''
    new_thread = '''    def _v62_thread_context(
        self,
        message: str,
    ) -> str:
        # V6.2.2+ — un rappel personnel utilise uniquement les paroles de
        # l'utilisateur comme preuve factuelle.
        if (
            hasattr(self, "_v621_is_personal_memory_query")
            and self._v621_is_personal_memory_query(message)
        ):
            return self._v622_recent_user_context(
                message,
                limit=12,
            )

        # V6.2.3 — une nouvelle déclaration personnelle autonome ne doit pas
        # réactiver une ancienne demande (ex. Londres/YAML). Si elle ne contient
        # qu'un pronom sans référent explicite, on garde le fil utilisateur seul.
        if self._v623_personal_statement(message):
            if (
                self._v622_reference_followup(message)
                and not self._v623_personal_statement_has_explicit_anchor(message)
            ):
                return self._v622_recent_user_context(
                    message,
                    limit=8,
                )
            return (
                "(NOUVELLE DÉCLARATION PERSONNELLE : ancien sujet masqué. "
                "Réponds uniquement au message courant et mémorise-le si utile.)"
            )

        understanding = getattr(
'''
    text = replace_once(
        text,
        old_thread,
        new_thread,
        "personal_manager.py / isolation d'un nouveau souvenir",
    )

    # 5) Injecte la chronologie résolue dans le prompt.
    old_prompt = '''RAISONNEMENT PERSONNEL V6.2.2 :

{self._v622_personal_reasoning_context(message)}

FIL DE CONVERSATION ACTIF :
'''
    new_prompt = '''RAISONNEMENT PERSONNEL V6.2.2 :

{self._v622_personal_reasoning_context(message)}

CHRONOLOGIE PERSONNELLE V6.2.3 :

{self._v623_timeline_context(message)}

FIL DE CONVERSATION ACTIF :
'''
    text = replace_once(
        text,
        old_prompt,
        new_prompt,
        "personal_manager.py / chronologie dans prompt",
    )

    # 6) Règles anti-contamination et 'dernière fois'.
    old_rules = '''- Si plusieurs souvenirs sont compatibles, choisis celui qui répond
  sémantiquement à la propriété demandée au lieu de tous les énumérer.
- Si la mémoire et le fil utilisateur ne suffisent pas pour répondre ou déduire
  raisonnablement, pose UNE question courte à l'utilisateur. Ne lance pas de
  recherche Internet pour combler une information privée manquante.
- Une date relative enregistrée dans un souvenir (hier, samedi, etc.) fait
  partie du souvenir et peut être utilisée pour répondre à une relance liée.
'''
    new_rules = '''- Si plusieurs souvenirs sont compatibles, choisis celui qui répond
  sémantiquement à la propriété demandée au lieu de tous les énumérer.
- Pour « la dernière fois », utilise en priorité CHRONOLOGIE PERSONNELLE V6.2.3.
  Compare la date à laquelle les événements ont eu lieu, PAS l'ordre dans lequel
  l'utilisateur les a racontés.
- Les expressions « dimanche dernier », « mardi dernier », « il y a 3 jours »,
  etc. sont de vraies informations temporelles et doivent être mémorisées.
- Si la mémoire et le fil utilisateur ne suffisent pas pour répondre ou déduire
  raisonnablement, pose UNE question courte à l'utilisateur. Ne lance pas de
  recherche Internet pour combler une information privée manquante.
- Une date relative enregistrée dans un souvenir (hier, samedi, etc.) fait
  partie du souvenir et peut être utilisée pour répondre à une relance liée.
- Une nouvelle déclaration personnelle n'est jamais une invitation à reprendre
  une ancienne demande sans rapport. Réponds au nouveau message, puis arrête-toi.
'''
    text = replace_once(
        text,
        old_rules,
        new_rules,
        "personal_manager.py / règles chronologiques",
    )

    return text


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_root(script_dir)

    personal_path = root / "agentos" / "personal_manager.py"
    memory_path = root / "agentos" / "memory.py"

    personal_original = personal_path.read_text(encoding="utf-8")
    memory_original = memory_path.read_text(encoding="utf-8")

    # Prépare tout en mémoire : aucun fichier n'est écrit si un motif manque.
    personal_new = patch_personal_manager(personal_original)
    memory_new = patch_memory(memory_original)

    validation_dir = script_dir / ".v623_validation"
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    validation_dir.mkdir(parents=True)

    try:
        for name, content in {
            "personal_manager.py": personal_new,
            "memory.py": memory_new,
        }.items():
            path = validation_dir / name
            path.write_text(content, encoding="utf-8")
            py_compile.compile(str(path), doraise=True)
    finally:
        shutil.rmtree(validation_dir, ignore_errors=True)

    # Écriture seulement après validation syntaxique des deux fichiers complets.
    personal_path.write_text(personal_new, encoding="utf-8")
    memory_path.write_text(memory_new, encoding="utf-8")

    print("")
    print("Agent-OS V6.2.3 MEMORY COHERENCE + TIMELINE appliqué.")
    print(f"Racine : {root}")
    print("")
    print("Fichiers modifiés :")
    print("- agentos/personal_manager.py")
    print("- agentos/memory.py")
    print("")
    print("Corrections :")
    print("- 'jai/javais/jsuis/jusqua' compris par les détecteurs personnels")
    print("- déclarations personnelles : jamais de recherche Web automatique")
    print("- nouveau souvenir : ancien sujet conversationnel masqué")
    print("- dimanche dernier / jours de semaine / il y a N jours reconnus")
    print("- event_date mémorise la date réelle de l'événement")
    print("- 'dernière fois' compare la chronologie vécue, pas l'ordre des messages")
    print("- anciens épisodes relatifs sont résolus à la volée depuis created_at")
    print("")
    print("Redémarre complètement api_server.py avant les tests.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERREUR V6.2.3 : {exc}\n", file=sys.stderr)
        raise SystemExit(1)
