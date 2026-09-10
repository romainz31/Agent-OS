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
            and (candidate / "agentos" / "understanding.py").is_file()
            and (candidate / "agentos" / "memory.py").is_file()
        ):
            return candidate

    raise RuntimeError(
        "Impossible de trouver Agent-OS-V6. Place le contenu du ZIP dans "
        "Agent-OS-V6 ou lance ce script depuis ce dossier."
    )


PERSONAL_RECALL_HELPERS = r'''
    # =========================================================
    # MEMORY-FIRST RECALL V6.2.1
    # =========================================================

    @classmethod
    def _v621_question_like(
        cls,
        message: str,
    ) -> bool:
        raw = str(message or "").strip()
        if not raw:
            return False

        normalized = cls._normalize(raw)
        if raw.endswith("?"):
            return True

        return normalized.startswith(
            (
                "qui ",
                "que ",
                "quoi ",
                "quel ",
                "quelle ",
                "quels ",
                "quelles ",
                "ou ",
                "où ",
                "quand ",
                "jusqu a quand ",
                "comment ",
                "pourquoi ",
                "combien ",
                "est ce que ",
                "est-ce que ",
                "tu te souviens ",
                "rappelle moi ",
                "rappelle-moi ",
            )
        )

    @classmethod
    def _v621_explicit_web_request(
        cls,
        message: str,
    ) -> bool:
        normalized = cls._normalize(message)
        return any(
            marker in normalized
            for marker in (
                "cherche sur internet",
                "recherche sur internet",
                "cherche sur le web",
                "recherche sur le web",
                "va voir sur internet",
                "verifie sur internet",
                "vérifie sur internet",
                "verifie sur le web",
                "vérifie sur le web",
                "google ",
                "sur internet pour moi",
            )
        )

    def _v621_known_person_names(self) -> set[str]:
        names: set[str] = set()

        try:
            items = self.memory.relational_active_items(
                "relations"
            )
        except Exception:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            value = self._normalize(
                str(item.get("value", "") or "")
            )
            if len(value) < 2:
                continue

            names.add(value)
            for token in value.split():
                token = token.strip(" .,!?:;()[]{}'\"")
                if len(token) >= 3:
                    names.add(token)

        return names

    def _v621_is_personal_memory_query(
        self,
        message: str,
    ) -> bool:
        """Détermine si la réponse doit venir de la mémoire privée.

        Une question sur la vie de l'utilisateur ou sur une personne connue
        ne doit jamais déclencher une recherche Web par défaut. L'utilisateur
        peut explicitement demander une recherche Internet pour lever ce garde.
        """
        if not self._v621_question_like(message):
            return False

        if self._v621_explicit_web_request(message):
            return False

        normalized = self._normalize(message)

        explicit_recall = any(
            marker in normalized
            for marker in (
                "tu te souviens",
                "te souviens tu",
                "je t ai dit",
                "je t avais dit",
                "je t ai raconte",
                "je t avais raconte",
                "qu est ce que je t ai dit",
                "qu est-ce que je t ai dit",
                "rappelle moi ce que",
                "rappelle-moi ce que",
                "d apres ce que je t ai dit",
                "d'après ce que je t'ai dit",
            )
        )
        if explicit_recall:
            return True

        first_person_past = bool(
            re.search(
                r"\b(?:j ai|j avais|j etais|je suis alle|je suis allee|"
                r"je t ai|je t avais|je faisais|on a|nous avons)\b",
                normalized,
            )
        )

        temporal = any(
            marker in normalized
            for marker in (
                "hier",
                "avant hier",
                "avant-hier",
                "aujourd hui",
                "aujourd'hui",
                "ce matin",
                "hier soir",
                "la semaine derniere",
                "la semaine dernière",
                "le mois dernier",
                "jusqu a quand",
                "jusqu'à quand",
            )
        )

        relation_anchor = any(
            marker in normalized
            for marker in (
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
        )

        known_person = any(
            name and re.search(
                rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])",
                normalized,
            )
            for name in self._v621_known_person_names()
        )

        try:
            memory_evidence = (
                self.memory.relevant_personal_summary(
                    message,
                    limit=8,
                )
                is not None
            )
        except Exception:
            memory_evidence = False

        possessive = bool(
            re.search(
                r"\b(?:mon|ma|mes|notre|nos)\b",
                normalized,
            )
        )

        if first_person_past:
            return True
        if relation_anchor:
            return True
        if known_person:
            return True
        if memory_evidence and (temporal or possessive):
            return True

        return False

    def _v621_personal_recall_context(
        self,
        message: str,
    ) -> str:
        if not self._v621_is_personal_memory_query(message):
            return (
                "NON — réponse normale. La recherche externe reste possible "
                "si elle est réellement nécessaire."
            )

        try:
            focused = self.memory.relevant_personal_summary(
                message,
                limit=8,
            )
        except Exception:
            focused = None

        if focused:
            return (
                "OUI — QUESTION SUR LA MÉMOIRE PERSONNELLE.\n"
                "Réponds d'abord avec les souvenirs ci-dessous. N'utilise "
                "aucune identité homonyme trouvée sur Internet.\n\n"
                "RAPPEL CIBLÉ :\n"
                + focused
            )

        return (
            "OUI — QUESTION SUR LA MÉMOIRE PERSONNELLE.\n"
            "Aucun souvenir ciblé n'a été retrouvé par l'index. Vérifie le "
            "fil actif et la mémoire personnelle fournis plus bas. Si la "
            "réponse n'y figure pas, dis simplement que tu ne t'en souviens pas."
        )

'''


def patch_personal_manager(text: str) -> str:
    if "# MEMORY-FIRST RECALL V6.2.1" in text:
        raise RuntimeError(
            "personal_manager.py semble déjà contenir V6.2.1."
        )

    if "# NATURAL MANAGER V6.2" not in text:
        raise RuntimeError(
            "personal_manager.py ne ressemble pas à V6.2. Applique d'abord V6.2."
        )

    insertion_marker = '''    # =========================================================
    # FACTUAL RESEARCH V4.9
    # =========================================================
'''
    text = replace_once(
        text,
        insertion_marker,
        PERSONAL_RECALL_HELPERS + insertion_marker,
        "personal_manager.py / helpers mémoire d'abord",
    )

    research_old = '''    def _research_response(
        self,
        message: str,
    ) -> str | None:
        gateway = getattr(
'''
    research_new = '''    def _research_response(
        self,
        message: str,
    ) -> str | None:
        # V6.2.1 — une question sur la vie privée de l'utilisateur ou sur une
        # personne mémorisée ne part jamais sur le Web par défaut.
        if self._v621_is_personal_memory_query(
            message
        ):
            return None

        gateway = getattr(
'''
    text = replace_once(
        text,
        research_old,
        research_new,
        "personal_manager.py / garde recherche Web",
    )

    prompt_old = '''STYLE DE RÉPONSE V6.2 :

{self._v62_response_style_context()}

FIL DE CONVERSATION ACTIF :
'''
    prompt_new = '''STYLE DE RÉPONSE V6.2 :

{self._v62_response_style_context()}

MODE DE RAPPEL PERSONNEL V6.2.1 :

{self._v621_personal_recall_context(message)}

FIL DE CONVERSATION ACTIF :
'''
    text = replace_once(
        text,
        prompt_old,
        prompt_new,
        "personal_manager.py / rappel ciblé dans prompt",
    )

    rules_old = '''FIABILITÉ FACTUELLE
- N'affirme pas comme certain un fait externe précis si le bloc de recherche
'''
    rules_new = '''RAPPEL PERSONNEL / VIE PRIVÉE
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

FIABILITÉ FACTUELLE
- N'affirme pas comme certain un fait externe précis si le bloc de recherche
'''
    text = replace_once(
        text,
        rules_old,
        rules_new,
        "personal_manager.py / règles rappel privé",
    )

    return text


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_root(script_dir)

    personal_path = root / "agentos" / "personal_manager.py"
    understanding_path = root / "agentos" / "understanding.py"
    payload_path = script_dir / "payload" / "understanding.py"

    if not payload_path.is_file():
        raise RuntimeError(
            "payload/understanding.py manque dans le ZIP."
        )

    payload_text = payload_path.read_text(encoding="utf-8")
    if "Agent-OS V6.2.1" not in payload_text:
        raise RuntimeError(
            "Le payload understanding.py n'est pas V6.2.1."
        )

    # Vérifie le nouveau moteur avant toute modification réelle.
    py_compile.compile(
        str(payload_path),
        doraise=True,
    )

    personal_original = personal_path.read_text(
        encoding="utf-8"
    )
    understanding_original = understanding_path.read_text(
        encoding="utf-8"
    )

    if "Agent-OS V6.2" not in understanding_original:
        raise RuntimeError(
            "understanding.py ne correspond pas à V6.2. Applique d'abord V6.2."
        )

    personal_new = patch_personal_manager(
        personal_original
    )

    # Validation syntaxique sur copies temporaires hors du projet.
    validation_dir = script_dir / ".v621_validation"
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    validation_dir.mkdir(parents=True)

    try:
        personal_tmp = validation_dir / "personal_manager.py"
        personal_tmp.write_text(
            personal_new,
            encoding="utf-8",
        )
        py_compile.compile(
            str(personal_tmp),
            doraise=True,
        )

        understanding_tmp = validation_dir / "understanding.py"
        understanding_tmp.write_text(
            payload_text,
            encoding="utf-8",
        )
        py_compile.compile(
            str(understanding_tmp),
            doraise=True,
        )
    finally:
        shutil.rmtree(
            validation_dir,
            ignore_errors=True,
        )

    # Écriture seulement après validation complète.
    personal_path.write_text(
        personal_new,
        encoding="utf-8",
    )
    understanding_path.write_text(
        payload_text,
        encoding="utf-8",
    )

    print("")
    print("Agent-OS V6.2.1 MEMORY-FIRST appliqué.")
    print(f"Racine : {root}")
    print("")
    print("Fichiers modifiés :")
    print("- agentos/personal_manager.py")
    print("- agentos/understanding.py")
    print("")
    print("Corrections :")
    print("- mémoire personnelle prioritaire avant la recherche Web")
    print("- les proches mémorisés ne sont plus recherchés comme personnes publiques")
    print("- rappel ciblé des épisodes récents et relations")
    print("- 'où est-ce que j'ai...' et 'jusqu'à quand Coralie...' deviennent des rappels")
    print("- capture renforcée des événements commençant par 'hier', 'ce matin', etc.")
    print("")
    print("Redémarre complètement api_server.py avant les tests.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"\nERREUR V6.2.1 : {exc}\n",
            file=sys.stderr,
        )
        raise SystemExit(1)
