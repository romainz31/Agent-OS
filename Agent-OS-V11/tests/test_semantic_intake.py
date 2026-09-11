from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_os_memory.helpers.intake import render_direct_reply, semantic_intake
from agent_os_memory.helpers.temporal import day_expression_to_iso_bounds, resolve_temporal_expression


class FakeStore:
    def __init__(self, root: Path):
        self.db_path = root / "intake_state.sqlite3"
        self.records: list[dict] = []
        self.facts: list[dict] = []
        self.current = datetime(2026, 9, 11, 22, 0, tzinfo=ZoneInfo("Europe/Paris"))

    def now(self):
        return self.current

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def capture(self, **kwargs):
        record = {
            "id": f"L-{len(self.records)+1}",
            "kind": kwargs["kind"],
            "title": kwargs["title"],
            "status": kwargs.get("status") or ("done" if kwargs["kind"] == "action" else "logged"),
            "completed_at": kwargs.get("completed_at"),
            "due_at": kwargs.get("due_at"),
            "start_at": kwargs.get("start_at"),
            "time_expression": kwargs.get("time_expression", ""),
            "entities": [
                {
                    "canonical_name": e["name"],
                    "entity_type": e.get("type", "person"),
                    "role": e.get("role", "related"),
                }
                for e in kwargs.get("entities", [])
            ],
            "source_text": kwargs.get("source_text", ""),
            "metadata": kwargs.get("metadata", {}),
        }
        self.records.append(record)
        result = {"operation": "created", "record": record}
        if kwargs["kind"] in {"fact", "preference", "relation"}:
            fact = {
                "fact_kind": kwargs["kind"],
                "subject": kwargs.get("subject", "user"),
                "predicate": kwargs.get("predicate", ""),
                "value": kwargs.get("value", ""),
            }
            self.facts.append(fact)
            result["fact"] = fact
        return result

    def query(self, **kwargs):
        # Used both for context snapshots and actual user queries.
        records = list(self.records)
        facts = list(self.facts)
        kinds = set(kwargs.get("kinds") or [])
        if kinds:
            records = [r for r in records if r["kind"] in kinds]
            if not (kinds & {"fact", "preference", "relation"}):
                facts = []
        start = kwargs.get("start")
        end = kwargs.get("end")
        if start:
            records = [
                r for r in records
                if (r.get("completed_at") or r.get("start_at") or r.get("due_at") or "9999")[:10] >= start[:10]
            ]
        if end:
            records = [
                r for r in records
                if (r.get("completed_at") or r.get("start_at") or r.get("due_at") or "0000")[:10] <= end[:10]
            ]
        entity = kwargs.get("entity")
        if entity:
            records = [
                r for r in records
                if any(entity.casefold() in e["canonical_name"].casefold() for e in r.get("entities", []))
            ]
        payload = {"records": records, "facts": facts, "found": len(records) + len(facts)}
        if kwargs.get("aggregate") == "count":
            payload["count"] = payload["found"]
        return payload

    def update(self, **kwargs):
        return {"operation": kwargs.get("action", "update"), "record": self.records[0] if self.records else {}}

    def forget(self, **kwargs):
        return {"operation": "forgotten", "count": 1, "record_ids": ["L-1"]}


class FakeAgent:
    pass


class SemanticIntakeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FakeStore(Path(self.temp.name))
        self.config = {
            "timezone": "Europe/Paris",
            "semantic_intake_confidence": 0.85,
            "semantic_intake_history_chars": 3000,
            "semantic_intake_known_items": 20,
            "allow_inferred_facts": False,
        }

    def tearDown(self):
        self.temp.cleanup()

    async def _run(self, model_payload: dict, message: str, context_id: str = "chat-a"):
        calls = {"count": 0}

        async def model_call(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                # V11.5 : premier appel = routeur minimal.
                return json.dumps({
                    "route": model_payload.get("mode", "none"),
                    "uses_pending": model_payload.get("pending_resolution") == "complete",
                    "confidence": 0.99,
                    "clarification": {"needed": False, "question": ""},
                }, ensure_ascii=False)
            # Deuxième appel = extracteur spécifique à la route.
            return json.dumps(model_payload, ensure_ascii=False)
        return await semantic_intake(
            agent=FakeAgent(),
            store=self.store,
            message=message,
            context_id=context_id,
            config=self.config,
            history="Romain: message précédent\nPaul: réponse précédente",
            model_call=model_call,
        )


    async def test_identity_and_home_are_two_user_facts_not_paul_facts(self):
        plan = {
            "mode": "capture",
            "confidence": 0.99,
            "clarification": {"needed": False, "question": ""},
            "items": [
                {
                    "kind": "fact", "title": "Romain s'appelle Romain",
                    "subject": "user", "predicate": "name", "value": "Romain",
                    "confidence": 0.99, "inferred": False,
                },
                {
                    "kind": "fact", "title": "Romain habite à Brens",
                    "subject": "user", "predicate": "home_location", "value": "Brens",
                    "confidence": 0.99, "inferred": False,
                    "entities": [{"type": "place", "name": "Brens", "role": "location"}],
                },
            ],
        }
        outcome = await self._run(plan, "je mapelle romain et jhabite a brens")
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(len(self.store.facts), 2)
        reply = render_direct_reply(outcome)
        self.assertEqual(
            reply,
            "D'accord, je retiens que tu t'appelles Romain et que tu habites à Brens.",
        )
        self.assertNotIn("je suis à Brens", reply)
        self.assertNotIn("Paul", reply)

    def test_mercredi_completed_action_resolves_to_previous_wednesday(self):
        resolved = resolve_temporal_expression(
            "mercredi",
            reference=self.store.current,
            timezone="Europe/Paris",
            prefer="past",
        )
        self.assertEqual(resolved.date().isoformat(), "2026-09-09")

    async def test_cleaning_list_writes_three_distinct_actions(self):
        plan = {
            "mode": "capture",
            "confidence": 0.98,
            "clarification": {"needed": False, "question": ""},
            "items": [
                {"kind": "action", "title": "nettoyé la machine à café", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.98, "entities": []},
                {"kind": "action", "title": "nettoyé la fontaine à chat", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.98, "entities": []},
                {"kind": "action", "title": "nettoyé les toilettes", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.98, "entities": []},
            ],
        }
        outcome = await self._run(plan, "aujourd'hui j'ai nettoyé la machine à café, la fontaine à chat et les toilettes")
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(len(self.store.records), 3)
        self.assertEqual({r["title"] for r in self.store.records}, {
            "nettoyé la machine à café", "nettoyé la fontaine à chat", "nettoyé les toilettes"
        })
        self.assertTrue(all(r["completed_at"].startswith("2026-09-11") for r in self.store.records))

    async def test_airport_sentence_keeps_semantic_roles_without_inventing_flight(self):
        plan = {
            "mode": "capture",
            "confidence": 0.98,
            "clarification": {"needed": False, "question": ""},
            "items": [{
                "kind": "action",
                "title": "emmené Coralie à l'aéroport",
                "status": "done",
                "time_expression": "mercredi",
                "confidence": 0.98,
                "actor": "user",
                "verb": "emmener",
                "object": "Coralie",
                "destination": "aéroport",
                "entities": [
                    {"type": "person", "name": "Coralie", "role": "object"},
                    {"type": "place", "name": "aéroport", "role": "destination"},
                ],
            }],
        }
        outcome = await self._run(plan, "mercredi jai emmené coralie a laeroport")
        self.assertEqual(outcome.status, "captured")
        record = self.store.records[0]
        self.assertTrue(record["completed_at"].startswith("2026-09-09"))
        self.assertEqual(record["metadata"]["semantic_intake"]["object"], "Coralie")
        self.assertEqual(record["metadata"]["semantic_intake"]["destination"], "aéroport")
        self.assertNotIn("avion", json.dumps(record, ensure_ascii=False).casefold())

    async def test_relation_is_structured_fact(self):
        plan = {
            "mode": "capture",
            "confidence": 0.99,
            "clarification": {"needed": False, "question": ""},
            "items": [{
                "kind": "relation",
                "title": "Coralie est la copine de Romain",
                "confidence": 0.99,
                "subject": "Coralie",
                "predicate": "relation_to_user",
                "value": "copine",
                "entities": [{"type": "person", "name": "Coralie", "role": "related"}],
            }],
        }
        outcome = await self._run(plan, "coralie est ma copine")
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(self.store.facts[0]["subject"], "Coralie")
        self.assertEqual(self.store.facts[0]["predicate"], "relation_to_user")
        self.assertEqual(self.store.facts[0]["value"], "copine")

    async def test_low_confidence_does_not_write_and_requests_clarification(self):
        plan = {
            "mode": "capture",
            "confidence": 0.55,
            "clarification": {"needed": True, "question": "Tu parles de qui quand tu dis « elle » ?"},
            "items": [],
        }
        outcome = await self._run(plan, "je l'ai emmenée mercredi")
        self.assertEqual(outcome.status, "clarification_required")
        self.assertEqual(len(self.store.records), 0)
        self.assertIn("qui", outcome.clarification_question.casefold())

    def test_three_last_months_is_resolved_by_python(self):
        self.assertEqual(
            day_expression_to_iso_bounds(
                "ces trois derniers mois",
                reference=self.store.current,
                timezone="Europe/Paris",
            ),
            ("2026-06-11", "2026-09-11"),
        )

    async def test_pending_clarification_is_reused_on_next_message(self):
        first = {
            "mode": "capture",
            "confidence": 0.55,
            "clarification": {"needed": True, "question": "Tu parles de qui ?"},
            "items": [],
            "pending_resolution": "still_ambiguous",
        }
        outcome = await self._run(first, "je l'ai emmenée mercredi")
        self.assertEqual(outcome.status, "clarification_required")

        second = {
            "mode": "capture",
            "confidence": 0.98,
            "clarification": {"needed": False, "question": ""},
            "pending_resolution": "complete",
            "items": [{
                "kind": "action",
                "title": "emmené Coralie",
                "status": "done",
                "time_expression": "mercredi",
                "confidence": 0.98,
                "actor": "user",
                "verb": "emmener",
                "object": "Coralie",
                "entities": [{"type": "person", "name": "Coralie", "role": "object"}],
            }],
        }
        outcome = await self._run(second, "Coralie")
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(self.store.records[0]["source_text"], "je l'ai emmenée mercredi")
        self.assertTrue(self.store.records[0]["completed_at"].startswith("2026-09-09"))

    async def test_query_yesterday_is_resolved_by_python(self):
        self.store.records.append({
            "id": "L-1", "kind": "action", "title": "nettoyé le filtre", "status": "done",
            "completed_at": "2026-09-10T12:00:00+02:00", "due_at": None, "start_at": None,
            "entities": [], "source_text": "hier j'ai nettoyé le filtre", "metadata": {},
        })
        plan = {
            "mode": "query",
            "confidence": 0.96,
            "clarification": {"needed": False, "question": ""},
            "items": [],
            "query": {
                "text": "", "kinds": ["action"], "statuses": [],
                "date_expression": "hier", "start_expression": "", "end_expression": "",
                "subject": "", "predicate": "", "entity": "", "entity_type": "",
                "aggregate": "list", "follow_up": False,
            },
        }
        outcome = await self._run(plan, "qu'est-ce que j'ai fait hier ?")
        self.assertEqual(outcome.status, "query_ready")
        self.assertEqual(outcome.query_result["found"], 1)
        self.assertEqual(outcome.query_result["records"][0]["title"], "nettoyé le filtre")

    async def test_item_confidence_inherits_global_confidence_when_omitted(self):
        plan = {
            "mode": "capture",
            "confidence": 0.99,
            "clarification": {"needed": False, "question": ""},
            "items": [{
                "kind": "relation",
                "title": "Coralie est la copine de Romain",
                "subject": "Coralie",
                "predicate": "relation_to_user",
                "value": "copine",
                "entities": [{"type": "person", "name": "Coralie", "role": "related"}],
            }],
        }
        outcome = await self._run(plan, "coralie est ma copine")
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(self.store.facts[0]["value"], "copine")
        self.assertEqual(render_direct_reply(outcome), "D'accord, je retiens que Coralie est ta copine.")

    async def test_direct_reply_for_cleaning_has_no_generic_commentary(self):
        plan = {
            "mode": "capture",
            "confidence": 0.98,
            "clarification": {"needed": False, "question": ""},
            "items": [
                {"kind": "action", "title": "nettoyé la machine à café", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.98},
                {"kind": "action", "title": "nettoyé la fontaine à chat", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.98},
                {"kind": "action", "title": "nettoyé les toilettes", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.98},
            ],
        }
        outcome = await self._run(plan, "aujourd'hui j'ai nettoyé la machine à café, la fontaine à chat et les toilettes")
        reply = render_direct_reply(outcome)
        self.assertEqual(
            reply,
            "D'accord, je retiens qu'aujourd'hui tu as nettoyé la machine à café, la fontaine à chat et les toilettes.",
        )
        self.assertNotIn("utile", reply.casefold())
        self.assertNotIn("merci", reply.casefold())

    async def test_direct_query_reply_uses_requested_day_not_previous_event(self):
        self.store.records.extend([
            {
                "id": "L-1", "kind": "action", "title": "nettoyé la machine à café", "status": "done",
                "completed_at": "2026-09-11T12:00:00+02:00", "due_at": None, "start_at": None,
                "entities": [], "source_text": "aujourd'hui j'ai nettoyé la machine à café", "metadata": {},
            },
            {
                "id": "L-2", "kind": "action", "title": "emmené Coralie à l'aéroport", "status": "done",
                "completed_at": "2026-09-09T12:00:00+02:00", "due_at": None, "start_at": None,
                "entities": [], "source_text": "mercredi jai emmené coralie a laeroport", "metadata": {},
            },
        ])
        plan = {
            "mode": "query",
            "confidence": 0.98,
            "clarification": {"needed": False, "question": ""},
            "items": [],
            "query": {
                "text": "", "kinds": ["action"], "statuses": [],
                "date_expression": "aujourd'hui", "start_expression": "", "end_expression": "",
                "subject": "", "predicate": "", "entity": "", "entity_type": "",
                "aggregate": "list", "follow_up": False,
            },
        }
        outcome = await self._run(plan, "qu'est-ce que j'ai fait aujourd'hui ?")
        reply = render_direct_reply(outcome)
        self.assertEqual(reply, "Aujourd'hui, tu as nettoyé la machine à café.")
        self.assertNotIn("mercredi", reply.casefold())
        self.assertNotIn("coralie", reply.casefold())

    async def test_clear_identity_is_saved_even_if_qwen_copies_zero_confidence(self):
        plan = {
            "mode": "capture",
            "confidence": 0.0,
            "clarification": {"needed": False, "question": ""},
            "items": [
                {
                    "kind": "fact", "title": "Romain s'appelle Romain",
                    "subject": "user", "predicate": "name", "value": "Romain",
                    "confidence": 0.0, "inferred": False,
                },
                {
                    "kind": "fact", "title": "Romain habite à Brens",
                    "subject": "user", "predicate": "home_location", "value": "Brens",
                    "confidence": 0.0, "inferred": False,
                },
            ],
        }
        outcome = await self._run(plan, "je mapelle romain et jhabite a brens")
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(len(self.store.facts), 2)
        self.assertEqual(
            render_direct_reply(outcome),
            "D'accord, je retiens que tu t'appelles Romain et que tu habites à Brens.",
        )

    async def test_clear_cleaning_is_saved_even_if_qwen_copies_zero_confidence(self):
        plan = {
            "mode": "capture",
            "confidence": 0.0,
            "clarification": {"needed": False, "question": ""},
            "items": [
                {"kind": "action", "title": "nettoyé la machine à café", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.0},
                {"kind": "action", "title": "nettoyé la fontaine à chat", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.0},
                {"kind": "action", "title": "nettoyé les toilettes", "status": "done", "time_expression": "aujourd'hui", "confidence": 0.0},
            ],
        }
        outcome = await self._run(plan, "aujourd'hui j'ai fait du nettoyage et plus particulièrement, j'ai nettoyé la machine a café, la fontaine a chat et les toilettes")
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(len(self.store.records), 3)
        self.assertEqual(
            render_direct_reply(outcome),
            "D'accord, je retiens qu'aujourd'hui tu as nettoyé la machine à café, la fontaine à chat et les toilettes.",
        )

    async def test_router_zero_confidence_does_not_block_a_clear_capture(self):
        calls = {"count": 0}
        async def model_call(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return json.dumps({
                    "route": "capture",
                    "confidence": 0.0,
                    "clarification": {"needed": False, "question": ""},
                }, ensure_ascii=False)
            return json.dumps({
                "confidence": 0.0,
                "clarification": {"needed": False, "question": ""},
                "items": [{
                    "kind": "fact", "title": "Romain habite à Brens",
                    "subject": "user", "predicate": "home_location", "value": "Brens",
                    "confidence": 0.0, "inferred": False,
                }],
            }, ensure_ascii=False)
        outcome = await semantic_intake(
            agent=FakeAgent(), store=self.store, message="jhabite a brens",
            context_id="chat-zero", config=self.config, history="", model_call=model_call,
        )
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(self.store.facts[0]["value"], "Brens")



    async def test_v116_retries_when_qwen_copies_capture_schema_for_identity(self):
        calls = {"count": 0}
        bad = {
            "clarification": {"needed": False, "question": ""},
            "items": [{
                "kind": "action|task|appointment|event|mood|note|fact|preference|relation",
                "title": "",
                "status": "done|pending|scheduled|logged",
                "time_expression": "",
                "inferred": False,
                "actor": "user ou nom explicite",
                "verb": "",
                "object": "",
                "destination": "",
                "subject": "",
                "predicate": "",
                "value": "",
                "entities": [{
                    "type": "person|place|project|organization|object",
                    "name": "",
                    "role": "actor|object|destination|location|related",
                }],
            }],
            "pending_resolution": "none|complete|still_ambiguous|abandon",
        }
        good = {
            "clarification": None,
            "items": [
                {"kind": "fact", "title": "Romain s'appelle Romain", "subject": "user", "predicate": "name", "value": "Romain", "inferred": False},
                {"kind": "fact", "title": "Romain habite à Brens", "subject": "user", "predicate": "home_location", "value": "Brens", "inferred": False},
            ],
        }

        async def model_call(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return json.dumps({"route": "capture", "clarification": None}, ensure_ascii=False)
            if calls["count"] == 2:
                return json.dumps(bad, ensure_ascii=False)
            return json.dumps(good, ensure_ascii=False)

        outcome = await semantic_intake(
            agent=FakeAgent(), store=self.store,
            message="je mapelle romain et jhabite a brens",
            context_id="chat-v116-identity", config=self.config, history="",
            model_call=model_call,
        )
        self.assertEqual(calls["count"], 3)
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(len(self.store.facts), 2)
        self.assertEqual(
            render_direct_reply(outcome),
            "D'accord, je retiens que tu t'appelles Romain et que tu habites à Brens.",
        )
        diag = outcome.raw_plan.get("_extractor_diagnostic", {})
        self.assertEqual(diag.get("attempts"), 2)
        self.assertTrue(diag.get("first_problem"))
        self.assertFalse(diag.get("remaining_problem"))

    async def test_v116_repairs_kind_placeholder_after_retry_for_three_actions(self):
        calls = {"count": 0}
        bad = {
            "clarification": {"needed": False, "question": ""},
            "items": [{
                "kind": "action|task|appointment|event|mood|note|fact|preference|relation",
                "title": "nettoyage",
                "status": "done",
                "time_expression": "aujourd'hui",
                "inferred": False,
                "actor": "user",
                "verb": "nettoyage",
                "object": "machine à café, fontaine à chat, toilettes",
                "entities": [
                    {"type": "object", "name": "machine à café", "role": "object"},
                    {"type": "object", "name": "fontaine à chat", "role": "object"},
                    {"type": "object", "name": "toilettes", "role": "object"},
                ],
            }],
        }
        repaired_retry = {
            "clarification": None,
            "items": [
                {"kind": "action|task|appointment", "title": "nettoyé la machine à café", "status": "done", "time_expression": "aujourd'hui", "actor": "user", "verb": "nettoyer", "object": "machine à café"},
                {"kind": "action|task|appointment", "title": "nettoyé la fontaine à chat", "status": "done", "time_expression": "aujourd'hui", "actor": "user", "verb": "nettoyer", "object": "fontaine à chat"},
                {"kind": "action|task|appointment", "title": "nettoyé les toilettes", "status": "done", "time_expression": "aujourd'hui", "actor": "user", "verb": "nettoyer", "object": "toilettes"},
            ],
        }

        async def model_call(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return json.dumps({"route": "capture", "clarification": None}, ensure_ascii=False)
            if calls["count"] == 2:
                return json.dumps(bad, ensure_ascii=False)
            return json.dumps(repaired_retry, ensure_ascii=False)

        outcome = await semantic_intake(
            agent=FakeAgent(), store=self.store,
            message="aujourd'hui j'ai fait du nettoyage et plus particulièrement, j'ai nettoyé la machine a café, la fontaine a chat et les toilettes",
            context_id="chat-v116-clean", config=self.config, history="",
            model_call=model_call,
        )
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(len(self.store.records), 3)
        self.assertEqual(
            render_direct_reply(outcome),
            "D'accord, je retiens qu'aujourd'hui tu as nettoyé la machine à café, la fontaine à chat et les toilettes.",
        )

    def test_v116_capture_prompt_does_not_offer_pipe_enum_as_json_value(self):
        from agent_os_memory.helpers.intake import CAPTURE_SYSTEM
        self.assertNotIn('"kind":"action|', CAPTURE_SYSTEM)
        self.assertNotIn('"status":"done|', CAPTURE_SYSTEM)
        self.assertNotIn('"actor":"user ou nom explicite"', CAPTURE_SYSTEM)



    async def test_v117_middle_name_is_a_normal_fact(self):
        plan = {
            "mode": "capture",
            "clarification": None,
            "items": [{
                "kind": "fact",
                "title": "ton deuxième prénom est Michel",
                "subject": "user",
                "predicate": "middle_name",
                "value": "Michel",
                "inferred": False,
            }],
        }
        outcome = await self._run(plan, "mon deuxième prénom est Michel", context_id="chat-middle")
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(self.store.facts[-1]["predicate"], "middle_name")
        self.assertEqual(self.store.facts[-1]["value"], "Michel")
        self.assertEqual(
            render_direct_reply(outcome),
            "D'accord, je retiens que ton deuxième prénom est Michel.",
        )

    async def test_v117_technical_extraction_failure_does_not_poison_next_message(self):
        ctx = "chat-no-poison"
        calls = {"count": 0}

        async def bad_model(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return json.dumps({"route": "capture", "clarification": None}, ensure_ascii=False)
            return json.dumps({"clarification": None, "items": []}, ensure_ascii=False)

        first = await semantic_intake(
            agent=FakeAgent(), store=self.store,
            message="mon deuxième prénom est Michel",
            context_id=ctx, config=self.config, history="",
            model_call=bad_model,
        )
        # V12 : une information personnelle routée en capture n'est plus perdue
        # si l'extracteur échoue complètement : elle est conservée comme note fallback.
        self.assertEqual(first.status, "captured")
        self.assertEqual(first.saved[0]["record"]["kind"], "note")
        self.assertEqual(first.saved[0]["record"]["source_text"], "mon deuxième prénom est Michel")

        # Cette erreur technique ne doit surtout PAS laisser de clarification
        # latente capable de détourner « Coralie est ma copine ».
        with self.store.connect() as db:
            row = db.execute(
                "SELECT pending_json FROM semantic_intake_state WHERE context_id=?",
                (ctx,),
            ).fetchone()
        self.assertIsNone(row)

        calls2 = {"count": 0}
        async def relation_model(**kwargs):
            calls2["count"] += 1
            if calls2["count"] == 1:
                return json.dumps({"route": "capture", "clarification": None}, ensure_ascii=False)
            return json.dumps({
                "clarification": None,
                "items": [{
                    "kind": "relation",
                    "title": "Coralie est la copine de Romain",
                    "subject": "Coralie",
                    "predicate": "relation_to_user",
                    "value": "copine",
                    "inferred": False,
                    "entities": [{"type": "person", "name": "Coralie", "role": "related"}],
                }],
            }, ensure_ascii=False)

        second = await semantic_intake(
            agent=FakeAgent(), store=self.store,
            message="Coralie est ma copine",
            context_id=ctx, config=self.config, history="",
            model_call=relation_model,
        )
        self.assertEqual(second.status, "captured")
        self.assertEqual(self.store.facts[-1]["subject"], "Coralie")
        self.assertEqual(self.store.facts[-1]["value"], "copine")
        self.assertEqual(render_direct_reply(second), "D'accord, je retiens que Coralie est ta copine.")

    async def test_v117_complete_new_capture_clears_real_pending_clarification(self):
        ctx = "chat-real-pending"

        # 1) Crée une vraie ambiguïté : l'objet de « je l'ai emmenée » est inconnu.
        calls = {"count": 0}
        async def ambiguous_model(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return json.dumps({"route": "capture", "clarification": None}, ensure_ascii=False)
            return json.dumps({
                "clarification": {
                    "needed": True,
                    "question": "Tu parles de qui quand tu dis que tu l'as emmenée mercredi ?",
                },
                "items": [],
            }, ensure_ascii=False)

        first = await semantic_intake(
            agent=FakeAgent(), store=self.store,
            message="je l'ai emmenée mercredi",
            context_id=ctx, config=self.config, history="",
            model_call=ambiguous_model,
        )
        self.assertEqual(first.status, "clarification_required")

        # 2) Au lieu de répondre à la clarification, Romain change de sujet avec
        # une phrase complète. Elle doit gagner sur le pending.
        calls2 = {"count": 0}
        async def new_message_model(**kwargs):
            calls2["count"] += 1
            if calls2["count"] == 1:
                return json.dumps({"route": "capture", "uses_pending": False, "clarification": None}, ensure_ascii=False)
            # Le prompt d'extraction ne doit plus contenir l'ancien message pending.
            self.assertIn("MESSAGE_UTILISATEUR: Coralie est ma copine", kwargs.get("message", ""))
            self.assertIn("PENDING_CLARIFICATION:\n{}", kwargs.get("message", ""))
            return json.dumps({
                "clarification": None,
                "items": [{
                    "kind": "relation",
                    "title": "Coralie est la copine de Romain",
                    "subject": "Coralie",
                    "predicate": "relation_to_user",
                    "value": "copine",
                    "inferred": False,
                }],
            }, ensure_ascii=False)

        second = await semantic_intake(
            agent=FakeAgent(), store=self.store,
            message="Coralie est ma copine",
            context_id=ctx, config=self.config, history="",
            model_call=new_message_model,
        )
        self.assertEqual(second.status, "captured")
        self.assertEqual(render_direct_reply(second), "D'accord, je retiens que Coralie est ta copine.")



    async def test_v118_primary_capture_prompt_is_isolated_from_known_memory(self):
        self.store.facts.extend([
            {"fact_kind":"fact","subject":"user","predicate":"name","value":"Romain"},
            {"fact_kind":"fact","subject":"user","predicate":"home_location","value":"Brens"},
            {"fact_kind":"fact","subject":"user","predicate":"middle_name","value":"Michel"},
        ])
        calls = {"n": 0}
        async def model_call(**kwargs):
            calls["n"] += 1
            prompt = kwargs.get("message", "")
            if calls["n"] == 1:
                self.assertIn("MESSAGE_UTILISATEUR: Coralie est ma copine", prompt)
                self.assertNotIn("MEMOIRE_UTILE", prompt)
                self.assertNotIn("Brens", prompt)
                self.assertNotIn("Michel", prompt)
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None}, ensure_ascii=False)
            self.assertIn("MESSAGE_UTILISATEUR: Coralie est ma copine", prompt)
            self.assertNotIn("MEMOIRE_UTILE", prompt)
            self.assertNotIn("Brens", prompt)
            self.assertNotIn("Michel", prompt)
            return json.dumps({
                "clarification": None,
                "items": [{
                    "kind":"relation","title":"Coralie est la copine de Romain",
                    "subject":"Coralie","predicate":"relation_to_user","value":"copine",
                    "inferred":False,"entities":[{"type":"person","name":"Coralie","role":"related"}]
                }]
            }, ensure_ascii=False)
        outcome = await semantic_intake(
            agent=FakeAgent(), store=self.store, message="Coralie est ma copine",
            context_id="iso-relation", config=self.config,
            history="Paul: Romain habite à Brens et son deuxième prénom est Michel",
            model_call=model_call,
        )
        self.assertEqual(outcome.status, "captured")
        self.assertEqual(len(outcome.saved), 1)
        self.assertEqual(outcome.saved[0]["fact"]["subject"], "Coralie")
        self.assertEqual(render_direct_reply(outcome), "D'accord, je retiens que Coralie est ta copine.")

    async def test_v118_relation_alias_is_resolved_only_in_second_context_pass(self):
        self.store.facts.append({
            "fact_kind":"relation","subject":"Coralie","predicate":"relation_to_user","value":"copine"
        })
        calls = {"n": 0}
        async def model_call(**kwargs):
            calls["n"] += 1
            system = kwargs.get("system", "")
            prompt = kwargs.get("message", "")
            if calls["n"] == 1:
                self.assertNotIn("Coralie", prompt)
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None}, ensure_ascii=False)
            if calls["n"] == 2:
                self.assertNotIn("Coralie", prompt)
                return json.dumps({
                    "clarification":None,
                    "items":[{
                        "kind":"event","title":"ma copine travaille demain matin",
                        "status":"scheduled","time_expression":"demain matin",
                        "actor":"","verb":"travailler","object":"","inferred":False,
                        "unresolved":[{"field":"actor","mention":"ma copine","reason":"relation_to_user","relation":"copine"}]
                    }]
                }, ensure_ascii=False)
            self.assertIn("PLAN_COURANT", prompt)
            self.assertIn("Coralie | relation_to_user | copine", prompt)
            return json.dumps({
                "patches":[{
                    "item_index":0,
                    "fields":{"actor":"Coralie"},
                    "entities":[{"type":"person","name":"Coralie","role":"actor"}],
                    "resolution":{"source":"known_memory","confidence":0.99}
                }],
                "clarification":None
            }, ensure_ascii=False)
        outcome = await semantic_intake(
            agent=FakeAgent(), store=self.store, message="ma copine travaille demain matin",
            context_id="resolve-relation", config=self.config, history="", model_call=model_call,
        )
        self.assertEqual(calls["n"], 3)
        self.assertEqual(outcome.status, "captured")
        rec = outcome.saved[0]["record"]
        self.assertEqual(rec["kind"], "event")
        self.assertTrue(rec["start_at"].startswith("2026-09-12"))
        self.assertEqual(rec["entities"][0]["canonical_name"], "Coralie")
        self.assertEqual(rec["entities"][0]["role"], "actor")

    async def test_v118_standalone_query_cannot_inherit_previous_filter(self):
        self.store.records.append({
            "id":"L-1","kind":"event","title":"ma copine travaille demain matin",
            "status":"scheduled","completed_at":None,"due_at":None,
            "start_at":"2026-09-12T12:00:00+02:00","time_expression":"demain matin",
            "entities":[{"canonical_name":"Coralie","entity_type":"person","role":"actor"}],
            "source_text":"ma copine travaille demain matin","metadata":{},
        })
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            prompt=kwargs.get("message","")
            if calls["n"] == 1:
                self.assertIn("MESSAGE_UTILISATEUR: qui travaille demain matin ?", prompt)
                self.assertNotIn("mardi", prompt)
                return json.dumps({"route":"query","uses_pending":False,"query_follow_up":False,"clarification":None}, ensure_ascii=False)
            # Même si Qwen se trompe ici et dit follow_up=true, Python doit le neutraliser.
            return json.dumps({
                "clarification":None,
                "query":{"text":"travaille","kinds":["event"],"statuses":[],
                         "date_expression":"demain matin","start_expression":"","end_expression":"",
                         "subject":"","predicate":"","entity":"","entity_type":"",
                         "aggregate":"list","follow_up":True}
            }, ensure_ascii=False)
        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="qui travaille demain matin ?",
            context_id="standalone-query",config=self.config,
            history="Romain: qu'est-ce que j'ai fait mardi ?",model_call=model_call,
        )
        self.assertEqual(outcome.status,"query_ready")
        self.assertFalse(outcome.raw_plan["query"]["follow_up"])
        self.assertEqual(outcome.query_result["found"],1)

    async def test_v118_past_action_is_capture_even_after_query_history(self):
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            prompt=kwargs.get("message","")
            if calls["n"] == 1:
                self.assertIn("MESSAGE_UTILISATEUR: mardi j'ai lavé ma voiture", prompt)
                self.assertNotIn("demain matin", prompt)
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None}, ensure_ascii=False)
            return json.dumps({
                "clarification":None,
                "items":[{"kind":"action","title":"lavé ma voiture","status":"done",
                          "time_expression":"mardi","actor":"user","verb":"laver",
                          "object":"ma voiture","inferred":False}]
            }, ensure_ascii=False)
        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="mardi j'ai lavé ma voiture",
            context_id="after-query",config=self.config,
            history="Paul: Je n'ai rien enregistré pour demain matin.",model_call=model_call,
        )
        self.assertEqual(outcome.status,"captured")
        self.assertEqual(outcome.saved[0]["record"]["kind"],"action")
        self.assertTrue(outcome.saved[0]["record"]["completed_at"].startswith("2026-09-08"))

    async def test_v118_standalone_tuesday_query_stays_tuesday_not_previous_date(self):
        self.store.records.append({
            "id":"L-1","kind":"action","title":"lavé ma voiture","status":"done",
            "completed_at":"2026-09-08T12:00:00+02:00","due_at":None,"start_at":None,
            "time_expression":"mardi","entities":[],"source_text":"mardi j'ai lavé ma voiture","metadata":{},
        })
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"]+=1
            if calls["n"]==1:
                return json.dumps({"route":"query","uses_pending":False,"query_follow_up":False,"clarification":None},ensure_ascii=False)
            return json.dumps({
                "clarification":None,
                "query":{"text":"","kinds":["action"],"statuses":[],"date_expression":"mardi",
                         "start_expression":"","end_expression":"","subject":"","predicate":"",
                         "entity":"","entity_type":"","aggregate":"list","follow_up":False}
            },ensure_ascii=False)
        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="qu'est-ce que j'ai fait mardi ?",
            context_id="tuesday-query",config=self.config,
            history="Paul: Je n'ai rien enregistré pour demain matin.",model_call=model_call,
        )
        self.assertEqual(outcome.status,"query_ready")
        self.assertEqual(outcome.query_result["found"],1)
        self.assertEqual(outcome.query_result["records"][0]["title"],"lavé ma voiture")


    async def test_v119_capture_reply_uses_ta_voiture(self):
        plan = {
            "mode": "capture",
            "clarification": None,
            "items": [{
                "kind": "action", "title": "lavé ma voiture", "status": "done",
                "time_expression": "mardi", "actor": "user",
                "verb": "laver", "object": "ma voiture", "inferred": False,
            }],
        }
        outcome = await self._run(plan, "mardi j'ai lavé ma voiture", context_id="chat-v119-capture")
        self.assertEqual(render_direct_reply(outcome), "D'accord, je retiens que tu as lavé ta voiture mardi.")

    async def test_v119_query_reply_uses_ta_voiture(self):
        self.store.records.append({
            "id": "L-119", "kind": "action", "title": "lavé ma voiture", "status": "done",
            "completed_at": "2026-09-08T12:00:00+02:00", "due_at": None, "start_at": None,
            "entities": [], "source_text": "mardi j'ai lavé ma voiture", "metadata": {},
        })
        plan = {
            "mode": "query", "clarification": None,
            "query": {
                "text": "", "kinds": ["action"], "statuses": [],
                "date_expression": "mardi", "start_expression": "", "end_expression": "",
                "subject": "", "predicate": "", "entity": "", "entity_type": "",
                "aggregate": "list", "follow_up": False,
            },
        }
        outcome = await self._run(plan, "qu'est-ce que j'ai fait mardi ?", context_id="chat-v119-query")
        self.assertEqual(render_direct_reply(outcome), "Mardi, tu as lavé ta voiture.")


    async def test_v120_future_task_with_explicit_coralia_needs_no_reference_clarification(self):
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None}, ensure_ascii=False)
            return json.dumps({
                "clarification":None,
                "items":[{
                    "kind":"task","title":"aller chercher Coralie à l'aéroport","status":"pending",
                    "time_expression":"samedi","actor":"user","verb":"aller chercher",
                    "object":"","destination":"aéroport","inferred":False,
                    "entities":[{"type":"place","name":"aéroport","role":"destination"}],
                    "unresolved":[{"field":"object","mention":"Coralie","reason":"named_entity"}]
                }]
            }, ensure_ascii=False)
        outcome=await semantic_intake(
            agent=FakeAgent(), store=self.store,
            message="samedi je dois aller chercher Coralie à l'aéroport",
            context_id="v120-task-airport", config=self.config, history="", model_call=model_call,
        )
        self.assertEqual(calls["n"],2)
        self.assertEqual(outcome.status,"captured")
        rec=outcome.saved[0]["record"]
        self.assertEqual(rec["kind"],"task")
        self.assertTrue(rec["due_at"].startswith("2026-09-12"))
        self.assertTrue(any(e["canonical_name"]=="Coralie" for e in rec["entities"]))

    async def test_v120_duck_observation_is_saved_as_episodic_action_with_source(self):
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None}, ensure_ascii=False)
            return json.dumps({
                "clarification":None,
                "items":[{
                    "kind":"action","title":"vu un canard","status":"done",
                    "time_expression":"aujourd'hui","actor":"user","verb":"voir","object":"canard",
                    "keywords":["voir","canard"],"details":{"animal":"canard"},"inferred":False,
                    "entities":[{"type":"object","name":"canard","role":"object"}]
                }]
            }, ensure_ascii=False)
        outcome=await semantic_intake(
            agent=FakeAgent(), store=self.store, message="j'ai vu un canard aujourd'hui",
            context_id="v120-duck", config=self.config, history="", model_call=model_call,
        )
        self.assertEqual(outcome.status,"captured")
        rec=outcome.saved[0]["record"]
        self.assertEqual(rec["source_text"],"j'ai vu un canard aujourd'hui")
        self.assertEqual(rec["metadata"]["semantic_intake"]["verb"],"voir")
        self.assertEqual(rec["metadata"]["semantic_intake"]["object"],"canard")
        self.assertEqual(rec["metadata"]["semantic_intake"]["details"]["animal"],"canard")

    async def test_v120_last_time_query_semantically_matches_washed_car(self):
        self.store.records.extend([
            {
                "id":"L-old","kind":"action","title":"lavé ma voiture","status":"done",
                "completed_at":"2026-08-20T12:00:00+02:00","due_at":None,"start_at":None,
                "time_expression":"","entities":[],"source_text":"j'ai lavé ma voiture",
                "metadata":{"semantic_intake":{"actor":"user","verb":"laver","object":"ma voiture"}},
            },
            {
                "id":"L-new","kind":"action","title":"lavé ma voiture","status":"done",
                "completed_at":"2026-09-08T12:00:00+02:00","due_at":None,"start_at":None,
                "time_expression":"mardi","entities":[],"source_text":"mardi j'ai lavé ma voiture",
                "metadata":{"semantic_intake":{"actor":"user","verb":"laver","object":"ma voiture"}},
            },
            {
                "id":"L-other","kind":"action","title":"nettoyé l'aquarium","status":"done",
                "completed_at":"2026-09-10T12:00:00+02:00","due_at":None,"start_at":None,
                "time_expression":"jeudi","entities":[],"source_text":"j'ai nettoyé l'aquarium",
                "metadata":{"semantic_intake":{"actor":"user","verb":"nettoyer","object":"aquarium"}},
            },
        ])
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"query","uses_pending":False,"query_follow_up":False,"clarification":None}, ensure_ascii=False)
            if calls["n"] == 2:
                return json.dumps({
                    "clarification":None,
                    "query":{"text":"","kinds":["action"],"statuses":[],"date_expression":"",
                             "start_expression":"","end_expression":"","subject":"","predicate":"",
                             "entity":"","entity_type":"","aggregate":"list","follow_up":False,
                             "semantic":{"actor":"user","verb":"laver","object":"voiture","destination":"",
                                         "concepts":["voiture"],"question_type":"when","order":"latest","limit":1}}
                }, ensure_ascii=False)
            self.assertIn("L-old", kwargs.get("message",""))
            self.assertIn("L-new", kwargs.get("message",""))
            return json.dumps({"record_ids":["L-old","L-new"],"reason":"lavage voiture"}, ensure_ascii=False)
        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,
            message="quand est ce que jai lavé la voiture la derniere fois?",
            context_id="v120-last-car",config=self.config,history="",model_call=model_call,
        )
        self.assertEqual(outcome.status,"query_ready")
        self.assertEqual([r["id"] for r in outcome.query_result["records"]],["L-new"])
        self.assertEqual(render_direct_reply(outcome), "La dernière fois enregistrée, c'était le 8 septembre 2026 : tu as lavé ta voiture.")

    async def test_v120_last_duck_query_works_without_exact_word_form(self):
        self.store.records.append({
            "id":"L-duck","kind":"action","title":"vu un canard","status":"done",
            "completed_at":"2026-09-11T12:00:00+02:00","due_at":None,"start_at":None,
            "time_expression":"aujourd'hui","entities":[{"canonical_name":"canard","entity_type":"object","role":"object"}],
            "source_text":"j'ai vu un canard aujourd'hui",
            "metadata":{"semantic_intake":{"actor":"user","verb":"voir","object":"canard","keywords":["voir","canard"]}},
        })
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"]+=1
            if calls["n"]==1:
                return json.dumps({"route":"query","uses_pending":False,"query_follow_up":False,"clarification":None},ensure_ascii=False)
            if calls["n"]==2:
                return json.dumps({"clarification":None,"query":{
                    "text":"","kinds":["action","event","note"],"statuses":[],"date_expression":"",
                    "start_expression":"","end_expression":"","subject":"","predicate":"","entity":"","entity_type":"",
                    "aggregate":"list","follow_up":False,
                    "semantic":{"actor":"user","verb":"voir","object":"canard","destination":"","concepts":["canard"],"question_type":"when","order":"latest","limit":1}
                }},ensure_ascii=False)
            return json.dumps({"record_ids":["L-duck"],"reason":"voir canard correspond à vu un canard"},ensure_ascii=False)
        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="c'était quand la dernière fois que j'avais vu un canard ?",
            context_id="v120-last-duck",config=self.config,history="",model_call=model_call,
        )
        self.assertEqual(outcome.status,"query_ready")
        self.assertEqual(outcome.query_result["records"][0]["id"],"L-duck")
        self.assertIn("11 septembre 2026", render_direct_reply(outcome))


    async def test_v121_ambiguity_search_proposes_full_source_memory(self):
        self.store.records.append({
            "id": "L-OLD", "kind": "action", "title": "déposé Coralie à l'aéroport",
            "status": "done", "completed_at": "2026-09-09T12:00:00+02:00",
            "due_at": None, "start_at": None,
            "entities": [{"canonical_name":"Coralie","entity_type":"person","role":"object"}],
            "source_text": "mercredi j'ai déposé Coralie à l'aéroport",
            "metadata": {"semantic_intake":{"actor":"user","verb":"déposer","object":"Coralie","destination":"aéroport"}},
        })
        calls = {"n": 0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None}, ensure_ascii=False)
            if calls["n"] == 2:
                return json.dumps({
                    "clarification":None,
                    "items":[{
                        "kind":"action","title":"croisé quelqu'un","status":"done","time_expression":"hier",
                        "actor":"user","verb":"croiser","object":"","inferred":False,
                        "unresolved":[{"field":"object","mention":"l'","reason":"pronoun"}]
                    }]
                }, ensure_ascii=False)
            if calls["n"] == 3:
                return json.dumps({"patches":[],"clarification":{"needed":True,"question":"Tu parles de qui ?"}}, ensure_ascii=False)
            self.assertIn("mercredi j'ai déposé Coralie à l'aéroport", kwargs.get("message",""))
            return json.dumps({"candidates":[{
                "item_index":0,"field":"object","value":"Coralie","record_id":"L-OLD",
                "confidence":0.88,"reason":"souvenir compatible"
            }]}, ensure_ascii=False)

        outcome = await semantic_intake(
            agent=FakeAgent(), store=self.store, message="je l'ai croisée hier",
            context_id="chat-v121-proposal", config=self.config, history="",
            model_call=model_call,
        )
        self.assertEqual(outcome.status, "clarification_required")
        self.assertIn("Coralie", outcome.clarification_question)
        self.assertIn("mercredi j'ai déposé Coralie à l'aéroport", outcome.clarification_question)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT pending_json FROM semantic_intake_state WHERE context_id=?",
                ("chat-v121-proposal",),
            ).fetchone()
        pending = json.loads(row["pending_json"])
        self.assertEqual(pending["type"], "memory_candidate_confirmation")
        self.assertEqual(pending["candidates"][0]["value"], "Coralie")

    async def test_v121_confirmed_candidate_is_applied_before_capture(self):
        self.store.records.append({
            "id": "L-OLD", "kind": "action", "title": "déposé Coralie à l'aéroport",
            "status": "done", "completed_at": "2026-09-09T12:00:00+02:00",
            "due_at": None, "start_at": None,
            "entities": [{"canonical_name":"Coralie","entity_type":"person","role":"object"}],
            "source_text": "mercredi j'ai déposé Coralie à l'aéroport",
            "metadata": {"semantic_intake":{"actor":"user","verb":"déposer","object":"Coralie"}},
        })
        ctx="chat-v121-confirm"
        calls={"n":0}
        async def first_model(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None})
            if calls["n"] == 2:
                return json.dumps({"clarification":None,"items":[{
                    "kind":"action","title":"croisé quelqu'un","status":"done","time_expression":"hier",
                    "actor":"user","verb":"croiser","object":"","inferred":False,
                    "unresolved":[{"field":"object","mention":"l'","reason":"pronoun"}]
                }]}, ensure_ascii=False)
            if calls["n"] == 3:
                return json.dumps({"patches":[],"clarification":{"needed":True,"question":"Tu parles de qui ?"}})
            return json.dumps({"candidates":[{
                "item_index":0,"field":"object","value":"Coralie","record_id":"L-OLD",
                "confidence":0.91,"reason":"souvenir compatible"
            }]}, ensure_ascii=False)

        first = await semantic_intake(
            agent=FakeAgent(), store=self.store, message="je l'ai croisée hier",
            context_id=ctx, config=self.config, history="", model_call=first_model,
        )
        self.assertEqual(first.status, "clarification_required")

        async def confirm_model(**kwargs):
            return json.dumps({"action":"accept","candidate_index":0,"value":""}, ensure_ascii=False)

        second = await semantic_intake(
            agent=FakeAgent(), store=self.store, message="oui",
            context_id=ctx, config=self.config, history="", model_call=confirm_model,
        )
        self.assertEqual(second.status, "captured")
        created = self.store.records[-1]
        self.assertEqual(created["source_text"], "je l'ai croisée hier")
        self.assertEqual(created["metadata"]["semantic_intake"]["object"], "Coralie")

    async def test_v121_multiple_memories_are_proposed_not_auto_selected(self):
        for rid, person, source in [
            ("L-A","Coralie","j'ai vu Coralie au marché"),
            ("L-B","Léa","j'ai vu Léa au marché"),
        ]:
            self.store.records.append({
                "id":rid,"kind":"action","title":f"vu {person} au marché","status":"done",
                "completed_at":"2026-09-09T12:00:00+02:00","due_at":None,"start_at":None,
                "entities":[{"canonical_name":person,"entity_type":"person","role":"object"}],
                "source_text":source,"metadata":{"semantic_intake":{"verb":"voir","object":person}},
            })
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None})
            if calls["n"] == 2:
                return json.dumps({"clarification":None,"items":[{
                    "kind":"action","title":"vue hier","status":"done","time_expression":"hier",
                    "actor":"user","verb":"voir","object":"","inferred":False,
                    "unresolved":[{"field":"object","mention":"elle","reason":"pronoun"}]
                }]})
            if calls["n"] == 3:
                return json.dumps({"patches":[],"clarification":{"needed":True,"question":"Tu parles de qui ?"}})
            return json.dumps({"candidates":[
                {"item_index":0,"field":"object","value":"Coralie","record_id":"L-A","confidence":0.79,"reason":"possible"},
                {"item_index":0,"field":"object","value":"Léa","record_id":"L-B","confidence":0.76,"reason":"possible"}
            ]}, ensure_ascii=False)
        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="je l'ai vue hier",
            context_id="chat-v121-multi",config=self.config,history="",model_call=model_call,
        )
        self.assertEqual(outcome.status,"clarification_required")
        self.assertIn("plusieurs souvenirs", outcome.clarification_question)
        self.assertIn("Coralie", outcome.clarification_question)
        self.assertIn("Léa", outcome.clarification_question)

    async def test_v121_no_candidate_falls_back_to_open_clarification(self):
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None})
            if calls["n"] == 2:
                return json.dumps({"clarification":None,"items":[{
                    "kind":"action","title":"parlé avec quelqu'un","status":"done",
                    "actor":"user","verb":"parler","object":"","inferred":False,
                    "unresolved":[{"field":"object","mention":"elle","reason":"pronoun"}]
                }]})
            if calls["n"] == 3:
                return json.dumps({"patches":[],"clarification":{"needed":True,"question":"Tu parles de qui ?"}})
            return json.dumps({"candidates":[]})
        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="j'ai parlé avec elle",
            context_id="chat-v121-none",config=self.config,history="",model_call=model_call,
        )
        self.assertEqual(outcome.status,"clarification_required")
        self.assertEqual(outcome.clarification_question,"De qui parles-tu ?")



    async def test_v122_pronoun_l_is_not_saved_as_quelquun(self):
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None})
            if calls["n"] == 2:
                # Reproduit le mauvais comportement observé : Qwen remplit le pronom par "quelqu'un".
                return json.dumps({"clarification":None,"items":[{
                    "kind":"action","title":"croisé quelqu'un","status":"done","time_expression":"hier",
                    "actor":"user","verb":"croiser","object":"quelqu'un","inferred":False
                }]}, ensure_ascii=False)
            if calls["n"] == 3:
                # L'auditeur corrige uniquement la référence.
                return json.dumps({"items":[{
                    "kind":"action","title":"croisé quelqu'un","status":"done","time_expression":"hier",
                    "actor":"user","verb":"croiser","object":"","inferred":False,
                    "unresolved":[{"field":"object","mention":"l'","reason":"pronoun_person"}]
                }]}, ensure_ascii=False)
            if calls["n"] == 4:
                return json.dumps({"patches":[],"clarification":None})
            return json.dumps({"question":"Qui as-tu croisé hier ?"}, ensure_ascii=False)

        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="je l'ai croisée hier",
            context_id="chat-v122-l",config=self.config,history="",model_call=model_call,
        )
        self.assertEqual(outcome.status,"clarification_required")
        self.assertEqual(outcome.clarification_question,"Qui as-tu croisé hier ?")
        self.assertEqual(len(self.store.records),0)

    async def test_v122_y_asks_where_not_reformulate(self):
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None})
            if calls["n"] == 2:
                return json.dumps({"clarification":None,"items":[{
                    "kind":"action","title":"retourné dans un lieu","status":"done","time_expression":"aujourd'hui",
                    "actor":"user","verb":"retourner","destination":"","inferred":False,
                    "unresolved":[{"field":"destination","mention":"y","reason":"deictic_place"}]
                }]}, ensure_ascii=False)
            if calls["n"] == 3:
                return json.dumps({"items":[{
                    "kind":"action","title":"retourné dans un lieu","status":"done","time_expression":"aujourd'hui",
                    "actor":"user","verb":"retourner","destination":"","inferred":False,
                    "unresolved":[{"field":"destination","mention":"y","reason":"deictic_place"}]
                }]}, ensure_ascii=False)
            if calls["n"] == 4:
                return json.dumps({"patches":[],"clarification":None})
            return json.dumps({"question":"Où es-tu retourné aujourd'hui ?"}, ensure_ascii=False)

        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="j'y suis retourné aujourd'hui",
            context_id="chat-v122-y",config=self.config,history="",model_call=model_call,
        )
        self.assertEqual(outcome.status,"clarification_required")
        self.assertEqual(outcome.clarification_question,"Où es-tu retourné aujourd'hui ?")
        self.assertNotIn("reformul", outcome.clarification_question.casefold())

    async def test_v122_lui_asks_a_qui_not_reformulate(self):
        calls={"n":0}
        async def model_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"route":"capture","uses_pending":False,"query_follow_up":False,"clarification":None})
            if calls["n"] == 2:
                return json.dumps({"clarification":None,"items":[{
                    "kind":"action","title":"parlé à une personne","status":"done","time_expression":"ce matin",
                    "actor":"user","verb":"parler","object":"","inferred":False,
                    "unresolved":[{"field":"object","mention":"lui","reason":"pronoun_person"}]
                }]}, ensure_ascii=False)
            if calls["n"] == 3:
                return json.dumps({"items":[{
                    "kind":"action","title":"parlé à une personne","status":"done","time_expression":"ce matin",
                    "actor":"user","verb":"parler","object":"","inferred":False,
                    "unresolved":[{"field":"object","mention":"lui","reason":"pronoun_person"}]
                }]}, ensure_ascii=False)
            if calls["n"] == 4:
                return json.dumps({"patches":[],"clarification":None})
            return json.dumps({"question":"À qui as-tu parlé ce matin ?"}, ensure_ascii=False)

        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="je lui ai parlé ce matin",
            context_id="chat-v122-lui",config=self.config,history="",model_call=model_call,
        )
        self.assertEqual(outcome.status,"clarification_required")
        self.assertEqual(outcome.clarification_question,"À qui as-tu parlé ce matin ?")
        self.assertNotIn("reformul", outcome.clarification_question.casefold())

    async def test_v122_open_reference_answer_completes_original_memory(self):
        ctx="chat-v122-open"
        # Crée directement l'état tel qu'il existe après « Qui as-tu croisé hier ? »
        partial={
            "mode":"capture","clarification":{"needed":True,"question":"Qui as-tu croisé hier ?"},
            "items":[{
                "kind":"action","title":"croisé une personne","status":"done","time_expression":"hier",
                "actor":"user","verb":"croiser","object":"","inferred":False,
                "unresolved":[{"field":"object","mention":"l'","reason":"pronoun_person"}]
            }]
        }
        from agent_os_memory.helpers.intake import _set_intake_state
        _set_intake_state(self.store,ctx,{
            "type":"reference_clarification",
            "original_message":"je l'ai croisée hier",
            "question":"Qui as-tu croisé hier ?",
            "partial_plan":partial,
            "candidates":[],
        })

        async def model_call(**kwargs):
            return json.dumps({"action":"provide_value","candidate_index":-1,"value":"Coralie"},ensure_ascii=False)

        outcome=await semantic_intake(
            agent=FakeAgent(),store=self.store,message="Coralie",
            context_id=ctx,config=self.config,history="",model_call=model_call,
        )
        self.assertEqual(outcome.status,"captured")
        self.assertEqual(self.store.records[-1]["source_text"],"je l'ai croisée hier")
        self.assertEqual(self.store.records[-1]["metadata"]["semantic_intake"]["object"],"Coralie")


if __name__ == "__main__":
    unittest.main()
