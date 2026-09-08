from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import agentos.memory as memory_module
from agentos.memory import Memory
from agentos.router import Router


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[OK] {label}")


def relational_item(
    memory: Memory,
    category: str,
    key: str,
):
    return next(
        (
            item
            for item in memory.data["relational"].get(category, [])
            if isinstance(item, dict)
            and str(item.get("key", "")) == key
        ),
        None,
    )


def main() -> None:
    print("=" * 68)
    print("TEST MISE À JOUR AGENT-OS — MÉMOIRE / PAUL / ROUTAGE")
    print("=" * 68)

    # =========================================================
    # ROUTER
    # =========================================================

    router = Router()

    routing_cases = (
        (
            "Je préfère que tu me donnes le fichier complet quand tu modifies du code.",
            "conversation",
            None,
        ),
        (
            "D'habitude je teste le code le soir.",
            "conversation",
            None,
        ),
        (
            "Finalement mon poisson préféré est le tétra amande.",
            "conversation",
            None,
        ),
        (
            "Oublie mon poisson préféré.",
            "conversation",
            None,
        ),
        (
            "Peux-tu oublier mon poisson préféré ?",
            "conversation",
            None,
        ),
        (
            "Corrige : ma copine s'appelle Coralie.",
            "conversation",
            None,
        ),
        (
            "Teste workspace/test_a.py",
            "task",
            "tester",
        ),
        (
            "Peux-tu modifier workspace/app.py ?",
            "task",
            "developer",
        ),
        (
            "Recherche des informations sur Zigbee2MQTT",
            "task",
            "researcher",
        ),
        (
            "Analyse ce problème",
            "task",
            "ai_worker",
        ),
    )

    for message, expected_kind, expected_worker in routing_cases:
        route = router.route(message)
        check(
            (route.kind, route.worker)
            == (expected_kind, expected_worker),
            f"Router : {message}",
        )

    # =========================================================
    # MEMORY — DOSSIER TEMPORAIRE
    # =========================================================

    original_data_dir = memory_module.DATA_DIR

    try:
        with tempfile.TemporaryDirectory(
            prefix="agentos-memory-test-"
        ) as temp_dir:
            memory_module.DATA_DIR = Path(temp_dir)
            memory = Memory()

            # -------------------------------------------------
            # Communication
            # -------------------------------------------------

            memory.maybe_remember(
                "Je préfère que tu ailles droit au but."
            )
            action = memory.consume_memory_action()
            check(
                isinstance(action, dict),
                "Préférence de communication détectée",
            )

            memory.maybe_remember(
                "Je préfère que tu me donnes le fichier complet quand tu modifies du code."
            )
            memory.consume_memory_action()

            directness = relational_item(
                memory,
                "communication",
                "response_directness",
            )
            full_files = relational_item(
                memory,
                "communication",
                "code_delivery",
            )

            check(
                directness is not None,
                "Réponses directes enregistrées",
            )
            check(
                full_files is not None,
                "Fichiers complets enregistrés",
            )

            # -------------------------------------------------
            # Renforcement utile vs double envoi
            # -------------------------------------------------

            memory.maybe_remember(
                "J'aime beaucoup l'aquariophilie."
            )
            memory.consume_memory_action()

            memory.maybe_remember(
                "L'aquariophilie est vraiment importante pour moi."
            )
            second_interest_action = memory.consume_memory_action()

            aquariophilie = relational_item(
                memory,
                "interests",
                "topic:aquariophilie",
            )
            check(
                aquariophilie is not None
                and int(aquariophilie.get("occurrences", 0)) == 2
                and float(aquariophilie.get("importance", 0.0)) > 0.90,
                "Deux formulations différentes renforcent un intérêt",
            )
            check(
                isinstance(second_interest_action, dict)
                and second_interest_action["changes"][0]["status"]
                == "reinforced",
                "Le renforcement est signalé au Manager",
            )

            memory.maybe_remember(
                "D'habitude je teste le code le soir."
            )
            memory.consume_memory_action()
            habit = relational_item(
                memory,
                "habits",
                "habit:d_habitude_je_teste_le_code_le_soir",
            )
            first_habit_count = int(
                habit.get("occurrences", 0)
            )

            memory.maybe_remember(
                "D'habitude je teste le code le soir."
            )
            duplicate_action = memory.consume_memory_action()
            habit = relational_item(
                memory,
                "habits",
                "habit:d_habitude_je_teste_le_code_le_soir",
            )

            check(
                int(habit.get("occurrences", 0))
                == first_habit_count,
                "Un double envoi immédiat ne gonfle pas les occurrences",
            )
            check(
                isinstance(duplicate_action, dict)
                and duplicate_action["changes"][0]["status"]
                == "unchanged",
                "Un doublon immédiat est identifié comme déjà pris en compte",
            )

            # -------------------------------------------------
            # Contradictions / corrections
            # -------------------------------------------------

            memory.maybe_remember(
                "Mon poisson préféré est le Rasbora brigittae."
            )
            memory.consume_memory_action()

            memory.maybe_remember(
                "Finalement mon poisson préféré est le tétra amande."
            )
            correction_action = memory.consume_memory_action()

            favorite = relational_item(
                memory,
                "preferences",
                "favorite:poisson",
            )
            check(
                favorite is not None
                and "tétra amande"
                in str(favorite.get("value", "")).lower(),
                "Une nouvelle préférence remplace l'ancienne",
            )
            check(
                isinstance(correction_action, dict)
                and correction_action["changes"][0]["status"]
                == "replaced",
                "La contradiction est signalée comme remplacement",
            )

            memory.maybe_remember(
                "Ma copine s'appelle Alice."
            )
            memory.consume_memory_action()
            memory.maybe_remember(
                "Corrige : ma copine s'appelle Coralie."
            )
            relation_action = memory.consume_memory_action()

            relation = relational_item(
                memory,
                "relations",
                "person:copine",
            )
            check(
                relation is not None
                and str(relation.get("value", "")) == "Coralie",
                "Correction naturelle d'une relation",
            )
            check(
                isinstance(relation_action, dict)
                and relation_action["changes"][0]["status"]
                == "replaced",
                "La correction relationnelle remplace l'ancienne valeur",
            )

            # -------------------------------------------------
            # Consolidation des anciens doublons V4.7.1
            # -------------------------------------------------

            memory.remember_relational(
                category="preferences",
                key="preference:legacy_directness",
                value=(
                    "je préfère qu'on aille droit au but "
                    "quand on travaille sur Agent-OS."
                ),
                content=(
                    "je préfère qu'on aille droit au but "
                    "quand on travaille sur Agent-OS."
                ),
                importance=0.85,
                confidence=0.90,
                occurrences=1,
            )

            directness_before = int(
                relational_item(
                    memory,
                    "communication",
                    "response_directness",
                ).get("occurrences", 1)
            )

            maintenance = memory.run_maintenance()

            check(
                int(maintenance.get("reclassified", 0)) >= 1,
                "Ancienne préférence générique reclassée",
            )
            check(
                int(maintenance.get("merged", 0)) >= 1,
                "Doublon conceptuel fusionné",
            )
            check(
                not any(
                    isinstance(item, dict)
                    and "droit au but quand on travaille"
                    in str(item.get("content", "")).lower()
                    for item in memory.data["relational"]["preferences"]
                ),
                "Le doublon n'existe plus dans PRÉFÉRENCES",
            )

            directness_after = int(
                relational_item(
                    memory,
                    "communication",
                    "response_directness",
                ).get("occurrences", 1)
            )
            check(
                directness_after == directness_before,
                "La fusion ne somme pas artificiellement les occurrences",
            )

            # -------------------------------------------------
            # Mémoire émotionnelle : péremption
            # -------------------------------------------------

            five_hours_ago = (
                datetime.now(timezone.utc)
                - timedelta(hours=5)
            ).isoformat()

            memory.data["emotional"]["current"] = {
                "mood": {
                    "value": "positive",
                    "confidence": 0.90,
                    "observed_at": five_hours_ago,
                    "source": "Ça va bien.",
                },
                "motivation": {
                    "value": "high",
                    "confidence": 0.90,
                    "observed_at": five_hours_ago,
                    "source": "Je suis motivé.",
                },
            }
            memory._save()

            check(
                not memory.current_emotional_state(),
                "Une humeur vieille de cinq heures n'est plus l'état du moment",
            )

            maintenance = memory.run_maintenance()
            check(
                int(maintenance.get("stale_emotions_removed", 0)) == 2,
                "Les états émotionnels périmés sont retirés du courant",
            )

            # -------------------------------------------------
            # Redémarrage : aucune inflation
            # -------------------------------------------------

            before_restart = {
                category: {
                    str(item.get("key", "")): int(
                        item.get("occurrences", 1)
                    )
                    for item in memory.data["relational"].get(
                        category,
                        [],
                    )
                    if isinstance(item, dict)
                }
                for category in memory.RELATIONAL_CATEGORIES
            }

            memory = Memory()

            after_restart = {
                category: {
                    str(item.get("key", "")): int(
                        item.get("occurrences", 1)
                    )
                    for item in memory.data["relational"].get(
                        category,
                        [],
                    )
                    if isinstance(item, dict)
                }
                for category in memory.RELATIONAL_CATEGORIES
            }

            check(
                before_restart == after_restart,
                "Un redémarrage ne renforce aucune mémoire",
            )

            # -------------------------------------------------
            # Oubli ciblé
            # -------------------------------------------------

            memory.maybe_remember(
                "Peux-tu oublier mon poisson préféré ?"
            )
            forget_action = memory.consume_memory_action()

            check(
                isinstance(forget_action, dict)
                and forget_action.get("type") == "forget"
                and int(forget_action.get("count", 0)) >= 1,
                "Commande d'oubli reconnue",
            )
            check(
                relational_item(
                    memory,
                    "preferences",
                    "favorite:poisson",
                )
                is None,
                "Préférence oubliée absente des données actives",
            )
            check(
                relational_item(
                    memory,
                    "interests",
                    "topic:aquariophilie",
                )
                is not None,
                "L'oubli du poisson ne supprime pas l'aquariophilie",
            )

            history_text = memory.relational_history_summary()
            check(
                "Rasbora" not in history_text
                and "tétra amande" not in history_text,
                "Les valeurs oubliées ne restent pas lisibles dans l'historique",
            )

            memory = Memory()
            check(
                relational_item(
                    memory,
                    "preferences",
                    "favorite:poisson",
                )
                is None,
                "Une donnée oubliée ne réapparaît pas au redémarrage",
            )

            context = memory.personal_conversation_context(
                "Parlons aquarium"
            )
            check(
                "Rasbora brigittae" not in context
                and "tétra amande" not in context,
                "La donnée oubliée ne fuit pas dans le contexte du LLM",
            )

            # Le chemin qui avait provoqué _effective_importance doit rester
            # couvert par le test.
            built_context = memory.relevant_context(
                "code"
            )
            check(
                "Préfère recevoir le fichier complet"
                in built_context,
                "Construction complète du contexte relationnel",
            )

            check(
                len(memory.data["working"]) == 0,
                "Aucun faux travail en cours",
            )

            # -------------------------------------------------
            # Oubli relationnel : purge du contexte récent
            # -------------------------------------------------

            memory.add_session(
                "user",
                "Ma copine s'appelle Alice.",
            )
            memory.add_session(
                "user",
                "Corrige : ma copine s'appelle Coralie.",
            )
            memory.add_session(
                "assistant",
                "Ta copine s'appelle Coralie.",
            )

            memory.maybe_remember(
                "Oublie le prénom de ma copine."
            )
            relation_forget_action = memory.consume_memory_action()

            check(
                isinstance(relation_forget_action, dict)
                and relation_forget_action.get("type") == "forget"
                and relational_item(
                    memory,
                    "relations",
                    "person:copine",
                ) is None,
                "Oubli du prénom d'une relation ciblé correctement",
            )

            recent_after_forget = memory.personal_session_context(
                limit=20
            )
            check(
                "Alice" not in recent_after_forget
                and "Coralie" not in recent_after_forget,
                "Une relation oubliée est purgée de la conversation récente",
            )

            habits_summary = memory.relational_category_summary(
                "habits"
            )
            communication_summary = memory.relational_category_summary(
                "communication"
            )
            check(
                "teste le code le soir" in habits_summary
                and "fichier complet" not in habits_summary,
                "La catégorie habitudes reste isolée",
            )
            check(
                "fichier complet" in communication_summary
                and "teste le code le soir" not in communication_summary,
                "La catégorie communication reste isolée",
            )

            # -------------------------------------------------
            # Commandes PersonalManager sans démarrer Ollama
            # -------------------------------------------------

            from agentos.personal_manager import PersonalManager

            paul = PersonalManager.__new__(PersonalManager)
            paul.memory = memory

            forgotten_relation_response = paul._direct_memory_response(
                "Comment s'appelle ma copine ?"
            )
            check(
                forgotten_relation_response is not None
                and "Coralie" not in forgotten_relation_response
                and "Alice" not in forgotten_relation_response
                and "pas le prénom" in forgotten_relation_response,
                "Une question précise ne ressuscite pas une relation oubliée",
            )

            habits_response = paul._direct_memory_response(
                "Que sais-tu sur mes habitudes ?"
            )
            check(
                habits_response is not None
                and "teste le code le soir" in habits_response
                and "fichier complet" not in habits_response,
                "Paul répond uniquement avec les habitudes à une question sur les habitudes",
            )

            communication_response = paul._direct_memory_response(
                "Que sais-tu sur mes préférences de communication ?"
            )
            check(
                communication_response is not None
                and "fichier complet" in communication_response
                and "teste le code le soir" not in communication_response,
                "Paul répond uniquement avec la communication à une question de communication",
            )

            correction_response = (
                paul._explicit_memory_command_response(
                    "memory correct Ma copine s'appelle Camille."
                )
            )
            relation = relational_item(
                memory,
                "relations",
                "person:copine",
            )
            check(
                relation is not None
                and str(relation.get("value", "")) == "Camille"
                and correction_response is not None,
                "Commande memory correct opérationnelle",
            )

            known_relation_response = paul._direct_memory_response(
                "Comment s'appelle ma copine ?"
            )
            check(
                known_relation_response == "Ta copine s'appelle Camille.",
                "Question relationnelle précise répond depuis la mémoire structurée",
            )

            forget_response = (
                paul._explicit_memory_command_response(
                    "memory forget ma copine"
                )
            )
            check(
                relational_item(
                    memory,
                    "relations",
                    "person:copine",
                )
                is None
                and forget_response is not None,
                "Commande memory forget opérationnelle",
            )

            after_command_forget = paul._direct_memory_response(
                "Comment s'appelle ma copine ?"
            )
            check(
                after_command_forget is not None
                and "Camille" not in after_command_forget
                and "pas le prénom" in after_command_forget,
                "L'oubli reste effectif pour les questions directes",
            )

            cleanup_response = paul._maintenance_response()
            check(
                isinstance(cleanup_response, str)
                and bool(cleanup_response.strip()),
                "Commande memory cleanup opérationnelle",
            )

    finally:
        memory_module.DATA_DIR = original_data_dir

    print()
    print("TOUS LES TESTS LOCAUX SONT PASSÉS.")
    print("Tu peux ensuite tester Paul via Web / CLI / Telegram.")


if __name__ == "__main__":
    main()
