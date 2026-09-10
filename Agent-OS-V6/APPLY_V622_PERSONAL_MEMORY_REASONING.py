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
            and (candidate / "agentos" / "conversation.py").is_file()
            and (candidate / "agentos" / "memory.py").is_file()
        ):
            return candidate

    raise RuntimeError(
        "Impossible de trouver Agent-OS-V6. Place ce script dans Agent-OS-V6 "
        "ou lance-le depuis ce dossier."
    )


USER_CONTEXT_METHOD = r'''
    # =========================================================
    # USER-SOURCE CONTEXT V6.2.2
    # =========================================================

    def user_context_for(
        self,
        query: str = "",
        *,
        limit: int = 10,
    ) -> str:
        """Contexte composé uniquement des déclarations de l'utilisateur.

        Ce flux sert aux questions de mémoire personnelle. Les anciennes
        réponses de Paul restent dans le fil conversationnel normal mais ne
        peuvent plus devenir des preuves sur la vie de l'utilisateur.
        """
        with self.lock:
            self._rotate_if_idle()
            current = self._current()
            query_state = self.transient_state_kind(query)

            source = [
                item
                for item in current.get("messages", [])
                if (
                    isinstance(item, dict)
                    and str(item.get("role", "")).strip().lower() == "user"
                )
            ]

            if query_state is None:
                source = [
                    item
                    for item in source
                    if self._message_kind(item) != "transient_state"
                ]
            else:
                source = [
                    item
                    for item in source
                    if (
                        self._message_kind(item) != "transient_state"
                        or str(item.get("state_kind", "")) == query_state
                    )
                ]

            messages = source[-max(1, int(limit)):]

            if not messages:
                return "(aucune déclaration utilisateur dans le fil actif)"

            lines = [
                "SOURCE UTILISATEUR UNIQUEMENT",
                "Les lignes ci-dessous sont des déclarations de l'utilisateur, "
                "pas des affirmations de Paul.",
                "Déclarations récentes :",
            ]

            for item in messages:
                content = self._clean(item.get("content", ""))
                if content:
                    lines.append(f"user: {content}")

            return "\n".join(lines)

'''


PERSONAL_REASONING_HELPERS = r'''
    # =========================================================
    # PERSONAL MEMORY REASONING V6.2.2
    # =========================================================

    @classmethod
    def _v622_reference_followup(
        cls,
        message: str,
    ) -> bool:
        normalized = cls._normalize(message)
        return bool(
            re.search(
                r"\b(?:elle|il|lui|elles|ils|son|sa|ses|leur|leurs)\b",
                normalized,
            )
            or normalized.startswith(
                (
                    "comment est elle ",
                    "comment est il ",
                    "ou est elle ",
                    "ou est il ",
                    "où est elle ",
                    "où est il ",
                    "quand est elle ",
                    "quand est il ",
                    "avec quoi est elle ",
                    "avec quoi est il ",
                )
            )
        )

    def _v622_recent_user_context(
        self,
        message: str,
        *,
        limit: int = 8,
    ) -> str:
        tracker = getattr(
            self,
            "conversation_tracker",
            None,
        )
        if tracker is None:
            return "(aucun fil utilisateur disponible)"

        try:
            return tracker.user_context_for(
                message,
                limit=limit,
            )
        except Exception:
            return "(fil utilisateur indisponible)"

    def _v622_private_followup_from_context(
        self,
        message: str,
    ) -> bool:
        """Relie 'elle/il/lui' au dernier contexte personnel utilisateur.

        Cette vérification a lieu avant toute recherche Web. Elle ne tente pas
        de résoudre le pronom : elle décide seulement que le Web est le mauvais
        outil tant que le contexte privé peut contenir le référent.
        """
        if not self._v621_question_like(message):
            return False
        if self._v621_explicit_web_request(message):
            return False
        if not self._v622_reference_followup(message):
            return False

        recent = self._normalize(
            self._v622_recent_user_context(
                message,
                limit=8,
            )
        )
        if not recent:
            return False

        relation_markers = (
            "ma copine",
            "mon copain",
            "ma compagne",
            "mon compagnon",
            "ma femme",
            "mon mari",
            "ma mere",
            "ma mère",
            "mon pere",
            "mon père",
            "mon frere",
            "mon frère",
            "ma soeur",
            "ma sœur",
            "mon ami",
            "mon amie",
            "mes parents",
        )

        if any(marker in recent for marker in relation_markers):
            return True

        for name in self._v621_known_person_names():
            if name and re.search(
                rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])",
                recent,
            ):
                return True

        return False

    def _v622_personal_reasoning_context(
        self,
        message: str,
    ) -> str:
        if not self._v621_is_personal_memory_query(message):
            return (
                "NON — ce tour n'est pas un rappel personnel."
            )

        try:
            focused = self.memory.relevant_personal_summary(
                message,
                limit=10,
            )
        except Exception:
            focused = None

        user_context = self._v622_recent_user_context(
            message,
            limit=10,
        )

        return (
            "OUI — RAISONNEMENT SUR MÉMOIRE PERSONNELLE.\n"
            "Règle de preuve : seules les déclarations utilisateur et les "
            "souvenirs personnels structurés peuvent servir de faits. Les "
            "anciennes réponses de Paul ne sont jamais des souvenirs vécus.\n\n"
            "SOUVENIRS CIBLÉS :\n"
            + (focused or "(aucun souvenir structuré ciblé)")
            + "\n\nFIL UTILISATEUR UNIQUEMENT :\n"
            + user_context
        )

'''


def patch_conversation(text: str) -> str:
    if "# USER-SOURCE CONTEXT V6.2.2" in text:
        raise RuntimeError(
            "conversation.py semble déjà contenir V6.2.2."
        )

    marker = '''    def context_for(\n'''
    return replace_once(
        text,
        marker,
        USER_CONTEXT_METHOD + marker,
        "conversation.py / contexte utilisateur seulement",
    )


def patch_personal_manager(text: str) -> str:
    if "# PERSONAL MEMORY REASONING V6.2.2" in text:
        raise RuntimeError(
            "personal_manager.py semble déjà contenir V6.2.2."
        )
    if "# MEMORY-FIRST RECALL V6.2.1" not in text:
        raise RuntimeError(
            "personal_manager.py ne correspond pas à V6.2.1. "
            "Applique d'abord V6.2.1."
        )

    # 1) Les relances pronominales sur un proche ('elle', 'il', 'lui')
    # restent dans la sphère privée avant toute tentative de recherche Web.
    old_end = '''        if memory_evidence and (temporal or possessive):
            return True

        return False
'''
    new_end = '''        if memory_evidence and (temporal or possessive):
            return True

        # V6.2.2 : une relance comme "comment est-elle partie ?" peut ne plus
        # contenir le prénom. Si le fil utilisateur récent parle d'un proche,
        # on reste en mémoire privée au lieu d'envoyer le pronom sur le Web.
        if self._v622_private_followup_from_context(
            message
        ):
            return True

        return False
'''
    text = replace_once(
        text,
        old_end,
        new_end,
        "personal_manager.py / relances pronominales privées",
    )

    # 2) Ajoute les helpers V6.2.2 avant la section Research.
    research_marker = '''    # =========================================================
    # FACTUAL RESEARCH V4.9
    # =========================================================
'''
    text = replace_once(
        text,
        research_marker,
        PERSONAL_REASONING_HELPERS + research_marker,
        "personal_manager.py / helpers raisonnement personnel",
    )

    # 3) Pour un rappel privé, le fil utilisé par le LLM ne contient plus les
    # anciennes réponses de Paul. Cela supprime les faux souvenirs du type
    # "j'ai également vu le canard".
    old_thread = '''    def _v62_thread_context(
        self,
        message: str,
    ) -> str:
        understanding = getattr(
'''
    new_thread = '''    def _v62_thread_context(
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
    text = replace_once(
        text,
        old_thread,
        new_thread,
        "personal_manager.py / fil utilisateur pour rappel",
    )

    # 4) Expose explicitement les sources privées fiables au prompt.
    old_prompt = '''MODE DE RAPPEL PERSONNEL V6.2.1 :

{self._v621_personal_recall_context(message)}

FIL DE CONVERSATION ACTIF :
'''
    new_prompt = '''MODE DE RAPPEL PERSONNEL V6.2.1 :

{self._v621_personal_recall_context(message)}

RAISONNEMENT PERSONNEL V6.2.2 :

{self._v622_personal_reasoning_context(message)}

FIL DE CONVERSATION ACTIF :
'''
    text = replace_once(
        text,
        old_prompt,
        new_prompt,
        "personal_manager.py / sources privées dans prompt",
    )

    # 5) Renforce les règles de raisonnement : répondre à la propriété demandée,
    # inférer prudemment quand la conclusion est évidente, sinon demander.
    old_rules = '''RAPPEL PERSONNEL / VIE PRIVÉE
- Si MODE DE RAPPEL PERSONNEL V6.2.1 indique OUI, la question porte sur ce que
  l'utilisateur t'a raconté ou sur une personne de sa vie déjà mémorisée.
- Dans ce mode, la mémoire personnelle et le fil actif sont les seules sources
  autorisées. Ne cherche pas d'homonyme public et ne cite jamais Wikipédia,
  Google, un article ou une autre source Web pour répondre sur un proche.
- Si le rappel ciblé contient la réponse, donne-la directement et brièvement.
- Si la mémoire ne contient pas l'information demandée, dis simplement que tu
  ne t'en souviens pas. N'invente pas et ne remplace pas le proche par une
  personnalité publique portant le même prénom.
- Une date relative enregistrée dans un souvenir (hier, samedi, etc.) fait
  partie du souvenir et peut être utilisée pour répondre à une relance liée.
'''
    new_rules = '''RAPPEL PERSONNEL / VIE PRIVÉE
- Si MODE DE RAPPEL PERSONNEL V6.2.1 indique OUI, la question porte sur ce que
  l'utilisateur t'a raconté ou sur une personne de sa vie déjà mémorisée.
- Dans ce mode, MÉMOIRE PERSONNELLE et RAISONNEMENT PERSONNEL V6.2.2 sont les
  seules sources factuelles autorisées. Ne cherche jamais un homonyme public et
  ne cite jamais Wikipédia, Google, un article ou une autre source Web pour
  répondre sur un proche, sauf demande Web explicite de l'utilisateur.
- Une ancienne réponse de Paul n'est PAS un souvenir de l'utilisateur. Paul est
  un logiciel : il ne peut pas avoir vu un canard, accompagné Coralie, conduit,
  voyagé ou vécu physiquement un événement avec l'utilisateur.
- Réponds uniquement à l'information demandée. Si la question demande un lieu,
  donne le lieu pertinent ; ne récite pas tous les souvenirs du même jour.
- Tu peux faire une inférence simple lorsque les souvenirs la rendent très
  probable, mais indique clairement qu'il s'agit d'une déduction. Exemple :
  "tu l'as emmenée à l'aéroport pour partir en voyage" permet de répondre
  "probablement en avion" à "comment est-elle partie ?".
- Ne transforme jamais une déduction en certitude si le moyen exact n'a pas été
  dit explicitement.
- Si plusieurs souvenirs sont compatibles, choisis celui qui répond
  sémantiquement à la propriété demandée au lieu de tous les énumérer.
- Si la mémoire et le fil utilisateur ne suffisent pas pour répondre ou déduire
  raisonnablement, pose UNE question courte à l'utilisateur. Ne lance pas de
  recherche Internet pour combler une information privée manquante.
- Une date relative enregistrée dans un souvenir (hier, samedi, etc.) fait
  partie du souvenir et peut être utilisée pour répondre à une relance liée.
'''
    text = replace_once(
        text,
        old_rules,
        new_rules,
        "personal_manager.py / règles de raisonnement personnel",
    )

    return text


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_root(script_dir)

    personal_path = root / "agentos" / "personal_manager.py"
    conversation_path = root / "agentos" / "conversation.py"

    personal_original = personal_path.read_text(encoding="utf-8")
    conversation_original = conversation_path.read_text(encoding="utf-8")

    personal_new = patch_personal_manager(personal_original)
    conversation_new = patch_conversation(conversation_original)

    validation_dir = script_dir / ".v622_validation"
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    validation_dir.mkdir(parents=True)

    try:
        files = {
            "personal_manager.py": personal_new,
            "conversation.py": conversation_new,
        }
        for name, content in files.items():
            path = validation_dir / name
            path.write_text(content, encoding="utf-8")
            py_compile.compile(str(path), doraise=True)
    finally:
        shutil.rmtree(validation_dir, ignore_errors=True)

    # Écriture seulement après validation des deux fichiers complets.
    personal_path.write_text(personal_new, encoding="utf-8")
    conversation_path.write_text(conversation_new, encoding="utf-8")

    print("")
    print("Agent-OS V6.2.2 PERSONAL MEMORY REASONING appliqué.")
    print(f"Racine : {root}")
    print("")
    print("Fichiers modifiés :")
    print("- agentos/personal_manager.py")
    print("- agentos/conversation.py")
    print("")
    print("Corrections :")
    print("- paroles utilisateur séparées des anciennes réponses de Paul")
    print("- les réponses de Paul ne peuvent plus devenir des souvenirs vécus")
    print("- relances 'elle / il / lui' sur un proche restent en mémoire privée")
    print("- réponse centrée sur la propriété demandée : lieu, durée, moyen, etc.")
    print("- inférences prudentes autorisées : aéroport + voyage => probablement avion")
    print("- information privée manquante => question à l'utilisateur, jamais Web par défaut")
    print("")
    print("Redémarre complètement api_server.py avant les tests.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERREUR V6.2.2 : {exc}\n", file=sys.stderr)
        raise SystemExit(1)
