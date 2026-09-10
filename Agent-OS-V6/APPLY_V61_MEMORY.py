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
            and (candidate / "agentos" / "memory.py").is_file()
            and (candidate / "agentos" / "router.py").is_file()
        ):
            return candidate

    raise RuntimeError(
        "Impossible de trouver la racine Agent-OS-V6. "
        "Place ce ZIP dans Agent-OS-V6 ou lance ce script depuis ce dossier."
    )


MEMORY_EXTENSION = r"""
    def maybe_remember_with_understanding(
        self,
        text: str,
        understanding: Any,
    ) -> dict[str, dict[str, Any]]:
        # V6.1 — ingestion mémoire guidée par UnderstandingEngine.
        self._last_memory_action = None

        forget_target = self.explicit_forget_fact(text)
        if forget_target is not None:
            self.forget_personal(
                forget_target,
                source="user_explicit",
                persist=True,
                track_action=True,
            )
            return {}

        operational = self._looks_operational_text(text)
        explicit = self._explicit_memory(text)

        if explicit or operational:
            return {}

        # Les couches déjà fiables de V4.7 restent actives.
        self._extract_profile(text)
        self._extract_relational(
            text,
            source="automatic",
            persist=True,
            track_action=True,
        )

        # D'abord l'extracteur émotionnel historique.
        emotional = self.observe_emotional_state(text)

        # Une phrase mixte terminée par "?" était historiquement considérée
        # comme une question entière et faisait perdre "je suis fatigué".
        # UnderstandingEngine peut compléter cet état sans court-circuiter
        # la demande conversationnelle.
        if not emotional:
            state = getattr(
                understanding,
                "user_state",
                {},
            )
            if isinstance(state, dict):
                allowed = {
                    "energy": {"low", "high"},
                    "motivation": {"low", "high"},
                    "stress": {"low", "moderate", "high"},
                    "mood": {"positive", "negative"},
                }

                signals: dict[str, dict[str, Any]] = {}

                for dimension, values in allowed.items():
                    raw_value = self._clean_text(
                        state.get(dimension, "")
                    ).lower()
                    if raw_value not in values:
                        continue

                    signals[dimension] = {
                        "value": raw_value,
                        "confidence": 0.82,
                    }

                if signals:
                    now = self._now()
                    source_text = self._clean_text(text)
                    current = self.data[
                        "emotional"
                    ].setdefault(
                        "current",
                        {},
                    )

                    for dimension, signal in signals.items():
                        current[dimension] = {
                            "value": signal["value"],
                            "confidence": signal["confidence"],
                            "observed_at": now,
                            "source": source_text,
                        }

                    self.data[
                        "emotional"
                    ].setdefault(
                        "history",
                        [],
                    ).append(
                        {
                            "at": now,
                            "source": source_text,
                            "signals": signals,
                        }
                    )
                    self.data["emotional"]["history"] = (
                        self.data["emotional"]["history"][
                            -self.EMOTIONAL_HISTORY_LIMIT:
                        ]
                    )
                    self._save()
                    emotional = signals

        raw_items = getattr(
            understanding,
            "memory_items",
            [],
        )
        memory_items = (
            raw_items
            if isinstance(raw_items, list)
            else []
        )

        ingested = 0

        for raw in memory_items[:12]:
            if isinstance(raw, dict):
                kind = self._clean_text(
                    raw.get(
                        "kind",
                        raw.get("type", ""),
                    )
                ).lower()
                content = self._clean_text(
                    raw.get("content", "")
                )
                confidence = self._clamp(
                    raw.get("confidence", 0.8)
                )
            else:
                kind = self._clean_text(
                    getattr(raw, "kind", "")
                ).lower()
                content = self._clean_text(
                    getattr(raw, "content", "")
                )
                confidence = self._clamp(
                    getattr(raw, "confidence", 0.8)
                )

            if (
                not content
                or confidence < 0.45
                or self._looks_like_question(content)
                or self._looks_task_request_text(content)
                or self._looks_operational_text(content)
            ):
                continue

            if kind == "episode":
                self.remember_episode(
                    content,
                    kind="user_event",
                    source="understanding",
                    confidence=confidence,
                )
                ingested += 1
                continue

            if kind == "fact":
                self.remember(
                    content,
                    kind="fact",
                    source="understanding",
                    confidence=confidence,
                )
                ingested += 1
                continue

            if kind == "profile":
                before = len(
                    self.data.get(
                        "profile",
                        [],
                    )
                )
                self._extract_profile(
                    content
                )
                after = len(
                    self.data.get(
                        "profile",
                        [],
                    )
                )
                if after == before:
                    self.remember(
                        content,
                        kind="profile_fact",
                        source="understanding",
                        confidence=confidence,
                    )
                ingested += 1
                continue

            if kind in {
                "preference",
                "habit",
                "relation",
            }:
                structured = self._extract_relational(
                    content,
                    source="understanding",
                    confidence_boost=0.03,
                    persist=True,
                    track_action=False,
                )
                if structured == 0:
                    self.remember(
                        content,
                        kind=kind,
                        source="understanding",
                        confidence=confidence,
                    )
                ingested += 1
                continue

        # Filet de sécurité historique si aucun élément structuré n'a été
        # produit. Une question entière ne devient jamais un épisode.
        if (
            ingested == 0
            and not emotional
            and not self._looks_like_question(text)
        ):
            self._extract_episode(
                text
            )

        return emotional

"""


def patch_memory(text: str) -> str:
    if "def maybe_remember_with_understanding(" in text:
        raise RuntimeError(
            "memory.py semble déjà contenir V6.1."
        )

    text = replace_once(
        text,
        '    LONG_TERM_LIMIT = 250\n',
        '    LONG_TERM_LIMIT = 2000\n',
        "memory.py / LONG_TERM_LIMIT",
    )
    text = replace_once(
        text,
        '    EPISODIC_LIMIT = 200\n',
        '    EPISODIC_LIMIT = 5000\n',
        "memory.py / EPISODIC_LIMIT",
    )
    text = replace_once(
        text,
        '    RELATIONAL_LIMIT = 120\n',
        '    RELATIONAL_LIMIT = 500\n',
        "memory.py / RELATIONAL_LIMIT",
    )

    marker = (
        "    # =========================================================\n"
        "    # SELECTIVE RETRIEVAL\n"
        "    # =========================================================\n"
    )
    text = replace_once(
        text,
        marker,
        MEMORY_EXTENSION + marker,
        "memory.py / insertion V6.1",
    )
    return text


def patch_manager(text: str) -> str:
    if "UnderstandingEngine" in text:
        raise RuntimeError(
            "manager.py semble déjà contenir V6.1."
        )

    text = replace_once(
        text,
        "from agentos.router import Router\n",
        (
            "from agentos.router import Router\n"
            "from agentos.understanding import UnderstandingEngine\n"
        ),
        "manager.py / import",
    )

    text = replace_once(
        text,
        (
            "        self.missions = MissionManager()\n"
            "        self.router = Router()\n"
        ),
        (
            "        self.missions = MissionManager()\n"
            "        self.router = Router()\n"
            "        self.understanding = UnderstandingEngine(\n"
            "            self.llm\n"
            "        )\n"
        ),
        "manager.py / __init__",
    )

    text = replace_once(
        text,
        (
            "        emotional_signals = self.memory.maybe_remember(\n"
            "            value\n"
            "        )\n"
        ),
        (
            "        understanding = self.understanding.analyze(\n"
            "            value\n"
            "        )\n\n"
            "        emotional_signals = (\n"
            "            self.memory.maybe_remember_with_understanding(\n"
            "                value,\n"
            "                understanding,\n"
            "            )\n"
            "        )\n"
        ),
        "manager.py / compréhension + mémoire",
    )

    text = replace_once(
        text,
        (
            "        # Router\n"
            "        route = self.router.route(\n"
            "            value\n"
            "        )\n"
        ),
        (
            "        # Router historique conservé comme filet de sécurité.\n"
            "        route = self.router.route(\n"
            "            value\n"
            "        )\n\n"
            "        route_kind = route.kind\n"
            "        route_worker = route.worker\n"
            "        route_reason = route.reason\n\n"
            "        # V6.1 : quand UnderstandingEngine a réellement compris le\n"
            "        # message, sa décision sémantique prime sur les regex.\n"
            "        # Si Ollama/JSON échoue, routing_confident=False et l'ancien\n"
            "        # Router reprend automatiquement la main.\n"
            "        if understanding.routing_confident:\n"
            "            if understanding.work_requested:\n"
            "                route_kind = \"task\"\n"
            "                route_worker = (\n"
            "                    understanding.worker\n"
            "                    or route.worker\n"
            "                    or \"ai_worker\"\n"
            "                )\n"
            "                route_reason = (\n"
            "                    \"compréhension V6.1 : \"\n"
            "                    + (\n"
            "                        understanding.reason\n"
            "                        or \"travail explicitement demandé\"\n"
            "                    )\n"
            "                )\n"
            "            else:\n"
            "                route_kind = \"conversation\"\n"
            "                route_worker = None\n"
            "                route_reason = (\n"
            "                    \"compréhension V6.1 : \"\n"
            "                    + (\n"
            "                        understanding.reason\n"
            "                        or \"échange conversationnel\"\n"
            "                    )\n"
            "                )\n"
        ),
        "manager.py / routing V6.1",
    )

    text = replace_once(
        text,
        '        if route.kind == "conversation" and emotional_signals:\n',
        (
            '        if (\n'
            '            route_kind == "conversation"\n'
            '            and emotional_signals\n'
            '            and understanding.pure_state_update\n'
            '        ):\n'
        ),
        "manager.py / émotion non bloquante",
    )

    text = replace_once(
        text,
        '        if route.kind == "conversation":\n',
        '        if route_kind == "conversation":\n',
        "manager.py / conversation route",
    )

    text = replace_once(
        text,
        (
            "            initial_worker=(\n"
            "                route.worker\n"
            "                or \"ai_worker\"\n"
            "            ),\n"
            "            router_reason=route.reason,\n"
        ),
        (
            "            initial_worker=(\n"
            "                route_worker\n"
            "                or \"ai_worker\"\n"
            "            ),\n"
            "            router_reason=route_reason,\n"
        ),
        "manager.py / création mission",
    )

    text = replace_once(
        text,
        (
            "Réponds naturellement en français et utilise toujours le tutoiement.\n"
            "Pour une question simple, réponds de façon courte et directe.\n"
        ),
        (
            "Réponds naturellement en français et utilise toujours le tutoiement.\n"
            "Quand un message contient à la fois un état personnel et une demande,\n"
            "réponds d'abord à la demande. L'état personnel sert à adapter la réponse,\n"
            "il ne doit jamais remplacer le but principal du message.\n"
            "Pour une question simple, réponds de façon courte et directe.\n"
        ),
        "manager.py / politique conversationnelle",
    )

    return text


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    root = find_root(script_dir)

    manager_path = root / "agentos" / "manager.py"
    memory_path = root / "agentos" / "memory.py"
    understanding_dest = root / "agentos" / "understanding.py"
    understanding_source = script_dir / "payload" / "understanding.py"

    if not understanding_source.is_file():
        raise RuntimeError(
            "Le fichier payload/understanding.py manque dans le ZIP."
        )

    manager_original = manager_path.read_text(
        encoding="utf-8"
    )
    memory_original = memory_path.read_text(
        encoding="utf-8"
    )

    # Toutes les transformations sont préparées en mémoire avant toute écriture.
    manager_new = patch_manager(
        manager_original
    )
    memory_new = patch_memory(
        memory_original
    )

    # Écritures seulement après validation complète des motifs.
    manager_path.write_text(
        manager_new,
        encoding="utf-8",
    )
    memory_path.write_text(
        memory_new,
        encoding="utf-8",
    )

    if (
        understanding_source.resolve()
        != understanding_dest.resolve()
    ):
        shutil.copyfile(
            understanding_source,
            understanding_dest,
        )

    # Vérification syntaxique immédiate.
    for path in (
        understanding_dest,
        memory_path,
        manager_path,
    ):
        py_compile.compile(
            str(path),
            doraise=True,
        )

    print("")
    print("Agent-OS V6.1 MEMORY / UNDERSTANDING appliqué.")
    print(f"Racine : {root}")
    print("")
    print("Modifications :")
    print("- nouveau agentos/understanding.py")
    print("- mémoire épisodique : 5000 événements")
    print("- mémoire durable : 2000 faits")
    print("- mémoire relationnelle : 500 éléments par catégorie")
    print("- événements banals mémorisables sans 'aujourd'hui/hier'")
    print("- émotion + autre demande traitées simultanément")
    print("- compréhension sémantique avant création d'une mission")
    print("- Router regex conservé comme fallback")
    print("")
    print("Test conseillé dans Paul :")
    print(
        "  il est tard je suis fatigué je ne veux pas travailler "
        "il faut que tu me divertisse"
    )
    print("")
    print("Puis :")
    print("  j'ai vu un canard")
    print("  tu te souviens du canard ?")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except Exception as exc:
        print(
            f"\nERREUR V6.1 : {exc}\n",
            file=sys.stderr,
        )
        raise SystemExit(1)
