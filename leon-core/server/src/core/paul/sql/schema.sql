PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS paul_schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paul_people (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL UNIQUE,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS paul_facts (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  value_json TEXT NOT NULL,
  canonical_text TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.9,
  source_text TEXT,
  source_ref TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  supersedes_id TEXT,
  is_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_paul_facts_subject_predicate
  ON paul_facts(subject, predicate, is_deleted);

CREATE TABLE IF NOT EXISTS paul_relationships (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  relation TEXT NOT NULL,
  object TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.95,
  source_text TEXT,
  source_ref TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  UNIQUE(subject, relation, object)
);

CREATE INDEX IF NOT EXISTS idx_paul_relationships_subject
  ON paul_relationships(subject, relation, is_deleted);

CREATE TABLE IF NOT EXISTS paul_activities (
  id TEXT PRIMARY KEY,
  occurred_at INTEGER NOT NULL,
  day_key TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT 'Romain',
  action TEXT NOT NULL,
  object TEXT,
  location TEXT,
  details_json TEXT NOT NULL DEFAULT '{}',
  source_text TEXT,
  source_ref TEXT,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_paul_activities_day_action
  ON paul_activities(day_key, action);
CREATE INDEX IF NOT EXISTS idx_paul_activities_occurred_at
  ON paul_activities(occurred_at);

CREATE TABLE IF NOT EXISTS paul_agenda_items (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('task', 'appointment', 'event', 'reminder')),
  title TEXT NOT NULL,
  description TEXT,
  start_at INTEGER,
  due_at INTEGER,
  end_at INTEGER,
  timezone TEXT NOT NULL DEFAULT 'Europe/Paris',
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'completed', 'cancelled', 'snoozed')),
  original_due_at INTEGER,
  related_person TEXT,
  recurrence_json TEXT,
  source_text TEXT,
  source_ref TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  completed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_paul_agenda_due_status
  ON paul_agenda_items(due_at, status);
CREATE INDEX IF NOT EXISTS idx_paul_agenda_start_status
  ON paul_agenda_items(start_at, status);
CREATE INDEX IF NOT EXISTS idx_paul_agenda_kind_status
  ON paul_agenda_items(kind, status);

CREATE TABLE IF NOT EXISTS paul_moods (
  id TEXT PRIMARY KEY,
  occurred_at INTEGER NOT NULL,
  day_key TEXT NOT NULL,
  label TEXT NOT NULL,
  score INTEGER,
  note TEXT,
  source_text TEXT,
  source_ref TEXT,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_paul_moods_day
  ON paul_moods(day_key, occurred_at);

CREATE TABLE IF NOT EXISTS paul_habits (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  schedule_json TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS paul_habit_occurrences (
  id TEXT PRIMARY KEY,
  habit_id TEXT NOT NULL,
  occurred_at INTEGER NOT NULL,
  day_key TEXT NOT NULL,
  source_text TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (habit_id) REFERENCES paul_habits(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_paul_habit_occurrences_day
  ON paul_habit_occurrences(habit_id, day_key);

CREATE TABLE IF NOT EXISTS paul_conversation_context (
  session_id TEXT PRIMARY KEY,
  last_intent TEXT,
  last_date_range_json TEXT,
  last_entity TEXT,
  last_query TEXT,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS paul_audit_events (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_paul_audit_created
  ON paul_audit_events(created_at);

CREATE TABLE IF NOT EXISTS paul_notification_outbox (
  id TEXT PRIMARY KEY,
  notification_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  delivered_at INTEGER,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_paul_outbox_pending
  ON paul_notification_outbox(delivered_at, created_at);

INSERT OR IGNORE INTO paul_schema_meta(key, value)
VALUES ('schema_version', '1');
