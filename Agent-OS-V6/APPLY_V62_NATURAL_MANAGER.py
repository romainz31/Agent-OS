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
            (candidate / "agentos" / "manager.py").is_file()
            and (candidate / "agentos" / "personal_manager.py").is_file()
            and (candidate / "agentos" / "understanding.py").is_file()
        ):
            return candidate

    raise RuntimeError(
        "Impossible de trouver Agent-OS-V6. Place le contenu du ZIP dans "
        "Agent-OS-V6 ou lance ce script depuis ce dossier."
    )


MANAGER_UNDERSTANDING_OLD = '''        understanding = self.understanding.analyze(
            value
        )

        emotional_signals = (
'''

MANAGER_UNDERSTANDING_NEW = '''        understanding = self.understanding.analyze(
            value
        )

        # V6.2 — rend la compréhension du tour courant disponible à la
        # surcouche conversationnelle PersonalManager.
        self._current_understanding = understanding

        emotional_signals = (
'''

MANAGER_MISSION_OLD = '''        # New mission
        mission = self.orchestrator.create_mission(
            message=value,
'''

MANAGER_MISSION_NEW = '''        # New mission
        # V6.2 — le Planner reçoit l'objectif sémantique lorsqu'il existe.
        # Cela transforme par exemple « tu peux apprendre YAML ? » en une
        # vraie mission d'apprentissage actionnable, au lieu de lui faire
        # planifier une simple réponse conversationnelle.
        mission_message = value
        if (
            understanding.work_requested
            and str(understanding.work_objective or "").strip()
        ):
            mission_message = str(
                understanding.work_objective
            ).strip()

        mission = self.orchestrator.create_mission(
            message=mission_message,
'''


PERSONAL_HELPERS = r'''
    # =========================================================
    # NATURAL MANAGER V6.2
    # =========================================================

    def _v62_understanding_context(self) -> str:
        understanding = getattr(
            self,
            "_current_understanding",
            None,
        )
        if understanding is None:
            return "(compréhension V6.2 non disponible pour ce tour)"

        topic = str(
            getattr(understanding, "topic", "")
            or ""
        ).strip()
        continuity = getattr(
            understanding,
            "continues_previous_topic",
            None,
        )
        goal = str(
            getattr(understanding, "conversation_goal", "")
            or ""
        ).strip()
        primary = str(
            getattr(understanding, "primary_intent", "")
            or ""
        ).strip()

        if continuity is True:
            continuity_text = "oui"
        elif continuity is False:
            continuity_text = "non — nouveau sujet"
        else:
            continuity_text = "indéterminée"

        lines = [
            f"- intention : {primary or 'conversation'}",
            f"- but conversationnel : {goal or 'casual_chat'}",
            f"- sujet actuel : {topic or '(non identifié)'}",
            f"- continue le sujet précédent : {continuity_text}",
        ]

        learning_requested = bool(
            getattr(
                understanding,
                "learning_requested",
                False,
            )
        )
        if learning_requested:
            subject = str(
                getattr(
                    understanding,
                    "learning_subject",
                    "",
                )
                or ""
            ).strip()
            lines.append(
                "- apprentissage demandé : "
                + (subject or "oui")
            )

        return "\n".join(lines)

    def _v62_thread_context(
        self,
        message: str,
    ) -> str:
        understanding = getattr(
            self,
            "_current_understanding",
            None,
        )

        if (
            understanding is not None
            and getattr(
                understanding,
                "continues_previous_topic",
                None,
            ) is False
        ):
            topic = str(
                getattr(
                    understanding,
                    "topic",
                    "",
                )
                or ""
            ).strip()
            suffix = (
                f" Sujet actuel : {topic}."
                if topic
                else ""
            )
            return (
                "(NOUVEAU SUJET : l'ancien fil est volontairement masqué "
                "pour cette réponse. Ne reprends aucune ancienne discussion "
                "sans référence explicite de l'utilisateur.)"
                + suffix
            )

        return self.conversation_tracker.context_for(
            message,
            limit=10,
        )

    def _v62_communication_preferences(self) -> str:
        lines: list[str] = []

        try:
            structured = self.memory.relational_category_summary(
                "communication"
            )
        except Exception:
            structured = ""

        if structured:
            normalized = structured.lower()
            if not any(
                marker in normalized
                for marker in (
                    "aucune",
                    "vide",
                    "non renseign",
                )
            ):
                lines.append(structured)

        # V6.1 sait déjà stocker une préférence non reconnue par l'ancien
        # parseur relationnel dans long_term. V6.2 récupère aussi ces règles
        # de communication pour qu'elles s'appliquent à tous les sujets.
        communication_markers = (
            "répond",
            "repond",
            "parle",
            "ton ",
            "enjou",
            "direct",
            "blabla",
            "bla bla",
            "demande si ça va",
            "demande si ca va",
            "demander si ça va",
            "demander si ca va",
            "plus calme",
            "plus court",
            "moins enthousiaste",
            "enthousias",
        )

        extras: list[str] = []
        try:
            candidates = list(
                self.memory.data.get(
                    "long_term",
                    [],
                )
            )
        except Exception:
            candidates = []

        for item in reversed(candidates[-250:]):
            if not isinstance(item, dict):
                continue
            kind = str(
                item.get("kind", "")
                or ""
            ).lower()
            if kind not in {
                "preference",
                "communication",
                "communication_preference",
            }:
                continue
            content = str(
                item.get("content", "")
                or ""
            ).strip()
            normalized = content.lower()
            if not content or not any(
                marker in normalized
                for marker in communication_markers
            ):
                continue
            if content not in extras:
                extras.append(content)
            if len(extras) >= 8:
                break

        if extras:
            lines.append(
                "Préférences conversationnelles mémorisées :\n- "
                + "\n- ".join(extras)
            )

        return (
            "\n\n".join(lines)
            if lines
            else "(aucune préférence de communication spécifique)"
        )

    def _v62_response_style_context(self) -> str:
        now = datetime.now().astimezone()
        hour = now.hour

        if 0 <= hour < 6:
            daypart = "nuit"
            default_tone = "calme"
            default_length = "plutôt courte"
        elif 6 <= hour < 12:
            daypart = "matin"
            default_tone = "neutre"
            default_length = "normale"
        elif 12 <= hour < 18:
            daypart = "après-midi"
            default_tone = "neutre"
            default_length = "normale"
        else:
            daypart = "soir"
            default_tone = "calme"
            default_length = "normale à courte"

        understanding = getattr(
            self,
            "_current_understanding",
            None,
        )
        state = (
            getattr(understanding, "user_state", {})
            if understanding is not None
            else {}
        )
        style = (
            getattr(understanding, "response_style", {})
            if understanding is not None
            else {}
        )
        if not isinstance(state, dict):
            state = {}
        if not isinstance(style, dict):
            style = {}

        tone_map = {
            "calm": "calme",
            "neutral": "neutre",
            "dynamic": "dynamique",
        }
        verbosity_map = {
            "short": "courte",
            "normal": "normale",
            "detailed": "détaillée",
        }

        requested_tone = tone_map.get(
            str(style.get("tone", "")),
            default_tone,
        )
        requested_length = verbosity_map.get(
            str(style.get("verbosity", "")),
            default_length,
        )

        # La fatigue influence seulement le style. Elle ne devient jamais un
        # sujet de conversation sauf demande explicite du message courant.
        if state.get("energy") == "low":
            requested_tone = "calme"
            if str(style.get("verbosity", "")) != "detailed":
                requested_length = "courte"

        mention_state = bool(
            style.get(
                "mention_state",
                False,
            )
        )

        return (
            f"- heure locale : {now.strftime('%H:%M')} ({daypart})\n"
            f"- ton conseillé : {requested_tone}\n"
            f"- longueur conseillée : {requested_length}\n"
            f"- mentionner explicitement l'état émotionnel : "
            f"{'oui' if mention_state else 'non'}\n"
            "- règle : l'état adapte la forme, jamais le sujet\n\n"
            "PRÉFÉRENCES DURABLES DE COMMUNICATION :\n"
            + self._v62_communication_preferences()
        )

'''


def patch_manager(text: str) -> str:
    if "NATURAL MANAGER V6.2" in text:
        raise RuntimeError("manager.py semble déjà contenir V6.2.")
    if "UnderstandingEngine" not in text or "maybe_remember_with_understanding" not in text:
        raise RuntimeError(
            "manager.py ne ressemble pas à la V6.1. Applique d'abord V6.1."
        )

    text = replace_once(
        text,
        MANAGER_UNDERSTANDING_OLD,
        MANAGER_UNDERSTANDING_NEW,
        "manager.py / compréhension courante",
    )
    text = replace_once(
        text,
        MANAGER_MISSION_OLD,
        MANAGER_MISSION_NEW,
        "manager.py / objectif sémantique",
    )
    # Marqueur volontairement inoffensif pour détecter une double application.
    text = text.replace(
        "        # V6.2 — rend la compréhension du tour courant disponible",
        "        # NATURAL MANAGER V6.2 — rend la compréhension du tour courant disponible",
        1,
    )
    return text


def patch_personal_manager(text: str) -> str:
    if "# NATURAL MANAGER V6.2" in text:
        raise RuntimeError("personal_manager.py semble déjà contenir V6.2.")

    text = replace_once(
        text,
        "import re\n\nfrom typing import Any\n",
        "import re\nfrom datetime import datetime\n\nfrom typing import Any\n",
        "personal_manager.py / import datetime",
    )

    insertion_marker = '''        cleaned = " ".join(kept).strip()
        return cleaned or raw

    def _conversation(
'''
    text = replace_once(
        text,
        insertion_marker,
        '''        cleaned = " ".join(kept).strip()
        return cleaned or raw

''' + PERSONAL_HELPERS + '''    def _conversation(
''',
        "personal_manager.py / helpers V6.2",
    )

    old_context = '''FIL DE CONVERSATION ACTIF :

{self.conversation_tracker.context_for(message, limit=10)}

ÉTAT AGENT-OS :
'''
    new_context = '''COMPRÉHENSION DU MESSAGE COURANT :

{self._v62_understanding_context()}

STYLE DE RÉPONSE V6.2 :

{self._v62_response_style_context()}

FIL DE CONVERSATION ACTIF :

{self._v62_thread_context(message)}

ÉTAT AGENT-OS :
'''
    text = replace_once(
        text,
        old_context,
        new_context,
        "personal_manager.py / contexte conversation",
    )

    old_rules = '''- N'ouvre pas un ancien sujet juste parce qu'il apparaît dans la conversation
  récente.
- Ne reparle pas d'une ancienne mission dans une conversation personnelle si
  l'utilisateur ne l'a pas demandée.
'''
    new_rules = '''- N'ouvre pas un ancien sujet juste parce qu'il apparaît dans la conversation
  récente.
- Si COMPRÉHENSION DU MESSAGE COURANT indique « nouveau sujet », ignore le
  contenu de l'ancien sujet. Ne complète jamais spontanément la réponse avec
  YAML, Agent-OS, une mission ou tout autre thème précédent.
- Le message courant et son sujet sont toujours prioritaires sur le fil.
- Ne reparle pas d'une ancienne mission dans une conversation personnelle si
  l'utilisateur ne l'a pas demandée.
'''
    text = replace_once(
        text,
        old_rules,
        new_rules,
        "personal_manager.py / isolation des sujets",
    )

    old_french = "- Réponds naturellement en français et tutoie toujours l'utilisateur.\n"
    new_french = '''- Réponds uniquement en français, sauf si l'utilisateur demande explicitement
  une autre langue. Ne mélange jamais spontanément plusieurs langues.
- Tutoie toujours l'utilisateur.
- Évite l'enthousiasme forcé, les compliments automatiques et les réactions
  surjouées. Par défaut, parle comme un collègue calme, direct et naturel.
- Les préférences durables de communication priment sur ce style par défaut.
'''
    text = replace_once(
        text,
        old_french,
        new_french,
        "personal_manager.py / français et ton",
    )

    old_emotion = '''- Si le message courant ne parle pas explicitement de l'état de l'utilisateur,
  ne mentionne absolument pas sa fatigue, son repos, son énergie, son stress,
  sa motivation, son confort ou son bien-être.
'''
    new_emotion = '''- Si le message courant ne parle pas explicitement de l'état de l'utilisateur,
  ne mentionne absolument pas sa fatigue, son repos, son énergie, son stress,
  sa motivation, son confort ou son bien-être.
- Une fatigue mémorisée peut rendre le ton plus calme et la réponse plus courte,
  mais ne justifie jamais une question spontanée sur le sommeil, le repos ou
  « est-ce que ça va ? ».
- STYLE DE RÉPONSE V6.2 indique explicitement si l'état peut être mentionné.
'''
    text = replace_once(
        text,
        old_emotion,
        new_emotion,
        "personal_manager.py / émotion non intrusive",
    )

    return text


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_root(script_dir)

    manager_path = root / "agentos" / "manager.py"
    personal_path = root / "agentos" / "personal_manager.py"
    understanding_path = root / "agentos" / "understanding.py"
    payload_path = script_dir / "payload" / "understanding.py"

    if not payload_path.is_file():
        raise RuntimeError("payload/understanding.py manque dans le ZIP.")

    payload_text = payload_path.read_text(encoding="utf-8")
    if "Agent-OS V6.2" not in payload_text:
        raise RuntimeError("Le payload understanding.py n'est pas V6.2.")

    # Vérifie le payload AVANT toute modification de l'installation.
    py_compile.compile(str(payload_path), doraise=True)

    manager_original = manager_path.read_text(encoding="utf-8")
    personal_original = personal_path.read_text(encoding="utf-8")
    understanding_original = understanding_path.read_text(encoding="utf-8")

    if "Agent-OS V6.1" not in understanding_original and "Agent-OS V6.2" not in understanding_original:
        raise RuntimeError(
            "understanding.py ne correspond pas à V6.1. Applique d'abord V6.1."
        )

    manager_new = patch_manager(manager_original)
    personal_new = patch_personal_manager(personal_original)

    # Validation syntaxique sur des copies temporaires hors du projet.
    validation_dir = script_dir / ".v62_validation"
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    validation_dir.mkdir(parents=True)

    try:
        validation_files = {
            "manager.py": manager_new,
            "personal_manager.py": personal_new,
            "understanding.py": payload_text,
        }
        for name, content in validation_files.items():
            path = validation_dir / name
            path.write_text(content, encoding="utf-8")
            py_compile.compile(str(path), doraise=True)
    finally:
        shutil.rmtree(validation_dir, ignore_errors=True)

    # Toutes les validations ont réussi : écriture réelle seulement maintenant.
    manager_path.write_text(manager_new, encoding="utf-8")
    personal_path.write_text(personal_new, encoding="utf-8")
    understanding_path.write_text(payload_text, encoding="utf-8")

    print("")
    print("Agent-OS V6.2 NATURAL MANAGER appliqué.")
    print(f"Racine : {root}")
    print("")
    print("Modifications :")
    print("- compréhension du sujet courant et changement de sujet")
    print("- ancien sujet masqué lorsqu'un nouveau sujet commence")
    print("- 'apprends X' / 'tu peux apprendre X ?' devient une mission")
    print("- objectif sémantique transmis au Planner")
    print("- fatigue/état = adaptation du style, pas nouveau sujet")
    print("- heure locale utilisée pour calmer/adapter le ton")
    print("- préférences de communication durables injectées dans les réponses")
    print("- français strict et enthousiasme forcé réduit")
    print("")
    print("Redémarre api_server.py avant les tests.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERREUR V6.2 : {exc}\n", file=sys.stderr)
        raise SystemExit(1)
