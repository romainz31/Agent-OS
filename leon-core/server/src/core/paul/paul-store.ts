import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'

import SQLite from 'better-sqlite3'
import type { Database as SQLiteDatabase } from 'better-sqlite3'

import { getProfilePaths } from '@/core/profile-runtime/profile-paths'
import { getActiveProfileName } from '@/core/profile-runtime/profile-context'

import type {
  PaulActivity,
  PaulAgendaItem,
  PaulAgendaKind,
  PaulAgendaStatus,
  PaulConversationContext,
  PaulDateRange,
  PaulFact,
  PaulHabit,
  PaulMoodEntry,
  PaulMoodScore,
  PaulPerson,
  PaulProgram,
  PaulRelationship,
  PaulStoreOptions
} from './types'
import { dayKeyInTimezone } from './temporal'

const SCHEMA_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'sql',
  'schema.sql'
)

function normalizeName(value: string): string {
  return value
    .trim()
    .toLocaleLowerCase('fr-FR')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
}

function parseJson<T>(value: unknown, fallback: T): T {
  if (typeof value !== 'string') {
    return fallback
  }

  try {
    return JSON.parse(value) as T
  } catch {
    return fallback
  }
}

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined) {
    return null
  }
  const result = Number(value)
  return Number.isFinite(result) ? result : null
}

function stringOrNull(value: unknown): string | null {
  return value === null || value === undefined || value === ''
    ? null
    : String(value)
}

function castRow<T>(row: unknown): T {
  return row as T
}

export interface PaulFactInput {
  subject: string
  predicate: string
  value: unknown
  canonicalText?: string
  confidence?: number
  sourceText?: string | null
  sourceRef?: string | null
}

export interface PaulRelationshipInput {
  subject: string
  relation: string
  object: string
  confidence?: number
  sourceText?: string | null
  sourceRef?: string | null
}

export interface PaulActivityInput {
  occurredAt: number
  actor?: string
  action: string
  object?: string | null
  location?: string | null
  details?: Record<string, unknown>
  sourceText?: string | null
  sourceRef?: string | null
}

export interface PaulAgendaInput {
  kind: PaulAgendaKind
  title: string
  description?: string | null
  startAt?: number | null
  dueAt?: number | null
  endAt?: number | null
  timezone?: string
  relatedPerson?: string | null
  recurrence?: Record<string, unknown> | null
  sourceText?: string | null
  sourceRef?: string | null
}

export interface PaulMoodInput {
  occurredAt?: number
  label: string
  score?: PaulMoodScore | null
  note?: string | null
  sourceText?: string | null
  sourceRef?: string | null
}

export interface PaulHabitInput {
  name: string
  description?: string | null
  schedule?: Record<string, unknown> | null
  active?: boolean
}

interface PaulActivityRow {
  id: string
  occurred_at: number
  day_key: string
  actor: string
  action: string
  object: string | null
  location: string | null
  details_json: string
  source_text: string | null
  created_at: number
}

interface PaulAgendaRow {
  id: string
  kind: PaulAgendaKind
  title: string
  description: string | null
  start_at: number | null
  due_at: number | null
  end_at: number | null
  timezone: string
  status: PaulAgendaStatus
  original_due_at: number | null
  related_person: string | null
  recurrence_json: string | null
  source_text: string | null
  created_at: number
  updated_at: number
  completed_at: number | null
}

interface PaulFactRow {
  id: string
  subject: string
  predicate: string
  value_json: string
  canonical_text: string
  confidence: number
  source_text: string | null
  created_at: number
  updated_at: number
}

interface PaulRelationshipRow {
  id: string
  subject: string
  relation: string
  object: string
  confidence: number
  source_text: string | null
  created_at: number
  updated_at: number
}

interface PaulMoodRow {
  id: string
  occurred_at: number
  day_key: string
  label: string
  score: number | null
  note: string | null
  source_text: string | null
  created_at: number
}

interface PaulHabitRow {
  id: string
  name: string
  description: string | null
  schedule_json: string | null
  active: number
  created_at: number
  updated_at: number
}

export default class PaulStore {
  private db: SQLiteDatabase | null = null
  private readonly profileName: string
  private readonly configuredDatabasePath: string | undefined
  private readonly timezone: string
  private readonly now: () => number

  public constructor(options: PaulStoreOptions = {}) {
    this.profileName = options.profileName || getActiveProfileName()
    this.configuredDatabasePath = options.databasePath
    this.timezone = options.timezone || process.env['PAUL_TIMEZONE'] || 'Europe/Paris'
    this.now = options.now || Date.now
  }

  public get databasePath(): string {
    return this.configuredDatabasePath || path.join(getProfilePaths(this.profileName).root, 'paul', 'paul.sqlite')
  }

  public get isReady(): boolean {
    return this.db !== null
  }

  public initialize(): void {
    if (this.db) {
      return
    }

    fs.mkdirSync(path.dirname(this.databasePath), { recursive: true })
    this.db = new SQLite(this.databasePath)
    this.db.pragma('foreign_keys = ON')
    this.db.pragma('journal_mode = WAL')
    this.db.pragma('synchronous = NORMAL')
    this.db.exec(fs.readFileSync(SCHEMA_PATH, 'utf8'))
  }

  public close(): void {
    this.db?.close()
    this.db = null
  }

  public addPerson(displayName: string, aliases: string[] = []): PaulPerson {
    const db = this.ensureDb()
    const now = this.now()
    const normalizedName = normalizeName(displayName)
    const existing = db
      .prepare('SELECT * FROM paul_people WHERE normalized_name = ?')
      .get(normalizedName) as Record<string, unknown> | undefined

    if (existing) {
      db.prepare(
        'UPDATE paul_people SET display_name = ?, aliases_json = ?, updated_at = ? WHERE id = ?'
      ).run(
        displayName.trim(),
        JSON.stringify([...new Set(aliases)]),
        now,
        existing['id']
      )
      return this.getPerson(String(existing['id'])) as PaulPerson
    }

    const id = randomUUID()
    db.prepare(
      `INSERT INTO paul_people
       (id, display_name, normalized_name, aliases_json, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)`
    ).run(id, displayName.trim(), normalizedName, JSON.stringify(aliases), now, now)
    this.audit('person.created', 'person', id, { displayName })
    return this.getPerson(id) as PaulPerson
  }

  public getPerson(id: string): PaulPerson | null {
    const row = this.ensureDb()
      .prepare('SELECT * FROM paul_people WHERE id = ?')
      .get(id) as Record<string, unknown> | undefined
    if (!row) return null
    return {
      id: String(row['id']),
      displayName: String(row['display_name']),
      normalizedName: String(row['normalized_name']),
      aliases: parseJson<string[]>(row['aliases_json'], []),
      createdAt: Number(row['created_at']),
      updatedAt: Number(row['updated_at'])
    }
  }

  public addFact(input: PaulFactInput): PaulFact {
    const db = this.ensureDb()
    const now = this.now()
    const subject = input.subject.trim()
    const predicate = input.predicate.trim()
    const canonicalText = input.canonicalText?.trim() ||
      `${subject} ${predicate} ${String(input.value)}`
    const existing = db.prepare(
      `SELECT * FROM paul_facts
       WHERE subject = ? AND predicate = ? AND is_deleted = 0
       ORDER BY updated_at DESC LIMIT 1`
    ).get(subject, predicate) as PaulFactRow | undefined

    if (existing && JSON.stringify(parseJson(existing.value_json, null)) === JSON.stringify(input.value)) {
      db.prepare('UPDATE paul_facts SET updated_at = ?, confidence = ?, source_text = ? WHERE id = ?')
        .run(now, input.confidence ?? existing.confidence, input.sourceText || existing.source_text, existing.id)
      return this.mapFact({ ...existing, updated_at: now, confidence: input.confidence ?? existing.confidence, source_text: input.sourceText || existing.source_text })
    }

    const id = randomUUID()
    db.prepare(
      `INSERT INTO paul_facts
       (id, subject, predicate, value_json, canonical_text, confidence, source_text, source_ref, created_at, updated_at, supersedes_id)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      id,
      subject,
      predicate,
      JSON.stringify(input.value),
      canonicalText,
      input.confidence ?? 0.9,
      input.sourceText || null,
      input.sourceRef || null,
      now,
      now,
      existing?.id || null
    )
    this.audit('fact.created', 'fact', id, input)
    return this.getFact(id) as PaulFact
  }

  public getFact(id: string): PaulFact | null {
    const row = this.ensureDb().prepare('SELECT * FROM paul_facts WHERE id = ?').get(id) as PaulFactRow | undefined
    return row ? this.mapFact(row) : null
  }

  public listFacts(subject?: string): PaulFact[] {
    const rows = subject
      ? this.ensureDb().prepare('SELECT * FROM paul_facts WHERE subject = ? AND is_deleted = 0 ORDER BY updated_at DESC').all(subject)
      : this.ensureDb().prepare('SELECT * FROM paul_facts WHERE is_deleted = 0 ORDER BY updated_at DESC').all()
    return rows.map((row) => this.mapFact(castRow<PaulFactRow>(row)))
  }

  public addRelationship(input: PaulRelationshipInput): PaulRelationship {
    const db = this.ensureDb()
    const now = this.now()
    const existing = db.prepare(
      'SELECT * FROM paul_relationships WHERE subject = ? AND relation = ? AND object = ? AND is_deleted = 0'
    ).get(input.subject.trim(), input.relation.trim(), input.object.trim()) as PaulRelationshipRow | undefined
    if (existing) {
      return this.mapRelationship(existing)
    }
    const id = randomUUID()
    db.prepare(
      `INSERT INTO paul_relationships
       (id, subject, relation, object, confidence, source_text, source_ref, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      id,
      input.subject.trim(),
      input.relation.trim(),
      input.object.trim(),
      input.confidence ?? 0.95,
      input.sourceText || null,
      input.sourceRef || null,
      now,
      now
    )
    this.audit('relationship.created', 'relationship', id, input)
    return this.getRelationship(id) as PaulRelationship
  }

  public getRelationship(id: string): PaulRelationship | null {
    const row = this.ensureDb().prepare('SELECT * FROM paul_relationships WHERE id = ?').get(id) as PaulRelationshipRow | undefined
    return row ? this.mapRelationship(row) : null
  }

  public listRelationships(subject?: string): PaulRelationship[] {
    const rows = subject
      ? this.ensureDb().prepare('SELECT * FROM paul_relationships WHERE subject = ? AND is_deleted = 0 ORDER BY updated_at DESC').all(subject)
      : this.ensureDb().prepare('SELECT * FROM paul_relationships WHERE is_deleted = 0 ORDER BY updated_at DESC').all()
    return rows.map((row) => this.mapRelationship(castRow<PaulRelationshipRow>(row)))
  }

  public recordActivity(input: PaulActivityInput): PaulActivity {
    const db = this.ensureDb()
    const now = this.now()
    const id = randomUUID()
    db.prepare(
      `INSERT INTO paul_activities
       (id, occurred_at, day_key, actor, action, object, location, details_json, source_text, source_ref, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      id,
      input.occurredAt,
      dayKeyInTimezone(input.occurredAt, this.timezone),
      input.actor?.trim() || 'Romain',
      input.action.trim(),
      input.object?.trim() || null,
      input.location?.trim() || null,
      JSON.stringify(input.details || {}),
      input.sourceText || null,
      input.sourceRef || null,
      now
    )
    this.audit('activity.created', 'activity', id, input)
    return this.getActivity(id) as PaulActivity
  }

  public getActivity(id: string): PaulActivity | null {
    const row = this.ensureDb().prepare('SELECT * FROM paul_activities WHERE id = ?').get(id) as PaulActivityRow | undefined
    return row ? this.mapActivity(row) : null
  }

  public listActivities(range: PaulDateRange, action?: string, object?: string): PaulActivity[] {
    const rows = this.ensureDb().prepare(
      `SELECT * FROM paul_activities
       WHERE occurred_at >= ? AND occurred_at <= ?
         AND (? IS NULL OR lower(action) LIKE lower(?))
         AND (? IS NULL OR lower(coalesce(object, '')) LIKE lower(?))
       ORDER BY occurred_at ASC`
    ).all(range.startAt, range.endAt, action || null, `%${action || ''}%`, object || null, `%${object || ''}%`)
    return rows.map((row) => this.mapActivity(castRow<PaulActivityRow>(row)))
  }

  public countActivities(range: PaulDateRange, action?: string, object?: string): number {
    const row = this.ensureDb().prepare(
      `SELECT COUNT(*) AS count FROM paul_activities
       WHERE occurred_at >= ? AND occurred_at <= ?
         AND (? IS NULL OR lower(action) LIKE lower(?))
         AND (? IS NULL OR lower(coalesce(object, '')) LIKE lower(?))`
    ).get(range.startAt, range.endAt, action || null, `%${action || ''}%`, object || null, `%${object || ''}%`) as { count: number }
    return Number(row.count || 0)
  }

  public createAgendaItem(input: PaulAgendaInput): PaulAgendaItem {
    const db = this.ensureDb()
    const now = this.now()
    const id = randomUUID()
    const dueAt = input.dueAt ?? input.startAt ?? null
    db.prepare(
      `INSERT INTO paul_agenda_items
       (id, kind, title, description, start_at, due_at, end_at, timezone, status, original_due_at,
        related_person, recurrence_json, source_text, source_ref, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      id,
      input.kind,
      input.title.trim(),
      input.description || null,
      input.startAt ?? null,
      dueAt,
      input.endAt ?? null,
      input.timezone || this.timezone,
      dueAt,
      input.relatedPerson || null,
      input.recurrence ? JSON.stringify(input.recurrence) : null,
      input.sourceText || null,
      input.sourceRef || null,
      now,
      now
    )
    this.audit('agenda.created', 'agenda', id, input)
    return this.getAgendaItem(id) as PaulAgendaItem
  }

  public getAgendaItem(id: string): PaulAgendaItem | null {
    const row = this.ensureDb().prepare('SELECT * FROM paul_agenda_items WHERE id = ?').get(id) as PaulAgendaRow | undefined
    return row ? this.mapAgenda(row) : null
  }

  public listAgenda(range: PaulDateRange, includeCompleted = false): PaulAgendaItem[] {
    const statusFilter = includeCompleted ? '' : 'AND status NOT IN (\'completed\', \'cancelled\')'
    const rows = this.ensureDb().prepare(
      `SELECT * FROM paul_agenda_items
       WHERE ((start_at IS NOT NULL AND start_at BETWEEN ? AND ?)
          OR (due_at IS NOT NULL AND due_at BETWEEN ? AND ?)
          OR (start_at IS NULL AND due_at IS NULL AND created_at BETWEEN ? AND ?))
       ${statusFilter}
       ORDER BY coalesce(start_at, due_at, created_at) ASC`
    ).all(range.startAt, range.endAt, range.startAt, range.endAt, range.startAt, range.endAt)
    return rows.map((row) => this.mapAgenda(castRow<PaulAgendaRow>(row)))
  }

  public completeAgendaItem(id: string): PaulAgendaItem | null {
    const db = this.ensureDb()
    const now = this.now()
    const result = db.prepare(
      'UPDATE paul_agenda_items SET status = \'completed\', completed_at = ?, updated_at = ? WHERE id = ? AND status != \'cancelled\''
    ).run(now, now, id)
    if ((result.changes ?? 0) > 0) this.audit('agenda.completed', 'agenda', id, {})
    return this.getAgendaItem(id)
  }

  public listDueReminders(untilAt: number): PaulAgendaItem[] {
    const rows = this.ensureDb().prepare(
      `SELECT * FROM paul_agenda_items
       WHERE kind = 'reminder' AND status = 'open' AND due_at IS NOT NULL AND due_at <= ?
       ORDER BY due_at ASC`
    ).all(untilAt)
    return rows.map((row) => this.mapAgenda(castRow<PaulAgendaRow>(row)))
  }

  public enqueueNotification(notificationType: string, payload: Record<string, unknown>): string {
    const id = randomUUID()
    this.ensureDb().prepare(
      'INSERT INTO paul_notification_outbox(id, notification_type, payload_json, created_at) VALUES (?, ?, ?, ?)'
    ).run(id, notificationType, JSON.stringify(payload), this.now())
    return id
  }

  public getPendingNotifications(limit = 20): Array<{ id: string, notificationType: string, payload: Record<string, unknown> }> {
    const rows = this.ensureDb().prepare(
      'SELECT * FROM paul_notification_outbox WHERE delivered_at IS NULL ORDER BY created_at ASC LIMIT ?'
    ).all(limit) as Array<Record<string, unknown>>
    return rows.map((row) => ({
      id: String(row['id']),
      notificationType: String(row['notification_type']),
      payload: parseJson<Record<string, unknown>>(row['payload_json'], {})
    }))
  }

  public markNotificationDelivered(id: string): void {
    this.ensureDb().prepare('UPDATE paul_notification_outbox SET delivered_at = ? WHERE id = ?').run(this.now(), id)
  }

  public recordMood(input: PaulMoodInput): PaulMoodEntry {
    const db = this.ensureDb()
    const now = this.now()
    const occurredAt = input.occurredAt || now
    const id = randomUUID()
    db.prepare(
      `INSERT INTO paul_moods
       (id, occurred_at, day_key, label, score, note, source_text, source_ref, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(id, occurredAt, dayKeyInTimezone(occurredAt, this.timezone), input.label.trim(), input.score ?? null, input.note || null, input.sourceText || null, input.sourceRef || null, now)
    this.audit('mood.created', 'mood', id, input)
    return this.getMood(id) as PaulMoodEntry
  }

  public getMood(id: string): PaulMoodEntry | null {
    const row = this.ensureDb().prepare('SELECT * FROM paul_moods WHERE id = ?').get(id) as PaulMoodRow | undefined
    return row ? this.mapMood(row) : null
  }

  public listMoods(range: PaulDateRange): PaulMoodEntry[] {
    const rows = this.ensureDb().prepare('SELECT * FROM paul_moods WHERE occurred_at BETWEEN ? AND ? ORDER BY occurred_at ASC').all(range.startAt, range.endAt)
    return rows.map((row) => this.mapMood(castRow<PaulMoodRow>(row)))
  }

  public upsertHabit(input: PaulHabitInput): PaulHabit {
    const db = this.ensureDb()
    const now = this.now()
    const name = input.name.trim()
    const existing = db.prepare('SELECT * FROM paul_habits WHERE lower(name) = lower(?)').get(name) as PaulHabitRow | undefined
    if (existing) {
      db.prepare('UPDATE paul_habits SET description = ?, schedule_json = ?, active = ?, updated_at = ? WHERE id = ?').run(input.description || existing.description, input.schedule ? JSON.stringify(input.schedule) : existing.schedule_json, input.active === false ? 0 : 1, now, existing.id)
      return this.getHabit(existing.id) as PaulHabit
    }
    const id = randomUUID()
    db.prepare('INSERT INTO paul_habits(id, name, description, schedule_json, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)').run(id, name, input.description || null, input.schedule ? JSON.stringify(input.schedule) : null, input.active === false ? 0 : 1, now, now)
    this.audit('habit.created', 'habit', id, input)
    return this.getHabit(id) as PaulHabit
  }

  public getHabit(id: string): PaulHabit | null {
    const row = this.ensureDb().prepare('SELECT * FROM paul_habits WHERE id = ?').get(id) as PaulHabitRow | undefined
    return row ? this.mapHabit(row) : null
  }

  public listHabits(activeOnly = false): PaulHabit[] {
    const rows = activeOnly
      ? this.ensureDb().prepare('SELECT * FROM paul_habits WHERE active = 1 ORDER BY name').all()
      : this.ensureDb().prepare('SELECT * FROM paul_habits ORDER BY name').all()
    return rows.map((row) => this.mapHabit(castRow<PaulHabitRow>(row)))
  }

  public saveConversationContext(context: PaulConversationContext): void {
    this.ensureDb().prepare(
      `INSERT INTO paul_conversation_context(session_id, last_intent, last_date_range_json, last_entity, last_query, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(session_id) DO UPDATE SET last_intent=excluded.last_intent,
       last_date_range_json=excluded.last_date_range_json, last_entity=excluded.last_entity,
       last_query=excluded.last_query, updated_at=excluded.updated_at`
    ).run(context.sessionId, context.lastIntent, context.lastDateRange ? JSON.stringify(context.lastDateRange) : null, context.lastEntity, context.lastQuery, context.updatedAt)
  }

  public getConversationContext(sessionId: string): PaulConversationContext | null {
    const row = this.ensureDb().prepare('SELECT * FROM paul_conversation_context WHERE session_id = ?').get(sessionId) as Record<string, unknown> | undefined
    if (!row) return null
    return {
      sessionId: String(row['session_id']),
      lastIntent: stringOrNull(row['last_intent']),
      lastDateRange: parseJson<PaulDateRange | null>(row['last_date_range_json'], null),
      lastEntity: stringOrNull(row['last_entity']),
      lastQuery: stringOrNull(row['last_query']),
      updatedAt: Number(row['updated_at'])
    }
  }

  public getProgram(range: PaulDateRange): PaulProgram {
    const agenda = this.listAgenda(range)
    const activities = this.listActivities(range)
    return {
      dayKey: range.startDay,
      tasks: agenda.filter((item) => item.kind === 'task'),
      appointments: agenda.filter((item) => item.kind === 'appointment'),
      events: agenda.filter((item) => item.kind === 'event'),
      reminders: agenda.filter((item) => item.kind === 'reminder'),
      activities
    }
  }

  private audit(eventType: string, entityType: string, entityId: string | null, payload: unknown): void {
    this.ensureDb().prepare(
      'INSERT INTO paul_audit_events(id, event_type, entity_type, entity_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)'
    ).run(randomUUID(), eventType, entityType, entityId, JSON.stringify(payload), this.now())
  }

  private ensureDb(): SQLiteDatabase {
    if (!this.db) this.initialize()
    if (!this.db) throw new Error('Paul store could not be initialized.')
    return this.db
  }

  private mapFact(row: PaulFactRow): PaulFact {
    return {
      id: row.id,
      subject: row.subject,
      predicate: row.predicate,
      value: parseJson(row.value_json, row.value_json),
      canonicalText: row.canonical_text,
      confidence: Number(row.confidence),
      sourceText: row.source_text,
      createdAt: Number(row.created_at),
      updatedAt: Number(row.updated_at)
    }
  }

  private mapRelationship(row: PaulRelationshipRow): PaulRelationship {
    return {
      id: row.id,
      subject: row.subject,
      relation: row.relation,
      object: row.object,
      confidence: Number(row.confidence),
      sourceText: row.source_text,
      createdAt: Number(row.created_at),
      updatedAt: Number(row.updated_at)
    }
  }

  private mapActivity(row: PaulActivityRow): PaulActivity {
    return {
      id: row.id,
      occurredAt: Number(row.occurred_at),
      dayKey: row.day_key,
      actor: row.actor,
      action: row.action,
      object: row.object,
      location: row.location,
      details: parseJson<Record<string, unknown>>(row.details_json, {}),
      sourceText: row.source_text,
      createdAt: Number(row.created_at)
    }
  }

  private mapAgenda(row: PaulAgendaRow): PaulAgendaItem {
    return {
      id: row.id,
      kind: row.kind,
      title: row.title,
      description: row.description,
      startAt: numberOrNull(row.start_at),
      dueAt: numberOrNull(row.due_at),
      endAt: numberOrNull(row.end_at),
      timezone: row.timezone,
      status: row.status,
      originalDueAt: numberOrNull(row.original_due_at),
      relatedPerson: row.related_person,
      recurrence: parseJson<Record<string, unknown> | null>(row.recurrence_json, null),
      sourceText: row.source_text,
      createdAt: Number(row.created_at),
      updatedAt: Number(row.updated_at),
      completedAt: numberOrNull(row.completed_at)
    }
  }

  private mapMood(row: PaulMoodRow): PaulMoodEntry {
    return {
      id: row.id,
      occurredAt: Number(row.occurred_at),
      dayKey: row.day_key,
      label: row.label,
      score: row.score === null ? null : Number(row.score) as PaulMoodScore,
      note: row.note,
      sourceText: row.source_text,
      createdAt: Number(row.created_at)
    }
  }

  private mapHabit(row: PaulHabitRow): PaulHabit {
    return {
      id: row.id,
      name: row.name,
      description: row.description,
      schedule: parseJson<Record<string, unknown> | null>(row.schedule_json, null),
      active: Number(row.active) === 1,
      createdAt: Number(row.created_at),
      updatedAt: Number(row.updated_at)
    }
  }
}
