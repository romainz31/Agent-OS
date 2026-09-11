import type { ActionFunction } from '@sdk/types'
import { leon } from '@sdk/leon'

import { saveAgendaEvent } from '../lib/core-memory'

function formatDate(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`)
  return Number.isNaN(parsed.getTime())
    ? date
    : new Intl.DateTimeFormat('fr-FR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
      }).format(parsed)
}

export const run: ActionFunction = async function (params) {
  const title = String(params.action_arguments['event_title'] || '').trim()
  const date = String(params.action_arguments['event_date'] || '').trim()
  const timeValue = params.action_arguments['event_time']
  const time = typeof timeValue === 'string' ? timeValue.trim() : ''

  if (!title || !date) {
    await leon.answer({ key: 'event_missing' })
    return
  }

  await saveAgendaEvent({ title, date, ...(time ? { time } : {}) })
  await leon.answer({
    key: 'event_created',
    data: {
      title,
      date: formatDate(date),
      time_suffix: time ? ` à ${time}` : ''
    }
  })
}
