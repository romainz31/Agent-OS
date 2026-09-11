import { EventEmitter } from 'node:events'

import PaulStore from './paul-store'
import type { PaulAgendaItem } from './types'

const POLL_INTERVAL_MS = 30_000

function nextOccurrence(item: PaulAgendaItem): number | null {
  const recurrence = item.recurrence
  if (!recurrence || !item.dueAt) return null
  const frequency = String(recurrence['frequency'] || recurrence['freq'] || '').toLowerCase()
  const interval = Math.max(1, Number(recurrence['interval'] || 1))
  const next = new Date(item.dueAt)
  if (frequency === 'daily' || frequency === 'day') next.setUTCDate(next.getUTCDate() + interval)
  else if (frequency === 'weekly' || frequency === 'week') next.setUTCDate(next.getUTCDate() + 7 * interval)
  else if (frequency === 'monthly' || frequency === 'month') next.setUTCMonth(next.getUTCMonth() + interval)
  else return null
  return next.getTime()
}

export default class PaulScheduler {
  private readonly store = new PaulStore()
  private timer: NodeJS.Timeout | null = null
  private running = false
  public readonly events = new EventEmitter()

  public start(): void {
    if (this.timer) return
    this.store.initialize()
    this.timer = setInterval(() => {
      void this.tick()
    }, POLL_INTERVAL_MS)
    this.timer.unref?.()
    void this.tick()
  }

  public stop(): void {
    if (!this.timer) return
    clearInterval(this.timer)
    this.timer = null
  }

  public async tick(): Promise<void> {
    if (this.running) return
    this.running = true
    try {
      const now = Date.now()
      const due = this.store.listDueReminders(now)
      for (const reminder of due) {
        const notificationId = this.store.enqueueNotification('reminder.due', {
          agendaId: reminder.id,
          title: reminder.title,
          description: reminder.description,
          dueAt: reminder.dueAt,
          relatedPerson: reminder.relatedPerson
        })
        this.events.emit('reminder', { notificationId, reminder })
        const nextDueAt = nextOccurrence(reminder)
        if (nextDueAt) {
          this.store.createAgendaItem({
            kind: reminder.kind,
            title: reminder.title,
            description: reminder.description,
            startAt: reminder.startAt ? reminder.startAt + (nextDueAt - reminder.dueAt!) : null,
            dueAt: nextDueAt,
            endAt: reminder.endAt ? reminder.endAt + (nextDueAt - reminder.dueAt!) : null,
            timezone: reminder.timezone,
            relatedPerson: reminder.relatedPerson,
            recurrence: reminder.recurrence,
            sourceText: reminder.sourceText
          })
        }
        this.store.completeAgendaItem(reminder.id)
      }
    } finally {
      this.running = false
    }
  }
}
