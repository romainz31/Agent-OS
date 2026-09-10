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
            (candidate / "agentos" / "memory.py").is_file()
            and (candidate / "agentos" / "personal_manager.py").is_file()
            and (candidate / "agentos" / "conversation.py").is_file()
        ):
            return candidate
    raise RuntimeError(
        "Impossible de trouver Agent-OS-V6. Place ce script dans Agent-OS-V6 "
        "ou lance-le depuis ce dossier."
    )


MEMORY_V63_HELPERS = r'''
    # =========================================================
    # PERSONAL MEMORY V2 / SQLITE V6.3
    # =========================================================

    def _personal_v2_known_people(self) -> list[str]:
        result: list[str] = []
        try:
            items = self.relational_active_items("relations")
        except Exception:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            value = self._clean_text(item.get("value", ""))
            if value and value not in result:
                result.append(value)
        return result

    def personal_memory_v2_observe(
        self,
        text: str,
    ) -> dict[str, Any] | None:
        store = getattr(self, "personal_v2", None)
        if store is None:
            return None
        try:
            if not store.looks_personal_statement(text):
                return None
            return store.remember_event(
                text,
                kind="user_event",
                source="user",
                confidence=0.92,
                recorded_at=self._now(),
            )
        except Exception:
            return None

    def personal_memory_v2_should_own(
        self,
        query: str,
    ) -> bool:
        store = getattr(self, "personal_v2", None)
        if store is None:
            return False
        try:
            return bool(store.looks_personal_query(query))
        except Exception:
            return False

    def personal_memory_v2_context(
        self,
        query: str,
        *,
        limit: int = 8,
    ) -> str:
        store = getattr(self, "personal_v2", None)
        if store is None:
            return "(mémoire personnelle V2 indisponible)"
        try:
            return store.context(query, limit=limit)
        except Exception as exc:
            return f"(mémoire personnelle V2 indisponible : {exc})"

    def personal_memory_v2_direct_answer(
        self,
        query: str,
        *,
        force: bool = False,
    ) -> str | None:
        store = getattr(self, "personal_v2", None)
        if store is None:
            return None
        try:
            if not force and not store.looks_personal_query(query):
                return None
            # direct_answer vérifie lui-même les questions privées. En mode
            # force (relance pronominale), on utilise une copie enrichie par le
            # fil utilisateur qui contient normalement un ancrage personnel.
            return store.direct_answer(query)
        except Exception:
            return None

    def personal_memory_v2_status(self) -> str:
        store = getattr(self, "personal_v2", None)
        if store is None:
            error = self.data.get("meta", {}).get(
                "personal_memory_v2_error"
            )
            if error:
                return (
                    "MÉMOIRE PERSONNELLE V2 indisponible.\n"
                    f"Erreur : {error}"
                )
            return "MÉMOIRE PERSONNELLE V2 indisponible."
        try:
            return store.status_summary()
        except Exception as exc:
            return f"MÉMOIRE PERSONNELLE V2 indisponible : {exc}"

'''


PERSONAL_MANAGER_V63_HELPERS = r'''
    # =========================================================
    # PERSONAL MEMORY V2 ROUTING V6.3
    # =========================================================

    def _v63_memory_store(self):
        return getattr(self.memory, "personal_v2", None)

    def _v63_last_user_statement(self) -> str | None:
        try:
            context = self._v622_recent_user_context(
                "",
                limit=10,
            )
        except Exception:
            return None

        lines = []
        for line in str(context or "").splitlines():
            line = line.strip()
            if line.lower().startswith("user:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    lines.append(value)
        return lines[-1] if lines else None

    def _v63_enriched_private_query(
        self,
        message: str,
    ) -> str:
        value = str(message or "").strip()
        try:
            followup = self._v622_reference_followup(value)
        except Exception:
            followup = False

        if not followup:
            return value

        last_user = self._v63_last_user_statement()
        if not last_user:
            return value

        return (
            value
            + "\nContexte utilisateur précédent : "
            + last_user
        )

    def _v63_personal_memory_owns(
        self,
        message: str,
    ) -> bool:
        try:
            if self.memory.personal_memory_v2_should_own(message):
                return True
        except Exception:
            pass

        try:
            if self._v622_private_followup_from_context(message):
                return True
        except Exception:
            pass

        try:
            if self._v621_is_personal_memory_query(message):
                return True
        except Exception:
            pass

        return False

    def _v63_personal_statement(
        self,
        message: str,
    ) -> bool:
        store = self._v63_memory_store()
        if store is None:
            try:
                return self._v623_personal_statement(message)
            except Exception:
                return False
        try:
            return bool(store.looks_personal_statement(message))
        except Exception:
            return False

    def _v63_personal_memory_context(
        self,
        message: str,
    ) -> str:
        query = self._v63_enriched_private_query(message)
        try:
            return self.memory.personal_memory_v2_context(
                query,
                limit=8,
            )
        except Exception:
            return "(mémoire personnelle V2 indisponible)"

    def _v63_direct_personal_answer(
        self,
        message: str,
    ) -> str | None:
        if not self._v63_personal_memory_owns(message):
            return None
        query = self._v63_enriched_private_query(message)
        store = self._v63_memory_store()
        if store is None:
            return None
        try:
            # L'enrichissement par le dernier message utilisateur permet à une
            # relance « comment est-elle partie ? » de retrouver Coralie sans
            # réintroduire les anciennes réponses de Paul.
            return store.direct_answer(query)
        except Exception:
            return None

    def _v63_memory_command_response(
        self,
        message: str,
    ) -> str | None:
        normalized = self._v623_chat_normalize(message)
        if normalized in {
            "memory v2",
            "memory v2 status",
            "memoire v2",
            "memoire v2 status",
            "personal memory v2",
        }:
            return self.memory.personal_memory_v2_status()

        prefixes = (
            "memory v2 search ",
            "memoire v2 cherche ",
            "memoire v2 recherche ",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                raw = str(message or "").strip()
                target = raw[len(prefix):].strip() if len(raw) >= len(prefix) else ""
                if not target:
                    return "Précise ce que tu veux rechercher dans la mémoire V2."
                return self.memory.personal_memory_v2_context(
                    target,
                    limit=12,
                )
        return None

'''


def patch_memory(text: str) -> str:
    if "# PERSONAL MEMORY V2 / SQLITE V6.3" in text:
        raise RuntimeError("memory.py semble déjà contenir V6.3.")
    if "# EVENT TIMELINE V6.2.3" not in text:
        raise RuntimeError(
            "memory.py ne correspond pas à V6.2.3. Applique d'abord V6.2.3."
        )

    text = replace_once(
        text,
        "from agentos.storage import JsonStore\n",
        "from agentos.storage import JsonStore\n"
        "from agentos.personal_memory_v2 import PersonalMemoryV2\n",
        "memory.py / import PersonalMemoryV2",
    )

    init_old = '''        self._prune_stale_emotional_current()\n        self._save()\n'''
    init_new = '''        self._prune_stale_emotional_current()\n        self._save()\n\n        # V6.3 : SQLite devient la source principale pour les événements\n        # personnels. Le JSON historique reste en dual-write pour compatibilité\n        # pendant la période de validation.\n        self.personal_v2 = None\n        try:\n            self.personal_v2 = PersonalMemoryV2(\n                DATA_DIR / "personal_memory.db",\n                known_people_provider=self._personal_v2_known_people,\n            )\n            migration = self.personal_v2.migrate_legacy(\n                self.data.get("episodic", [])\n            )\n            self.data.setdefault("meta", {})["personal_memory_v2"] = {\n                "schema_version": 2,\n                "migration_seen": migration.get("seen", 0),\n                "migration_imported": migration.get("imported", 0),\n                "updated_at": self._now(),\n            }\n            self.data.get("meta", {}).pop("personal_memory_v2_error", None)\n            self._save()\n        except Exception as exc:\n            self.personal_v2 = None\n            self.data.setdefault("meta", {})["personal_memory_v2_error"] = str(exc)\n            self._save()\n'''
    text = replace_once(
        text,
        init_old,
        init_new,
        "memory.py / initialisation SQLite V2",
    )

    selective_marker = '''    # =========================================================\n    # SELECTIVE RETRIEVAL\n    # =========================================================\n'''
    text = replace_once(
        text,
        selective_marker,
        MEMORY_V63_HELPERS + selective_marker,
        "memory.py / helpers V6.3",
    )

    dual_write_old = '''        # V6.2.3 : mémorise aussi quand l'événement s'est réellement produit.\n        self._attach_event_date(text)\n'''
    dual_write_new = '''        # V6.2.3 : mémorise aussi quand l'événement s'est réellement produit.\n        self._attach_event_date(text)\n\n        # V6.3 : dual-write vers la mémoire événementielle SQLite.\n        store = getattr(self, "personal_v2", None)\n        if store is not None:\n            try:\n                store.remember_event(\n                    text,\n                    kind=kind,\n                    source=source,\n                    confidence=confidence,\n                    recorded_at=self._now(),\n                )\n            except Exception:\n                pass\n'''
    text = replace_once(
        text,
        dual_write_old,
        dual_write_new,
        "memory.py / dual-write SQLite",
    )

    latest_old = '''        a été raconté. Les anciens épisodes sans ``event_date`` sont résolus à\n        la volée à partir de leur texte et de leur ``created_at``.\n        """\n        ignored = {\n'''
    latest_new = '''        a été raconté. Les anciens épisodes sans ``event_date`` sont résolus à\n        la volée à partir de leur texte et de leur ``created_at``.\n        """\n        # V6.3 : la base structurée SQLite est consultée en premier.\n        store = getattr(self, "personal_v2", None)\n        if store is not None:\n            try:\n                result = store.latest_match(query)\n            except Exception:\n                result = None\n            if isinstance(result, dict) and result:\n                # Compatibilité avec le format historique attendu par Paul.\n                return {\n                    "content": result.get("content", ""),\n                    "kind": result.get("kind", "user_event"),\n                    "source": result.get("source", "user"),\n                    "confidence": result.get("confidence", 0.9),\n                    "event_date": result.get("event_start"),\n                    "event_end": result.get("event_end"),\n                    "people": result.get("people", []),\n                    "places": result.get("places", []),\n                    "transport": result.get("transport"),\n                    "transport_inferred": result.get("transport_inferred", False),\n                    "created_at": result.get("recorded_at", ""),\n                }\n\n        ignored = {\n'''
    text = replace_once(
        text,
        latest_old,
        latest_new,
        "memory.py / latest via SQLite",
    )

    forget_old = '''        result["forgotten_values"] = sorted(forgotten_values)\n\n        if changed and persist:\n            self._save()\n'''
    forget_new = '''        result["forgotten_values"] = sorted(forgotten_values)\n\n        # V6.3 : un oubli explicite s'applique aussi à la base SQLite.\n        if persist:\n            store = getattr(self, "personal_v2", None)\n            if store is not None:\n                try:\n                    removed_v2 = int(store.forget(clean))\n                except Exception:\n                    removed_v2 = 0\n                if removed_v2 > 0:\n                    result["count"] += removed_v2\n                    if "personal_v2" not in result["categories"]:\n                        result["categories"].append("personal_v2")\n                    changed = True\n\n        if changed and persist:\n            self._save()\n'''
    text = replace_once(
        text,
        forget_old,
        forget_new,
        "memory.py / oubli SQLite",
    )

    return text


def patch_personal_manager(text: str) -> str:
    if "# PERSONAL MEMORY V2 ROUTING V6.3" in text:
        raise RuntimeError("personal_manager.py semble déjà contenir V6.3.")
    if "# MEMORY COHERENCE / CHAT FRENCH V6.2.3" not in text:
        raise RuntimeError(
            "personal_manager.py ne correspond pas à V6.2.3. "
            "Applique d'abord V6.2.3."
        )

    research_marker = '''    # =========================================================\n    # FACTUAL RESEARCH V4.9\n    # =========================================================\n'''
    text = replace_once(
        text,
        research_marker,
        PERSONAL_MANAGER_V63_HELPERS + research_marker,
        "personal_manager.py / helpers V6.3",
    )

    research_guard_old = '''        if (\n            self._v621_is_personal_memory_query(message)\n            or self._v623_personal_statement(message)\n        ):\n            # V6.2.3 : le Web ne peut pas confirmer la vie privée de\n            # l'utilisateur. Les affirmations personnelles vont au Manager/\n            # mémoire ; les questions personnelles vont au rappel mémoire.\n            return None\n\n        gateway = getattr(\n'''
    research_guard_new = '''        if (\n            self._v63_personal_memory_owns(message)\n            or self._v63_personal_statement(message)\n            or self._v621_is_personal_memory_query(message)\n            or self._v623_personal_statement(message)\n        ):\n            # V6.3 : une information sur la vie privée reste strictement dans\n            # Personal Memory V2 / conversation utilisateur. Le Web n'est\n            # autorisé que sur demande explicite.\n            return None\n\n        gateway = getattr(\n'''
    text = replace_once(
        text,
        research_guard_old,
        research_guard_new,
        "personal_manager.py / priorité mémoire V2 sur Web",
    )

    prompt_old = '''CHRONOLOGIE PERSONNELLE V6.2.3 :\n\n{self._v623_timeline_context(message)}\n\nFIL DE CONVERSATION ACTIF :\n'''
    prompt_new = '''CHRONOLOGIE PERSONNELLE V6.2.3 :\n\n{self._v623_timeline_context(message)}\n\nMÉMOIRE PERSONNELLE V2 / SQLITE V6.3 :\n\n{self._v63_personal_memory_context(message)}\n\nFIL DE CONVERSATION ACTIF :\n'''
    text = replace_once(
        text,
        prompt_old,
        prompt_new,
        "personal_manager.py / mémoire V2 dans prompt",
    )

    factual_marker = '''FIABILITÉ FACTUELLE\n'''
    v63_rules = '''MÉMOIRE PERSONNELLE V2 / V6.3\n- Pour les événements personnels, MÉMOIRE PERSONNELLE V2 / SQLITE V6.3 est la\n  source structurée prioritaire. Elle sépare la date vécue de la date où le\n  souvenir a été raconté.\n- Les personnes, lieux, sujets et bornes temporelles sont des index de recherche\n  complémentaires : n'utilise jamais un seul mot-clé comme unique preuve.\n- Les anciennes réponses de Paul ne sont jamais une source d'événements vécus.\n- Si une question personnelle n'a pas de réponse dans cette mémoire ni dans les\n  déclarations utilisateur du fil, pose une question courte à l'utilisateur.\n  N'utilise pas le Web pour remplir un trou de mémoire privée.\n- Une déduction structurée peut être utilisée si elle est explicitement marquée\n  comme déduite (ex. aéroport + départ en voyage => probablement avion).\n- Ne mélange jamais une ancienne demande de travail/recherche avec un nouveau\n  souvenir personnel simplement parce qu'ils partagent un lieu ou un mot.\n\n'''
    text = replace_once(
        text,
        factual_marker,
        v63_rules + factual_marker,
        "personal_manager.py / règles Memory V2",
    )

    handle_old = '''        research_response = self._research_response(value)\n        if research_response is not None:\n'''
    handle_new = '''        # V6.3 — commandes et journal personnel avant toute recherche Web.\n        memory_v2_command = self._v63_memory_command_response(value)\n        if memory_v2_command is not None:\n            self.memory.add_session("user", value)\n            self.memory.add_session("assistant", memory_v2_command)\n            self._track_exchange(value, memory_v2_command)\n            return memory_v2_command\n\n        if self._v63_personal_statement(value):\n            try:\n                self.memory.personal_memory_v2_observe(value)\n            except Exception:\n                pass\n\n        # Les questions personnelles simples dont la réponse est structurée\n        # peuvent être résolues sans LLM ni Web : date, lieu, fin de période,\n        # transport explicite/déduit.\n        direct_personal = self._v63_direct_personal_answer(value)\n        if direct_personal is not None:\n            self.memory.add_session("user", value)\n            self.memory.add_session("assistant", direct_personal)\n            self._track_exchange(value, direct_personal)\n            return direct_personal\n\n        research_response = self._research_response(value)\n        if research_response is not None:\n'''
    text = replace_once(
        text,
        handle_old,
        handle_new,
        "personal_manager.py / Memory V2 avant Researcher",
    )

    return text


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_root(script_dir)

    memory_path = root / "agentos" / "memory.py"
    personal_path = root / "agentos" / "personal_manager.py"
    payload_path = script_dir / "payload" / "personal_memory_v2.py"
    target_module = root / "agentos" / "personal_memory_v2.py"

    if not payload_path.is_file():
        raise RuntimeError("payload/personal_memory_v2.py manque dans le ZIP.")

    payload_text = payload_path.read_text(encoding="utf-8")
    if "class PersonalMemoryV2" not in payload_text:
        raise RuntimeError("Le payload Personal Memory V2 est invalide.")

    py_compile.compile(str(payload_path), doraise=True)

    memory_original = memory_path.read_text(encoding="utf-8")
    personal_original = personal_path.read_text(encoding="utf-8")

    memory_new = patch_memory(memory_original)
    personal_new = patch_personal_manager(personal_original)

    validation_dir = script_dir / ".v63_validation"
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    validation_dir.mkdir(parents=True)

    try:
        for name, content in {
            "memory.py": memory_new,
            "personal_manager.py": personal_new,
            "personal_memory_v2.py": payload_text,
        }.items():
            path = validation_dir / name
            path.write_text(content, encoding="utf-8")
            py_compile.compile(str(path), doraise=True)
    finally:
        shutil.rmtree(validation_dir, ignore_errors=True)

    # Écriture uniquement après validation syntaxique de l'ensemble.
    target_module.write_text(payload_text, encoding="utf-8")
    memory_path.write_text(memory_new, encoding="utf-8")
    personal_path.write_text(personal_new, encoding="utf-8")

    print("")
    print("Agent-OS V6.3 PERSONAL MEMORY V2 appliqué.")
    print(f"Racine : {root}")
    print("")
    print("Fichiers projet ajoutés/modifiés :")
    print("- agentos/personal_memory_v2.py  [nouveau]")
    print("- agentos/memory.py")
    print("- agentos/personal_manager.py")
    print("")
    print("Nouveau stockage créé au premier démarrage :")
    print("- data/personal_memory.db")
    print("")
    print("V6.3 :")
    print("- SQLite devient la source principale des événements personnels")
    print("- migration automatique des anciens souvenirs episodic")
    print("- event_start/event_end séparés de recorded_at")
    print("- index personnes / lieux / sujets / transport")
    print("- dates : hier, dimanche dernier, il y a N jours, semaine/mois dernier")
    print("- recherche privée avant Researcher / Web")
    print("- réponses déterministes possibles pour quand/où/jusqu'à quand")
    print("- inférence prudente de transport (aéroport + voyage => avion déduit)")
    print("- oubli explicite propagé à SQLite")
    print("- ancien episodic JSON conservé en compatibilité pendant validation")
    print("")
    print("Commande de contrôle après redémarrage : memory v2 status")
    print("Redémarre complètement api_server.py avant les tests.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERREUR V6.3 : {exc}\n", file=sys.stderr)
        raise SystemExit(1)
