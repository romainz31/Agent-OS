from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "overlay" / "usr" / "plugins"
sys.path.insert(0, str(PLUGIN_ROOT))

from agent_os_memory.helpers.store import PersonalMemoryStore  # noqa: E402


def migration_key(paths: Iterable[Path]) -> str:
    signature = "|".join(
        f"{path.resolve()}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for path in paths if path and path.exists()
    )
    return "v10:" + hashlib.sha256(signature.encode("utf-8")).hexdigest()


def migrate_agenda(path: Path, store: PersonalMemoryStore) -> int:
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    count = 0
    try:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agenda_items'"
        ).fetchone()
        if not exists:
            return 0
        for row in db.execute("SELECT * FROM agenda_items ORDER BY id"):
            item = dict(row)
            old_kind = str(item.get("kind") or "note")
            kind = {
                "todo": "task", "appointment": "appointment", "event": "event",
                "action": "action", "mood": "mood", "humeur": "mood",
            }.get(old_kind, "note")
            status = {
                "open": "pending", "todo": "pending", "done": "done",
                "scheduled": "scheduled", "logged": "logged",
                "cancelled": "cancelled",
            }.get(str(item.get("status") or ""), "")
            day = str(item.get("due_date") or "").strip()
            clock = str(item.get("start_time") or "").strip()
            moment = f"{day}T{clock or '00:00:00'}" if day else None
            metadata = _json_object(item.get("metadata_json"))
            metadata.update({"legacy_v10_id": item.get("id"), "legacy_kind": old_kind})
            store.capture(
                kind=kind,
                title=str(item.get("title") or "").strip(),
                status=status,
                start_at=moment if kind in {"appointment", "event"} else None,
                due_at=moment if kind == "task" else None,
                completed_at=item.get("completed_at") if kind in {"task", "action"} else None,
                date_precision="day" if day else "unknown",
                source_text=str(item.get("source_text") or item.get("title") or ""),
                metadata=metadata,
            )
            count += 1
    finally:
        db.close()
    return count


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _items(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item
    elif isinstance(value, dict):
        for category, entries in value.items():
            if isinstance(entries, list):
                for item in entries:
                    if isinstance(item, dict):
                        yield {"_category": category, **item}


def migrate_memory_json(path: Path, store: PersonalMemoryStore) -> int:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    count = 0

    profile = data.get("profile", {})
    if isinstance(profile, dict):
        for predicate, value in profile.items():
            if value in (None, "", [], {}):
                continue
            store.capture(
                kind="fact", title=f"{predicate}: {value}", subject="user",
                predicate=str(predicate), value=json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value),
                source_text=f"Migration V10 profile.{predicate}",
                metadata={"origin": "v10_memory_json"},
            )
            count += 1

    for section, kind in (
        ("relational", "preference"),
        ("long_term", "fact"),
        ("episodic", "note"),
        ("emotional", "mood"),
    ):
        for item in _items(data.get(section, [])):
            content = next(
                (str(item[key]) for key in ("content", "value", "text", "summary", "title") if item.get(key)),
                "",
            ).strip()
            if not content:
                continue
            if kind in {"fact", "preference"}:
                predicate = str(item.get("subject") or item.get("key") or item.get("_category") or section)
                store.capture(
                    kind=kind, title=content, subject="user", predicate=predicate,
                    value=content, source_text=content,
                    confidence=float(item.get("confidence", 0.8) or 0.8),
                    metadata={"origin": "v10_memory_json", "legacy": item},
                )
            else:
                store.capture(
                    kind=kind, title=content, source_text=content,
                    confidence=float(item.get("confidence", 0.8) or 0.8),
                    metadata={"origin": "v10_memory_json", "legacy": item},
                )
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Migration explicite Agent-OS V10 vers V11")
    parser.add_argument("--agenda", type=Path)
    parser.add_argument("--memory", type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()

    sources = [path for path in (args.agenda, args.memory) if path]
    if not sources:
        parser.error("Fournis --agenda et/ou --memory.")
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        parser.error("Fichier introuvable : " + ", ".join(missing))

    store = PersonalMemoryStore(args.target)
    key = migration_key(sources)
    if store.migration_applied(key):
        print("Migration déjà appliquée : aucune duplication.")
        return 0

    agenda_count = migrate_agenda(args.agenda, store) if args.agenda else 0
    memory_count = migrate_memory_json(args.memory, store) if args.memory else 0
    store.register_migration(
        key,
        {
            "agenda": str(args.agenda or ""), "memory": str(args.memory or ""),
            "agenda_records": agenda_count, "memory_records": memory_count,
            "finished_at": datetime.now().astimezone().isoformat(),
        },
    )
    print(f"Migration terminée : {agenda_count} éléments de timeline, {memory_count} souvenirs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
