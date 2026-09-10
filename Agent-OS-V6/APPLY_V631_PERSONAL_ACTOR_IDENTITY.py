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
            and (candidate / "agentos" / "personal_memory_v2.py").is_file()
        ):
            return candidate

    raise RuntimeError(
        "Impossible de trouver Agent-OS-V6. Place ce script dans "
        "Agent-OS-V6 ou lance-le depuis ce dossier."
    )


V631_HELPERS = r'''
    # =========================================================
    # PERSONAL ACTOR IDENTITY / PRIVATE QUERY GUARD V6.3.1
    # =========================================================

    def _v631_private_query_guard(
        self,
        message: str,
    ) -> bool:
        """Protège les questions sur la vie privée avant toute recherche Web."""
        store = self._v63_memory_store()

        if store is not None:
            try:
                if store.explicit_web_request(message):
                    return False
            except Exception:
                pass

            try:
                if store.looks_personal_query(message):
                    return True
            except Exception:
                pass

        try:
            if self._v63_personal_memory_owns(message):
                return True
        except Exception:
            pass

        try:
            if self._v621_is_personal_memory_query(message):
                return True
        except Exception:
            pass

        normalized = self._v623_chat_normalize(message)
        question_like = bool(
            normalized.startswith(
                (
                    "qui ",
                    "avec qui ",
                    "comment ",
                    "quand ",
                    "ou ",
                    "jusqu a quand ",
                )
            )
        )
        if not question_like:
            return False

        try:
            relations = self.memory.relational_active_items("relations")
        except Exception:
            relations = []

        for item in relations:
            if not isinstance(item, dict):
                continue
            person = str(item.get("value", "") or "").strip()
            if not person:
                continue
            wanted = self._v623_chat_normalize(person)
            if wanted and wanted in normalized:
                return True

        return False

    def _v631_private_fallback(
        self,
        message: str,
    ) -> str:
        """Répond sans Web quand la mémoire privée ne suffit pas."""
        normalized = self._v623_chat_normalize(message)

        if normalized.startswith("avec qui "):
            return (
                "Tu ne me l'as pas dit, ou je ne l'ai pas retrouvé "
                "dans ta mémoire personnelle. Avec qui est-elle partie ?"
            )

        return self._conversation(message)

'''


def patch_personal_manager(text: str) -> str:
    if "# PERSONAL ACTOR IDENTITY / PRIVATE QUERY GUARD V6.3.1" in text:
        raise RuntimeError("personal_manager.py contient déjà V6.3.1.")

    if "# PERSONAL MEMORY V2 ROUTING V6.3" not in text:
        raise RuntimeError(
            "personal_manager.py ne correspond pas à V6.3. "
            "Applique d'abord V6.3."
        )

    research_marker = '''    # =========================================================
    # FACTUAL RESEARCH V4.9
    # =========================================================
'''
    text = replace_once(
        text,
        research_marker,
        V631_HELPERS + research_marker,
        "personal_manager.py / helpers V6.3.1",
    )

    research_guard_old = '''        if (
            self._v63_personal_memory_owns(message)
            or self._v63_personal_statement(message)
            or self._v621_is_personal_memory_query(message)
            or self._v623_personal_statement(message)
        ):
'''
    research_guard_new = '''        if (
            self._v631_private_query_guard(message)
            or self._v63_personal_memory_owns(message)
            or self._v63_personal_statement(message)
            or self._v621_is_personal_memory_query(message)
            or self._v623_personal_statement(message)
        ):
'''
    text = replace_once(
        text,
        research_guard_old,
        research_guard_new,
        "personal_manager.py / garde Web V6.3.1",
    )

    v63_rule_old = '''- Les anciennes réponses de Paul ne sont jamais une source d'événements vécus.
- Si une question personnelle n'a pas de réponse dans cette mémoire ni dans les
'''
    v63_rule_new = '''- Les anciennes réponses de Paul ne sont jamais une source d'événements vécus.
- Les phrases en « je / j'ai / je suis » présentes dans les souvenirs ont été
  écrites par l'utilisateur. Elles décrivent donc L'UTILISATEUR, jamais Paul.
  Quand tu les reformules, utilise « tu / tu as / tu es ». Ne dis jamais
  « j'ai emmené », « j'ai vu », « je suis allé » pour une action de l'utilisateur.
- Les faits structurés suivent la forme sujet -> action -> objet. Si le sujet
  vaut « toi », l'acteur est l'utilisateur.
- Si une question personnelle n'a pas de réponse dans cette mémoire ni dans les
'''
    text = replace_once(
        text,
        v63_rule_old,
        v63_rule_new,
        "personal_manager.py / identité grammaticale",
    )

    handle_old = '''        direct_personal = self._v63_direct_personal_answer(value)
        if direct_personal is not None:
            self.memory.add_session("user", value)
            self.memory.add_session("assistant", direct_personal)
            self._track_exchange(value, direct_personal)
            return direct_personal

        research_response = self._research_response(value)
'''
    handle_new = '''        direct_personal = self._v63_direct_personal_answer(value)
        if direct_personal is not None:
            self.memory.add_session("user", value)
            self.memory.add_session("assistant", direct_personal)
            self._track_exchange(value, direct_personal)
            return direct_personal

        # V6.3.1 : une question privée ne part jamais chez Researcher juste
        # parce que la réponse structurée exacte manque.
        if self._v631_private_query_guard(value):
            private_response = self._v631_private_fallback(value)
            self.memory.add_session("user", value)
            self.memory.add_session("assistant", private_response)
            self._track_exchange(value, private_response)
            return private_response

        research_response = self._research_response(value)
'''
    text = replace_once(
        text,
        handle_old,
        handle_new,
        "personal_manager.py / priorité privée absolue",
    )

    return text


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_root(script_dir)

    personal_path = root / "agentos" / "personal_manager.py"
    memory_v2_path = root / "agentos" / "personal_memory_v2.py"
    payload_path = script_dir / "payload" / "personal_memory_v2.py"

    if not payload_path.is_file():
        raise RuntimeError("payload/personal_memory_v2.py manque dans le ZIP.")

    personal_text = personal_path.read_text(encoding="utf-8")
    old_module_text = memory_v2_path.read_text(encoding="utf-8")
    new_module_text = payload_path.read_text(encoding="utf-8")

    if "SCHEMA_VERSION = 3" not in new_module_text:
        raise RuntimeError("Le payload n'est pas Personal Memory V2 V6.3.1.")

    if "# PERSONAL MEMORY V2 ROUTING V6.3" not in personal_text:
        raise RuntimeError("La base installée n'est pas V6.3.")

    if "SCHEMA_VERSION = 2" not in old_module_text:
        if "SCHEMA_VERSION = 3" in old_module_text:
            raise RuntimeError("Personal Memory V2 semble déjà être en V6.3.1.")
        raise RuntimeError("personal_memory_v2.py ne correspond pas à V6.3.")

    patched_personal = patch_personal_manager(personal_text)

    temp_dir = script_dir / ".v631_validation"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    try:
        temp_personal = temp_dir / "personal_manager.py"
        temp_module = temp_dir / "personal_memory_v2.py"
        temp_personal.write_text(patched_personal, encoding="utf-8")
        temp_module.write_text(new_module_text, encoding="utf-8")
        py_compile.compile(str(temp_personal), doraise=True)
        py_compile.compile(str(temp_module), doraise=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    personal_path.write_text(patched_personal, encoding="utf-8")
    memory_v2_path.write_text(new_module_text, encoding="utf-8")

    print("=" * 68)
    print("Agent-OS V6.3.1 — PERSONAL ACTOR IDENTITY appliqué.")
    print("=" * 68)
    print()
    print("Fichiers modifiés :")
    print("- agentos/personal_manager.py")
    print("- agentos/personal_memory_v2.py")
    print()
    print("La base personal_memory.db est conservée.")
    print("Les faits acteur/action/objet sont reconstruits automatiquement")
    print("à partir des événements V6.3 existants au prochain démarrage.")
    print()
    print(r"Redémarre : python -u .\api_server.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERREUR V6.3.1 : {exc}\n", file=sys.stderr)
        raise SystemExit(1)
