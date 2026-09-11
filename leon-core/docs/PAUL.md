# Paul — Leon + Letta

Paul is the personal-assistant layer built on top of Leon 2.0.

The design deliberately separates two kinds of memory:

| Layer | Role | Source of truth |
| --- | --- | --- |
| Paul structured store | Facts, relationships, activities, mood, habits, tasks, appointments, events, reminders, exact dates and counts | Local SQLite database per Leon profile |
| Leon memory | Conversation recall, owner profile and recent context | Existing Leon memory/QMD/session layers |
| Letta (optional) | Long-lived conversational identity, dialogue continuity and semantic recall | Local/self-hosted Letta agent |

Letta is never required for the structured Paul store. This keeps reminders and questions such as “combien de fois ai-je joué au tennis le 12/09 ?” deterministic and locally auditable.

## Local-first startup

1. Install the normal Leon dependencies and start Leon.

   ```sh
   pnpm install
   pnpm start
   ```

2. Enable the Paul toolkit through the normal Leon toolkit registry. The first runtime initialization creates the profile-local Paul database automatically.

3. Use the HTTP API or Leon’s agent mode:

   ```sh
   curl "http://127.0.0.1:5366/api/v1/paul/summary?date=demain"
   curl "http://127.0.0.1:5366/api/v1/paul/count?date=12/09/2026&object=tennis"
   ```

The exact database path is `<Leon profile root>/paul/paul.sqlite`. SQLite runs in WAL mode and every write is auditable in `paul_audit_events`.

## Letta layer

Letta is opt-in. Add these values to the profile `.env`:

```dotenv
PAUL_LETTA_ENABLED=true
PAUL_LETTA_URL=http://127.0.0.1:4500
PAUL_LETTA_TOKEN=
PAUL_LETTA_AGENT_ID=
PAUL_LETTA_MODEL=
```

For a local self-hosted Letta installation, the current Letta CLI flow is:

```sh
npm install -g @letta-ai/letta-code
letta --backend local connect ollama
letta server --backend local --listen ws://127.0.0.1:4500
```

If `PAUL_LETTA_AGENT_ID` is empty, Paul creates one agent through Letta’s `/v1/agents` endpoint and stores its id in `<Leon profile root>/paul/letta-agent.json`. Set `PAUL_LETTA_MODEL` when the server requires an explicit model. The `/api/v1/paul/letta` endpoint reports reachability without exposing credentials.

Chat through the bridge:

```sh
curl -X POST http://127.0.0.1:5366/api/v1/paul/chat \
  -H 'content-type: application/json' \
  -d '{"input":"Que sais-tu de mon programme demain ?"}'
```

Paul injects a compact structured context into every Letta turn. Letta can answer naturally, but Paul’s local data remains authoritative for dates, counts and reminders.

## Telegram

Leon includes a small dependency-free long-polling Telegram adapter. It is also opt-in:

```dotenv
PAUL_TELEGRAM_BOT_TOKEN=123456:replace-me
PAUL_TELEGRAM_ALLOWED_CHAT_IDS=123456789
PAUL_TELEGRAM_CHAT_ID=123456789
```

The adapter supports `/programme [date]`, `/rappels`, `/help`, free-form Letta chat when Letta is enabled, and delivery of due reminders from Paul’s outbox.

Do not run Letta’s native Telegram channel with the same bot token at the same time: Telegram only permits one polling consumer per token. The Leon adapter is the recommended first integration because it keeps Paul’s exact agenda and reminder delivery in the same profile runtime.

## Paul toolkit behavior

The `personal_assistant/paul` tool is available to Leon’s agent loop. It provides:

- durable facts and relationships;
- individual activity journal entries and exact counts;
- dated tasks, appointments, events and reminders;
- mood and habit tracking;
- date-aware program and context queries.

The intended write policy is simple: a durable personal statement is saved as a fact, a person-to-person statement as a relationship, a completed action as one activity, and a future intention as an agenda item. Each distinct activity is recorded separately so counts stay correct.

## HTTP endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/v1/paul/summary?date=...` | Combined program and context |
| GET | `/api/v1/paul/agenda?date=...` | Tasks, appointments, events and reminders |
| GET | `/api/v1/paul/activities?date=...` | Exact activity journal query |
| GET | `/api/v1/paul/count?date=...` | Exact activity count |
| GET | `/api/v1/paul/letta` | Letta status and reachability |
| POST | `/api/v1/paul/chat` | Optional Letta-backed conversation |
| POST | `/api/v1/paul/facts` | Add a durable fact |
| POST | `/api/v1/paul/relationships` | Add a relationship |
| POST | `/api/v1/paul/activities` | Add one activity |
| POST | `/api/v1/paul/agenda` | Add one dated item |
| POST | `/api/v1/paul/agenda/:id/complete` | Complete an item |
| POST | `/api/v1/paul/mood` | Record mood |
| POST | `/api/v1/paul/habits` | Create/update a habit |

All API routes remain behind Leon’s existing profile authentication hook.

## Next evolution

The current boundary is intentional: Leon owns exact personal data and action tools; Letta owns the conversational memory. The next safe extension is to expose Paul’s toolkit as a Letta MCP/client-tool surface so a Letta agent can write through the same validated Paul service instead of merely receiving context. That can be added without changing the SQLite schema or Telegram contract.
