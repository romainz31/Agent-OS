import type { ActionFunction } from '@sdk/types'
import { leon } from '@sdk/leon'

import { saveTask } from '../lib/core-memory'

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
  const rawTitles = params.action_arguments['task_titles']
  const titles = Array.isArray(rawTitles)
    ? rawTitles.map((title) => String(title).trim()).filter(Boolean)
    : []
  const dateValue = params.action_arguments['task_date']
  const date = typeof dateValue === 'string' ? dateValue.trim() : ''

  if (titles.length === 0) {
    await leon.answer({ key: 'task_missing' })
    return
  }

  for (const title of titles) {
    await saveTask({ title, ...(date ? { date } : {}) })
  }

  await leon.answer({
    key: 'tasks_created',
    data: {
      count: titles.length,
      titles: titles.join(', '),
      date_suffix: date ? ` pour le ${formatDate(date)}` : ''
    }
  })
}
