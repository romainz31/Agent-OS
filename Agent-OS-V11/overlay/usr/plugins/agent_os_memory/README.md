# Agent-OS Personal Memory

This Agent Zero plugin stores Paul's personal memory in a structured SQLite
database. It complements Agent Zero's vector memory; it does not replace it.

## Tools

- `life_capture`: add a task, appointment, event, completed action, mood, note,
  preference or fact. Every user declaration keeps an evidence row with the
  original text and its details.
- `life_query`: retrieve or count personal records and current facts.
- `life_update`: complete, reschedule, cancel or correct an existing record.
- `life_forget`: soft-delete explicitly selected personal information.
- `life_rollover`: move overdue explicitly dated tasks to the general backlog
  without losing their original date.

The rollover also runs automatically at the start of each top-level chat loop.
It is idempotent and never moves appointments, events or undated backlog items.

All mutations are transactional and appended to `record_history`. Every capture
also writes to `record_observations`, so repeated actions can be counted and
their individual messages and metadata can be recovered. Current facts are
versioned: a correction closes the previous value rather than deleting its
history.
