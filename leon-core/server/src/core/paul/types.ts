export type PaulAgendaKind =
  | 'task'
  | 'appointment'
  | 'event'
  | 'reminder'

export type PaulAgendaStatus =
  | 'open'
  | 'completed'
  | 'cancelled'
  | 'snoozed'

export type PaulMoodScore = -2 | -1 | 0 | 1 | 2

export interface PaulPerson {
  id: string
  displayName: string
  normalizedName: string
  aliases: string[]
  createdAt: number
  updatedAt: number
}

export interface PaulFact {
  id: string
  subject: string
  predicate: string
  value: unknown
  canonicalText: string
  confidence: number
  sourceText: string | null
  createdAt: number
  updatedAt: number
}

export interface PaulRelationship {
  id: string
  subject: string
  relation: string
  object: string
  confidence: number
  sourceText: string | null
  createdAt: number
  updatedAt: number
}

export interface PaulActivity {
  id: string
  occurredAt: number
  dayKey: string
  actor: string
  action: string
  object: string | null
  location: string | null
  details: Record<string, unknown>
  sourceText: string | null
  createdAt: number
}

export interface PaulAgendaItem {
  id: string
  kind: PaulAgendaKind
  title: string
  description: string | null
  startAt: number | null
  dueAt: number | null
  endAt: number | null
  timezone: string
  status: PaulAgendaStatus
  originalDueAt: number | null
  relatedPerson: string | null
  recurrence: Record<string, unknown> | null
  sourceText: string | null
  createdAt: number
  updatedAt: number
  completedAt: number | null
}

export interface PaulMoodEntry {
  id: string
  occurredAt: number
  dayKey: string
  label: string
  score: PaulMoodScore | null
  note: string | null
  sourceText: string | null
  createdAt: number
}

export interface PaulHabit {
  id: string
  name: string
  description: string | null
  schedule: Record<string, unknown> | null
  active: boolean
  createdAt: number
  updatedAt: number
}

export interface PaulDateRange {
  startDay: string
  endDay: string
  startAt: number
  endAt: number
  expression: string | null
}

export interface PaulConversationContext {
  sessionId: string
  lastIntent: string | null
  lastDateRange: PaulDateRange | null
  lastEntity: string | null
  lastQuery: string | null
  updatedAt: number
}

export interface PaulProgram {
  dayKey: string
  tasks: PaulAgendaItem[]
  appointments: PaulAgendaItem[]
  events: PaulAgendaItem[]
  reminders: PaulAgendaItem[]
  activities: PaulActivity[]
}

export interface PaulContextPack {
  today: string
  profile: {
    facts: PaulFact[]
    relationships: PaulRelationship[]
  }
  agenda: PaulAgendaItem[]
  recentActivities: PaulActivity[]
  recentMoods: PaulMoodEntry[]
  pendingReminders: PaulAgendaItem[]
  previousContext: PaulConversationContext | null
}

export interface PaulStoreOptions {
  profileName?: string
  databasePath?: string
  now?: () => number
  timezone?: string
}
