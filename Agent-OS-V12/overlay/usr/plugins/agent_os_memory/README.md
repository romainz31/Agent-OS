# Agent-OS V12 — Personal Memory

This Agent Zero plugin stores personal information in a structured SQLite
database. It complements Agent Zero's vector memory; it does not replace it.
V12 adds a local Qwen/Ollama semantic layer for extracting memories and
understanding natural-language queries. Python validates the proposal and
SQLite remains the source of truth.

## Tools

- `life_capture`: add a task, appointment, event, completed action, mood or fact.
- `life_query`: retrieve or count personal records and current facts.
- `life_update`: complete, reschedule, cancel or correct an existing record.
- `life_forget`: soft-delete explicitly selected personal information.
- `life_rollover`: move overdue explicitly dated tasks to today.

The semantic intake also preserves the complete source message, semantic
states, occurrences, places, people and versioned entity attributes. When the
local model is unavailable, a deterministic offline fallback keeps basic
identity, preference, task and activity flows available.

The rollover also runs automatically at the start of each top-level chat loop.
It is idempotent and never moves appointments, events or undated backlog items.

All mutations are transactional and appended to `record_history`. Current facts
are versioned: a correction closes the previous value rather than deleting its
history.
