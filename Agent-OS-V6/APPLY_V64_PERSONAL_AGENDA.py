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


V64_HELPERS = r'''
    # =========================================================
    # PERSONAL AGENDA / TODO V6.4
    # =========================================================

    def _v64_agenda_response(
        self,
        message: str,
    ) -> str | None:
        agenda = getattr(self, "agenda", None)
        if agenda is None:
            return None
        try:
            return agenda.handle_message(message)
        except Exception:
            return None

    def _v64_agenda_context(
        self,
        message: str,
    ) -> str:
        agenda = getattr(self, "agenda", None)
        if agenda is None:
            return "(agenda personnel indisponible)"
        try:
            return agenda.context_for(message)
        except Exception:
            return "(agenda personnel indisponible)"

'''


def patch_personal_manager(text: str) -> str:
    if "# PERSONAL AGENDA / TODO V6.4" in text:
        raise RuntimeError("personal_manager.py contient déjà V6.4.")

    if "# PERSONAL ACTOR IDENTITY / PRIVATE QUERY GUARD V6.3.1" not in text:
        raise RuntimeError(
            "personal_manager.py ne correspond pas à V6.3.1. "
            "Applique d'abord V6.3.1."
        )

    text = replace_once(
        text,
        "from typing import Any\n",
        "from typing import Any\n\n"
        "from agentos.agenda import PersonalAgenda\n"
        "from agentos.config import DATA_DIR\n",
        "personal_manager.py / imports agenda",
    )

    init_old = '''        super().__init__(*args, **kwargs)\n        self.conversation_tracker = ConversationTracker()\n'''
    init_new = '''        super().__init__(*args, **kwargs)\n\n        # V6.4 : agenda distinct de la mémoire personnelle et des missions.\n        # Une panne de l'agenda ne doit jamais empêcher Paul de démarrer.\n        self.agenda = None\n        try:\n            self.agenda = PersonalAgenda(\n                DATA_DIR / "agenda.db",\n                personal_memory_provider=lambda: getattr(\n                    self.memory,\n                    "personal_v2",\n                    None,\n                ),\n            )\n        except Exception:\n            self.agenda = None\n\n        self.conversation_tracker = ConversationTracker()\n'''
    text = replace_once(
        text,
        init_old,
        init_new,
        "personal_manager.py / initialisation agenda",
    )

    memory_actions_marker = '''    # =========================================================\n    # MEMORY ACTIONS\n    # =========================================================\n'''
    text = replace_once(
        text,
        memory_actions_marker,
        V64_HELPERS + memory_actions_marker,
        "personal_manager.py / helpers agenda",
    )

    prompt_old = '''MÉMOIRE PERSONNELLE V2 / SQLITE V6.3 :\n\n{self._v63_personal_memory_context(message)}\n\nFIL DE CONVERSATION ACTIF :\n'''
    prompt_new = '''MÉMOIRE PERSONNELLE V2 / SQLITE V6.3 :\n\n{self._v63_personal_memory_context(message)}\n\nAGENDA PERSONNEL V6.4 :\n\n{self._v64_agenda_context(message)}\n\nFIL DE CONVERSATION ACTIF :\n'''
    text = replace_once(
        text,
        prompt_old,
        prompt_new,
        "personal_manager.py / agenda dans contexte",
    )

    rules_marker = '''MÉMOIRE PERSONNELLE V2 / V6.3\n'''
    agenda_rules = '''AGENDA PERSONNEL / V6.4\n- Une liste de choses que l'utilisateur dit devoir faire est une TODO LIST,\n  pas une demande de mission Agent-OS et pas une recherche Internet.\n- Les tâches, rendez-vous et événements planifiés sont trois catégories\n  distinctes. Ne les mélange pas.\n- « mon programme aujourd'hui/demain » doit réunir les rendez-vous, les tâches\n  ouvertes et les événements notables du jour.\n- Une tâche terminée ne doit plus apparaître dans « ce qu'il me reste à faire ».\n- Une tâche personnelle (« je dois nettoyer le filtre ») concerne l'utilisateur.\n  Une demande adressée à Paul (« refais-moi mon dashboard ») reste une mission.\n- N'utilise jamais le Web pour expliquer une tâche que l'utilisateur est\n  simplement en train d'ajouter à son agenda.\n\n'''
    text = replace_once(
        text,
        rules_marker,
        agenda_rules + rules_marker,
        "personal_manager.py / règles agenda",
    )

    handle_marker = '''        # V6.3 — commandes et journal personnel avant toute recherche Web.\n        memory_v2_command = self._v63_memory_command_response(value)\n'''
    handle_new = '''        # V6.4 — agenda AVANT mémoire personnelle, Researcher et missions.\n        # Ainsi « aujourd'hui il faut que je fasse... » devient une liste de\n        # tâches personnelle et ne peut pas être interprété comme une recherche.\n        agenda_response = self._v64_agenda_response(value)\n        if agenda_response is not None:\n            self.memory.add_session("user", value)\n            self.memory.add_session("assistant", agenda_response)\n            self._track_exchange(value, agenda_response)\n            return agenda_response\n\n        # V6.3 — commandes et journal personnel avant toute recherche Web.\n        memory_v2_command = self._v63_memory_command_response(value)\n'''
    text = replace_once(
        text,
        handle_marker,
        handle_new,
        "personal_manager.py / agenda avant mémoire et Web",
    )

    return text


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_root(script_dir)

    personal_path = root / "agentos" / "personal_manager.py"
    agenda_target = root / "agentos" / "agenda.py"
    payload_path = script_dir / "payload" / "agenda.py"

    if not payload_path.is_file():
        raise RuntimeError("payload/agenda.py manque dans le ZIP.")

    agenda_text = payload_path.read_text(encoding="utf-8")
    if "class PersonalAgenda" not in agenda_text or "SCHEMA_VERSION = 1" not in agenda_text:
        raise RuntimeError("Le payload agenda V6.4 est invalide.")

    personal_original = personal_path.read_text(encoding="utf-8")
    if agenda_target.exists():
        existing = agenda_target.read_text(encoding="utf-8", errors="ignore")
        if "class PersonalAgenda" in existing:
            raise RuntimeError("agentos/agenda.py existe déjà. V6.4 semble déjà appliquée.")

    personal_new = patch_personal_manager(personal_original)

    # Validation syntaxique complète avant toute écriture projet.
    validation_dir = script_dir / ".v64_validation"
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    validation_dir.mkdir(parents=True)

    try:
        temp_personal = validation_dir / "personal_manager.py"
        temp_agenda = validation_dir / "agenda.py"
        temp_personal.write_text(personal_new, encoding="utf-8")
        temp_agenda.write_text(agenda_text, encoding="utf-8")
        py_compile.compile(str(temp_personal), doraise=True)
        py_compile.compile(str(temp_agenda), doraise=True)
    finally:
        shutil.rmtree(validation_dir, ignore_errors=True)

    # Écriture seulement après validation.
    agenda_target.write_text(agenda_text, encoding="utf-8")
    personal_path.write_text(personal_new, encoding="utf-8")

    print("=" * 68)
    print("Agent-OS V6.4 — PERSONAL AGENDA / TODO appliqué.")
    print("=" * 68)
    print()
    print("Fichiers projet ajoutés/modifiés :")
    print("- agentos/agenda.py  [nouveau]")
    print("- agentos/personal_manager.py")
    print()
    print("Nouveau stockage créé au redémarrage :")
    print("- data/agenda.db")
    print()
    print("Fonctions principales :")
    print("- tâches datées : aujourd'hui, demain, dans N jours, date précise")
    print("- rendez-vous séparés des tâches")
    print("- événements notables séparés")
    print("- programme journalier fusionné")
    print("- tâches terminées / reste à faire")
    print("- agenda traité avant Researcher et missions")
    print()
    print("Redémarre ensuite :")
    print(r"python -u .\api_server.py")
    print()
    print("Test de départ :")
    print("aujourdhui il faut que je fasse : remettre du terrau aux papyrus, nettoyer le filtre de l'aquarium, manucure")
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERREUR V6.4 : {exc}\n", file=sys.stderr)
        raise SystemExit(1)
