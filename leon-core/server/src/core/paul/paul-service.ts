import { getActiveConversationSessionId } from '@/core/session-manager/session-context'

import PaulStore, {
  type PaulActivityInput,
  type PaulAgendaInput,
  type PaulFactInput,
  type PaulHabitInput,
  type PaulMoodInput,
  type PaulRelationshipInput
} from './paul-store'
import { inferDateRangeFromText, resolveDateRange } from './temporal'
import LettaBridge, { type PaulLettaReply, type PaulLettaStatus } from './letta-bridge'
import type {
  PaulContextPack,
  PaulDateRange,
  PaulProgram
} from './types'

export default class PaulService {
  private readonly store = new PaulStore()
  private readonly letta = new LettaBridge()

  public initialize(): void {
    this.store.initialize()
  }

  public get databasePath(): string {
    return this.store.databasePath
  }

  public addFact(input: PaulFactInput): ReturnType<PaulStore['addFact']> {
    return this.store.addFact(input)
  }

  public addRelationship(input: PaulRelationshipInput): ReturnType<PaulStore['addRelationship']> {
    return this.store.addRelationship(input)
  }

  public recordActivity(input: PaulActivityInput): ReturnType<PaulStore['recordActivity']> {
    return this.store.recordActivity(input)
  }

  public createAgendaItem(input: PaulAgendaInput): ReturnType<PaulStore['createAgendaItem']> {
    return this.store.createAgendaItem(input)
  }

  public completeAgendaItem(id: string): ReturnType<PaulStore['completeAgendaItem']> {
    return this.store.completeAgendaItem(id)
  }

  public recordMood(input: PaulMoodInput): ReturnType<PaulStore['recordMood']> {
    return this.store.recordMood(input)
  }

  public upsertHabit(input: PaulHabitInput): ReturnType<PaulStore['upsertHabit']> {
    return this.store.upsertHabit(input)
  }

  public resolveDate(expression: string, direction: 'past' | 'future' | 'nearest' = 'nearest'): PaulDateRange {
    return resolveDateRange(expression, new Date(), direction)
  }

  public resolveDateFromText(text: string, direction: 'past' | 'future' | 'nearest' = 'nearest'): PaulDateRange | null {
    return inferDateRangeFromText(text, new Date(), direction)
  }

  public queryActivities(range: PaulDateRange, action?: string, object?: string): ReturnType<PaulStore['listActivities']> {
    return this.store.listActivities(range, action, object)
  }

  public countActivities(range: PaulDateRange, action?: string, object?: string): number {
    return this.store.countActivities(range, action, object)
  }

  public queryAgenda(range: PaulDateRange, includeCompleted = false): ReturnType<PaulStore['listAgenda']> {
    return this.store.listAgenda(range, includeCompleted)
  }

  public getProgram(range: PaulDateRange): PaulProgram {
    return this.store.getProgram(range)
  }

  public saveQueryContext(input: {
    intent: string
    dateRange?: PaulDateRange | null
    entity?: string | null
    query: string
  }): void {
    const sessionId = getActiveConversationSessionId() || 'default'
    this.store.saveConversationContext({
      sessionId,
      lastIntent: input.intent,
      lastDateRange: input.dateRange || null,
      lastEntity: input.entity || null,
      lastQuery: input.query,
      updatedAt: Date.now()
    })
  }

  public getContextPack(range?: PaulDateRange): PaulContextPack {
    const effectiveRange = range || resolveDateRange('aujourd\'hui')
    const sessionId = getActiveConversationSessionId() || 'default'
    const activities = this.store.listActivities(effectiveRange)
    const agenda = this.store.listAgenda(effectiveRange)
    return {
      today: effectiveRange.startDay,
      profile: {
        facts: this.store.listFacts(),
        relationships: this.store.listRelationships()
      },
      agenda,
      recentActivities: activities,
      recentMoods: this.store.listMoods(effectiveRange),
      pendingReminders: agenda.filter((item) => item.kind === 'reminder'),
      previousContext: this.store.getConversationContext(sessionId)
    }
  }

  public getPendingNotifications(limit = 20): ReturnType<PaulStore['getPendingNotifications']> {
    return this.store.getPendingNotifications(limit)
  }

  public markNotificationDelivered(id: string): void {
    this.store.markNotificationDelivered(id)
  }

  public getLettaStatus(): PaulLettaStatus {
    return this.letta.status
  }

  public checkLetta(): Promise<PaulLettaStatus> {
    return this.letta.check()
  }

  public chatWithLetta(input: string): Promise<PaulLettaReply> {
    return this.letta.chat({
      input,
      context: this.getContextPack(),
      sessionId: getActiveConversationSessionId()
    })
  }
}
