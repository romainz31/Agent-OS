from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from agentos.agenda import PersonalAgenda


CHECKS = 0


def check(condition, message):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"ÉCHEC #{CHECKS}: {message}")
    print(f"[OK {CHECKS:02d}] {message}")


def understanding(*, target="", view="program"):
    return SimpleNamespace(
        agenda_requested=True,
        agenda_confidence=0.95,
        agenda_action="query",
        agenda_view=view,
        agenda_target=target,
        agenda_subject="",
        agenda_field="what",
    )


def main():
    fixed_now = datetime(2026, 9, 10, 18, 0).astimezone()

    with tempfile.TemporaryDirectory(prefix="agentos-v643-") as directory:
        agenda = PersonalAgenda(
            Path(directory) / "agenda.db",
            now_provider=lambda: fixed_now,
        )

        agenda._add_item(
            kind="todo",
            title="aller chercher Coralie à l'aéroport",
            due_date=datetime(2026, 9, 12).date(),
            start_time=None,
            source_text="samedi je dois aller chercher Coralie à l'aéroport",
        )
        agenda._add_item(
            kind="todo",
            title="préparer les papiers",
            due_date=datetime(2026, 10, 12).date(),
            start_time=None,
            source_text="le 12/10/2026 je dois préparer les papiers",
        )
        agenda._add_item(
            kind="todo",
            title="nettoyer le filtre de l'aquarium",
            due_date=datetime(2026, 9, 10).date(),
            start_time=None,
            source_text="aujourd'hui je dois nettoyer le filtre de l'aquarium",
        )

        first = agenda.handle_understanding(
            "qu'ai-je prévu samedi ?",
            understanding(target="samedi"),
        )
        check("Coralie" in first, "la première question vise bien samedi")

        # Reproduction du bug : la compréhension annonce aujourd'hui alors que
        # la date explicite du message est le 12/10/2026.
        second = agenda.handle_understanding(
            "et le 12/10/2026 ?",
            understanding(target="aujourd'hui"),
        )
        check("12/10/2026" in second, "la date utilisateur prime sur la cible LLM")
        check("préparer les papiers" in second, "la bonne journée est consultée")
        check("nettoyer le filtre" not in second, "les tâches d'aujourd'hui ne fuient plus")

        # Même relance sans aucune aide du LLM : la vue précédente est héritée.
        third = agenda.query("et le 12/10/2026 ?")
        check(third is not None, "une relance date seule est reconnue sans LLM")
        check("préparer les papiers" in third, "la relance conserve le sujet agenda")

        # La déduplication existante reste effective après redémarrage.
        _, created = agenda._add_item(
            kind="todo",
            title="aller chercher Coralie à l’aéroport",
            due_date=datetime(2026, 9, 12).date(),
            start_time=None,
            source_text="doublon typographique",
        )
        check(not created, "les apostrophes différentes ne créent pas de doublon")
        check(
            len(agenda.items_for_date(datetime(2026, 9, 12).date(), kind="todo")) == 1,
            "une seule tâche équivalente reste active",
        )

    print(f"V6.4.3 : {CHECKS} contrôles réussis.")


if __name__ == "__main__":
    main()
