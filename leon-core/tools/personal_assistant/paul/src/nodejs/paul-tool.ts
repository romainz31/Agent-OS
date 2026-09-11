import { Tool } from '@sdk/base-tool'
import { ToolkitConfig } from '@sdk/toolkit-config'
import { getActiveProfileName } from '@@/server/src/core/profile-runtime/profile-context'
import PaulService from '@@/server/src/core/paul/paul-service'
import { inferDateRangeFromText, resolveDateRange } from '@@/server/src/core/paul/temporal'

function timestamp(value: unknown, fallback = Date.now()): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value !== 'string' || !value.trim()) return fallback
  const expression = value.trim()
  const inferred = inferDateRangeFromText(expression, new Date(fallback), 'nearest')
  if (inferred) return inferred.startAt
  const parsed = Date.parse(expression)
  if (Number.isFinite(parsed)) return parsed
  return fallback
}

export default class PaulTool extends Tool {
  private readonly config: ReturnType<typeof ToolkitConfig.load>
  private readonly service = new PaulService()

  public constructor() {
    super()
    this.config = ToolkitConfig.load('personal_assistant', this.toolName)
    this.settings = ToolkitConfig.loadToolSettings('personal_assistant', this.toolName, {})
    this.requiredSettings = []
    this.checkRequiredSettings(this.toolName)
  }

  public get toolName(): string { return 'paul' }
  public get toolkit(): string { return 'personal_assistant' }
  public get description(): string { return String(this.config['description'] || '') }

  public async saveFact(
    subject: string,
    predicate: string,
    value: unknown,
    canonicalText?: string,
    sourceText?: string,
    confidence?: number
  ): Promise<Record<string, unknown>> {
    const result = this.service.addFact({ subject, predicate, value, canonicalText, sourceText, confidence })
    return { success: true, profile: getActiveProfileName(), fact: result }
  }

  public async saveRelationship(
    subject: string,
    relation: string,
    object: string,
    sourceText?: string,
    confidence?: number
  ): Promise<Record<string, unknown>> {
    const result = this.service.addRelationship({ subject, relation, object, sourceText, confidence })
    return { success: true, relationship: result }
  }

  public async recordActivity(
    occurredAt: string | number,
    actor: string | undefined,
    action: string,
    object?: string,
    location?: string,
    details?: Record<string, unknown>,
    sourceText?: string
  ): Promise<Record<string, unknown>> {
    const result = this.service.recordActivity({
      occurredAt: timestamp(occurredAt),
      actor,
      action,
      object,
      location,
      details,
      sourceText
    })
    return { success: true, activity: result }
  }

  public async createAgendaItem(
    kind: 'task' | 'appointment' | 'event' | 'reminder',
    title: string,
    description?: string,
    startAt?: string | number,
    dueAt?: string | number,
    endAt?: string | number,
    timezone?: string,
    relatedPerson?: string,
    recurrence?: Record<string, unknown>,
    sourceText?: string
  ): Promise<Record<string, unknown>> {
    const result = this.service.createAgendaItem({
      kind,
      title,
      description,
      startAt: startAt ? timestamp(startAt) : null,
      dueAt: dueAt ? timestamp(dueAt) : null,
      endAt: endAt ? timestamp(endAt) : null,
      timezone,
      relatedPerson,
      recurrence,
      sourceText
    })
    return { success: true, agendaItem: result }
  }

  public async completeAgendaItem(id: string): Promise<Record<string, unknown>> {
    const result = this.service.completeAgendaItem(id)
    return result
      ? { success: true, agendaItem: result }
      : { success: false, error: `Unknown agenda item: ${id}` }
  }

  public async getProgram(dateExpression?: string, includeCompleted?: boolean): Promise<Record<string, unknown>> {
    const range = resolveDateRange(dateExpression || 'aujourd\'hui')
    const agenda = this.service.queryAgenda(range, includeCompleted === true)
    const program = this.service.getProgram(range)
    this.service.saveQueryContext({ intent: 'program', dateRange: range, query: dateExpression || 'aujourd\'hui' })
    return { success: true, range, program, agenda }
  }

  public async queryActivities(dateExpression: string, action?: string, object?: string): Promise<Record<string, unknown>> {
    const range = resolveDateRange(dateExpression || 'aujourd\'hui', new Date(), 'past')
    const activities = this.service.queryActivities(range, action, object)
    this.service.saveQueryContext({ intent: 'activities', dateRange: range, entity: object || action || null, query: dateExpression || 'aujourd\'hui' })
    return { success: true, range, activities, count: activities.length }
  }

  public async countActivities(dateExpression: string, action?: string, object?: string): Promise<Record<string, unknown>> {
    const range = resolveDateRange(dateExpression || 'ce mois-ci', new Date(), 'past')
    const count = this.service.countActivities(range, action, object)
    this.service.saveQueryContext({ intent: 'activity_count', dateRange: range, entity: object || action || null, query: dateExpression || 'ce mois-ci' })
    return { success: true, range, count, action: action || null, object: object || null }
  }

  public async recordMood(
    label: string,
    score?: -2 | -1 | 0 | 1 | 2,
    note?: string,
    occurredAt?: string | number,
    sourceText?: string
  ): Promise<Record<string, unknown>> {
    return { success: true, mood: this.service.recordMood({ label, score, note, occurredAt: timestamp(occurredAt), sourceText }) }
  }

  public async saveHabit(
    name: string,
    description?: string,
    schedule?: Record<string, unknown>,
    active?: boolean
  ): Promise<Record<string, unknown>> {
    return { success: true, habit: this.service.upsertHabit({ name, description, schedule, active }) }
  }

  public async getContext(): Promise<Record<string, unknown>> {
    return { success: true, context: this.service.getContextPack() }
  }
}
